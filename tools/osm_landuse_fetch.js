// Fetch OpenStreetMap land use for the DEM tile and convert it to the DEM grid.
//
// How to run: open https://overpass-api.de/ in Chrome, open DevTools (F12) > Console,
// paste this whole file and press Enter. After about a minute the browser downloads
// nchoe_landuse_osm.json; pass it to opengeostreams.watershed.build_terrain().
//
// The grid numbers below must match your elevation tile (read_geotiff() gives the
// transform and shape): west edge, north edge, cell size in degrees, columns, rows.

(async () => {
  const W0 = 76.64374998888891, N0 = 30.78430556666666;   // west and north edges of the tile
  const S0 = 30.532638899999995, E0 = 76.85402776666669;  // south and east edges
  const RES = 0.0002777777777777778, GW = 757, GH = 906;   // 1 arc-second cells, grid size

  // 1. Download land-use polygons and pollution point sources
  const bb = `${S0},${W0},${N0},${E0}`;
  const q = `[out:json][timeout:180];(
    way["landuse"](${bb});relation["landuse"](${bb});
    way["natural"~"wood|scrub|water|grassland"](${bb});relation["natural"~"wood|scrub|water"](${bb});
    way["leisure"~"park|garden|golf_course|nature_reserve"](${bb});
    way["amenity"~"hospital|university|college"](${bb});
    nwr["man_made"~"wastewater_plant|works"](${bb});
    nwr["amenity"~"waste_disposal|waste_transfer_station"](${bb});
    nwr["industrial"](${bb});
  );out geom;`;
  const r = await fetch("https://overpass-api.de/api/interpreter", { method: "POST", body: "data=" + encodeURIComponent(q) });
  const osm = await r.json();
  console.log("OSM features:", osm.elements.length);

  // 2. Land-use class for each feature (higher number wins where they overlap)
  //    0 unmapped, 1 green, 2 water, 3 farmland, 4 institutional,
  //    5 residential, 6 commercial, 7 construction, 8 industrial
  const cls = t => {
    if (["industrial", "landfill"].includes(t.landuse)) return 8;
    if (t.landuse === "construction") return 7;
    if (["commercial", "retail"].includes(t.landuse)) return 6;
    if (t.landuse === "residential") return 5;
    if (["college", "university", "hospital"].includes(t.amenity) ||
        ["education", "religious", "community", "military", "railway", "special"].includes(t.landuse)) return 4;
    if (["farmland", "farmyard", "orchard", "meadow", "plant_nursery", "greenhouse_horticulture", "aquaculture", "vineyard"].includes(t.landuse)) return 3;
    if (t.natural === "water" || ["basin", "reservoir"].includes(t.landuse)) return 2;
    if (["wood", "scrub", "grassland"].includes(t.natural) ||
        ["forest", "grass", "greenfield", "recreation_ground", "cemetery", "village_green"].includes(t.landuse) ||
        ["park", "garden", "golf_course", "nature_reserve"].includes(t.leisure)) return 1;
    return 0;
  };

  // 3. Draw each class onto a canvas the size of the DEM grid, lowest class first
  const out = new Uint8Array(GW * GH), counts = {};
  const cv = document.createElement("canvas"); cv.width = GW; cv.height = GH;
  const x = cv.getContext("2d", { willReadFrequently: true });
  for (let c = 1; c <= 8; c++) {
    x.clearRect(0, 0, GW, GH); x.fillStyle = "#fff"; let n = 0;
    for (const e of osm.elements) {
      if (!e.tags || cls(e.tags) !== c) continue;
      const rings = [];
      if (e.type === "way" && e.geometry && e.geometry.length > 3) rings.push(e.geometry);
      if (e.type === "relation" && e.members) e.members.forEach(m => { if (m.geometry && m.geometry.length > 2) rings.push(m.geometry); });
      if (!rings.length) continue;
      n++; x.beginPath();
      for (const rg of rings) {
        for (let i = 0; i < rg.length; i++) {
          const g = rg[i]; if (!g) continue;
          const X = (g.lon - W0) / RES, Y = (N0 - g.lat) / RES;
          i ? x.lineTo(X, Y) : x.moveTo(X, Y);
        }
        x.closePath();
      }
      x.fill("evenodd");
    }
    const d = x.getImageData(0, 0, GW, GH).data; let a = 0;
    for (let i = 0; i < GW * GH; i++) if (d[i * 4 + 3] > 127) { out[i] = c; a++; }
    counts[c] = [n, a];
  }

  // 4. Compress the grid: run-length pairs "<class><run length in base 36>"
  const s = []; let prev = out[0], run = 0;
  for (let i = 0; i < out.length; i++) { if (out[i] === prev) run++; else { s.push(prev + run.toString(36)); prev = out[i]; run = 1; } }
  s.push(prev + run.toString(36));

  // 5. Point sources: factories, sewage plants, waste sites, hospitals
  const pts = [];
  for (const e of osm.elements) {
    const t = e.tags || {}; let ty = null;
    if (t.man_made === "wastewater_plant") ty = "Sewage treatment plant";
    else if (t.man_made === "works" || t.industrial) ty = "Factory / works";
    else if (t.amenity === "waste_disposal" || t.amenity === "waste_transfer_station" || t.landuse === "landfill") ty = "Waste site";
    else if (t.amenity === "hospital") ty = "Hospital";
    if (!ty) continue;
    let la, lo;
    if (e.type === "node") { la = e.lat; lo = e.lon; }
    else if (e.bounds) { la = (e.bounds.minlat + e.bounds.maxlat) / 2; lo = (e.bounds.minlon + e.bounds.maxlon) / 2; }
    else if (e.geometry) { const g = e.geometry.filter(Boolean); la = g.reduce((a, q) => a + q.lat, 0) / g.length; lo = g.reduce((a, q) => a + q.lon, 0) / g.length; }
    if (la == null || isNaN(la)) continue;
    pts.push([ty, (t.name || "").replace(/[^\w .,()-]/g, "").slice(0, 50), +la.toFixed(5), +lo.toFixed(5)]);
  }

  // 6. Save
  const payload = JSON.stringify({
    grid: { w: GW, h: GH, classes: { 0: "unmapped", 1: "green", 2: "water", 3: "farmland", 4: "institutional", 5: "residential", 6: "commercial", 7: "construction", 8: "industrial" } },
    counts, rle: s.join(","), pts,
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([payload], { type: "application/json" }));
  a.download = "nchoe_landuse_osm.json"; document.body.appendChild(a); a.click();
  console.log("Saved. Classes [features, cells]:", counts, "point sources:", pts.length);
})();
