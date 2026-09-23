/*
 * Dashboard shell: panels, theme, toasts, drag-and-drop import, layer and station lists.
 * Loaded before app.js. The analysis code in app.js exposes window.OGS and fires
 * "ogs:ready" / "ogs:update"; this file only arranges and mirrors that state.
 */
(function () {
  "use strict";

  const root = document.documentElement;
  const shell = document.getElementById("app-shell");
  const data = window.NCHOE_DASHBOARD_DATA || {};
  const hasData = Array.isArray(data.records) && data.records.length > 0;
  const mobileQuery = window.matchMedia("(max-width: 900px)");
  const $ = (id) => document.getElementById(id);

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (_error) {
      return null;
    }
    return null;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function afterLayoutChange() {
    // Plotly charts listen for window resize; Leaflet needs its own nudge.
    window.dispatchEvent(new Event("resize"));
    window.OGS?.map?.invalidateSize({ pan: false });
  }

  /* ---------- Initial shell state ---------- */

  document.body.classList.toggle("is-empty", !hasData);
  const savedDrawerWidth = Number(store("ogs-drawer-width"));
  if (Number.isFinite(savedDrawerWidth) && savedDrawerWidth >= 340) {
    root.style.setProperty("--drawer-w", `${savedDrawerWidth}px`);
  }
  setLayersOpen(mobileQuery.matches ? false : store("ogs-layers-open") !== "0", false);
  setAnalysisOpen(hasData && store("ogs-analysis-open") !== "0", false);
  setImportOpen(!hasData);
  if (mobileQuery.matches) {
    setCollapsed("toggle-legend", document.querySelector(".legend-card"), true);
  }
  if (mobileQuery.matches) {
    setCollapsed("toggle-screening", document.querySelector(".suitability-panel"), true);
  }
  $("empty-state").hidden = hasData;

  /* ---------- Panels ---------- */

  function setLayersOpen(open, persist = true) {
    shell.classList.toggle("layers-collapsed", !open);
    $("toggle-layers-panel").setAttribute("aria-expanded", String(open));
    $("layers-panel").inert = !open;
    if (persist && !mobileQuery.matches) store("ogs-layers-open", open ? "1" : "0");
  }

  function setAnalysisOpen(open, persist = true) {
    shell.classList.toggle("analysis-collapsed", !open);
    $("toggle-analysis").setAttribute("aria-expanded", String(open));
    $("toggle-analysis").classList.toggle("is-active", open);
    if (persist) store("ogs-analysis-open", open ? "1" : "0");
  }

  function setImportOpen(open) {
    $("import-panel").hidden = !open;
    $("add-data-toggle").setAttribute("aria-expanded", String(open));
  }

  function setCollapsed(buttonId, card, collapsed) {
    if (!card) return;
    card.classList.toggle("is-collapsed", collapsed);
    $(buttonId)?.setAttribute("aria-expanded", String(!collapsed));
  }

  $("toggle-layers-panel").addEventListener("click", () => {
    setLayersOpen(shell.classList.contains("layers-collapsed"));
    setTimeout(afterLayoutChange, 260);
  });
  $("toggle-analysis").addEventListener("click", () => {
    setAnalysisOpen(shell.classList.contains("analysis-collapsed"));
    setTimeout(afterLayoutChange, 260);
  });
  $("close-analysis").addEventListener("click", () => {
    setAnalysisOpen(false);
    setTimeout(afterLayoutChange, 260);
  });
  // On phones the analysis sheet header works as a pull tab.
  document.querySelector(".drawer-header").addEventListener("click", (event) => {
    if (!mobileQuery.matches || event.target.closest("button")) return;
    setAnalysisOpen(shell.classList.contains("analysis-collapsed"));
  });
  $("add-data-toggle").addEventListener("click", () => setImportOpen($("import-panel").hidden));
  $("empty-add-data").addEventListener("click", () => {
    setLayersOpen(true);
    setImportOpen(true);
    submitOnChoose = true;
    $("csv-file").click();
  });
  $("toggle-screening").addEventListener("click", () => {
    const card = document.querySelector(".suitability-panel");
    setCollapsed("toggle-screening", card, !card.classList.contains("is-collapsed"));
  });
  $("toggle-legend").addEventListener("click", () => {
    const card = document.querySelector(".legend-card");
    setCollapsed("toggle-legend", card, !card.classList.contains("is-collapsed"));
  });
  $("topbar-parameter").addEventListener("click", () => {
    setLayersOpen(true);
    const search = $("parameter-search");
    search.scrollIntoView({ block: "nearest", behavior: "smooth" });
    setTimeout(() => search.focus({ preventScroll: true }), 150);
  });

  /* ---------- Drawer resize ---------- */

  const resizeHandle = $("drawer-resize");
  function clampDrawerWidth(width) {
    return Math.round(Math.max(360, Math.min(width, Math.min(900, window.innerWidth - 420))));
  }
  function setDrawerWidth(width) {
    const next = clampDrawerWidth(width);
    root.style.setProperty("--drawer-w", `${next}px`);
    store("ogs-drawer-width", String(next));
  }
  resizeHandle.addEventListener("pointerdown", (event) => {
    if (mobileQuery.matches) return;
    event.preventDefault();
    resizeHandle.setPointerCapture(event.pointerId);
    document.body.classList.add("is-resizing");
    const move = (moveEvent) => setDrawerWidth(window.innerWidth - moveEvent.clientX - 12);
    const stop = () => {
      document.body.classList.remove("is-resizing");
      resizeHandle.removeEventListener("pointermove", move);
      resizeHandle.removeEventListener("pointerup", stop);
      resizeHandle.removeEventListener("pointercancel", stop);
      afterLayoutChange();
    };
    resizeHandle.addEventListener("pointermove", move);
    resizeHandle.addEventListener("pointerup", stop);
    resizeHandle.addEventListener("pointercancel", stop);
  });
  resizeHandle.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const current = $("analysis-drawer").getBoundingClientRect().width;
    setDrawerWidth(current + (event.key === "ArrowLeft" ? 32 : -32));
    afterLayoutChange();
  });

  /* ---------- Drawer section tabs (scroll-spy) ---------- */

  const analysisBody = $("analysis-body");
  const tabButtons = Array.from(document.querySelectorAll(".drawer-tabs [data-target]"));
  tabButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const target = $(button.dataset.target);
      if (!target) return;
      analysisBody.scrollTo({ top: target.offsetTop - 8, behavior: "smooth" });
    });
  });
  function syncActiveTab() {
    const top = analysisBody.scrollTop + 40;
    let active = tabButtons[0];
    tabButtons.forEach((button) => {
      const section = $(button.dataset.target);
      if (section && section.offsetTop <= top) active = button;
    });
    if (analysisBody.scrollTop + analysisBody.clientHeight >= analysisBody.scrollHeight - 4) active = tabButtons[tabButtons.length - 1];
    tabButtons.forEach((button) => button.classList.toggle("is-active", button === active));
  }
  analysisBody.addEventListener("scroll", () => requestAnimationFrame(syncActiveTab), { passive: true });

  /* ---------- Theme ---------- */

  function syncThemeButton() {
    const dark = root.dataset.theme !== "light";
    $("theme-toggle").title = dark ? "Switch to light theme" : "Switch to dark theme";
  }
  syncThemeButton();
  $("theme-toggle").addEventListener("click", () => {
    const next = root.dataset.theme === "light" ? "dark" : "light";
    root.dataset.theme = next;
    store("ogs-theme", next);
    syncThemeButton();
    const api = window.OGS;
    if (!api) return;
    api.refreshTheme();
  });

  /* ---------- Map controls ---------- */

  const basemapButton = $("map-basemap-button");
  const basemapPopover = $("basemap-popover");
  function setBasemapPopover(open) {
    basemapPopover.hidden = !open;
    basemapButton.setAttribute("aria-expanded", String(open));
  }
  basemapButton.addEventListener("click", (event) => {
    event.stopPropagation();
    setBasemapPopover(basemapPopover.hidden);
  });
  basemapPopover.addEventListener("click", (event) => {
    if (event.target.closest("[data-basemap]")) setBasemapPopover(false);
  });
  document.addEventListener("click", (event) => {
    if (!basemapPopover.hidden && !event.target.closest(".map-controls")) setBasemapPopover(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setBasemapPopover(false);
  });
  $("map-zoom-in").addEventListener("click", () => window.OGS?.map.zoomIn());
  $("map-zoom-out").addEventListener("click", () => window.OGS?.map.zoomOut());
  $("map-fit").addEventListener("click", () => window.OGS?.fitStations());

  /* ---------- Map padding for fitBounds ---------- */

  window.OGS_UI = {
    // Space covered by floating panels, so fitted stations land in the visible map.
    viewPadding() {
      const map = $("map").getBoundingClientRect();
      const visible = (element) => element && !element.closest(".is-collapsed") && element.getBoundingClientRect().width > 0;
      let left = 32;
      let right = 32;
      let top = 32;
      let bottom = 32;
      const layers = $("layers-panel");
      if (!shell.classList.contains("layers-collapsed") && !mobileQuery.matches) {
        left = Math.max(left, layers.getBoundingClientRect().right - map.left + 32);
      }
      const drawer = $("analysis-drawer");
      if (!shell.classList.contains("analysis-collapsed")) {
        const rect = drawer.getBoundingClientRect();
        if (mobileQuery.matches) bottom = Math.max(bottom, map.bottom - rect.top + 24);
        else right = Math.max(right, map.right - rect.left + 32);
      }
      right += 52;
      const toolbar = document.querySelector(".map-toolbar");
      if (visible(toolbar)) top = Math.max(top, toolbar.getBoundingClientRect().bottom - map.top + 24);
      const bottomStack = document.querySelector(".map-bottom");
      if (visible(bottomStack)) bottom = Math.max(bottom, map.bottom - bottomStack.getBoundingClientRect().top + 24);
      return { topLeft: [Math.round(left), Math.round(top)], bottomRight: [Math.round(right), Math.round(bottom)] };
    },
  };

  /* ---------- Toasts ---------- */

  const toastRegion = $("toast-region");
  function toast(message, tone = "info") {
    if (!message) return;
    const item = document.createElement("div");
    item.className = `toast toast-${tone}`;
    item.setAttribute("role", tone === "error" ? "alert" : "status");
    item.textContent = message;
    toastRegion.appendChild(item);
    requestAnimationFrame(() => item.classList.add("is-visible"));
    const remove = () => {
      item.classList.remove("is-visible");
      setTimeout(() => item.remove(), 250);
    };
    setTimeout(remove, tone === "error" ? 8000 : 4200);
    item.addEventListener("click", remove);
  }
  function toneFor(text) {
    if (/fail|error|could not|unsupported|invalid|unavailable/i.test(text)) return "error";
    if (/loaded|stations have elevations/i.test(text)) return "success";
    return "info";
  }
  // Mirror the existing status lines as toasts without changing how they are written.
  ["csv-upload-status", "elevation-status"].forEach((id) => {
    const element = $(id);
    if (!element) return;
    let last = "";
    const announce = () => {
      const text = element.textContent.trim();
      if (text && text !== last) toast(text, toneFor(text));
      last = text;
    };
    new MutationObserver(announce).observe(element, { childList: true, characterData: true, subtree: true });
    // Messages restored from sessionStorage are written after this script runs.
    setTimeout(announce, 0);
  });

  /* ---------- Drag and drop import ---------- */

  const dropOverlay = $("drop-overlay");
  const fileInput = $("csv-file");
  let dragDepth = 0;
  var submitOnChoose = false;
  const hasFiles = (event) => Array.from(event.dataTransfer?.types || []).includes("Files");
  window.addEventListener("dragenter", (event) => {
    if (!hasFiles(event)) return;
    dragDepth += 1;
    dropOverlay.hidden = false;
  });
  window.addEventListener("dragleave", (event) => {
    if (!hasFiles(event)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) dropOverlay.hidden = true;
  });
  window.addEventListener("dragover", (event) => {
    if (hasFiles(event)) event.preventDefault();
  });
  window.addEventListener("drop", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    dragDepth = 0;
    dropOverlay.hidden = true;
    if (fileInput.disabled || !event.dataTransfer.files.length) return;
    fileInput.files = event.dataTransfer.files;
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    $("csv-upload-form").requestSubmit($("csv-upload-button"));
  });
  fileInput.addEventListener("change", () => {
    const names = Array.from(fileInput.files || []).map((file) => file.name);
    $("csv-file-names").textContent = names.length ? names.join(", ") : "";
    // Files picked from the empty-state button import straight away.
    if (submitOnChoose && names.length) {
      submitOnChoose = false;
      $("csv-upload-form").requestSubmit($("csv-upload-button"));
    }
  });

  /* ---------- Data layer list (mirrors the Active CSV select) ---------- */

  const selector = $("csv-dataset-select");
  function renderLayerList() {
    const list = $("layer-list");
    const options = Array.from(selector.options).filter((option) => option.value);
    const summary = data.summary || {};
    list.replaceChildren();
    if (!options.length) {
      list.innerHTML = '<p class="list-empty">No data yet. Add a file to create a layer.</p>';
      return;
    }
    options.forEach((option) => {
      const active = option.value === selector.value;
      const row = document.createElement("button");
      row.type = "button";
      row.className = `layer-row${active ? " is-active" : ""}`;
      row.setAttribute("aria-pressed", String(active));
      row.dataset.id = option.value;
      const meta = active && Number.isFinite(summary.recordCount)
        ? `${summary.recordCount.toLocaleString()} rows · ${summary.mappedLocationCount ?? 0} stations`
        : "Click to switch";
      row.innerHTML = `
        <span class="layer-icon"><svg class="i"><use href="#i-file"/></svg></span>
        <span class="layer-text"><strong title="${escapeHtml(option.textContent)}">${escapeHtml(option.textContent)}</strong><small>${escapeHtml(meta)}</small></span>
        <span class="layer-radio" aria-hidden="true"></span>`;
      row.addEventListener("click", () => {
        if (active || selector.disabled) return;
        selector.value = option.value;
        selector.dispatchEvent(new Event("change"));
      });
      list.appendChild(row);
    });
  }
  new MutationObserver(renderLayerList).observe(selector, { childList: true, attributes: true, attributeFilter: ["disabled"] });
  selector.addEventListener("change", renderLayerList);
  renderLayerList();

  /* ---------- Parameter filter ---------- */

  const parameterTabs = $("parameter-tabs");
  const parameterSearch = $("parameter-search");
  function applyParameterFilter() {
    const query = parameterSearch.value.trim().toLowerCase();
    const buttons = Array.from(parameterTabs.querySelectorAll("button"));
    buttons.forEach((button) => {
      button.hidden = Boolean(query) && !button.textContent.toLowerCase().includes(query);
    });
    $("parameter-count").textContent = String(buttons.length);
  }
  parameterSearch.addEventListener("input", applyParameterFilter);
  new MutationObserver(applyParameterFilter).observe(parameterTabs, { childList: true });

  /* ---------- Station list and context labels ---------- */

  const stationSearch = $("station-search");
  function renderStations() {
    const api = window.OGS;
    const list = $("station-list");
    if (!api) return;
    const stations = api.getStations();
    const query = stationSearch.value.trim().toLowerCase();
    $("station-count").textContent = String(stations.length);
    list.replaceChildren();
    if (!stations.length) {
      list.innerHTML = '<p class="list-empty">Stations with coordinates appear here.</p>';
      return;
    }
    stations
      .filter((station) => !query || station.name.toLowerCase().includes(query))
      .sort((a, b) => a.name.localeCompare(b.name))
      .forEach((station) => {
        const row = document.createElement("button");
        row.type = "button";
        row.className = `station-row${station.active ? " is-active" : ""}`;
        row.title = `${station.name}: ${station.statusLabel}`;
        row.innerHTML = `
          <span class="status-dot status-${escapeHtml(station.status)}" aria-hidden="true"></span>
          <span class="station-text">
            <span class="station-name">${escapeHtml(station.name)}</span>
            <span class="station-value">${escapeHtml(station.latest || "No value for this period")}</span>
          </span>
          <span class="sr-only">${escapeHtml(station.statusLabel)}</span>`;
        row.addEventListener("click", () => {
          api.selectLocation(station.name);
          if (mobileQuery.matches) setLayersOpen(false);
        });
        list.appendChild(row);
      });
  }
  stationSearch.addEventListener("input", renderStations);

  function renderContext() {
    const api = window.OGS;
    if (!api) return;
    const state = api.getState();
    $("topbar-parameter-name").textContent = state.parameter || "No parameter";
    $("analysis-context").textContent = state.location || (state.hasData ? "Select a station" : "No data loaded");
    const period = state.period === "annual" ? "Annual" : state.period.charAt(0).toUpperCase() + state.period.slice(1);
    const year = state.year === "all" ? "all years" : String(state.year);
    $("analysis-subtitle").textContent = state.parameter
      ? `${state.parameter}${state.unit ? ` (${state.unit})` : ""} · ${period}, ${year}`
      : "Import a file and choose a parameter.";
  }

  function onUpdate() {
    renderStations();
    renderContext();
    applyParameterFilter();
  }
  window.addEventListener("ogs:ready", onUpdate);
  window.addEventListener("ogs:update", onUpdate);

  /* ---------- Responsive changes ---------- */

  mobileQuery.addEventListener("change", (event) => {
    setLayersOpen(!event.matches && store("ogs-layers-open") !== "0", false);
    setTimeout(afterLayoutChange, 50);
  });
})();
