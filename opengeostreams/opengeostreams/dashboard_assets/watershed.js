/*
 * Watershed analysis and sampling planner for OpenGeoStreams.
 *
 * Runs on an existing Leaflet map (the dashboard's, or the standalone page's) and fills
 * a panel element with its controls. Draw an area and it:
 *   1. splits the area into watersheds at stream confluences and boundary crossings,
 *   2. finds each watershed's pour point,
 *   3. picks the pour points where samples tell you most about the area
 *      (Sharp's method for monitoring networks, weighted by land use).
 *
 * The terrain (D8 flow directions, elevation and land use on one grid) comes from
 * opengeostreams.watershed.build_terrain(); the dashboard serves it at /api/watershed.
 *
 *   const planner = await OGSWatershed.create({map, root, data, stations, showStations});
 *   planner.show(); planner.hide();
 *   planner.pickPoint(lat, lon);            // area = all land draining to the nearest stream
 *   planner.setAOI([[lat, lon], ...]);       // area = a polygon
 *
 * Needs Leaflet and leaflet.draw.
 */
(function () {
"use strict";

const DR = [-1, -1, 0, 1, 1, 1, 0, -1], DC = [0, 1, 1, 1, 0, -1, -1, -1];
const LU = [
  {k: 0, name: "Unmapped", col: [0, 0, 0, 0], w: 0.25}, {k: 1, name: "Green / forest", col: [92, 160, 98, 150], w: 0.05},
  {k: 2, name: "Water", col: [66, 140, 200, 170], w: 0}, {k: 3, name: "Farmland", col: [214, 190, 80, 170], w: 0.5},
  {k: 4, name: "Institutional", col: [150, 140, 205, 160], w: 0.35}, {k: 5, name: "Residential", col: [236, 160, 84, 160], w: 0.5},
  {k: 6, name: "Commercial", col: [214, 84, 138, 170], w: 0.6}, {k: 7, name: "Construction", col: [176, 158, 128, 170], w: 0.5},
  {k: 8, name: "Industrial", col: [120, 72, 178, 190], w: 1.0}];
const LUsw = c => c.k === 0 ? "#9aa5a3" : `rgb(${c.col[0]},${c.col[1]},${c.col[2]})`;
const CELLW = LU.map(c => 0.3 + c.w);               // pollution-load weight per cell
const SRC_COL = {"Sewage treatment plant": "#2b6cb0", "Hospital": "#c53030", "Waste site": "#744210", "Factory / works": "#553c9a"};
const wsColor = k => `hsl(${(k * 137.508) % 360},70%,${k % 2 ? 46 : 56}%)`;
const escHtml = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const typeLabel = t => ({Outlet: "stream leaves your area", Inflow: "stream enters your area", Junction: "above a confluence", Outside: "outside your area"})[t];
const fmt = (v, d = 1) => v.toFixed(d);
const level = v => v >= 55 ? ["hi", "High"] : v >= 35 ? ["med", "Medium"] : ["lo", "Low"];

async function unpack(b64) {
  const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const ds = new Blob([bin]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Uint8Array(await new Response(ds).arrayBuffer());
}

const PANEL = `
<div class="ws-panel">
  <p class="ws-intro">Choose an area inside the elevation tile (dashed box on the map). It is split into watersheds,
    each watershed's pour point is found, and the pour points where field samples tell you most about your area's
    effect on the stream are picked. <span data-ws="tileNote"></span></p>

  <section class="ws-box">
    <div class="ws-lbl">1 · Choose your area</div>
    <div class="ws-modes">
      <button type="button" class="ws-mode" data-ws="point"><b>Click a stream</b><span>Everything that drains to that point</span></button>
      <button type="button" class="ws-mode" data-ws="box"><b>Drag a box</b><span>Press, drag and let go</span></button>
      <button type="button" class="ws-mode" data-ws="draw"><b>Draw a shape</b><span>Click corners, then the first one</span></button>
    </div>
    <label class="ws-hint ws-station-pick" data-ws="stationRow" hidden>Or everything that drains to a station
      <select data-ws="station"><option value="">Choose a station…</option></select></label>
    <div class="ws-row">
      <button type="button" class="ws-btn" data-ws="example" hidden>Load example</button>
      <button type="button" class="ws-btn" data-ws="clear">Clear</button>
    </div>
    <div class="ws-hint" data-ws="drawHint">Pick one of the three ways above. <b>Click a stream</b> is the quickest: click on or next to a blue stream line.</div>
  </section>

  <section class="ws-box">
    <div class="ws-lbl">2 · Watershed size</div>
    <label class="ws-hint" data-ws="thrLabel">A stream starts once <b class="ws-mono" data-ws="thrVal">0.50 km²</b> of land drains to a point. A new watershed starts wherever two streams join, so a higher value gives fewer, larger watersheds.</label>
    <input type="range" min="0" max="100" value="41" data-ws="thr" aria-label="Watershed size">
  </section>

  <section class="ws-box">
    <div class="ws-lbl">3 · Watersheds in your area</div>
    <div class="ws-hint" data-ws="sumBody">No area drawn yet.</div>
  </section>

  <section class="ws-box">
    <div class="ws-lbl">4 · Watersheds and pour points</div>
    <div class="ws-hint" data-ws="wsBody">Each watershed is listed with its pour point, the single cell where all of its water drains out.</div>
  </section>

  <section class="ws-box">
    <div class="ws-lbl">5 · Where to collect samples</div>
    <div class="ws-row">
      <label class="ws-hint">Number of samples <select data-ws="budget"><option value="auto">Recommended</option></select></label>
      <label class="ws-hint">Shade map by <select data-ws="shade"><option value="ws">Watershed</option><option value="zone">What each sample measures</option></select></label>
    </div>
    <div data-ws="curveBody"></div>
    <div class="ws-plan" data-ws="plan"></div>
  </section>

  <section class="ws-box">
    <div class="ws-lbl">6 · On the map</div>
    <div class="ws-layers" data-ws="layers"></div>
    <div class="ws-key">
      <div><span class="ws-pin"><span></span></span>Sampling point</div>
      <div><span class="ws-pp Outlet"></span>Pour point: stream leaves area</div>
      <div><span class="ws-pp Inflow"></span>Pour point: stream enters area</div>
      <div><span class="ws-pp"></span>Pour point: above a confluence</div>
      <div><span class="ws-pp Outside"></span>Pour point outside your area</div>
    </div>
  </section>

  <section class="ws-box">
    <div class="ws-lbl">7 · Download</div>
    <div class="ws-row">
      <button type="button" class="ws-btn" data-ws="dlWs">Watersheds (GeoJSON)</button>
      <button type="button" class="ws-btn" data-ws="dlPP">Pour points (GeoJSON)</button>
      <button type="button" class="ws-btn" data-ws="dlPts">Sampling points (CSV)</button>
      <button type="button" class="ws-btn" data-ws="dlPtsG">Sampling points (GeoJSON)</button>
      <button type="button" class="ws-btn" data-ws="dlKml">Everything for Google Earth (KML)</button>
    </div>
  </section>

  <section class="ws-box">
    <details>
      <summary>How it works</summary>
      <p><b>Flow:</b> the elevation tile is depression-filled and every cell is given one downhill direction (D8). A cell is a stream once the drainage area set in step 2 flows through it.</p>
      <p><b>Watersheds:</b> pour points are placed at the lowest cell of every stream stretch: just above each confluence, where a stream leaves your area, and where a stream enters it. Every cell in your area is traced downhill to the first pour point it meets, so the watersheds cover the whole area with no gaps or overlaps. A watershed shown as <b>outside</b> is land along your edge that runs off across the boundary; its pour point lies outside your area.</p>
      <p><b>Sampling:</b> a sample at a pour point measures all water from upstream of it. Comparing it with the samples upstream isolates the land in between. Every pour point is a candidate, including those outside your area where edge strips of your area drain. Only your area's land counts as load to measure. The planner picks pour points one at a time, each time taking the one that best evens out your area's load across samples (Sharp's method for monitoring networks, weighted by land use). Water from outside your area that mixes in counts against a sample, because it blurs your area's signal; that is why samples just before streams enter your area are useful. Your area's land that passes no sample counts as lost. <b>Recommended</b> stops at the last sample that adds at least 3 percentage points, and continues until at least 95% of your area drains through a sample.</p>
      <p><b>Pollution load weights</b> per cell: industrial 1.3, commercial 0.9, residential 0.8, farmland 0.8, construction 0.8, institutional 0.65, unmapped 0.55, green 0.35, water 0.3, plus the equivalent of 0.2 km² of industrial land for each mapped factory, sewage plant, hospital or waste site. These are starting assumptions, not measured loads.</p>
      <p data-ws="dataNote"></p>
    </details>
  </section>
  <div class="ws-busy" data-ws="busy">Loading terrain…</div>
</div>`;

async function create(options) {
  const {map, root} = options, D = options.data;
  const notify = options.notify || (message => window.alert(message));
  const W = D.W, H = D.H, N = W * H, RES = D.res, cellKm2 = D.dx * D.dy / 1e6;
  const SRC_W = 1.3 * 0.2 / cellKm2;                 // one point source = 0.2 km² of industrial land
  root.innerHTML = PANEL;
  const $ = key => root.querySelector(`[data-ws="${key}"]`);

  const fdir = await unpack(D.fdir), demRaw = await unpack(D.dem), lu = await unpack(D.lu);
  const dem = new Float32Array(N); {const u = new Uint16Array(demRaw.buffer); for (let i = 0; i < N; i++) dem[i] = u[i] / 10;}

  // ---------- flow network ----------
  const down = new Int32Array(N).fill(-1);
  for (let i = 0; i < N; i++) {const k = fdir[i]; if (k === 255) continue; const r = (i / W | 0) + DR[k], c = i % W + DC[k]; if (r >= 0 && r < H && c >= 0 && c < W) down[i] = r * W + c;}
  const acc = new Float32Array(N).fill(1);
  {const indeg = new Int32Array(N); for (let i = 0; i < N; i++) if (down[i] >= 0) indeg[down[i]]++;
   const st = new Int32Array(N); let sp = 0; for (let i = 0; i < N; i++) if (!indeg[i]) st[sp++] = i;
   while (sp) {const i = st[--sp], d = down[i]; if (d >= 0) {acc[d] += acc[i]; if (--indeg[d] === 0) st[sp++] = d;}}}
  const cOff = new Int32Array(N + 1); for (let i = 0; i < N; i++) if (down[i] >= 0) cOff[down[i] + 1]++; for (let i = 0; i < N; i++) cOff[i + 1] += cOff[i];
  const cList = new Int32Array(cOff[N]); {const f = cOff.slice(0, N); for (let i = 0; i < N; i++) if (down[i] >= 0) cList[f[down[i]]++] = i;}

  const toGrid = (lat, lon) => [(D.lat0 - lat) / RES - 0.5, (lon - D.lon0) / RES - 0.5];
  const toLL = (r, c) => [D.lat0 - (r + 0.5) * RES, D.lon0 + (c + 0.5) * RES];
  const cellLL = i => toLL(i / W | 0, i % W);
  const corner = (r, c) => [+(D.lon0 + c * RES).toFixed(6), +(D.lat0 - r * RES).toFixed(6)];
  const bounds = L.latLngBounds([[D.lat0 - H * RES, D.lon0], [D.lat0, D.lon0 + W * RES]]);

  // ---------- stations, sources, notes ----------
  const stations = (options.stations || []).map(s => Array.isArray(s) ? {name: s[0], lat: s[1], lon: s[2]} : s)
    .filter(s => Number.isFinite(s.lat) && Number.isFinite(s.lon))
    .map(s => {const [r, c] = toGrid(s.lat, s.lon); return {...s, r, c};});
  const onTile = stations.filter(s => bounds.contains([s.lat, s.lon])).length;
  const sources = (D.sources || []).map(([type, name, lat, lon]) => {const [r, c] = toGrid(lat, lon); return {type, name, lat, lon, r: Math.round(r), c: Math.round(c)};})
    .filter(s => s.r >= 0 && s.r < H && s.c >= 0 && s.c < W);
  const srcCount = new Uint16Array(N); sources.forEach(s => srcCount[s.r * W + s.c]++);
  $("tileNote").innerHTML = `Terrain: <b>${escHtml(D.name || "elevation tile")}</b>.` + (stations.length && !onTile
    ? ` <span class="ws-err">None of your ${stations.length} stations are on this tile; build terrain for your area with <span class="ws-mono">opengeostreams.watershed.build_terrain()</span>.</span>` : "");
  $("dataNote").innerHTML = `<b>Data:</b> elevation tile ${escHtml(D.name || "")} with cells of about ${Math.round(D.dy)} m. ` +
    (D.hasLU ? `Land use and point sources from ${escHtml(D.landuseSource || "OpenStreetMap")}. Farmland is often barely mapped in OpenStreetMap, so rural land may show as unmapped.`
      : "No land-use map was supplied, so every cell counts as unmapped land.") + " The planner only works inside the elevation tile shown by the dashed box.";
  $("example").hidden = !D.example;

  // ---------- map layers (all inside one group, so the planner can be shown and hidden) ----------
  const group = L.layerGroup();
  L.rectangle(bounds, {color: "#cbd5e1", weight: 1.5, dashArray: "6 5", fill: false, interactive: false}).addTo(group);
  const luCanvas = document.createElement("canvas"); luCanvas.width = W; luCanvas.height = H;
  {const x = luCanvas.getContext("2d"), img = x.createImageData(W, H), p = img.data; for (let i = 0; i < N; i++) {const c = LU[lu[i]].col; p[i * 4] = c[0]; p[i * 4 + 1] = c[1]; p[i * 4 + 2] = c[2]; p[i * 4 + 3] = c[3];} x.putImageData(img, 0, 0);}
  const luLayer = L.imageOverlay(luCanvas.toDataURL(), bounds, {opacity: 0.75, className: "ws-pixel", interactive: false});
  const streamLayer = L.layerGroup(), shadeLayer = L.layerGroup(), aoiLayer = L.featureGroup(), ppLayer = L.layerGroup(), ptLayer = L.layerGroup();
  const icon = (html, size, anchor, popupAnchor) => L.divIcon({className: "", html, iconSize: size, iconAnchor: anchor, popupAnchor});
  const stnLayer = L.layerGroup(stations.map(s => L.marker([s.lat, s.lon], {icon: icon('<div class="ws-stn"></div>', [11, 11], [6, 6])}).bindTooltip("Existing station: " + escHtml(s.name))));
  const srcLayer = L.layerGroup(sources.map(s => L.marker([s.lat, s.lon], {icon: icon(`<div class="ws-src" style="background:${SRC_COL[s.type]}"></div>`, [10, 10], [5, 5])}).bindTooltip(escHtml(s.type + (s.name ? ": " + s.name : "")))));
  const layerList = [
    ["Streams (from elevation)", streamLayer, true], ["Watersheds / sample zones", shadeLayer, true], ["Pour points", ppLayer, true],
    ["Sampling points", ptLayer, true], ["Your area", aoiLayer, true], ["Land use (OpenStreetMap)", luLayer, false],
    ["Point sources (OpenStreetMap)", srcLayer, false]];
  if (options.showStations) layerList.splice(5, 0, ["Existing stations", stnLayer, true]);
  $("layers").innerHTML = layerList.map(([name, , on], k) =>
    `<label class="ws-check"><input type="checkbox" data-layer="${k}"${on ? " checked" : ""}> ${name}</label>`).join("");
  layerList.forEach(([, layer, on]) => on && layer.addTo(group));
  $("layers").querySelectorAll("input").forEach(box => box.addEventListener("change", () => {
    const layer = layerList[+box.dataset.layer][1]; box.checked ? group.addLayer(layer) : group.removeLayer(layer);}));

  let thrKm2 = 0.5, thrCells = thrKm2 / cellKm2, isStream = new Uint8Array(N), sChild = new Uint8Array(N);
  function prepThreshold() {isStream = new Uint8Array(N); sChild = new Uint8Array(N);
    for (let i = 0; i < N; i++) if (acc[i] >= thrCells) isStream[i] = 1;
    for (let i = 0; i < N; i++) if (isStream[i] && down[i] >= 0 && sChild[down[i]] < 255) sChild[down[i]]++;}
  function buildStreams() {
    streamLayer.clearLayers(); const seen = new Uint8Array(N), lines = {1: [], 2: [], 3: []};
    const cls = i => acc[i] >= thrCells * 40 ? 3 : acc[i] >= thrCells * 6 ? 2 : 1;
    for (let i = 0; i < N; i++) {if (!isStream[i] || seen[i] || sChild[i] === 1) continue;
      let j = i; const line = [cellLL(j)]; const c0 = cls(j);
      while (true) {seen[j] = 1; const d = down[j]; if (d < 0) break; line.push(cellLL(d)); if (sChild[d] > 1 || seen[d] || cls(d) !== c0) break; j = d;}
      lines[c0].push(line);}
    const st = {1: {w: 1.2, o: .75}, 2: {w: 2, o: .85}, 3: {w: 3.4, o: .95}};
    for (const k of [1, 2, 3]) if (lines[k].length) L.polyline(lines[k], {color: "#38a8ff", weight: st[k].w, opacity: st[k].o, interactive: false}).addTo(streamLayer);
  }

  // ---------- helpers ----------
  function pip(r, c, pts) {let ins = false; for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {const [ri, ci] = pts[i], [rj, cj] = pts[j]; if (((ri > r) !== (rj > r)) && (c < (cj - ci) * (r - ri) / (rj - ri) + ci)) ins = !ins;} return ins;}
  function impactOf(cnt, ns) {let t = 0, s = 0; for (let k = 0; k < 9; k++) {t += cnt[k]; s += LU[k].w * cnt[k];} return t ? Math.min(100, Math.round(100 * s / t + Math.min(20, 4 * ns))) : 0;}
  const topLU = cnt => {let b = -1, bv = -1; for (let k = 0; k < 9; k++) {if (cnt[k] > bv) {bv = cnt[k]; b = k;}} const t = cnt.reduce((a, v) => a + v, 0); return [LU[b].name.toLowerCase(), t ? Math.round(100 * bv / t) : 0];};
  function nearestStation(i) {const r = i / W | 0, c = i % W; let bs = null, bd = 1e9; stations.forEach(s => {const d = Math.hypot(s.r - r, s.c - c); if (d < bd) {bd = d; bs = s;}}); return bd <= 10 ? {name: bs.name, dist: Math.round(bd * D.dx)} : null;}

  // raster labels -> GeoJSON MultiPolygons
  function vectorize(lab, labels) {
    const KW = W + 2, res = new Map(); labels.forEach(l => res.set(l, new Map()));
    const addE = (l, a, b) => {const m = res.get(l); const k = a[0] * KW + a[1]; let arr = m.get(k); if (!arr) {arr = []; m.set(k, arr);} arr.push(b);};
    for (let r = 0; r < H; r++) for (let c = 0; c < W; c++) {const l = lab[r * W + c]; if (!res.has(l)) continue;
      if (r === 0 || lab[(r - 1) * W + c] !== l) addE(l, [r, c], [r, c + 1]);
      if (c === W - 1 || lab[r * W + c + 1] !== l) addE(l, [r, c + 1], [r + 1, c + 1]);
      if (r === H - 1 || lab[(r + 1) * W + c] !== l) addE(l, [r + 1, c + 1], [r + 1, c]);
      if (c === 0 || lab[r * W + c - 1] !== l) addE(l, [r + 1, c], [r, c]);}
    const out = new Map(), key = p => p[0] * KW + p[1];
    res.forEach((m, l) => {const rings = [];
      for (const [k0, arr0] of m) {while (arr0.length) {const start = [Math.floor(k0 / KW), k0 % KW]; let cur = arr0.pop(); const ring = [start, cur]; let guard = 0;
          while ((cur[0] !== start[0] || cur[1] !== start[1]) && guard++ < 2e6) {const a = m.get(key(cur)); if (!a || !a.length) break;
            let pick = a.length - 1;
            if (a.length > 1) {const prev = ring[ring.length - 2], dr = cur[0] - prev[0], dc = cur[1] - prev[1];
              const rank = n => {const er = n[0] - cur[0], ec = n[1] - cur[1]; if (er === -dc && ec === dr) return 0; if (er === dr && ec === dc) return 1; return 2;};
              let best = 3; a.forEach((n, ix) => {const rk = rank(n); if (rk < best) {best = rk; pick = ix;}});}
            cur = a.splice(pick, 1)[0]; ring.push(cur);}
          const loops = [], stk = [], pos = new Map();
          for (const p of ring) {const k = key(p);
            if (pos.has(k)) {const lp = stk.splice(pos.get(k)); lp.forEach(q => pos.delete(key(q))); lp.push(p); loops.push(lp);}
            stk.push(p); pos.set(k, stk.length - 1);}
          for (const lp of loops) {if (lp.length < 5) continue;
            const s = []; for (let i = 0; i < lp.length; i++) {const p = lp[i], q = s[s.length - 1], o = s[s.length - 2]; if (o && ((o[0] === q[0] && q[0] === p[0]) || (o[1] === q[1] && q[1] === p[1]))) s[s.length - 1] = p; else s.push(p);}
            rings.push(s.map(([r, c]) => corner(r, c)));}}}
      const area = ring => {let a = 0; for (let i = 0; i < ring.length - 1; i++) a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]; return a / 2;};
      const outers = [], holes = []; rings.forEach(rg => {if (rg.length < 4) return; const r2 = rg.slice().reverse(); (area(rg) < 0 ? outers : holes).push(r2);});
      const polys = outers.map(o => [o]);
      holes.forEach(h => {const [x, y] = h[0]; const host = polys.find(p => {let ins = false, o = p[0]; for (let i = 0, j = o.length - 1; i < o.length; j = i++) {if (((o[i][1] > y) !== (o[j][1] > y)) && (x < (o[j][0] - o[i][0]) * (y - o[i][1]) / (o[j][1] - o[i][1]) + o[i][0])) ins = !ins;} return ins;}); if (host) host.push(h);});
      out.set(l, {type: "MultiPolygon", coordinates: polys});});
    return out;
  }

  // ---------- analysis ----------
  let aoi = null, result = null, selWs = -1, selS = -1;
  function analyse() {
    if (!aoi) {result = null; return;}
    if (aoi.error) {result = {error: aoi.error}; return;}
    let P = new Uint8Array(N), pCells = [];
    if (aoi.mask) {                                   // a catchment: the cells already chosen
      P = aoi.mask; for (let i = 0; i < N; i++) if (P[i]) pCells.push(i);
    } else {
      const poly = aoi.pts.map(([la, lo]) => toGrid(la, lo));
      let r0 = 1e9, r1 = -1e9, c0 = 1e9, c1 = -1e9; poly.forEach(([r, c]) => {r0 = Math.min(r0, r); r1 = Math.max(r1, r); c0 = Math.min(c0, c); c1 = Math.max(c1, c);});
      for (let r = Math.max(0, Math.floor(r0)); r <= Math.min(H - 1, Math.ceil(r1)); r++) for (let c = Math.max(0, Math.floor(c0)); c <= Math.min(W - 1, Math.ceil(c1)); c++) if (pip(r, c, poly)) {P[r * W + c] = 1; pCells.push(r * W + c);}
      if (pCells.length < 9) {result = {error: (r1 < 0 || r0 > H || c1 < 0 || c0 > W) ? "That area is outside the elevation tile (dashed box). Choose an area inside it." : "That area is too small for a 30 m grid. Choose something at least a few hundred metres across."}; return;}
    }
    if (pCells.length < 9) {result = {error: "Very little land drains to that point. Click on a blue stream line, or lower the watershed size in step 2 to show smaller streams."}; return;}

    // 1. pour points: lowest cell of each stream stretch, plus where streams cross your boundary
    const isPP = i => {const d = down[i]; if (d < 0) return true; if (!isStream[i]) return false; return sChild[d] >= 2 || (P[i] && !P[d]) || (!P[i] && P[d]);};
    const bas = new Int32Array(N).fill(-1);
    const basinOf = i => {const path = []; let j = i; while (bas[j] < 0 && !isPP(j)) {path.push(j); j = down[j];} const b = bas[j] >= 0 ? bas[j] : j; bas[j] = b; for (const q of path) bas[q] = b; return b;};
    const B = new Set(); for (const i of pCells) B.add(basinOf(i));
    for (const i of pCells) for (let q = cOff[i]; q < cOff[i + 1]; q++) {const j = cList[q]; if (!P[j] && isStream[j]) B.add(j);} // streams entering
    // 2. full watershed of each pour point (upstream until the next pour point)
    const wl = new Int32Array(N); const sheds = [...B].sort((a, b) => acc[b] - acc[a]).map((pp, k) => ({pp, k}));
    for (const s of sheds) {const st = [s.pp]; wl[s.pp] = s.k + 1; const cells = [s.pp];
      while (st.length) {const i = st.pop(); for (let q = cOff[i]; q < cOff[i + 1]; q++) {const j = cList[q]; if (wl[j] || isPP(j)) continue; wl[j] = s.k + 1; st.push(j); cells.push(j);}}
      const cnt = new Float64Array(9); let inP = 0, ns = 0; for (const i of cells) {cnt[lu[i]]++; if (P[i]) inP++; ns += srcCount[i];}
      const d = down[s.pp];
      s.type = !P[s.pp] ? (d >= 0 && P[d] && isStream[s.pp] ? "Inflow" : "Outside") : (d < 0 || !P[d] ? "Outlet" : "Junction");
      Object.assign(s, {id: "W" + (s.k + 1), area: cells.length * cellKm2, areaIn: inP * cellKm2, cnt, nsrc: ns, impact: impactOf(cnt, ns), up: acc[s.pp] * cellKm2, color: wsColor(s.k)});
      [s.lat, s.lon] = cellLL(s.pp); s.elev = dem[s.pp];}
    let covered = 0; for (const i of pCells) if (wl[i]) covered++;
    const shedByPP = new Map(sheds.map(s => [s.pp, s]));

    // 3. sampling network: every stream pour point of the listed watersheds, inside or outside your area
    const cand = sheds.filter(s => isStream[s.pp]);
    const dm = new Int32Array(N); const node = cand.slice().sort((a, b) => acc[a.pp] - acc[b.pp]).map(s => ({s}));
    node.forEach((nd, ix) => {nd.ix = ix; const st = [nd.s.pp]; dm[nd.s.pp] = ix + 1; let p = 0, e = 0, n = 0, pc = 0; const cnt = new Float64Array(9);
      const take = i => {const w = CELLW[lu[i]] + SRC_W * srcCount[i]; n++; if (P[i]) {p += w; pc++; cnt[lu[i]]++;} else e += w;}; take(nd.s.pp);
      while (st.length) {const i = st.pop(); for (let q = cOff[i]; q < cOff[i + 1]; q++) {const j = cList[q]; if (dm[j]) continue; dm[j] = ix + 1; st.push(j); take(j);}}
      Object.assign(nd, {p, e, cells: n, pc, cnt});});
    const ixOf = new Map(node.map(nd => [nd.s.pp, nd.ix]));
    node.forEach(nd => {let j = down[nd.s.pp], g = 0; nd.parent = -1; while (j >= 0 && g++ < 5000) {if (ixOf.has(j)) {nd.parent = ixOf.get(j); break;} j = down[j];}});
    const order = node.slice().sort((a, b) => acc[b.s.pp] - acc[a.s.pp]).map(nd => nd.ix); // downstream first
    const zoneOf = sel => {const z = new Int32Array(node.length); for (const i of order) {const q = node[i].parent; z[i] = sel.has(i) ? i : (q >= 0 ? z[q] : -1 - i);} return z;};
    // Information cost, counting only your area's load (p). Each sample's own zone costs p² (balanced zones tell
    // you more), plus MIX·p·e when water from outside your area (e) is mixed in, which blurs your area's signal.
    // Your area's load that passes no sample is lost: it costs as much as being mixed with everything.
    const MIX = 0.2, totP = node.reduce((a, b) => a + b.p, 0), totE = node.reduce((a, b) => a + b.e, 0), totPC = node.reduce((a, b) => a + b.pc, 0);
    const zoneSums = sel => {const z = zoneOf(sel), m = new Map(); let un = 0, unc = 0; node.forEach((nd, i) => {if (z[i] < 0) {un += nd.p; unc += nd.pc;} else {let a = m.get(z[i]); if (!a) {a = {p: 0, e: 0}; m.set(z[i], a);} a.p += nd.p; a.e += nd.e;}}); return {m, un, unc};};
    const J = sel => {const {m, un} = zoneSums(sel); let j = un * (totP + MIX * totE); m.forEach(a => j += a.p * a.p + MIX * a.p * a.e); return j;};
    const J0 = totP * (totP + MIX * totE);
    const picks = [], curve = [0], cover = [0]; const sel = new Set();
    const maxK = Math.min(node.length, 25);
    while (picks.length < maxK) {let best = -1, bj = Infinity; for (let i = 0; i < node.length; i++) {if (sel.has(i)) continue; sel.add(i); const j = J(sel); sel.delete(i); if (j < bj - 1e-9) {bj = j; best = i;}}
      if (best < 0) break; sel.add(best); picks.push(best); curve.push(1 - bj / J0); cover.push(totPC ? 1 - zoneSums(sel).unc / totPC : 0);}
    let rec = picks.length ? 1 : 0; for (let i = 1; i < curve.length; i++) if (curve[i] - curve[i - 1] >= 0.03) rec = i;
    while (rec < picks.length && cover[rec] < 0.95 && rec < 15) rec++;   // keep going until 95% of your area drains through a sample
    rec = Math.min(Math.max(rec, 1), picks.length);

    result = {P, pCells, sheds, shedByPP, wl, covered, node, dm, picks, curve, cover, rec, J0, totP, totE, totPC, zoneOf, aoiGeom: aoi.geom,
      polyArea: pCells.length * cellKm2, totArea: sheds.reduce((a, s) => a + s.area, 0)};
    const g = vectorize(wl, sheds.map(s => s.k + 1)); sheds.forEach(s => s.geom = g.get(s.k + 1));
    buildPlan();
  }

  function buildPlan() {
    const R = result; if (!R || R.error) return;
    const bv = $("budget").value;
    const k = bv === "auto" ? R.rec : Math.min(+bv, R.picks.length);
    const chosen = R.picks.slice(0, k); const set = new Set(chosen); const z = R.zoneOf(set);
    const zone = new Map();
    R.node.forEach((nd, i) => {const key = z[i]; let a = zone.get(key); if (!a) {a = {p: 0, e: 0, cells: 0, pc: 0, cnt: new Float64Array(9), sheds: []}; zone.set(key, a);} a.p += nd.p; a.e += nd.e; a.cells += nd.cells; a.pc += nd.pc; for (let q = 0; q < 9; q++) a.cnt[q] += nd.cnt[q]; a.sheds.push(nd.s);});
    const isUpstreamOf = (a, b) => {let q = R.node[a].parent; while (q >= 0) {if (q === b) return true; if (set.has(q)) return false; q = R.node[q].parent;} return false;};
    R.samples = chosen.map((ix, rank) => {const nd = R.node[ix], s = nd.s, a = zone.get(ix);
      const lead = {Outlet: "Where a stream leaves your area.", Inflow: "Where a stream enters your area, just before it crosses your boundary.", Junction: "Just above a point where two streams join inside your area.", Outside: "Just outside your area, downstream of where water from your area leaves it."}[s.type];
      const ups = chosen.filter(j => j !== ix && isUpstreamOf(j, ix)).map(j => "P" + (chosen.indexOf(j) + 1));
      const inKm = a.pc * cellKm2, outKm = (a.cells - a.pc) * cellKm2;
      let body;
      if (a.pc === 0 || (inKm < 0.1 && outKm > 20 * inKm)) body = `Measures the water arriving from ${outKm.toFixed(1)} km² upstream of your area, so it can be subtracted from the samples below it.`;
      else {const [tl, tp] = topLU(a.cnt);
        body = `Measures ${inKm.toFixed(2)} km² of your area that no other sample covers (${Math.round(100 * a.p / R.totP)}% of your area's load), mostly ${tl} (${tp}%).` +
          (outKm > 0.05 ? ` The water here also carries ${outKm.toFixed(1)} km² from outside your area${!ups.length && outKm > inKm ? ", so expect a diluted signal" : ""}.` : "");}
      return {rank: rank + 1, id: "P" + (rank + 1), ix, shed: s, lat: s.lat, lon: s.lon, elev: s.elev, up: s.up, type: s.type,
        inKm, outKm, share: a.p / R.totP, zoneCnt: a.cnt, sheds: a.sheds.map(x => x.id), existing: nearestStation(s.pp), extra: bv !== "auto" && rank >= R.rec,
        why: `${lead} ${body}${ups.length ? ` Subtract ${ups.join(", ")} to isolate it.` : ""}`};});
    R.unmon = [...zone.entries()].filter(([key]) => key < 0).reduce((t, [, a]) => ({p: t.p + a.p, pc: t.pc + a.pc}), {p: 0, pc: 0});
    R.unmon.pc += R.pCells.length - R.totPC;   // area cells that drain to no stream pour point (tile edge)
    R.coverNow = 1 - R.unmon.pc / R.pCells.length;
    // zone raster: each sample's own zone; your area's land that passes no sample is marked -1
    const zl = new Int32Array(N); const idxS = new Map(chosen.map((ix, r) => [ix, r + 1]));
    for (let i = 0; i < N; i++) {const d = R.dm[i]; const key = d ? z[d - 1] : -1; if (key >= 0) zl[i] = idxS.get(key); else if (R.P[i]) zl[i] = -1;}
    const lbls = chosen.map((_, r) => r + 1); if (R.unmon.pc) lbls.push(-1);
    const g = vectorize(zl, lbls); R.samples.forEach(s => s.zoneGeom = g.get(s.rank)); R.unmonGeom = R.unmon.pc ? g.get(-1) : null;
    selS = -1;
  }

  // ---------- drawing ----------
  function drawResult() {
    shadeLayer.clearLayers(); ppLayer.clearLayers(); ptLayer.clearLayers(); if (!result || result.error) return;
    const R = result, mode = $("shade").value;
    if (mode === "ws") {
      R.sheds.forEach((s, k) => {if (!s.geom || !s.geom.coordinates.length) return; const on = selWs === k;
        L.geoJSON(s.geom, {style: {color: s.type === "Outside" ? "#9ca3af" : s.color, weight: on ? 3.5 : 1.6, dashArray: s.type === "Outside" ? "4 3" : null, fillColor: s.color, fillOpacity: on ? 0.5 : (s.type === "Outside" ? 0.12 : 0.28)}})
          .bindTooltip(`${s.id} · ${s.area.toFixed(2)} km² · pour point: ${typeLabel(s.type)}`, {sticky: true}).on("click", () => pickWs(k, false)).addTo(shadeLayer);});
    } else {
      if (R.unmonGeom) L.geoJSON(R.unmonGeom, {style: {color: "#fff", weight: 1, dashArray: "3 3", fillColor: "#777", fillOpacity: .25}}).bindTooltip("Part of your area that drains past none of the chosen samples", {sticky: true}).addTo(shadeLayer);
      R.samples.forEach((s, k) => {if (!s.zoneGeom) return; const col = wsColor(k * 3 + 1);
        L.geoJSON(s.zoneGeom, {style: {color: col, weight: selS === k ? 3.5 : 2, fillColor: col, fillOpacity: selS === k ? 0.5 : 0.3}}).bindTooltip(`Measured only by ${s.id} · ${s.inKm.toFixed(2)} km² of your area`, {sticky: true}).on("click", () => pickS(k, false)).addTo(shadeLayer);});
    }
    R.sheds.forEach(s => {L.marker([s.lat, s.lon], {icon: icon(`<div class="ws-pp ${s.type}"></div>`, [11, 11], [6, 6])})
      .bindPopup(`<b>Pour point of ${s.id}</b> (${typeLabel(s.type)})<br>All water from ${s.id} drains out here.<br><span class="ws-mono">${s.lat.toFixed(6)}, ${s.lon.toFixed(6)}</span> · ${s.elev.toFixed(0)} m<br>Watershed ${s.area.toFixed(2)} km² (${s.areaIn.toFixed(2)} km² inside your area)<br>Total area upstream ${s.up.toFixed(2)} km²`).addTo(ppLayer);});
    R.samples.forEach((p, k) => {L.marker([p.lat, p.lon], {zIndexOffset: 1000, icon: icon(`<div class="ws-pin${p.extra ? " extra" : ""}${k === selS ? " on" : ""}"><span>${p.rank}</span></div>`, [26, 26], [13, 26], [0, -24])})
      .bindPopup(`<b>${p.id} · sample at pour point of ${p.shed.id}</b><br>${p.why}<br><span class="ws-mono">${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}</span> · ${p.elev.toFixed(0)} m${p.existing ? `<br>Existing station <b>${escHtml(p.existing.name)}</b> is ${p.existing.dist} m away.` : ""}<br><a href="https://www.google.com/maps?q=${p.lat.toFixed(6)},${p.lon.toFixed(6)}" target="_blank" rel="noopener">Open in Google Maps</a>`, {maxWidth: 320})
      .on("click", () => pickS(k, false)).addTo(ptLayer);});
  }
  function pickWs(k, fly) {selWs = k; renderWs(); drawResult(); const s = result.sheds[k]; if (fly && s.geom) map.fitBounds(L.geoJSON(s.geom).getBounds(), {padding: [40, 40], maxZoom: 16}); const el = root.querySelector(`tr.ws-shed[data-k="${k}"]`); el && el.scrollIntoView({block: "nearest"});}
  function pickS(k, fly) {selS = k; renderPlan(); drawResult(); const p = result.samples[k]; if (fly) map.flyTo([p.lat, p.lon], Math.max(map.getZoom(), 15), {duration: .6}); const el = root.querySelector(`.ws-pt[data-k="${k}"]`); el && el.scrollIntoView({block: "nearest", behavior: "smooth"});}

  // ---------- panel ----------
  function render() {renderSummary(); renderWs(); renderPlan();}
  function renderSummary() {
    const sb = $("sumBody");
    if (!result) {sb.innerHTML = "No area drawn yet."; return;} if (result.error) {sb.innerHTML = `<span class="ws-err">${result.error}</span>`; return;}
    const R = result, inside = R.sheds.filter(s => s.type !== "Outside" && s.type !== "Inflow").length;
    const cnt = new Float64Array(9); for (const i of R.pCells) cnt[lu[i]]++; const t = R.pCells.length;
    sb.innerHTML = `<div class="ws-stats"><div><span class="v">${fmt(R.polyArea)}</span><span class="k">km² your area</span></div>
      <div><span class="v">${R.sheds.length}</span><span class="k">watersheds</span></div>
      <div><span class="v">${Math.round(100 * R.covered / t)}%</span><span class="k">of your area covered</span></div></div>
      <div class="ws-hint">${inside} have their pour point inside your area, ${R.sheds.filter(s => s.type === "Inflow").length} bring water in from upstream, and ${R.sheds.filter(s => s.type === "Outside").length} are edge strips that drain out across your boundary.</div>
      <div class="ws-lbl">Land use inside your area</div>
      <div class="ws-lubar">${LU.map(c => cnt[c.k] / t > 0.004 ? `<span style="width:${(cnt[c.k] / t * 100).toFixed(2)}%;background:${LUsw(c)}" title="${c.name}"></span>` : "").join("")}</div>
      <div class="ws-legend">${LU.filter(c => cnt[c.k] / t > 0.002).sort((a, b) => cnt[b.k] - cnt[a.k]).map(c => `<div><span class="ws-sw" style="background:${LUsw(c)}"></span>${c.name}<span class="pc">${Math.round(cnt[c.k] / t * 100)}%</span></div>`).join("")}</div>`;
  }
  function renderWs() {
    const wb = $("wsBody");
    if (!result || result.error) {wb.innerHTML = "Each watershed is listed with its pour point, the single cell where all of its water drains out."; return;}
    wb.innerHTML = `<div class="ws-scroll"><table><thead><tr><th>Watershed</th><th>Pour point</th><th class="n">km²</th><th class="n">inside</th><th>Impact</th></tr></thead><tbody>
      ${result.sheds.map((s, k) => {const [c] = level(s.impact); return `<tr class="ws-shed${k === selWs ? " on" : ""}" data-k="${k}" tabindex="0"><td><span class="ws-sw" style="background:${s.color}"></span> ${s.id}</td><td><span class="ws-tag ${s.type}">${s.type}</span></td><td class="n">${fmt(s.area, 2)}</td><td class="n">${fmt(s.areaIn, 2)}</td><td><span class="ws-chip ${c}">${s.impact}</span></td></tr>`;}).join("")}
      </tbody></table></div><div class="ws-hint">Click a row to zoom to it. Click a dot on the map for the pour point's coordinates.</div>`;
    wb.querySelectorAll("tr.ws-shed").forEach(el => {const go = () => pickWs(+el.dataset.k, true); el.onclick = go; el.onkeydown = e => {if (e.key === "Enter") go();};});
  }
  function renderPlan() {
    const pl = $("plan"), cv = $("curveBody");
    if (!result || result.error) {pl.innerHTML = ""; cv.innerHTML = ""; return;}
    const R = result;
    if (!R.node.length) {cv.innerHTML = ""; pl.innerHTML = `<div class="ws-hint">No stream flows through this area at the current watershed size. Lower it in step 2.</div>`; return;}
    const k = R.samples.length, K = R.curve.length - 1, bw = Math.min(22, 260 / K);
    const bars = R.curve.slice(1).map((v, i) => {const x = 34 + i * bw, h = v * 80; return `<rect x="${x + 1}" y="${92 - h}" width="${bw - 2}" height="${h}" class="${i < k ? "on" : ""}"><title>${i + 1} samples: ${Math.round(v * 100)}% of the information</title></rect>${(i + 1) % 5 === 0 || i === 0 || i === K - 1 ? `<text x="${x + bw / 2}" y="105" text-anchor="middle">${i + 1}</text>` : ""}`;}).join("");
    cv.innerHTML = `<svg class="ws-curve" viewBox="0 0 300 110" role="img" aria-label="Information captured by number of samples">
      <line x1="32" y1="12" x2="300" y2="12"/><line x1="32" y1="52" x2="300" y2="52"/><line x1="32" y1="92" x2="300" y2="92" class="axis"/>
      <text x="28" y="15" text-anchor="end">100%</text><text x="28" y="55" text-anchor="end">50%</text><text x="28" y="95" text-anchor="end">0</text>${bars}</svg>
      <div class="ws-hint">Information about your area captured as you add samples (100% would mean every bit of your area measured on its own, with no outside water mixed in). <b>${R.rec} sample${R.rec > 1 ? "s" : ""}</b> recommended: ${Math.round(R.curve[R.rec] * 100)}% of the information, and ${Math.round(R.cover[R.rec] * 100)}% of your area drains through at least one sample. Samples are listed in the order they add the most information.</div>`;
    pl.innerHTML = R.samples.map((p, i) => `<div class="ws-pt${p.extra ? " extra" : ""}${i === selS ? " on" : ""}" data-k="${i}" tabindex="0" role="button">
        <div class="top"><span class="id">${p.id}</span><span class="ty">Pour point of ${p.shed.id}</span><span class="ws-tag ${p.type}">${p.type}</span><span class="pr">${p.extra ? "Extra" : "Recommended"}</span></div>
        <div class="why">${p.why}</div>
        <div class="meta"><span>${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}</span><span>${fmt(p.elev, 0)} m</span><span>${fmt(p.up, 2)} km² upstream</span></div>
        ${p.existing ? `<div class="ws-hint">Your existing station <b>${escHtml(p.existing.name)}</b> is ${p.existing.dist} m away and may already cover this.</div>` : ""}</div>`).join("") +
      `<div class="ws-hint"><b>${Math.round(R.coverNow * 100)}%</b> of your area drains through these samples.${R.unmon.pc ? ` The other ${fmt(R.unmon.pc * cellKm2, 2)} km² (shaded grey in the sample view) runs off in small strips; add samples to cover it.` : ""}</div>`;
    pl.querySelectorAll(".ws-pt").forEach(el => {const go = () => pickS(+el.dataset.k, true); el.onclick = go; el.onkeydown = e => {if (e.key === "Enter") go();};});
  }
  function refreshBudget() {const b = $("budget"), v = b.value; const n = result && !result.error ? result.picks.length : 0;
    b.innerHTML = `<option value="auto">Recommended${n ? ` (${result.rec})` : ""}</option>` + Array.from({length: n}, (_, i) => `<option value="${i + 1}">${i + 1}</option>`).join("");
    b.value = [...b.options].some(o => o.value === v) ? v : "auto";}

  // ---------- choosing the area ----------
  // Three ways: click a stream (the area is all land draining to that point), drag a
  // box, or draw a shape. Picking a station from the list works like clicking a stream.
  const shapeStyle = {color: "#ffffff", weight: 3, fill: false};
  const drawers = {draw: new L.Draw.Polygon(map, {allowIntersection: false, showArea: true, shapeOptions: shapeStyle}),
                   box: new L.Draw.Rectangle(map, {showArea: false, shapeOptions: shapeStyle})};
  const HINTS = {
    point: "Click on or next to a blue stream line. Your area becomes all the land that drains to that point. <b>Esc</b> cancels.",
    box: "Press on the map, drag to the opposite corner and let go. <b>Esc</b> cancels.",
    draw: "Click around your area on the map, then click the first point to close the shape. <b>Esc</b> cancels."};
  const hint = $("drawHint"), idleHint = hint.innerHTML;
  let active = false, busyCount = 0, mode = null, areaHint = "";
  const restingHint = () => {hint.innerHTML = aoi && !aoi.error ? areaHint : idleHint;};
  function clearModeUI() {mode = null; document.body.classList.remove("ws-drawing"); root.querySelectorAll(".ws-mode").forEach(b => b.classList.remove("on"));}
  function stopModes() {
    if (mode === "point") {map.off("click", onPointClick); document.removeEventListener("keydown", onEsc);}
    const was = mode; clearModeUI(); if (drawers[was]) drawers[was].disable();
  }
  function startMode(next) {
    const was = mode; stopModes();
    if (was === next) {restingHint(); return;}          // pressing the same button again cancels
    mode = next; $(next).classList.add("on"); hint.innerHTML = HINTS[next];
    if (next === "point") {document.body.classList.add("ws-drawing"); setTimeout(() => map.on("click", onPointClick), 0); document.addEventListener("keydown", onEsc);}
    else drawers[next].enable();
  }
  function onEsc(e) {if (e.key === "Escape") {stopModes(); restingHint();}}
  function onPointClick(e) {stopModes(); $("station").value = ""; pickPoint(e.latlng.lat, e.latlng.lng);}
  ["point", "box", "draw"].forEach(key => {$(key).onclick = () => startMode(key);});
  map.on(L.Draw.Event.CREATED, e => {if (active) setAOI(e.layer.getLatLngs()[0].map(ll => [ll.lat, ll.lng]));});
  map.on(L.Draw.Event.DRAWSTART, () => {if (active) document.body.classList.add("ws-drawing");});
  map.on(L.Draw.Event.DRAWSTOP, () => {if (mode && mode !== "point") {clearModeUI(); restingHint();}});

  /** The area draining to the stream cell nearest (lat, lon), within about 300 m. */
  function pickPoint(lat, lon, label) {
    const [gr, gc] = toGrid(lat, lon), r = Math.round(gr), c = Math.round(gc);
    if (r < 0 || r >= H || c < 0 || c >= W) return setArea({error: "That point is outside the elevation tile (dashed box). Choose a point inside it."});
    const R = 10; let best = -1, bd = Infinity, off = [0, 0];
    for (let dr = -R; dr <= R; dr++) for (let dc = -R; dc <= R; dc++) {
      const rr = r + dr, cc = c + dc; if (rr < 0 || rr >= H || cc < 0 || cc >= W) continue;
      const i = rr * W + cc; if (!isStream[i]) continue;
      const d = Math.hypot(dr * D.dy, dc * D.dx) - acc[i] * 1e-9;   // nearest; the bigger stream on a tie
      if (d < bd) {bd = d; best = i; off = [dr, dc];}}
    if (best < 0) return setArea({error: `No stream within ${Math.round(R * D.dy)} m of ${label ? escHtml(label) : "that point"}. Click on or next to a blue stream line, or lower the watershed size in step 2 to show smaller streams.`});
    const mask = new Uint8Array(N); mask[best] = 1; const st = [best]; let cells = 1, edge = false;
    while (st.length) {const i = st.pop(), rr = i / W | 0, cc = i % W; if (!rr || !cc || rr === H - 1 || cc === W - 1) edge = true;
      for (let q = cOff[i]; q < cOff[i + 1]; q++) {const j = cList[q]; if (!mask[j]) {mask[j] = 1; cells++; st.push(j);}}}
    const moved = Math.round(Math.hypot(off[0] * D.dy, off[1] * D.dx));
    setArea({mask, geom: vectorize(mask, [1]).get(1), outlet: cellLL(best),
      hint: `Your area: all land that drains to ${label ? `<b>${escHtml(label)}</b>` : "the point you chose"} (${fmt(cells * cellKm2, 2)} km²)` +
        (moved > 20 ? `, moved ${moved} m to the nearest stream` : "") + "." +
        (edge ? " Part of it lies beyond the elevation tile, so it is cut off at the dashed box." : "") + " Choose again to replace it."});
  }
  function setAOI(pts) {
    $("station").value = "";
    const ring = pts.map(([la, lo]) => [+lo.toFixed(6), +la.toFixed(6)]); ring.push(ring[0]);
    setArea({pts, geom: {type: "Polygon", coordinates: [ring]}, hint: "Area set. Choose again to replace it."});
  }
  function busy(on, text = "Working…") {busyCount += on ? 1 : -1; const b = $("busy"); b.hidden = busyCount <= 0; b.textContent = text;}
  function run(fn) {busy(true); setTimeout(() => {try {fn();} catch (err) {console.error(err); notify("Watershed analysis failed: " + err.message);} busy(false);}, 30);}
  function setArea(area) {
    aoi = area; aoiLayer.clearLayers(); selWs = -1;
    if (area.geom) {
      L.geoJSON(area.geom, {style: {color: "#000", weight: 5, opacity: .5, fill: false}, interactive: false}).addTo(aoiLayer);
      L.geoJSON(area.geom, {style: {color: "#fff", weight: 2.5, fill: false}, interactive: false}).addTo(aoiLayer);
    }
    areaHint = area.hint || ""; hint.innerHTML = area.error ? `<span class="ws-err">${area.error}</span>` : areaHint;
    run(() => {analyse(); refreshBudget(); if (result && !result.error) buildPlan(); render(); drawResult();
      if (result && !result.error) {const b = L.geoJSON(area.geom).getBounds(); result.sheds.forEach(s => {if (s.geom && s.type !== "Inflow") b.extend(L.geoJSON(s.geom).getBounds());}); map.fitBounds(b, {padding: [30, 30]});}});
  }
  $("clear").onclick = () => {stopModes(); aoi = null; result = null; areaHint = ""; aoiLayer.clearLayers(); $("station").value = ""; render(); drawResult(); refreshBudget(); hint.innerHTML = idleHint;};
  $("example").onclick = () => {stopModes(); D.example && setAOI(D.example);};
  {const onTileStations = stations.filter(s => bounds.contains([s.lat, s.lon])).sort((a, b) => String(a.name).localeCompare(String(b.name)));
   $("stationRow").hidden = !onTileStations.length;
   $("station").innerHTML += onTileStations.map((s, k) => `<option value="${k}">${escHtml(s.name)}</option>`).join("");
   $("station").onchange = e => {const s = onTileStations[+e.target.value]; if (e.target.value !== "" && s) {stopModes(); pickPoint(s.lat, s.lon, s.name);}};}
  $("budget").onchange = () => run(() => {buildPlan(); renderPlan(); drawResult();});
  $("shade").onchange = () => drawResult();
  const thr = $("thr"), tf = v => 0.1 * Math.pow(50, v / 100);
  thr.oninput = () => {thrKm2 = tf(+thr.value); $("thrVal").textContent = thrKm2.toFixed(2) + " km²";};
  thr.onchange = () => {thrCells = thrKm2 / cellKm2; run(() => {prepThreshold(); buildStreams(); if (aoi) {analyse(); refreshBudget(); if (!result.error) buildPlan(); render(); drawResult();}});};
  thrKm2 = tf(+thr.value); thrCells = thrKm2 / cellKm2; $("thrVal").textContent = thrKm2.toFixed(2) + " km²";

  // ---------- downloads ----------
  function save(name, text, type) {const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], {type})); a.download = name; document.body.appendChild(a); a.click(); setTimeout(() => {URL.revokeObjectURL(a.href); a.remove();}, 500);}
  const need = () => {if (!result || result.error) {notify("Draw an area first."); return false;} return true;};
  const aoiF = () => ({type: "Feature", properties: {name: "Area of interest"}, geometry: result.aoiGeom});
  const pct = cnt => {const t = cnt.reduce((a, b) => a + b, 0) || 1, o = {}; LU.forEach(c => o["pct_" + c.name.toLowerCase().replace(/[^a-z]+/g, "_")] = +(100 * cnt[c.k] / t).toFixed(1)); return o;};
  const shedProps = s => ({id: s.id, pour_point_type: s.type, pour_point_lat: +s.lat.toFixed(6), pour_point_lon: +s.lon.toFixed(6), pour_point_elev_m: +s.elev.toFixed(1), area_km2: +s.area.toFixed(3), area_in_aoi_km2: +s.areaIn.toFixed(3), upstream_km2: +s.up.toFixed(3), impact: s.impact, point_sources: s.nsrc, ...pct(s.cnt)});
  const sampProps = p => ({id: p.id, rank: p.rank, pour_point_of: p.shed.id, pour_point_type: p.type, elevation_m: +p.elev.toFixed(1), upstream_km2: +p.up.toFixed(3), aoi_km2_only_here: +p.inKm.toFixed(3), outside_km2_mixed_in: +p.outKm.toFixed(3), aoi_load_share_pct: +(100 * p.share).toFixed(1), watersheds: p.sheds.join(" "), status: p.extra ? "Extra" : "Recommended", reason: p.why, existing_station: p.existing ? p.existing.name : null});
  $("dlWs").onclick = () => {if (!need()) return; save("watersheds.geojson", JSON.stringify({type: "FeatureCollection", features: [aoiF(), ...result.sheds.filter(s => s.geom).map(s => ({type: "Feature", properties: shedProps(s), geometry: s.geom}))]}), "application/geo+json");};
  $("dlPP").onclick = () => {if (!need()) return; save("pour_points.geojson", JSON.stringify({type: "FeatureCollection", features: result.sheds.map(s => ({type: "Feature", properties: shedProps(s), geometry: {type: "Point", coordinates: [+s.lon.toFixed(6), +s.lat.toFixed(6)]}}))}), "application/geo+json");};
  $("dlPtsG").onclick = () => {if (!need()) return; save("sampling_points.geojson", JSON.stringify({type: "FeatureCollection", features: [aoiF(), ...result.samples.map(p => ({type: "Feature", properties: sampProps(p), geometry: {type: "Point", coordinates: [+p.lon.toFixed(6), +p.lat.toFixed(6)]}}))]}), "application/geo+json");};
  $("dlPts").onclick = () => {if (!need()) return; const q = s => `"${String(s ?? "").replace(/"/g, '""')}"`;
    const rows = ["id,rank,latitude,longitude,pour_point_of,pour_point_type,elevation_m,upstream_km2,aoi_km2_only_here,outside_km2_mixed_in,aoi_load_share_pct,watersheds,status,reason,existing_station",
      ...result.samples.map(p => {const o = sampProps(p); return [o.id, o.rank, p.lat.toFixed(6), p.lon.toFixed(6), o.pour_point_of, o.pour_point_type, o.elevation_m, o.upstream_km2, o.aoi_km2_only_here, o.outside_km2_mixed_in, o.aoi_load_share_pct, q(o.watersheds), o.status, q(o.reason), q(o.existing_station)].join(",");})];
    save("sampling_points.csv", rows.join("\n"), "text/csv");};
  $("dlKml").onclick = () => {if (!need()) return; const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
    const kc = css => {const m = css.match(/hsl\((\d+(?:\.\d+)?),(\d+)%,(\d+)%\)/); if (!m) return "ff0000"; const h = +m[1] / 360, s = +m[2] / 100, l = +m[3] / 100; const f = n => {const k = (n + h * 12) % 12, a = s * Math.min(l, 1 - l); return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))));}; const hx = v => v.toString(16).padStart(2, "0"); return hx(f(4)) + hx(f(8)) + hx(f(0));};
    const rs = r => r.map(([x, y]) => x + "," + y + ",0").join(" ");
    const kmlPolys = g => `<MultiGeometry>${(g.type === "Polygon" ? [g.coordinates] : g.coordinates).map(pg => `<Polygon><outerBoundaryIs><LinearRing><coordinates>${rs(pg[0])}</coordinates></LinearRing></outerBoundaryIs>${pg.slice(1).map(h => `<innerBoundaryIs><LinearRing><coordinates>${rs(h)}</coordinates></LinearRing></innerBoundaryIs>`).join("")}</Polygon>`).join("")}</MultiGeometry>`;
    let k = `<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>${esc(D.name || "Watershed")} sampling plan</name>`;
    k += `<Placemark><name>Area of interest</name><Style><LineStyle><color>ffffffff</color><width>3</width></LineStyle><PolyStyle><fill>0</fill></PolyStyle></Style>${kmlPolys(result.aoiGeom)}</Placemark>`;
    k += `<Folder><name>Watersheds</name>` + result.sheds.filter(s => s.geom).map(s => `<Placemark><name>${s.id}</name><description>${s.area.toFixed(2)} km², pour point: ${typeLabel(s.type)}</description><Style><LineStyle><color>ff${kc(s.color)}</color><width>2</width></LineStyle><PolyStyle><color>55${kc(s.color)}</color></PolyStyle></Style>${kmlPolys(s.geom)}</Placemark>`).join("") + `</Folder>`;
    k += `<Folder><name>Pour points</name>` + result.sheds.map(s => `<Placemark><name>Pour point ${s.id}</name><description>${typeLabel(s.type)}</description><Point><coordinates>${s.lon.toFixed(6)},${s.lat.toFixed(6)},0</coordinates></Point></Placemark>`).join("") + `</Folder>`;
    k += `<Folder><name>Sampling points</name>` + result.samples.map(p => `<Placemark><name>${p.id}</name><description>${esc(p.why)}</description><Point><coordinates>${p.lon.toFixed(6)},${p.lat.toFixed(6)},0</coordinates></Point></Placemark>`).join("") + `</Folder></Document></kml>`;
    save("sampling_plan.kml", k, "application/vnd.google-earth.kml+xml");};

  prepThreshold(); buildStreams(); render(); $("busy").hidden = true;

  const api = {
    bounds,
    get result() {return result;},
    get active() {return active;},
    setAOI,
    pickPoint,
    /** Put the planner's layers on the map; zoom to the tile unless the map already shows part of it. */
    show() {
      if (active) return; active = true; group.addTo(map);
      if (!map.getBounds().intersects(bounds) || map.getZoom() < 10) map.fitBounds(bounds, {padding: [20, 20]});
    },
    /** Take the planner's layers off the map and stop any drawing in progress. */
    hide() {if (!active) return; active = false; stopModes(); restingHint(); map.removeLayer(group);},
  };
  window.__planner = api;
  return api;
}

window.OGSWatershed = {create};
})();
