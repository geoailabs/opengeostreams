(function () {
  // All dashboard data is prebuilt into a global object before this script runs.
  const dashboardData = window.NCHOE_DASHBOARD_DATA;
  // Keep the upload controls and the visualization code on the same active payload.
  window.NCHOE_DASHBOARD_DATA = dashboardData;

  // Stop early with a visible message if the generated dashboard payload is missing.
  if (!dashboardData || !Array.isArray(dashboardData.records)) {
    document.getElementById("location-name").textContent = "Dashboard data not found";
    document.getElementById("location-meta").textContent = "Start dashboard_server.py to generate dashboard data.";
    return;
  }

  // Central UI state. Every user interaction updates some part of this object.
  const state = {
    selectedLocation: null,
    selectedParameter: null,
    selectedTimelineKey: null,
    selectedPeriod: "annual",
    selectedYear: "all",
    baseMap: "osm",
    selectedUseCase: "human_consumption",
    boxplotGrouping: "year",
  };

  // Month options used by the period filter and monthly chart logic.
  const MONTH_OPTIONS = [
    { key: "jan", label: "Jan", monthIndex: 1 },
    { key: "feb", label: "Feb", monthIndex: 2 },
    { key: "mar", label: "Mar", monthIndex: 3 },
    { key: "apr", label: "Apr", monthIndex: 4 },
    { key: "may", label: "May", monthIndex: 5 },
    { key: "jun", label: "Jun", monthIndex: 6 },
    { key: "jul", label: "Jul", monthIndex: 7 },
    { key: "aug", label: "Aug", monthIndex: 8 },
    { key: "sep", label: "Sep", monthIndex: 9 },
    { key: "oct", label: "Oct", monthIndex: 10 },
    { key: "nov", label: "Nov", monthIndex: 11 },
    { key: "dec", label: "Dec", monthIndex: 12 },
  ];

  // Separate month labels for weather aggregation and chart rendering.
  const WEATHER_MONTHS = [
    { key: 1, label: "Jan" },
    { key: 2, label: "Feb" },
    { key: 3, label: "Mar" },
    { key: 4, label: "Apr" },
    { key: 5, label: "May" },
    { key: 6, label: "Jun" },
    { key: 7, label: "Jul" },
    { key: 8, label: "Aug" },
    { key: 9, label: "Sep" },
    { key: 10, label: "Oct" },
    { key: 11, label: "Nov" },
    { key: 12, label: "Dec" },
  ];

  // Fixed Y-axis width keeps the chart area aligned even when tick labels change.
  // These are the four suitability modes the user can switch between.
  const USE_CASES = [
    { key: "human_consumption", label: "Human Consumption" },
    { key: "agriculture", label: "Agriculture" },
    { key: "aquatic_life", label: "Aquatic Life" },
    { key: "bathing", label: "Bathing" },
  ];
  // Marker colors on the map depend on the screening result for the chosen use case.
  const SUITABILITY_COLORS = {
    safe: "#16a34a",
    caution: "#d97706",
    unsafe: "#dc2626",
    unknown: "#64748b",
  };
  // For each use case, this maps our internal screening fields to dataset parameter names.
  // "confirmed" means we trust that CSV field directly. "proxy" means it is only a near match.
  const SCREENING_PARAMETER_SPECS = {
    human_consumption: [
      { key: "pH", confirmed: ["pH"] },
      { key: "turbidity_ntu", confirmed: ["Turbidity"] },
      { key: "tds_mg_l", confirmed: ["TDS"] },
      { key: "nitrate_mg_l", confirmed: [], proxy: ["NO3-N", "Nitrate"] },
      { key: "fluoride_mg_l", confirmed: ["Fluoride"] },
      { key: "chloride_mg_l", confirmed: ["Chloride"] },
      { key: "sulphate_mg_l", confirmed: ["Sulphate", "SO4"] },
      { key: "hardness_mg_l_as_caco3", confirmed: ["TH as CaCO3"] },
      { key: "alkalinity_mg_l_as_caco3", confirmed: ["Total alkalinity as CaCO3"], proxy: ["P-Alkalinity"] },
      { key: "total_coliform_mpn_100ml", confirmed: ["Total Coliform", "T-Coliform"] },
      { key: "e_coli_present", confirmed: [] },
    ],
    agriculture: [
      { key: "pH", confirmed: ["pH"] },
      { key: "ec_us_cm", confirmed: [], proxy: ["Conductivity"] },
      { key: "sar", confirmed: [] },
      { key: "boron_mg_l", confirmed: ["Boron(B)"] },
      { key: "chloride_mg_l", confirmed: ["Chloride"] },
      { key: "nitrate_mg_l", confirmed: [], proxy: ["NO3-N", "Nitrate"] },
      { key: "bicarbonate_mg_l", confirmed: [] },
      { key: "carbonate_mg_l", confirmed: [] },
      { key: "rsc_meq_l", confirmed: [] },
    ],
    aquatic_life: [
      { key: "pH", confirmed: ["pH"] },
      { key: "dissolved_oxygen_mg_l", confirmed: ["DO"] },
      { key: "free_ammonia_mg_l_as_n", confirmed: [], proxy: ["NH3-N"] },
      { key: "bod_mg_l", confirmed: ["BOD"] },
      { key: "nitrate_mg_l", confirmed: [], proxy: ["NO3-N", "Nitrate"] },
      { key: "phosphate_mg_l", confirmed: ["Phosphate"], proxy: ["Phosphate-P"] },
      { key: "turbidity_ntu", confirmed: ["Turbidity"] },
      { key: "temperature_c", confirmed: ["Temperature"] },
    ],
    bathing: [
      { key: "pH", confirmed: ["pH"] },
      { key: "dissolved_oxygen_mg_l", confirmed: ["DO"] },
      { key: "bod_mg_l", confirmed: ["BOD"] },
      { key: "total_coliform_mpn_100ml", confirmed: ["Total Coliform", "T-Coliform"] },
      { key: "fecal_coliform_mpn_100ml", confirmed: ["Faecal Coliform"] },
      { key: "turbidity_ntu", confirmed: ["Turbidity"] },
      { key: "e_coli_present", confirmed: [] },
    ],
  };
  // Core keys are the minimum checks needed before we can confidently classify a site.
  const CORE_KEYS_BY_USE_CASE = {
    human_consumption: ["pH", "turbidity_ntu", "tds_mg_l", "nitrate_mg_l", "fluoride_mg_l", "total_coliform_mpn_100ml", "e_coli_present"],
    agriculture: ["pH", "ec_us_cm", "sar", "boron_mg_l"],
    aquatic_life: ["pH", "dissolved_oxygen_mg_l", "free_ammonia_mg_l_as_n"],
    bathing: ["pH", "dissolved_oxygen_mg_l", "bod_mg_l", "total_coliform_mpn_100ml", "fecal_coliform_mpn_100ml", "e_coli_present"],
  };
  // Threshold metadata for the parameter safety scale panel.
  const PARAMETER_SCALE_DEFINITIONS = {
    human_consumption: {
      ph: { label: "pH", type: "range", safeMin: 6.5, safeMax: 8.5, domainMin: 0, domainMax: 14 },
      turbidity: { label: "Turbidity", type: "max", safeMax: 1.0, unit: "NTU" },
      tds: { label: "TDS", type: "max", safeMax: 500, unit: "mg/L" },
      nitrate: { label: "Nitrate", type: "max", safeMax: 45, unit: "mg/L" },
      fluoride: { label: "Fluoride", type: "max", safeMax: 1.0, unit: "mg/L" },
      chloride: { label: "Chloride", type: "max", safeMax: 250, unit: "mg/L" },
      sulphate: { label: "Sulphate", type: "max", safeMax: 200, unit: "mg/L" },
      hardness: { label: "Hardness", type: "max", safeMax: 200, unit: "mg/L as CaCO3" },
      alkalinity: { label: "Alkalinity", type: "max", safeMax: 200, unit: "mg/L as CaCO3" },
      total_coliform: { label: "Total Coliform", type: "max", safeMax: 0, unit: "MPN/100mL", domainMin: 0, domainMax: 1000 },
    },
    agriculture: {
      ph: { label: "pH", type: "range", safeMin: 6.0, safeMax: 8.5, domainMin: 0, domainMax: 14 },
      conductivity: { label: "Conductivity", type: "max", safeMax: 2250, unit: "uS/cm" },
      boron: { label: "Boron", type: "max", safeMax: 2.0, unit: "mg/L", domainMin: 0, domainMax: 4 },
      chloride: { label: "Chloride", type: "max", safeMax: 140, unit: "mg/L" },
      nitrate: { label: "Nitrate", type: "max", safeMax: 30, unit: "mg/L" },
    },
    aquatic_life: {
      ph: { label: "pH", type: "range", safeMin: 6.5, safeMax: 8.5, domainMin: 0, domainMax: 14 },
      do: { label: "Dissolved Oxygen", type: "min", safeMin: 4.0, unit: "mg/L", domainMin: 0, domainMax: 10 },
      ammonia: { label: "Free Ammonia", type: "max", safeMax: 1.2, unit: "mg/L as N", domainMin: 0, domainMax: 3 },
      bod: { label: "BOD", type: "max", safeMax: 3.0, unit: "mg/L", domainMin: 0, domainMax: 10 },
      nitrate: { label: "Nitrate", type: "max", safeMax: 10, unit: "mg/L" },
      phosphate: { label: "Phosphate", type: "max", safeMax: 0.1, unit: "mg/L", domainMin: 0, domainMax: 1 },
      turbidity: { label: "Turbidity", type: "max", safeMax: 25, unit: "NTU" },
      temperature: { label: "Temperature", type: "max", safeMax: 32, unit: "°C", domainMin: 0, domainMax: 40 },
    },
    bathing: {
      ph: { label: "pH", type: "range", safeMin: 6.5, safeMax: 8.5, domainMin: 0, domainMax: 14 },
      do: { label: "Dissolved Oxygen", type: "min", safeMin: 5.0, unit: "mg/L", domainMin: 0, domainMax: 10 },
      bod: { label: "BOD", type: "max", safeMax: 3.0, unit: "mg/L", domainMin: 0, domainMax: 10 },
      total_coliform: { label: "Total Coliform", type: "max", safeMax: 0, unit: "MPN/100mL", domainMin: 0, domainMax: 2000 },
      fecal_coliform: { label: "Faecal Coliform", type: "max", safeMax: 0, unit: "MPN/100mL", domainMin: 0, domainMax: 2000 },
      turbidity: { label: "Turbidity", type: "max", safeMax: 10, unit: "NTU" },
    },
  };
  const GLOBAL_PARAMETER_SCALE_DEFINITIONS = {
    total_coliform: { label: "Total Coliform", type: "max", safeMax: 0, unit: "MPN/100mL", domainMin: 0, domainMax: 2000 },
    fecal_coliform: { label: "Faecal Coliform", type: "max", safeMax: 0, unit: "MPN/100mL", domainMin: 0, domainMax: 2000 },
  };
  const PARAMETER_DESCRIPTIONS = {
    "BOD": "Oxygen used by microbes to break down organic matter.",
    "Boron(B)": "Boron level, important for irrigation suitability.",
    "COD": "Oxygen needed to chemically oxidize pollutants.",
    "Ca as CaCO3": "Calcium hardness expressed as CaCO3.",
    "Chloride": "Dissolved chloride salt concentration.",
    "Colour": "Water colour from dissolved or suspended material.",
    "Conductivity": "Indicator of dissolved ions and salinity.",
    "DO": "Oxygen available for aquatic life.",
    "FS": "Mineral fraction of total solids.",
    "Faecal Coliform": "Indicator of fecal contamination.",
    "Fixed Suspended Solids": "Mineral fraction of suspended particles.",
    "Fluoride": "Dissolved fluoride concentration.",
    "Mg as CaCO3": "Magnesium hardness expressed as CaCO3.",
    "NH3-N": "Ammonia nitrogen from waste or decay.",
    "NO2-N": "Nitrite nitrogen, often a pollution indicator.",
    "NO3-N": "Nitrate nitrogen from fertilizers or sewage.",
    "P-Alkalinity": "Carbonate/hydroxide alkalinity above pH 8.3.",
    "Phosphate": "Nutrient that can drive algal growth.",
    "Phosphate-P": "Phosphate reported as phosphorus.",
    "Potassium": "Dissolved potassium ion concentration.",
    "SO4": "Dissolved sulfate concentration.",
    "Sodium": "Dissolved sodium affecting salinity and soils.",
    "Sulphate": "Dissolved sulfate concentration.",
    "T-Coliform": "Broad sanitary indicator bacteria.",
    "TDS": "Dissolved salts, minerals, and organics.",
    "TH as CaCO3": "Total calcium and magnesium hardness.",
    "TKN": "Organic nitrogen plus ammonia.",
    "TSS": "Suspended particles in the water.",
    "Temperature": "Water temperature affecting oxygen and habitat.",
    "Total Coliform": "Broad sanitary indicator bacteria.",
    "Total alkalinity as CaCO3": "Water's acid-neutralizing capacity.",
    "Turbidity": "Cloudiness from suspended particles.",
    "VSS": "Organic fraction of suspended solids.",
    "pH": "How acidic or basic the water is.",
  };

  // Cache DOM references once so we do not repeatedly query the page. So that code can update UI easily
  const els = {
    heroCard: document.getElementById("hero-card"),
    heroToggle: document.getElementById("hero-toggle"),
    heroDetails: document.getElementById("hero-details"),
    locationBadge: document.getElementById("location-badge"),
    locationSelect: document.getElementById("location-select"),
    locationName: document.getElementById("location-name"),
    locationMeta: document.getElementById("location-meta"),
    locationCoords: document.getElementById("location-coords"),
    parameterUnit: document.getElementById("parameter-unit"),
    parameterTabs: document.getElementById("parameter-tabs"),
    valueSummary: document.getElementById("value-summary"),
    trendChart: document.getElementById("trend-chart"),
    trendEmpty: document.getElementById("trend-empty"),
    boxplotChart: document.getElementById("boxplot-chart"),
    boxplotEmpty: document.getElementById("boxplot-empty"),
    boxplotGrouping: document.getElementById("boxplot-grouping"),
    boxplotTooltip: document.getElementById("boxplot-tooltip"),
    weatherStatus: document.getElementById("weather-status"),
    streamVisualization: document.getElementById("stream-visualization"),
    streamStatus: document.getElementById("stream-status"),
    periodPanel: document.getElementById("period-panel"),
    periodFilter: document.getElementById("period-filter"),
    yearFilter: document.getElementById("year-filter"),
    mappedCount: document.getElementById("mapped-count"),
    parameterScale: document.getElementById("parameter-scale"),
    mapNote: document.getElementById("map-note"),
    basemapToggle: document.getElementById("basemap-toggle"),
    useCaseTabs: document.getElementById("use-case-tabs"),
    suitabilitySummary: document.getElementById("suitability-summary"),
    suitabilityDetail: document.getElementById("suitability-detail"),
  };

  // Fast lookup stores used throughout the dashboard. Builds maps and caches
  const locationIndex = new Map();
  const groupedRecords = new Map();
  const markers = new Map();
  const figureRequests = new Map();
  let interpolationData = null;
  let interpolationOverlay = null;
  let interpolationEnabled = true;
  let interpolationRequest = null;

  function clearLibraryFigure(kind, element, empty, message) {
    figureRequests.get(kind)?.abort();
    figureRequests.delete(kind);
    if (kind === "distribution") { els.boxplotTooltip?.classList.add("is-hidden"); }
    if (!element) return;
    element.removeAttribute("aria-busy");
    if (window.Plotly && element.data) Plotly.purge(element);
    if (empty) {
      element.style.visibility = "hidden";
      empty.textContent = message;
      empty.classList.remove("is-hidden");
    } else {
      element.textContent = message;
    }
  }

  function installBoxplotHover(element, statistics) {
    const tooltip = els.boxplotTooltip;
    if (!tooltip) return;
    if (tooltip.parentElement !== document.body) {
      document.body.appendChild(tooltip);
      element.addEventListener("pointerleave", () => tooltip.classList.add("is-hidden"));
    }
    tooltip.classList.add("is-hidden");
    element.removeAllListeners("plotly_hover");
    element.removeAllListeners("plotly_unhover");
    element.on("plotly_hover", event => {
      const point = event.points.find(point => point.curveNumber === 0) || event.points[0];
      if (!point) { tooltip.classList.add("is-hidden"); return; }
      const item = statistics.find(item => item.group === String(point.x)) || statistics[point.pointNumber];
      if (!item) return;
      const fields = [["min", "Minimum"], ["q1", "Q1"], ["median", "Median"], ["q3", "Q3"],
        ["max", "Maximum"], ["mean", "Mean"], ["iqr", "IQR"], ["count", "Sample count"],
        ["lowerWhisker", "Lower whisker"], ["upperWhisker", "Upper whisker"]];
      tooltip.innerHTML = `<strong>${escapeHtml(state.selectedParameter)} &mdash; ${escapeHtml(item.group)}</strong><dl>` +
        fields.map(([key, label]) => `<div><dt>${label}</dt><dd>${Number(item[key]).toLocaleString(undefined, {maximumSignificantDigits: 6})}</dd></div>`).join("") + "</dl>";
      tooltip.classList.remove("is-hidden");
      const bounds = element.getBoundingClientRect();
      const x = event.event?.clientX ?? bounds.left + bounds.width / 2;
      const y = event.event?.clientY ?? bounds.top + bounds.height / 2;
      tooltip.style.left = `${Math.max(8, Math.min(x + 14, window.innerWidth - tooltip.offsetWidth - 8))}px`;
      tooltip.style.top = `${Math.max(8, Math.min(y + 14, window.innerHeight - tooltip.offsetHeight - 8))}px`;
    });
    element.on("plotly_unhover", () => tooltip.classList.add("is-hidden"));
  }

  function installTrendHover(element, kind = "trend") {
    const tooltipId = `${kind}-tooltip`;
    let tooltip = document.getElementById(tooltipId);
    if (!tooltip) {
      tooltip = document.createElement("div");
      tooltip.id = tooltipId;
      tooltip.className = "is-hidden";
      tooltip.setAttribute("role", "tooltip");
      document.body.appendChild(tooltip);
      const hide = () => tooltip.classList.add("is-hidden");
      element.addEventListener("pointerleave", hide);
      document.addEventListener("scroll", hide, true);
      document.addEventListener("pointerdown", hide, true);
      document.addEventListener("keydown", hide);
      window.addEventListener("blur", hide);
      window.addEventListener("resize", hide);
      document.addEventListener("visibilitychange", hide);
      document.addEventListener("pointermove", event => {
        if (!element.contains(event.target)) hide();
      });
    }
    tooltip.classList.add("is-hidden");
    element.removeAllListeners("plotly_hover");
    element.removeAllListeners("plotly_unhover");
    element.on("plotly_hover", event => {
      const point = event.points?.[0];
      if (!point) return;
      if (kind === "stream" && !Number.isFinite(point.z)) { tooltip.classList.add("is-hidden"); return; }
      const data = point.customdata || [];
      const rain = point.data.yaxis === "y2";
      const fields = [["Location", data[0]], ["Period", data[1]],
        [rain ? "Precipitation total" : point.data.name || "Value", `${formatCompactNumber(point.y)} ${data[2] || ""}`],
        ["Source", data[3]]];
      if (kind === "stream") {
        fields.splice(0, fields.length, ["Location", point.y], ["Year", point.x], ["Parameter", state.selectedParameter], ["Mean value", formatCompactNumber(point.z)]);
      } else if (!rain && data[4] != null) fields.push(["Precipitation total", data[4]]);
      tooltip.innerHTML = fields.map(([label, value]) => `<div><strong>${escapeHtml(label)}</strong><span>${escapeHtml(String(value ?? "Unavailable"))}</span></div>`).join("");
      tooltip.classList.remove("is-hidden");
      const bounds = element.getBoundingClientRect();
      const x = event.event?.clientX ?? bounds.right;
      const y = event.event?.clientY ?? bounds.top;
      tooltip.style.left = `${Math.max(8, Math.min(x + 14, window.innerWidth - tooltip.offsetWidth - 8))}px`;
      tooltip.style.top = `${Math.max(8, Math.min(y + 14, window.innerHeight - tooltip.offsetHeight - 8))}px`;
    });
    element.on("plotly_unhover", () => tooltip.classList.add("is-hidden"));
  }

  let streamPage = 0;
  const streamPageSize = 8;

  function chartLayout(kind, figure) {
    const heatmap = figure.data.find(trace => trace.type === "heatmap");
    const stationCount = kind === "stream" ? (heatmap?.y?.length || 0) : 0;
    const axis = (original, title) => ({
      ...original, automargin: true, nticks: 4,
      tickfont: {size: 11},
      title: {...original?.title, ...(title ? {text: title} : {}), standoff: 10}
    });
    const layout = {
      ...figure.layout, autosize: true, width: undefined,
      height: kind === "stream" ? Math.max(280, Math.min(stationCount, streamPageSize) * 42 + 180) : kind === "interpolation" ? 440 : 380,
      margin: {l: kind === "stream" ? 110 : 48, r: kind === "stream" ? 14 : kind === "trend" ? 48 : 42, t: 35, b: kind === "stream" ? 140 : kind === "trend" ? 95 : 65},
      title: {...figure.layout.title, text: ""},
      font: {family: "Manrope, sans-serif", size: 12},
      legend: {...figure.layout.legend, orientation: "h", x: 0, xanchor: "left", y: -0.26, yanchor: "top", font: {size: 10}},
      hoverlabel: {bgcolor: "#ffffff", bordercolor: "#0f766e", font: {family: "Manrope, sans-serif", size: 12, color: "#162020"}},
      xaxis: axis(figure.layout.xaxis),
      yaxis: axis(figure.layout.yaxis)
    };
    if (kind === "trend") {
      layout.annotations = (layout.annotations || []).filter(annotation => !annotation.text.startsWith("Precipitation unavailable"));
      layout.yaxis2 = axis(figure.layout.yaxis2);
      layout.yaxis.tickformat = ".4~g";
      layout.yaxis2.tickformat = ".4~g";
    } else if (kind === "distribution") {
      layout.yaxis.tickformat = ".4~g";
    } else if (kind === "stream" && heatmap) {
      layout.yaxis.title.text = "";
      layout.yaxis.autorange = false;
      layout.yaxis.range = [Math.min(stationCount, (streamPage + 1) * streamPageSize) - 0.5, streamPage * streamPageSize - 0.5];
      layout.xaxis.title.standoff = 8;
      layout.yaxis.tickmode = "array";
      layout.yaxis.tickvals = heatmap.y;
      layout.yaxis.ticktext = heatmap.y.map(name => escapeHtml(String(name).length > 18 ? String(name).slice(0, 17) + "..." : String(name)));
    } else if (kind === "interpolation") {
      layout.xaxis.constrain = "domain";
      layout.xaxis.tickformat = ".3f";
      layout.yaxis.tickformat = ".3f";
      layout.yaxis.scaleanchor = "x";
      layout.yaxis.scaleratio = 1;
      layout.yaxis.constrain = "domain";
    }
    // Keep color bars clear of the plot and prevent large values from taking over the margin.
    figure.data.forEach(trace => {
      if (trace.type === "scatter" && trace.mode?.includes("markers")) {
        const count = trace.x?.length || 0;
        trace.marker = {...trace.marker, size: count > 300 ? 3 : count > 60 ? 4 : 6, opacity: count > 300 ? 0.35 : 0.8};
      }
      if (kind === "trend" && trace.yaxis !== "y2") {
        const variant = String(trace.name).match(/\((Min|Max)\)$/i);
        if (state.selectedLocation) trace.name = variant ? `Reported ${variant[1]}` : "Measured value";
      }
      if (trace.colorbar) trace.colorbar = {...trace.colorbar, thickness: 12, len: 0.8, x: 1.02, tickformat: ".3~g", tickfont: {size: 12}};
    });
    if (kind === "stream" && heatmap) {
      layout.legend = {...layout.legend, y: -0.65, font: {size: 10}};
      heatmap.xgap = 2;
      heatmap.ygap = 2;
      heatmap.textfont = {size: 10};
      if (heatmap.x.length > 8) heatmap.texttemplate = "";
      heatmap.colorbar = {...heatmap.colorbar, orientation: "h", x: 0.5, xanchor: "center", y: -0.27,
        yanchor: "top", len: 1, thickness: 10, title: {text: "Value", side: "bottom", font: {size: 10}}, nticks: 3};
    }
    return layout;
  }

  async function renderLibraryFigure(kind, element, empty) {
    if (!element) return;
    document.getElementById(`${kind}-tooltip`)?.classList.add("is-hidden");
    if (!dashboardData.datasetId || !state.selectedParameter) {
      clearLibraryFigure(kind, element, empty, "Import a CSV and select a parameter.");
      return;
    }
    figureRequests.get(kind)?.abort();
    const controller = new AbortController();
    figureRequests.set(kind, controller);
    const query = new URLSearchParams({
      id: dashboardData.datasetId, kind, parameter: state.selectedParameter,
      year: String(state.selectedYear), grouping: state.boxplotGrouping || "year"
    });
    if (kind !== "stream" && kind !== "interpolation" && state.selectedLocation) query.set("location", state.selectedLocation);
    const month = MONTH_OPTIONS.find(item => item.key === state.selectedPeriod);
    if (month && kind !== "interpolation") query.set("month", String(month.monthIndex));
    if (empty) {
      empty.textContent = "Loading visualization...";
      empty.classList.remove("is-hidden");
    }
    if (kind === "distribution") els.boxplotTooltip?.classList.add("is-hidden");
    element.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(`/api/figure?${query}`, {signal: controller.signal});
      const figure = await response.json();
      if (!response.ok) throw new Error(figure.error || "Could not load chart.");
      if (figureRequests.get(kind) !== controller) return;
      if (!window.Plotly) throw new Error("Plotly could not load. Please refresh the dashboard.");
      if (empty) empty.classList.add("is-hidden");
      element.style.visibility = "visible";
      element.classList.remove("is-hidden");
      if (!element.data) element.replaceChildren();
      if (kind === "distribution" || kind === "trend") {
        figure.data.forEach(trace => {
          trace.hoverinfo = "none";
          delete trace.hovertemplate;
        });
        els.boxplotTooltip?.classList.add("is-hidden");
      }
      if (kind === "stream") {
        figure.data.forEach((trace, index) => { trace.hoverinfo = index === 0 ? "none" : "skip"; delete trace.hovertemplate; });
        streamPage = 0;
        const years = figure.data.find(trace => trace.type === "heatmap")?.x?.length || 0;
        element.style.minWidth = `${Math.max(0, years * 42 + 130)}px`;
      }
      if (kind === "distribution") {
        const groups = figure.layout.meta?.boxplotStatistics?.length || 0;
        element.style.minWidth = groups > 4 ? `${groups * 65 + 90}px` : "0";
      }
      const rangeNote = document.getElementById("range-note");
      rangeNote.hidden = !figure.layout.meta?.rangeNote;
      rangeNote.textContent = figure.layout.meta?.rangeNote || "";
      const layout = chartLayout(kind, figure);
      if (kind === "stream") element.style.height = `${layout.height}px`;
      await Plotly.react(element, figure.data, layout, {
        responsive: true, displaylogo: false, displayModeBar: true,
        modeBarButtonsToRemove: ["select2d", "lasso2d", "zoomIn2d", "zoomOut2d", "autoScale2d"],
        toImageButtonOptions: {format: "png", filename: `${kind}-${state.selectedParameter}`, width: 1400, height: 900, scale: 2}
      });
      if (kind === "stream") {
        installTrendHover(element, "stream");
        const count = figure.data.find(trace => trace.type === "heatmap")?.y?.length || 0;
        const pager = document.getElementById("stream-pagination");
        pager.hidden = count <= streamPageSize;
        const updatePage = () => {
          document.getElementById("stream-tooltip")?.classList.add("is-hidden");
          document.getElementById("stream-page-label").textContent = `${streamPage * streamPageSize + 1}-${Math.min(count, (streamPage + 1) * streamPageSize)} of ${count} stations`;
          document.getElementById("stream-prev").disabled = streamPage === 0;
          document.getElementById("stream-next").disabled = (streamPage + 1) * streamPageSize >= count;
          Plotly.relayout(element, {"yaxis.range": [Math.min(count, (streamPage + 1) * streamPageSize) - 0.5, streamPage * streamPageSize - 0.5]});
        };
        document.getElementById("stream-prev").onclick = () => { streamPage--; updatePage(); };
        document.getElementById("stream-next").onclick = () => { streamPage++; updatePage(); };
        if (count) updatePage();
      }
      if (kind === "distribution") installBoxplotHover(element, figure.layout.meta?.boxplotStatistics || []);
      if (kind === "trend") {
        installTrendHover(element);
        els.weatherStatus.textContent = figure.layout.meta?.precipitationStatus || (figure.data.some(trace => trace.yaxis === "y2") ? "Precipitation (mm)" : "Precipitation unavailable");
        element.removeAllListeners("plotly_click");
        element.on("plotly_click", event => {
          const details = event.points[0]?.customdata;
          const record = getTimelineRecords().find(item => item.date === details?.[1]);
          if (record) {
            state.selectedTimelineKey = record.timelineKey;
            els.valueSummary.textContent = `${formatValue(record)} on ${record.timelineLabel || record.dateLabel}`;
            refreshParameterScale();
            refreshInterpolationOverlay();
          }
        });
      }
    } catch (error) {
      if (error.name !== "AbortError" && figureRequests.get(kind) === controller) {
        clearLibraryFigure(kind, element, empty, error.message);
      }
    } finally {
      if (figureRequests.get(kind) === controller) element.removeAttribute("aria-busy");
    }
  }

  // Index every location by name so later functions can retrieve metadata quickly.
  dashboardData.locations.forEach((location) => {
    locationIndex.set(location.name, location);
  });

  // Group raw measurement rows by location; most UI features work from this grouped shape.
  dashboardData.records.forEach((record) => {
    const key = record.locationGroup;
    if (!groupedRecords.has(key)) {
      groupedRecords.set(key, []);
    }
    groupedRecords.get(key).push(record);
  });

  // Keep each location's records in chronological order for charting and "latest value" lookups.
  groupedRecords.forEach((records) => {
    records.sort((a, b) => a.sortKey - b.sortKey || a.fileName.localeCompare(b.fileName));
  });

  // Only mapped locations can appear as markers on the Leaflet map.
  const mappedLocations = dashboardData.locations.filter((location) => location.hasCoordinates);
  const defaultLocation = mappedLocations[0] || dashboardData.locations[0];
  populateLocationSelect(mappedLocations);

  const inferredLocationCount = dashboardData.locations.filter((location) => location.coordinateInferred).length;
  els.mappedCount.textContent = String(dashboardData.summary.mappedLocationCount);
  if (els.mapNote) {
    els.mapNote.textContent = `${dashboardData.summary.mappedLocationCount} mapped locations come directly from the latitude/longitude fields in the dataset CSVs. ${inferredLocationCount} location(s) currently use inferred coordinates pending verification. ${dashboardData.summary.unmappedLocationCount} location(s) remain off-map because no coordinates were available.`;
  }

  // Create the Leaflet map and a custom pane for raster interpolation overlays.
  const map = L.map("map", {
    zoomControl: true,
    scrollWheelZoom: true,
  });
  syncMapOverlayOffsets();
  window.addEventListener("resize", syncMapOverlayOffsets);
  map.createPane("interpolationPane");
  map.getPane("interpolationPane").style.zIndex = "350";
  map.getPane("interpolationPane").style.pointerEvents = "none";

  // Basemap choices exposed in the UI.
  const baseLayers = {
    osm: L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }),
    minimal: L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      className: "minimal-basemap",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }),
    satellite: L.layerGroup([
      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
        maxZoom: 19,
        attribution: 'Tiles &copy; Esri',
      }),
      L.tileLayer("https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", {
        maxZoom: 19,
        attribution: 'Labels &copy; Esri',
        pane: "overlayPane",
      }),
    ]),
  };

  baseLayers[state.baseMap].addTo(map);

  els.basemapToggle.querySelectorAll("[data-basemap]").forEach((button) => {
    button.addEventListener("click", () => {
      const nextBaseMap = button.dataset.basemap;
      if (nextBaseMap === state.baseMap) {
        return;
      }

      map.removeLayer(baseLayers[state.baseMap]);
      state.baseMap = nextBaseMap;
      baseLayers[state.baseMap].addTo(map);
      refreshBaseMapButtons();
    });
  });

  document.getElementById("show-stations").addEventListener("change", event => {
    markers.forEach(marker => event.target.checked ? marker.addTo(map) : map.removeLayer(marker));
  });
  document.getElementById("view-interpolation").addEventListener("click", async () => {
    interpolationEnabled = true;
    document.getElementById("map-interpolation-toggle").checked = true;
    await loadInterpolationData();
    refreshInterpolationOverlay();
    const surface = getInterpolationSurface();
    const point = surface?.samplePoints?.find(item => item.location === state.selectedLocation) || surface?.samplePoints?.[0];
    if (!point) return;
    document.getElementById("show-stations").checked = false;
    markers.forEach(marker => map.removeLayer(marker));
    map.closePopup();
    map.setView([point.latitude, point.longitude], 10);
  });

  // Visually marks the currently active basemap button.
  document.getElementById("map-interpolation-toggle").addEventListener("change", event => {
    interpolationEnabled = event.target.checked;
    if (interpolationEnabled && !interpolationData) loadInterpolationData().then(refreshInterpolationOverlay);
    refreshInterpolationOverlay();
  });

  function refreshBaseMapButtons() {
    els.basemapToggle.querySelectorAll("[data-basemap]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.basemap === state.baseMap);
    });
  }

  function syncMapOverlayOffsets() {
    const mapArea = document.querySelector(".map-area");
    const mapToolbar = document.querySelector(".map-toolbar");
    if (!mapArea || !mapToolbar) {
      return;
    }

    mapArea.style.setProperty("--map-overlay-top", `${Math.round(mapToolbar.offsetHeight + 28)}px`);
  }

  refreshBaseMapButtons();
  if (els.boxplotGrouping) {
    els.boxplotGrouping.querySelectorAll("[data-boxplot-grouping]").forEach((button) => {
      button.addEventListener("click", () => {
        state.boxplotGrouping = button.dataset.boxplotGrouping;
        els.boxplotGrouping.querySelectorAll("[data-boxplot-grouping]").forEach((item) => {
          item.classList.toggle("is-active", item === button);
        });
        refreshBoxplot();
      });
    });
  }
  renderUseCaseTabs();
  loadInterpolationData().then(() => {
    refreshInterpolationOverlay();
  });
  if (mappedLocations.length) {
    const bounds = L.latLngBounds(mappedLocations.map((location) => [location.latitude, location.longitude]));
    map.fitBounds(bounds, {
      paddingTopLeft: [28, 24],
      paddingBottomRight: [28, 150],
      maxZoom: 11,
    });
  } else {
    map.setView([20, 0], 2);
  }

  // Create one clickable marker per mapped location.
  mappedLocations.forEach((location) => {
    const isStp = isSewageTreatmentPlant(location.name);
    const marker = L.circleMarker([location.latitude, location.longitude], {
      radius: 8,
      weight: 2,
      color: "#ffffff",
      fillColor: isStp ? "#d99d06" : "#0f766e",
      fillOpacity: 0.92,
    }).addTo(map);

    marker.bindPopup(
      buildLocationPopup(location.name)
    );
    marker.bindTooltip("", {
      permanent: true,
      direction: "top",
      offset: [0, -14],
      className: "point-value-tooltip",
      opacity: 1,
    });

    marker.on("click", (event) => {
      if (event.originalEvent) {
        L.DomEvent.stopPropagation(event.originalEvent);
      }
      selectLocation(location.name, { focusMap: true });
    });

    markers.set(location.name, marker);
  });

  // Query the active Python-generated interpolation grid at a clicked map position.
  map.on("click", (event) => {
    if (!interpolationEnabled) return;
    const estimate = getInterpolationEstimateAt(event.latlng);
    if (!estimate) return;
    const periodLabel = estimate.surface.year == null
      ? "All available years"
      : String(estimate.surface.year);
    L.popup({ className: "interpolation-value-popup", maxWidth: 260 })
      .setLatLng(event.latlng)
      .setContent([
        '<div class="interpolation-estimate">',
        '<strong>Interpolated estimate</strong>',
        `<span>${escapeHtml(estimate.surface.parameterFamily || estimate.surface.parameter)}</span>`,
        `<b>${escapeHtml(formatCompactNumber(estimate.value))}${estimate.surface.unit ? ` ${escapeHtml(estimate.surface.unit)}` : ""}</b>`,
        `<small>Period: ${escapeHtml(periodLabel)}</small>`,
        '<small>Estimated by Python ordinary kriging; this is not an observed sample.</small>',
        '</div>',
      ].join(""))
      .openOn(map);
  });

  refreshSuitabilitySummary();
  refreshParameterScale();

  // Fill the station dropdown and wire it to the main selection flow.
  function populateLocationSelect(locations) {
    if (!els.locationSelect) {
      return;
    }

    els.locationSelect.innerHTML = locations
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((location) => `<option value="${escapeHtml(location.name)}">${escapeHtml(location.name)}</option>`)
      .join("");

    els.locationSelect.addEventListener("change", () => {
      if (!els.locationSelect.value) {
        return;
      }
      selectLocation(els.locationSelect.value, { focusMap: true });
    });
  }

  // Draw the four use-case buttons and refresh dependent UI on click.
  function renderUseCaseTabs() {
    if (!els.useCaseTabs) {
      return;
    }

    els.useCaseTabs.innerHTML = "";
    USE_CASES.forEach((useCase) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `use-case-button${useCase.key === state.selectedUseCase ? " is-active" : ""}`;
      button.textContent = useCase.label;
      button.addEventListener("click", () => {
        state.selectedUseCase = useCase.key;
        renderUseCaseTabs();
        refreshSuitabilitySummary();
        refreshParameterScale();
        refreshMarkerStyles();
      });
      els.useCaseTabs.appendChild(button);
    });
  }

  // Recompute the pass/caution/fail counts for all mapped locations.
  function refreshSuitabilitySummary() {
    if (!els.suitabilitySummary) {
      return;
    }

    const counts = {
      safe: 0,
      caution: 0,
      unsafe: 0,
      unknown: 0,
    };

    mappedLocations.forEach((location) => {
      const evaluation = evaluateLocationSuitability(location.name);
      counts[evaluation.status] += 1;
    });

    const useCaseLabel = USE_CASES.find((item) => item.key === state.selectedUseCase)?.label || "Selected use case";
    els.suitabilitySummary.textContent = `${counts.safe} pass, ${counts.caution} caution, ${counts.unsafe} fail, ${counts.unknown} insufficient for ${useCaseLabel.toLowerCase()} using the latest sample in ${getSuitabilityFilterLabel()}.`;
    refreshSuitabilityDetail();
  }

  // Show how much of the screening result is based on confirmed vs proxy vs missing inputs.
  function refreshSuitabilityDetail() {
    if (!els.suitabilityDetail) {
      return;
    }

    const evaluation = state.selectedLocation ? evaluateLocationSuitability(state.selectedLocation) : null;
    if (!evaluation?.coverage) {
      els.suitabilityDetail.textContent = "Confirmed CSV matches, proxy-only fields, and missing checks will appear for the selected station.";
      return;
    }

    const confirmed = evaluation.coverage.confirmed.length;
    const proxy = evaluation.coverage.proxy.length;
    const missing = evaluation.coverage.missing.length;
    const proxyText = evaluation.coverage.proxy.length ? ` Proxy-only: ${evaluation.coverage.proxy.join(", ")}.` : "";
    els.suitabilityDetail.textContent = `${state.selectedLocation}: ${confirmed} confirmed, ${proxy} proxy-only, ${missing} missing checks.${proxyText}`;
  }

  // Convert the current year/month selection into user-friendly text.
  function getSuitabilityFilterLabel() {
    const yearLabel = state.selectedYear === "all" ? "all sampled years" : String(state.selectedYear);
    if (state.selectedPeriod === "annual") {
      return yearLabel;
    }

    const selectedMonth = MONTH_OPTIONS.find((month) => month.key === state.selectedPeriod);
    return selectedMonth ? `${selectedMonth.label} within ${yearLabel}` : yearLabel;
  }

  // Run the rule-based screening engine for one location under the current filters/use case.
  function evaluateLocationSuitability(locationName) {
    const sampleRecords = getSuitabilitySampleRecords(locationName);
    if (!sampleRecords.length) {
      return {
        status: "unknown",
        label: "Insufficient data",
        reasons: ["No sample matches the current timeline filter."],
        result: null,
        sampleLabel: getSuitabilityFilterLabel(),
      };
    }

    const inputBundle = extractScreeningInputs(sampleRecords, state.selectedUseCase);
    const checkedValues = inputBundle.values;
    const result = runUseCaseScreening(state.selectedUseCase, checkedValues);
    const status = determineSuitabilityStatus(state.selectedUseCase, result);

    return {
      status,
      label: formatSuitabilityStatus(status),
      reasons: [...result.core_reasons, ...result.extended_reasons],
      result,
      sampleLabel: sampleRecords[0]?.dateLabel || getSuitabilityFilterLabel(),
      coverage: inputBundle.coverage,
    };
  }

  // Suitability is based on the most recent sample that matches the current year/month filter.
  function getSuitabilitySampleRecords(locationName) {
    const locationRecords = filterRecordsBySelectedYear(groupedRecords.get(locationName) || []);
    const selectedMonth = MONTH_OPTIONS.find((month) => month.key === state.selectedPeriod);
    const matchingRecords = state.selectedPeriod === "annual"
      ? locationRecords
      : locationRecords.filter((record) => record.monthIndex === selectedMonth?.monthIndex);

    if (!matchingRecords.length) {
      return [];
    }

    const groupedSamples = new Map();
    matchingRecords.forEach((record) => {
      const key = `${record.fileName}|${record.sortKey}`;
      if (!groupedSamples.has(key)) {
        groupedSamples.set(key, []);
      }
      groupedSamples.get(key).push(record);
    });

    const sortedEntries = Array.from(groupedSamples.entries()).sort((left, right) => {
      const leftRecord = left[1][0];
      const rightRecord = right[1][0];
      return rightRecord.sortKey - leftRecord.sortKey || rightRecord.fileName.localeCompare(leftRecord.fileName);
    });

    return sortedEntries[0]?.[1] || [];
  }

  // Pull only the values needed for the selected use case out of the raw sample rows.
  function extractScreeningInputs(records, useCase) {
    const specs = SCREENING_PARAMETER_SPECS[useCase] || [];
    const values = {
      pH: null,
      turbidity_ntu: null,
      tds_mg_l: null,
      nitrate_mg_l: null,
      fluoride_mg_l: null,
      chloride_mg_l: null,
      sulphate_mg_l: null,
      hardness_mg_l_as_caco3: null,
      alkalinity_mg_l_as_caco3: null,
      total_coliform_mpn_100ml: null,
      fecal_coliform_mpn_100ml: null,
      e_coli_present: null,
      ec_us_cm: null,
      sar: null,
      boron_mg_l: null,
      bicarbonate_mg_l: null,
      carbonate_mg_l: null,
      rsc_meq_l: null,
      dissolved_oxygen_mg_l: null,
      free_ammonia_mg_l_as_n: null,
      bod_mg_l: null,
      phosphate_mg_l: null,
      temperature_c: null,
    };
    const coverage = {
      confirmed: [],
      proxy: [],
      missing: [],
    };

    // For each required field, prefer confirmed aliases; fall back to proxy coverage reporting.
    specs.forEach((spec) => {
      const confirmedMatch = getParameterMatch(records, spec.confirmed || []);
      if (confirmedMatch) {
        values[spec.key] = confirmedMatch.numericValue;
        coverage.confirmed.push(getCoverageLabel(spec.key, confirmedMatch.parameter));
        return;
      }

      const proxyMatch = getParameterMatch(records, spec.proxy || []);
      if (proxyMatch) {
        coverage.proxy.push(getCoverageLabel(spec.key, proxyMatch.parameter));
        return;
      }

      coverage.missing.push(getCoverageLabel(spec.key));
    });

    return { values, coverage };
  }

  // Find the best numeric record whose parameter name matches one of the accepted aliases.
  function getParameterMatch(records, aliases) {
    const aliasSet = new Set(aliases.map((alias) => alias.toLowerCase()));
    if (!aliasSet.size) {
      return null;
    }

    const candidates = records
      .filter((record) => aliasSet.has(getParameterFamily(record.parameter).toLowerCase()) && Number.isFinite(record.numericValue))
      .sort((left, right) =>
        compareParameterVariants(left.parameter, right.parameter) ||
        right.fileName.localeCompare(left.fileName)
      );

    return candidates[0] || null;
  }

  // Turns internal screening keys into human-readable labels for the popup/detail text.
  function getCoverageLabel(key, parameterName = "") {
    const friendlyNames = {
      pH: "pH",
      turbidity_ntu: "Turbidity",
      tds_mg_l: "TDS",
      nitrate_mg_l: "Nitrate",
      fluoride_mg_l: "Fluoride",
      chloride_mg_l: "Chloride",
      sulphate_mg_l: "Sulphate",
      hardness_mg_l_as_caco3: "Hardness",
      alkalinity_mg_l_as_caco3: "Alkalinity",
      total_coliform_mpn_100ml: "Total coliform",
      fecal_coliform_mpn_100ml: "Fecal coliform",
      e_coli_present: "E. coli",
      ec_us_cm: "EC",
      sar: "SAR",
      boron_mg_l: "Boron",
      bicarbonate_mg_l: "Bicarbonate",
      carbonate_mg_l: "Carbonate",
      rsc_meq_l: "RSC",
      dissolved_oxygen_mg_l: "DO",
      free_ammonia_mg_l_as_n: "Free ammonia",
      bod_mg_l: "BOD",
      phosphate_mg_l: "Phosphate",
      temperature_c: "Temperature",
    };
    const label = friendlyNames[key] || key;
    return parameterName ? `${label} via ${parameterName}` : label;
  }

  // Dispatch to the correct screening rule set.
  function runUseCaseScreening(useCase, values) {
    if (useCase === "human_consumption") {
      return fitForHumanConsumption({
        pH: values.pH,
        turbidity_ntu: values.turbidity_ntu,
        tds_mg_l: values.tds_mg_l,
        nitrate_mg_l: values.nitrate_mg_l,
        fluoride_mg_l: values.fluoride_mg_l,
        chloride_mg_l: values.chloride_mg_l,
        sulphate_mg_l: values.sulphate_mg_l,
        hardness_mg_l_as_caco3: values.hardness_mg_l_as_caco3,
        alkalinity_mg_l_as_caco3: values.alkalinity_mg_l_as_caco3,
        total_coliform_mpn_100ml: values.total_coliform_mpn_100ml,
        e_coli_present: values.e_coli_present,
        strict: true,
      });
    }

    if (useCase === "agriculture") {
      return fitForAgriculture({
        pH: values.pH,
        ec_us_cm: values.ec_us_cm,
        sar: values.sar,
        boron_mg_l: values.boron_mg_l,
        chloride_mg_l: values.chloride_mg_l,
        nitrate_mg_l: values.nitrate_mg_l,
        bicarbonate_mg_l: values.bicarbonate_mg_l,
        carbonate_mg_l: values.carbonate_mg_l,
        rsc_meq_l: values.rsc_meq_l,
      });
    }

    if (useCase === "aquatic_life") {
      return fitForAquaticLife({
        pH: values.pH,
        dissolved_oxygen_mg_l: values.dissolved_oxygen_mg_l,
        free_ammonia_mg_l_as_n: values.free_ammonia_mg_l_as_n,
        bod_mg_l: values.bod_mg_l,
        nitrate_mg_l: values.nitrate_mg_l,
        phosphate_mg_l: values.phosphate_mg_l,
        turbidity_ntu: values.turbidity_ntu,
        temperature_c: values.temperature_c,
      });
    }

    return fitForBathing({
      pH: values.pH,
      dissolved_oxygen_mg_l: values.dissolved_oxygen_mg_l,
      bod_mg_l: values.bod_mg_l,
      total_coliform_mpn_100ml: values.total_coliform_mpn_100ml,
      fecal_coliform_mpn_100ml: values.fecal_coliform_mpn_100ml,
      turbidity_ntu: values.turbidity_ntu,
      e_coli_present: values.e_coli_present,
    });
  }

  // Collapse the detailed screening result into a simple status used by the UI and map colors.
  function determineSuitabilityStatus(useCase, result) {
    const availableCoreCount = (CORE_KEYS_BY_USE_CASE[useCase] || []).filter((key) => hasCheckedValue(result.checked_values[key])).length;
    if (!availableCoreCount) {
      return "unknown";
    }

    if (!result.fit_core) {
      return "unsafe";
    }

    return result.fit_extended ? "safe" : "caution";
  }

  function hasCheckedValue(value) {
    return value !== null && value !== undefined;
  }

  function formatSuitabilityStatus(status) {
    if (status === "safe") return "Pass";
    if (status === "caution") return "Caution";
    if (status === "unsafe") return "Fail";
    return "Insufficient data";
  }

  // Build the HTML shown when a map marker is opened.
  function buildLocationPopup(locationName) {
    const location = locationIndex.get(locationName);
    const isStp = isSewageTreatmentPlant(locationName);
    const evaluation = evaluateLocationSuitability(locationName);
    const reasonText = evaluation.reasons[0] || "No threshold exceedance found in the checked values.";
    const coverageText = evaluation.coverage
      ? `${evaluation.coverage.confirmed.length} confirmed, ${evaluation.coverage.proxy.length} proxy-only, ${evaluation.coverage.missing.length} missing checks`
      : "No screening coverage details available";

    return [
      '<div class="location-popup">',
      `<strong>${escapeHtml(locationName)}</strong>`,
      `<span>${isStp ? "Sewage treatment plant" : "Sampling location"}</span><br>`,
      `<span>${location?.sources.length || 0} source file(s)</span>`,
      `<br><span>${escapeHtml(USE_CASES.find((item) => item.key === state.selectedUseCase)?.label || "Use case")}: ${escapeHtml(evaluation.label)}</span>`,
      `<br><span>Sample used: ${escapeHtml(evaluation.sampleLabel)}</span>`,
      `<br><span>${escapeHtml(coverageText)}</span>`,
      `<br><span>${escapeHtml(reasonText)}</span>`,
      location?.hasCoordinates ? `<br><span>Lat: ${escapeHtml(Number(location.latitude).toFixed(6))}, Lon: ${escapeHtml(Number(location.longitude).toFixed(6))}</span>` : "",
      location?.coordinateInferred ? '<br><span class="location-popup-note">Coordinate inferred from nearby context</span>' : "",
      "</div>",
    ].join("");
  }

  // Main controller for station changes. Almost every panel refresh starts here.
  function selectLocation(locationName, options = {}) {
    state.selectedLocation = locationName;
    state.selectedYear = "all";
    const parameters = getLocationParameters(locationName);

    // Handle stations that exist in metadata but do not have usable measurements.
    if (!parameters.length) {
      state.selectedParameter = null;
      renderLocation();
      refreshStreamVisualization();
      renderParameterTabs([]);
      renderPeriodFilter();
      renderEmptyChart("No parameter data is available for this location.");
      renderBoxplotEmpty("No parameter distribution is available for this location.");
      return;
    }

    if (!parameters.includes(state.selectedParameter)) {
      state.selectedParameter = parameters[0];
    }

    syncPeriodSelection();
    renderLocation();
    refreshWeatherChart();
    refreshStreamVisualization();
    renderParameterTabs(parameters);
    renderPeriodFilter();
    refreshTrendChart();
    refreshBoxplot();
    refreshSuitabilitySummary();
    refreshParameterScale();
    refreshMarkerStyles(options.openPopup !== false);
    updateMapLabels();

    if (els.locationSelect && els.locationSelect.value !== locationName) {
      els.locationSelect.value = locationName;
    }

    if (options.focusMap) {
      focusLocationOnMap(locationName);
    }
  }

  // Center the map on the selected station and open its popup if possible.
  function focusLocationOnMap(locationName) {
    const location = locationIndex.get(locationName);
    const marker = markers.get(locationName);
    if (!location?.hasCoordinates) {
      return;
    }

    map.setView([location.latitude, location.longitude], Math.max(map.getZoom(), 12), {
      animate: true,
    });
    if (marker) {
      marker.openPopup();
    }
  }

  // Keep the selected parameter valid after the period/year filters change available data.
  function syncSelectedParameterAvailability() {
    const parameters = getLocationParameters();
    if (!parameters.includes(state.selectedParameter)) {
      state.selectedParameter = parameters[0] ?? null;
    }
  }

  // Shared redraw path for parameter changes where weather and suitability do not change.
  function refreshViewsForParameterChange(parameters) {
    refreshStreamVisualization();
    renderParameterTabs(parameters);
    renderPeriodFilter();
    refreshTrendChart();
    refreshBoxplot();
    refreshParameterScale();
    updateMapLabels();
  }

  // Shared redraw path for time filter changes that affect more of the dashboard.
  function refreshViewsForTimeFilterChange(options = {}) {
    const { includeWeather = false } = options;
    syncSelectedParameterAvailability();
    syncSelectedYearForParameter();
    syncPeriodSelection();
    renderParameterTabs(getLocationParameters());
    renderPeriodFilter();
    refreshTrendChart();
    refreshBoxplot();
    refreshStreamVisualization();
    if (includeWeather) {
      refreshWeatherChart();
    }
    refreshSuitabilitySummary();
    refreshParameterScale();
    refreshMarkerStyles(false);
    updateMapLabels();
  }

  // Raw records for the currently selected location + parameter family.
  function getParameterRecords() {
    const records = groupedRecords.get(state.selectedLocation) || [];
    return records.filter((record) => getParameterFamily(record.parameter) === state.selectedParameter);
  }

  // All parameter families observed at the chosen location.
  function getLocationParameters(locationName = state.selectedLocation) {
    const records = groupedRecords.get(locationName) || [];
    return Array.from(new Set(
      records
        .filter((record) => record.parameter && (record.rawValue || Number.isFinite(record.numericValue)))
        .map((record) => getParameterFamily(record.parameter))
    )).sort((a, b) => a.localeCompare(b));
  }

  // All parameter families observed at the chosen location that have usable values.
  function getAvailableParameters(locationName = state.selectedLocation) {
    const records = groupedRecords.get(locationName) || [];

    return Array.from(new Set(
      records
        .filter((record) => {
          if (!record.parameter || (!record.rawValue && !Number.isFinite(record.numericValue))) {
            return false;
          }
          return true;
        })
        .map((record) => getParameterFamily(record.parameter))
    )).sort((a, b) => a.localeCompare(b));
  }

  function getAvailableYearsForParameter(locationName = state.selectedLocation, parameter = state.selectedParameter) {
    const records = (groupedRecords.get(locationName) || [])
      .filter((record) => getParameterFamily(record.parameter) === parameter);

    return Array.from(new Set(
      records
        .map((record) => record.year)
        .filter((year) => Number.isFinite(year) && year > 0)
    )).sort((a, b) => a - b);
  }

  // Build the series the trend chart should currently plot.
  function getTimelineRecords() {
    const records = filterRecordsBySelectedYear(getParameterRecords());

    if (state.selectedPeriod === "annual") {
      return buildTrendSeries(records);
    }

    const option = MONTH_OPTIONS.find((month) => month.key === state.selectedPeriod);
    if (!option) {
      return [];
    }

    return records
      .filter((record) => record.monthIndex === option.monthIndex)
      .map((record) => ({
        ...record,
        timelineKey: record.sortKey,
        timelineLabel: String(record.year || record.dateLabel),
        timelineMeta: record.source || record.fileName,
      }));
  }

  // Merge monthly records with annual fallback values into one ordered chart series.
  function buildTrendSeries(records) {
    const monthlyRecords = records
      .filter((record) => record.monthIndex > 0)
      .sort((a, b) => a.sortKey - b.sortKey || a.fileName.localeCompare(b.fileName))
      .map((record) => ({
        ...record,
        timelineKey: record.sortKey,
        timelineLabel: record.dateLabel,
        timelineMeta: record.source || record.fileName,
      }));

    // If a year already has monthly rows, we suppress duplicate annual rows for that year.
    const yearsWithMonthlyData = new Set(monthlyRecords.map((record) => record.year));
    const yearlyFallbackRecords = records
      .filter((record) => !record.monthIndex && !yearsWithMonthlyData.has(record.year))
      .sort((a, b) =>
        a.sortKey - b.sortKey ||
        compareParameterVariants(a.parameter, b.parameter) ||
        a.fileName.localeCompare(b.fileName)
      )
      .map((record, index, annualRecords) => {
        const yearOffset = annualRecords
          .slice(0, index)
          .filter((candidate) => candidate.year === record.year)
          .length;

        return {
          ...record,
          timelineKey: record.sortKey + yearOffset,
          timelineLabel: buildTrendLabel(record),
          timelineMeta: record.source || record.fileName,
        };
      });

    return [...monthlyRecords, ...yearlyFallbackRecords]
      .sort((a, b) => a.timelineKey - b.timelineKey || a.fileName.localeCompare(b.fileName));
  }

  function getAnnualTrendRecords() {
    return buildYearlySeries(getParameterRecords());
  }

  // Keep the selected point valid, redraw the chart, then sync the interpolation overlay.
  function refreshTrendChart() {
    const trendRecords = getTimelineRecords();
    if (!trendRecords.some((record) => record.timelineKey === state.selectedTimelineKey)) {
      state.selectedTimelineKey = trendRecords[trendRecords.length - 1]?.timelineKey ?? null;
    }
    renderTrendChart(trendRecords);
    refreshInterpolationOverlay();
  }

  // Draw Python-calculated five-number summaries for the active station/parameter.
  function refreshBoxplot() {
    renderLibraryFigure("distribution", els.boxplotChart, els.boxplotEmpty);
  }

  function renderBoxplotEmpty(message) {
    clearLibraryFigure("distribution", els.boxplotChart, els.boxplotEmpty, message);
  }

  function renderLocation() {
    const location = locationIndex.get(state.selectedLocation);
    const records = groupedRecords.get(state.selectedLocation) || [];
    const yearSet = new Set(records.map((record) => record.year).filter(Boolean));
    const sourceSet = new Set(records.map((record) => record.source).filter(Boolean));
    const mappedLabel = location?.coordinateInferred ? "Inferred coordinate" : (location?.hasCoordinates ? "Mapped" : "No coordinates");
    const latitude = Number.isFinite(location?.latitude) ? location.latitude.toFixed(6) : null;
    const longitude = Number.isFinite(location?.longitude) ? location.longitude.toFixed(6) : null;

    if (els.locationBadge) {
      els.locationBadge.textContent = mappedLabel;
    }
    if (els.locationName) {
      els.locationName.textContent = state.selectedLocation || "Unknown location";
    }
    if (els.locationMeta) {
      els.locationMeta.textContent = `${records.length} measurements across ${yearSet.size} year(s) from ${sourceSet.size} source(s).${location?.coordinateInferred ? " Map position is inferred and should be verified." : ""}`;
    }
    if (els.locationCoords) {
      els.locationCoords.textContent = latitude && longitude
        ? `Latitude: ${latitude} | Longitude: ${longitude}`
        : "Latitude/longitude not available for this location.";
    }
  }

  // Render the stream-style heatmap comparing yearly values across mapped points.
  function refreshStreamVisualization() {
    renderLibraryFigure("stream", els.streamVisualization, null);
    if (els.streamStatus) els.streamStatus.textContent = state.selectedParameter || "Select parameter";
  }

  function renderStreamVisualizationEmpty(message) {
    clearLibraryFigure("stream", els.streamVisualization, null, message);
  }

  function getAllAvailableYears() {
    return Array.from(new Set(
      dashboardData.records
        .map((record) => record.year)
        .filter((year) => Number.isFinite(year) && year > 0)
    )).sort((a, b) => a - b);
  }

  function refreshWeatherChart() {
    // The library supplies precipitation alongside the parameter trend.
  }

  function getDivergingHeatmapStyle(value, min, max) {
    if (!Number.isFinite(value)) {
      return "";
    }

    if (max === min) {
      return "--stream-r:248; --stream-g:250; --stream-b:252; --stream-border-r:148; --stream-border-g:163; --stream-border-b:184;";
    }

    const normalized = clamp((value - min) / (max - min), 0, 1);
    const color = getDivergingColor(normalized);
    const borderPosition = clamp(normalized < 0.5 ? normalized * 0.82 : 0.5 + ((normalized - 0.5) * 1.18), 0, 1);
    const borderColor = getDivergingColor(borderPosition);

    return [
      `--stream-r:${color[0]}`,
      `--stream-g:${color[1]}`,
      `--stream-b:${color[2]}`,
      `--stream-border-r:${borderColor[0]}`,
      `--stream-border-g:${borderColor[1]}`,
      `--stream-border-b:${borderColor[2]}`,
    ].join("; ");
  }

  function getDivergingColor(normalized) {
    const low = [37, 99, 235];
    const mid = [248, 250, 252];
    const high = [220, 38, 38];

    if (normalized <= 0.5) {
      return interpolateRgb(low, mid, normalized / 0.5);
    }

    return interpolateRgb(mid, high, (normalized - 0.5) / 0.5);
  }

  function interpolateRgb(start, end, amount) {
    return start.map((channel, index) => Math.round(channel + ((end[index] - channel) * amount)));
  }

  function formatRainfall(value, compact = false) {
    if (!Number.isFinite(value)) {
      return "NA";
    }

    const digits = compact ? 0 : 1;
    return `${value.toLocaleString(undefined, { maximumFractionDigits: digits })}${compact ? "" : " mm"}`;
  }

  // Draw the safety scale for the selected parameter under the active use case.
  function refreshParameterScale() {
    if (!els.parameterScale) {
      return;
    }

    if (!state.selectedParameter) {
      els.parameterScale.innerHTML = '<div class="parameter-scale-empty">Select a parameter to see its safety scale.</div>';
      return;
    }

    const parameterKey = getParameterScaleKey(state.selectedParameter);
    const definition = PARAMETER_SCALE_DEFINITIONS[state.selectedUseCase]?.[parameterKey]
      || GLOBAL_PARAMETER_SCALE_DEFINITIONS[parameterKey];
    const useCaseLabel = USE_CASES.find((item) => item.key === state.selectedUseCase)?.label || "Selected use case";
    if (!definition) {
      els.parameterScale.innerHTML = `<div class="parameter-scale-empty">${escapeHtml(state.selectedParameter)} has no configured screening scale for ${escapeHtml(useCaseLabel.toLowerCase())}.</div>`;
      return;
    }

    const selectedRecord = getSelectedParameterScaleRecord();
    const currentValue = selectedRecord?.numericValue ?? null;
    // Expand the visual domain enough to show both the threshold band and the current value.
    const scaleDomain = buildParameterScaleDomain(definition, currentValue);
    const markerPosition = Number.isFinite(currentValue)
      ? clamp(((currentValue - scaleDomain.min) / (scaleDomain.max - scaleDomain.min || 1)) * 100, 0, 100)
      : null;
    const safeStart = getScalePercent(
      definition.type === "range"
        ? definition.safeMin
        : definition.type === "min"
          ? definition.safeMin
          : scaleDomain.min,
      scaleDomain
    );
    const safeEnd = getScalePercent(
      definition.type === "range"
        ? definition.safeMax
        : definition.type === "max"
          ? definition.safeMax
          : scaleDomain.max,
      scaleDomain
    );
    const safeBandStart = definition.type === "max" && definition.safeMax === 0 ? 0 : safeStart;
    const safeBandEnd = definition.type === "max" && definition.safeMax === 0
      ? Math.max(safeEnd, 1.2)
      : safeEnd;
    const valueStatus = getParameterScaleStatus(definition, currentValue);
    const valueTone = valueStatus === "safe" ? "is-safe" : "is-unsafe";
    const unitLabel = definition.unit || getParameterScaleUnit(selectedRecord);
    const thresholdText = buildParameterScaleThresholdText(definition, unitLabel);
    const valueText = Number.isFinite(currentValue)
      ? `${formatCompactNumber(currentValue)}${unitLabel ? ` ${unitLabel}` : ""}`
      : "No numeric value";
    const sampleText = selectedRecord
      ? `${selectedRecord.timelineLabel || selectedRecord.dateLabel || selectedRecord.source || "Selected sample"}`
      : "No selected sample";
    const axisTicks = definition.type === "range"
      ? [scaleDomain.min, definition.safeMin, definition.safeMax, scaleDomain.max]
      : [scaleDomain.min, definition.type === "min" ? definition.safeMin : definition.safeMax, scaleDomain.max];
    const renderedTicks = Array.from(new Map(
      axisTicks.map((tick) => [String(tick), {
        value: tick,
        position: getScalePercent(tick, scaleDomain),
      }])
    ).values());

    els.parameterScale.innerHTML = `
      <div class="parameter-scale-heading">
        <div>
          <div class="parameter-scale-title">${escapeHtml(definition.label)}</div>
          <div class="parameter-scale-usecase">${escapeHtml(useCaseLabel)}</div>
        </div>
        <span class="parameter-scale-value ${valueTone}">${escapeHtml(valueText)}</span>
      </div>
      <div class="parameter-scale-threshold">${escapeHtml(thresholdText)}</div>
      <div class="parameter-scale-track">
        ${definition.type !== "min" ? `<span class="parameter-scale-band is-unsafe-left" style="width:${Math.max(0, safeStart)}%"></span>` : ""}
        <span class="parameter-scale-band is-safe" style="left:${safeBandStart}%; width:${Math.max(0, safeBandEnd - safeBandStart)}%"></span>
        ${definition.type !== "max" ? `<span class="parameter-scale-band is-unsafe-right" style="left:${safeEnd}%; width:${Math.max(0, 100 - safeEnd)}%"></span>` : ""}
        ${definition.type === "max" ? `<span class="parameter-scale-band is-unsafe-right" style="left:${safeBandEnd}%; width:${Math.max(0, 100 - safeBandEnd)}%"></span>` : ""}
        ${markerPosition == null ? "" : `<span class="parameter-scale-marker ${valueTone}" style="left:${markerPosition}%"></span>`}
      </div>
      <div class="parameter-scale-axis">${renderedTicks.map((tick) => `<span style="left:${tick.position}%">${escapeHtml(formatCompactNumber(tick.value))}</span>`).join("")}</div>
      <div class="parameter-scale-detail">${escapeHtml(state.selectedLocation || "No location selected")}: ${escapeHtml(sampleText)}${Number.isFinite(currentValue) ? ` (${valueStatus})` : ""}</div>
    `;
  }

  function getSelectedParameterScaleRecord() {
    const trendRecords = getTimelineRecords().filter((record) => Number.isFinite(record.numericValue));
    if (!trendRecords.length) {
      return null;
    }

    return trendRecords.find((record) => record.timelineKey === state.selectedTimelineKey) || trendRecords[trendRecords.length - 1];
  }

  // Normalize parameter labels from the CSV into one internal key used by scale definitions.
  function getParameterScaleKey(parameterName) {
    const clean = String(parameterName || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    if (clean === "ph") return "ph";
    if (clean === "turbidity") return "turbidity";
    if (clean === "tds") return "tds";
    if (clean === "no3 n" || clean === "nitrate") return "nitrate";
    if (clean === "fluoride") return "fluoride";
    if (clean === "chloride") return "chloride";
    if (clean === "sulphate" || clean === "so4") return "sulphate";
    if (clean === "th as caco3" || clean === "hardness") return "hardness";
    if (clean === "total alkalinity as caco3" || clean === "p alkalinity") return "alkalinity";
    if (clean === "conductivity") return "conductivity";
    if (clean === "boron b" || clean === "boron") return "boron";
    if (clean === "do" || clean === "dissolved oxygen") return "do";
    if (clean === "nh3 n" || clean === "free ammonia") return "ammonia";
    if (clean === "bod") return "bod";
    if (clean === "phosphate" || clean === "phosphate p") return "phosphate";
    if (clean === "temperature") return "temperature";
    if (clean === "total coliform" || clean === "t coliform") return "total_coliform";
    if (clean === "faecal coliform" || clean === "fecal coliform") return "fecal_coliform";
    return clean.replace(/\s+/g, "_");
  }

  function getParameterScaleUnit(record) {
    return record?.unit ? String(record.unit) : "";
  }

  // Choose a chart-like domain that keeps the safe band readable.
  function buildParameterScaleDomain(definition, currentValue) {
    if (Number.isFinite(definition.domainMin) && Number.isFinite(definition.domainMax)) {
      return { min: definition.domainMin, max: Math.max(definition.domainMax, currentValue ?? definition.domainMax) };
    }

    if (definition.type === "range") {
      const buffer = Math.max((definition.safeMax - definition.safeMin) * 0.75, 1);
      const min = Math.max(0, Math.min(definition.safeMin - buffer, Number.isFinite(currentValue) ? currentValue - (buffer * 0.25) : definition.safeMin - buffer));
      const max = Math.max(definition.safeMax + buffer, Number.isFinite(currentValue) ? currentValue + (buffer * 0.25) : definition.safeMax + buffer);
      return { min, max };
    }

    if (definition.type === "min") {
      return {
        min: Number.isFinite(definition.domainMin) ? definition.domainMin : 0,
        max: Math.max(definition.safeMin * 1.6, Number.isFinite(currentValue) ? currentValue * 1.15 : 0, definition.safeMin + 1),
      };
    }

    return {
      min: Number.isFinite(definition.domainMin) ? definition.domainMin : 0,
      max: Math.max(definition.safeMax * 1.6, Number.isFinite(currentValue) ? currentValue * 1.15 : 0, definition.safeMax + 1),
    };
  }

  function getScalePercent(value, domain) {
    return clamp(((value - domain.min) / (domain.max - domain.min || 1)) * 100, 0, 100);
  }

  function getParameterScaleStatus(definition, value) {
    if (!Number.isFinite(value)) {
      return "unknown";
    }
    if (definition.type === "range") {
      return value >= definition.safeMin && value <= definition.safeMax ? "safe" : "unsafe";
    }
    if (definition.type === "min") {
      return value >= definition.safeMin ? "safe" : "unsafe";
    }
    return value <= definition.safeMax ? "safe" : "unsafe";
  }

  function buildParameterScaleThresholdText(definition, unitLabel) {
    const suffix = unitLabel ? ` ${unitLabel}` : "";
    if (definition.type === "range") {
      return `Safe between ${formatCompactNumber(definition.safeMin)}${suffix} and ${formatCompactNumber(definition.safeMax)}${suffix}; unsafe outside that band.`;
    }
    if (definition.type === "min") {
      return `Safe from ${formatCompactNumber(definition.safeMin)}${suffix} upward; unsafe below.`;
    }
    return `Safe up to ${formatCompactNumber(definition.safeMax)}${suffix}; unsafe above.`;
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }


  function buildScreeningResult(useCase, fitCore, fitExtended, coreReasons, extendedReasons, checkedValues) {
    return {
      use_case: useCase,
      fit_core: fitCore,
      fit_extended: fitExtended,
      core_reasons: coreReasons,
      extended_reasons: extendedReasons,
      checked_values: checkedValues,
    };
  }

  // Screening logic for drinking-water style suitability.
  function fitForHumanConsumption({
    pH = null,
    turbidity_ntu = null,
    tds_mg_l = null,
    nitrate_mg_l = null,
    fluoride_mg_l = null,
    chloride_mg_l = null,
    sulphate_mg_l = null,
    hardness_mg_l_as_caco3 = null,
    alkalinity_mg_l_as_caco3 = null,
    total_coliform_mpn_100ml = null,
    e_coli_present = null,
    strict = true,
  }) {
    const checked = {
      pH,
      turbidity_ntu,
      tds_mg_l,
      nitrate_mg_l,
      fluoride_mg_l,
      chloride_mg_l,
      sulphate_mg_l,
      hardness_mg_l_as_caco3,
      alkalinity_mg_l_as_caco3,
      total_coliform_mpn_100ml,
      e_coli_present,
      strict,
    };

    const coreReasons = [];
    const extendedReasons = [];
    const turbidityLimit = strict ? 1.0 : 5.0;
    const fluorideLimit = strict ? 1.0 : 1.5;

    if (pH != null && !(pH >= 6.5 && pH <= 8.5)) coreReasons.push(`pH ${pH} outside 6.5-8.5`);
    if (turbidity_ntu != null && turbidity_ntu > turbidityLimit) coreReasons.push(`Turbidity ${turbidity_ntu} NTU exceeds ${turbidityLimit} NTU`);
    if (tds_mg_l != null && tds_mg_l > 500) coreReasons.push(`TDS ${tds_mg_l} mg/L exceeds 500 mg/L desirable limit`);
    if (nitrate_mg_l != null && nitrate_mg_l > 45) coreReasons.push(`Nitrate ${nitrate_mg_l} mg/L exceeds 45 mg/L`);
    if (fluoride_mg_l != null && fluoride_mg_l > fluorideLimit) coreReasons.push(`Fluoride ${fluoride_mg_l} mg/L exceeds ${fluorideLimit} mg/L`);
    if (total_coliform_mpn_100ml != null && total_coliform_mpn_100ml > 0) coreReasons.push(`Total coliform ${total_coliform_mpn_100ml} MPN/100mL should be 0`);
    if (e_coli_present === true) coreReasons.push("E. coli detected");

    if (chloride_mg_l != null && chloride_mg_l > 250) extendedReasons.push(`Chloride ${chloride_mg_l} mg/L exceeds 250 mg/L desirable limit`);
    if (sulphate_mg_l != null && sulphate_mg_l > 200) extendedReasons.push(`Sulphate ${sulphate_mg_l} mg/L exceeds 200 mg/L desirable limit`);
    if (hardness_mg_l_as_caco3 != null && hardness_mg_l_as_caco3 > 200) extendedReasons.push(`Hardness ${hardness_mg_l_as_caco3} mg/L as CaCO3 exceeds 200 mg/L desirable limit`);
    if (alkalinity_mg_l_as_caco3 != null && alkalinity_mg_l_as_caco3 > 200) extendedReasons.push(`Alkalinity ${alkalinity_mg_l_as_caco3} mg/L as CaCO3 exceeds 200 mg/L desirable limit`);

    return buildScreeningResult("human_consumption", coreReasons.length === 0, coreReasons.length === 0 && extendedReasons.length === 0, coreReasons, extendedReasons, checked);
  }

  // Screening logic for irrigation/agriculture suitability.
  function fitForAgriculture({
    pH = null,
    ec_us_cm = null,
    sar = null,
    boron_mg_l = null,
    chloride_mg_l = null,
    nitrate_mg_l = null,
    bicarbonate_mg_l = null,
    carbonate_mg_l = null,
    rsc_meq_l = null,
  }) {
    const checked = { pH, ec_us_cm, sar, boron_mg_l, chloride_mg_l, nitrate_mg_l, bicarbonate_mg_l, carbonate_mg_l, rsc_meq_l };
    const coreReasons = [];
    const extendedReasons = [];

    if (pH != null && !(pH >= 6.0 && pH <= 8.5)) coreReasons.push(`pH ${pH} outside 6.0-8.5`);
    if (ec_us_cm != null && ec_us_cm > 2250) coreReasons.push(`EC ${ec_us_cm} µS/cm exceeds 2250 µS/cm`);
    if (sar != null && sar > 26) coreReasons.push(`SAR ${sar} exceeds 26`);
    if (boron_mg_l != null && boron_mg_l > 2.0) coreReasons.push(`Boron ${boron_mg_l} mg/L exceeds 2.0 mg/L`);

    if (chloride_mg_l != null && chloride_mg_l > 140) extendedReasons.push(`Chloride ${chloride_mg_l} mg/L may be restrictive for chloride-sensitive crops`);
    if (nitrate_mg_l != null && nitrate_mg_l > 30) extendedReasons.push(`Nitrate ${nitrate_mg_l} mg/L is high for irrigation screening`);
    if (rsc_meq_l != null && rsc_meq_l > 2.5) {
      extendedReasons.push(`RSC ${rsc_meq_l} meq/L exceeds 2.5 meq/L`);
    } else {
      if (bicarbonate_mg_l != null && bicarbonate_mg_l > 610) extendedReasons.push(`Bicarbonate ${bicarbonate_mg_l} mg/L is high and may create alkalinity hazard`);
      if (carbonate_mg_l != null && carbonate_mg_l > 120) extendedReasons.push(`Carbonate ${carbonate_mg_l} mg/L is high and may create alkalinity hazard`);
    }

    return buildScreeningResult("agriculture", coreReasons.length === 0, coreReasons.length === 0 && extendedReasons.length === 0, coreReasons, extendedReasons, checked);
  }

  // Screening logic for aquatic ecosystem health.
  function fitForAquaticLife({
    pH = null,
    dissolved_oxygen_mg_l = null,
    free_ammonia_mg_l_as_n = null,
    bod_mg_l = null,
    nitrate_mg_l = null,
    phosphate_mg_l = null,
    turbidity_ntu = null,
    temperature_c = null,
  }) {
    const checked = { pH, dissolved_oxygen_mg_l, free_ammonia_mg_l_as_n, bod_mg_l, nitrate_mg_l, phosphate_mg_l, turbidity_ntu, temperature_c };
    const coreReasons = [];
    const extendedReasons = [];

    if (pH != null && !(pH >= 6.5 && pH <= 8.5)) coreReasons.push(`pH ${pH} outside 6.5-8.5`);
    if (dissolved_oxygen_mg_l != null && dissolved_oxygen_mg_l < 4.0) coreReasons.push(`DO ${dissolved_oxygen_mg_l} mg/L below 4.0 mg/L`);
    if (free_ammonia_mg_l_as_n != null && free_ammonia_mg_l_as_n > 1.2) coreReasons.push(`Free ammonia ${free_ammonia_mg_l_as_n} mg/L exceeds 1.2 mg/L`);

    if (bod_mg_l != null && bod_mg_l > 3.0) extendedReasons.push(`BOD ${bod_mg_l} mg/L exceeds 3.0 mg/L`);
    if (nitrate_mg_l != null && nitrate_mg_l > 10) extendedReasons.push(`Nitrate ${nitrate_mg_l} mg/L is high for stream ecology screening`);
    if (phosphate_mg_l != null && phosphate_mg_l > 0.1) extendedReasons.push(`Phosphate ${phosphate_mg_l} mg/L may promote eutrophication`);
    if (turbidity_ntu != null && turbidity_ntu > 25) extendedReasons.push(`Turbidity ${turbidity_ntu} NTU is high for healthy stream habitat`);
    if (temperature_c != null && temperature_c > 32) extendedReasons.push(`Temperature ${temperature_c}°C is stressful for many stream organisms`);

    return buildScreeningResult("aquatic_life", coreReasons.length === 0, coreReasons.length === 0 && extendedReasons.length === 0, coreReasons, extendedReasons, checked);
  }

  // Screening logic for recreational/bathing suitability.
  function fitForBathing({
    pH = null,
    dissolved_oxygen_mg_l = null,
    bod_mg_l = null,
    total_coliform_mpn_100ml = null,
    fecal_coliform_mpn_100ml = null,
    turbidity_ntu = null,
    e_coli_present = null,
  }) {
    const checked = { pH, dissolved_oxygen_mg_l, bod_mg_l, total_coliform_mpn_100ml, fecal_coliform_mpn_100ml, turbidity_ntu, e_coli_present };
    const coreReasons = [];
    const extendedReasons = [];

    if (pH != null && !(pH >= 6.5 && pH <= 8.5)) coreReasons.push(`pH ${pH} outside 6.5-8.5`);
    if (dissolved_oxygen_mg_l != null && dissolved_oxygen_mg_l < 5.0) coreReasons.push(`DO ${dissolved_oxygen_mg_l} mg/L below 5.0 mg/L`);
    if (bod_mg_l != null && bod_mg_l > 3.0) coreReasons.push(`BOD ${bod_mg_l} mg/L exceeds 3.0 mg/L`);

    if (fecal_coliform_mpn_100ml != null) {
      if (fecal_coliform_mpn_100ml > 0) coreReasons.push(`Fecal coliform ${fecal_coliform_mpn_100ml} MPN/100mL should be 0`);
    } else if (total_coliform_mpn_100ml != null && total_coliform_mpn_100ml > 0) {
      coreReasons.push(`Total coliform ${total_coliform_mpn_100ml} MPN/100mL should be 0`);
    }

    if (turbidity_ntu != null && turbidity_ntu > 10) extendedReasons.push(`Turbidity ${turbidity_ntu} NTU is high for safe/pleasant bathing`);
    if (e_coli_present === true) extendedReasons.push("E. coli detected");

    return buildScreeningResult("bathing", coreReasons.length === 0, coreReasons.length === 0 && extendedReasons.length === 0, coreReasons, extendedReasons, checked);
  }

  // Parameter buttons react to both location changes and period/year availability.
  function renderParameterTabs(parameters) {
    parameters = Array.from(new Set(dashboardData.records.filter(record => record.parameter && (record.rawValue || Number.isFinite(record.numericValue))).map(record => getParameterFamily(record.parameter)))).sort((a, b) => a.localeCompare(b));
    els.parameterTabs.innerHTML = "";
    const availableParameters = new Set(getAvailableParameters());

    parameters.forEach((parameter) => {
      const isAvailable = availableParameters.has(parameter);
      const description = getParameterDescription(parameter);
      const button = document.createElement("button");
      button.type = "button";
      button.className = `tab-button${parameter === state.selectedParameter ? " is-active" : ""}`;
      button.textContent = parameter;
      button.title = isAvailable ? parameter : `${parameter}: select to view a station with measurements`;
      button.setAttribute("aria-label", `${parameter}: ${description}`);
      button.dataset.parameterDescription = description;
      button.addEventListener("mouseenter", () => showParameterDescription(button));
      button.addEventListener("mousemove", () => positionParameterDescription(button));
      button.addEventListener("mouseleave", hideParameterDescription);
      button.addEventListener("focus", () => showParameterDescription(button));
      button.addEventListener("blur", hideParameterDescription);
      button.addEventListener("click", () => {
        if (!isAvailable) {
          const station = Array.from(groupedRecords.keys()).find(name => getAvailableParameters(name).includes(parameter));
          if (station) {
            state.selectedParameter = parameter;
            selectLocation(station, {openPopup: false});
          }
          return;
        }
        state.selectedParameter = parameter;
        syncSelectedYearForParameter();
        syncPeriodSelection();
        refreshViewsForParameterChange(parameters);
      });
      els.parameterTabs.appendChild(button);
    });

    const activeRecord = getParameterRecords()[0];
    els.parameterUnit.textContent = activeRecord?.unit || "No unit";
  }

  function getParameterDescription(parameter) {
    return PARAMETER_DESCRIPTIONS[getParameterFamily(parameter)] || "Water-quality parameter measured for the selected sampling point.";
  }

  function getParameterDescriptionTooltip() {
    let tooltip = document.getElementById("parameter-description-tooltip");
    if (!tooltip) {
      tooltip = document.createElement("div");
      tooltip.id = "parameter-description-tooltip";
      tooltip.className = "parameter-description-tooltip is-hidden";
      tooltip.setAttribute("role", "tooltip");
      document.body.appendChild(tooltip);
    }
    return tooltip;
  }

  function showParameterDescription(button) {
    const description = button.dataset.parameterDescription;
    if (!description) {
      return;
    }

    const tooltip = getParameterDescriptionTooltip();
    tooltip.textContent = description;
    tooltip.classList.remove("is-hidden");
    positionParameterDescription(button);
  }

  function positionParameterDescription(button) {
    const tooltip = document.getElementById("parameter-description-tooltip");
    if (!tooltip || tooltip.classList.contains("is-hidden")) {
      return;
    }

    const buttonRect = button.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    const viewportPadding = 12;
    const top = buttonRect.bottom + 8;
    const centeredLeft = buttonRect.left + (buttonRect.width / 2) - (tooltipRect.width / 2);
    const left = Math.min(
      window.innerWidth - tooltipRect.width - viewportPadding,
      Math.max(viewportPadding, centeredLeft)
    );

    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${Math.min(top, window.innerHeight - tooltipRect.height - viewportPadding)}px`;
  }

  function hideParameterDescription() {
    const tooltip = document.getElementById("parameter-description-tooltip");
    if (tooltip) {
      tooltip.classList.add("is-hidden");
    }
  }

  // If the current month/annual selection no longer has data, move to the next valid option.
  function syncPeriodSelection() {
    const records = filterRecordsBySelectedYear(getParameterRecords());
    const availableMonthIndexes = new Set(records.map((record) => record.monthIndex).filter((monthIndex) => monthIndex > 0));
    const hasAnnual = records.some((record) => !record.monthIndex) || availableMonthIndexes.size > 0;
    const currentMonth = MONTH_OPTIONS.find((month) => month.key === state.selectedPeriod);
    const monthStillAvailable = currentMonth && availableMonthIndexes.has(currentMonth.monthIndex);

    if (state.selectedPeriod === "annual" && hasAnnual) {
      return;
    }

    if (monthStillAvailable) {
      return;
    }

    state.selectedPeriod = hasAnnual ? "annual" : (MONTH_OPTIONS.find((month) => availableMonthIndexes.has(month.monthIndex))?.key || "annual");
  }

  function syncSelectedYearForParameter() {
    const availableYears = getAvailableYearsForParameter();
    if (state.selectedYear === "all" || availableYears.includes(state.selectedYear)) {
      return;
    }

    state.selectedYear = "all";
  }

  // Draw the annual/month filter buttons and refresh dependent panels when one is chosen.
  function renderPeriodFilter() {
    syncYearSelection();

    const locationRecords = groupedRecords.get(state.selectedLocation) || [];
    const parameterPool = state.selectedParameter
      ? locationRecords.filter((record) => getParameterFamily(record.parameter) === state.selectedParameter)
      : locationRecords;
    const records = filterRecordsBySelectedYear(parameterPool);
    const availableMonthIndexes = new Set(records.map((record) => record.monthIndex).filter((monthIndex) => monthIndex > 0));
    const hasAnnual = records.some((record) => !record.monthIndex) || availableMonthIndexes.size > 0;

    syncPeriodSelection();

    els.periodFilter.innerHTML = "";
    const annualButton = document.createElement("button");
    annualButton.type = "button";
    annualButton.className = `period-button annual-button${state.selectedPeriod === "annual" ? " is-active" : ""}`;
    annualButton.textContent = "Annual";
    annualButton.disabled = !hasAnnual;
    annualButton.addEventListener("click", () => {
      state.selectedPeriod = "annual";
      syncSelectedParameterAvailability();
      refreshViewsForTimeFilterChange();
    });
    els.periodFilter.appendChild(annualButton);

    MONTH_OPTIONS.forEach((month) => {
      const isAvailable = availableMonthIndexes.has(month.monthIndex);
      const button = document.createElement("button");
      button.type = "button";
      button.className = `period-button${month.key === state.selectedPeriod ? " is-active" : ""}`;
      button.textContent = month.label;
      button.disabled = !isAvailable;
      button.addEventListener("click", () => {
        if (!isAvailable) {
          return;
        }
        state.selectedPeriod = month.key;
        syncSelectedParameterAvailability();
        refreshViewsForTimeFilterChange();
      });
      els.periodFilter.appendChild(button);
    });

    renderYearFilter();
  }

  function getAvailableYears(locationName = state.selectedLocation) {
    const records = groupedRecords.get(locationName) || [];

    return Array.from(new Set(
      records
        .map((record) => record.year)
        .filter((year) => Number.isFinite(year) && year > 0)
    )).sort((a, b) => a - b);
  }

  // Guards against stale state when switching to a location that lacks the current year.
  function syncYearSelection() {
    const availableYears = getAvailableYears();
    if (state.selectedYear === "all" || availableYears.includes(state.selectedYear)) {
      return;
    }

    state.selectedYear = "all";
  }

  // Draw the "All" button plus one button per sampled year.
  function renderYearFilter() {
    if (!els.yearFilter) {
      return;
    }

    syncYearSelection();
    const availableYears = getAvailableYears();
    els.yearFilter.innerHTML = "";

    const allButton = document.createElement("button");
    allButton.type = "button";
    allButton.className = `period-button${state.selectedYear === "all" ? " is-active" : ""}`;
    allButton.textContent = "All";
    allButton.disabled = !availableYears.length;
    allButton.addEventListener("click", () => {
      state.selectedYear = "all";
      refreshViewsForTimeFilterChange({ includeWeather: true });
    });
    els.yearFilter.appendChild(allButton);

    availableYears.forEach((year) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `period-button${state.selectedYear === year ? " is-active" : ""}`;
      button.textContent = String(year);
      button.addEventListener("click", () => {
        state.selectedYear = year;
        refreshViewsForTimeFilterChange({ includeWeather: true });
      });
      els.yearFilter.appendChild(button);
    });
  }

  // Create the main water-quality line chart for the selected parameter.
  function renderTrendChart(records) {
    const point = records.find(record => record.timelineKey === state.selectedTimelineKey) || records[records.length - 1];
    els.valueSummary.textContent = point ? `${formatValue(point)} on ${point.timelineLabel || point.dateLabel}` : "No numeric trend";
    renderLibraryFigure("trend", els.trendChart, els.trendEmpty);
    refreshParameterScale();
  }

  function renderEmptyChart(message) {
    clearLibraryFigure("trend", els.trendChart, els.trendEmpty, message);
    els.valueSummary.textContent = "No numeric trend";
    refreshParameterScale();
  }

  // Recolor map markers whenever suitability or selection state changes.
  function refreshMarkerStyles(openActivePopup = true) {
    markers.forEach((marker, locationName) => {
      const isActive = locationName === state.selectedLocation;
      const isStp = isSewageTreatmentPlant(locationName);
      const suitability = evaluateLocationSuitability(locationName);
      const markerColor = SUITABILITY_COLORS[suitability.status] || SUITABILITY_COLORS.unknown;
      marker.setStyle({
        radius: isActive ? 12 : 8,
        fillColor: markerColor,
        color: isActive ? "#111827" : (isStp ? "#92400e" : "#ffffff"),
        weight: isActive ? 3 : 2,
      });
      marker.setPopupContent(buildLocationPopup(locationName));
    });

    const activeMarker = markers.get(state.selectedLocation);
    if (activeMarker && openActivePopup) {
      activeMarker.openPopup();
    }
  }

  // Permanent marker labels show the station name plus the latest visible value.
  function updateMapLabels() {
    const selectedParameter = state.selectedParameter;

    markers.forEach((marker, locationName) => {
      const periodRecords = getRecordsForLocationPeriod(locationName, selectedParameter);
      const latestRecord = periodRecords[periodRecords.length - 1];
      const labelName = getMapLabelName(locationName);

      if (!latestRecord) {
        marker.unbindTooltip();
        marker.bindTooltip(`<span class="point-value-name">${escapeHtml(labelName)}</span>`, {
          permanent: markers.size <= 12 || locationName === state.selectedLocation,
          direction: "top",
          offset: [0, -14],
          className: "point-value-tooltip",
          opacity: 1,
        });
        return;
      }

      let labelValue = Number.isFinite(latestRecord.numericValue)
        ? formatCompactNumber(latestRecord.numericValue)
        : latestRecord.rawValue || "NA";

      const endpoints = periodRecords.filter(record => record.date === latestRecord.date && getParameterVariant(record.parameter));
      const low = endpoints.find(record => getParameterVariant(record.parameter).toLowerCase() === "min");
      const high = endpoints.find(record => getParameterVariant(record.parameter).toLowerCase() === "max");
      if (low && high) labelValue = `${formatCompactNumber(low.numericValue)} - ${formatCompactNumber(high.numericValue)}`;
      marker.unbindTooltip();
      marker.bindTooltip([
        `<span class="point-value-name">${escapeHtml(labelName)}</span>`,
        `<span class="point-value-text">${escapeHtml(labelValue)}</span>`,
      ].join(""), {
        permanent: markers.size <= 12 || locationName === state.selectedLocation,
        direction: "top",
        offset: [0, -14],
        className: "point-value-tooltip",
        opacity: 1,
      });
    });
  }

  function getRecordsForLocationPeriod(locationName, parameter) {
    const records = groupedRecords.get(locationName) || [];
    const parameterRecords = filterRecordsByYear(
      records.filter((record) => getParameterFamily(record.parameter) === parameter),
      state.selectedYear
    );

    if (state.selectedPeriod === "annual") {
      return buildTrendSeries(parameterRecords);
    }

    const option = MONTH_OPTIONS.find((month) => month.key === state.selectedPeriod);
    if (!option) {
      return [];
    }

    return parameterRecords
      .filter((record) => record.monthIndex === option.monthIndex)
      .sort((a, b) => a.sortKey - b.sortKey || a.fileName.localeCompare(b.fileName));
  }

  function getMapLabelName(locationName) {
    const match = String(locationName).match(/^(NCC\d+|NCM\d+|NCP\d+|3BRD|Diggian|CPCB Station Code 2047)/i);
    return match ? match[1] : locationName;
  }

  function filterRecordsBySelectedYear(records) {
    return filterRecordsByYear(records, state.selectedYear);
  }

  function filterRecordsByYear(records, year) {
    if (year === "all") {
      return records;
    }

    return records.filter((record) => record.year === year);
  }

  // Desktop-only drag support for the floating period panel.
  function initializePeriodPanelDrag() {
    if (!els.periodPanel) {
      return;
    }

    let isDragging = false;
    let pointerOffsetX = 0;
    let pointerOffsetY = 0;

    const handlePointerMove = (event) => {
      if (!isDragging || window.innerWidth <= 1080) {
        return;
      }

      const mapRect = document.querySelector(".map-area").getBoundingClientRect();
      const panelRect = els.periodPanel.getBoundingClientRect();
      const nextLeft = Math.min(
        Math.max(18, event.clientX - mapRect.left - pointerOffsetX),
        mapRect.width - panelRect.width - 18
      );
      const nextTop = Math.min(
        Math.max(96, event.clientY - mapRect.top - pointerOffsetY),
        mapRect.height - panelRect.height - 18
      );

      els.periodPanel.style.left = `${nextLeft}px`;
      els.periodPanel.style.top = `${nextTop}px`;
    };

    const stopDragging = () => {
      isDragging = false;
      document.body.classList.remove("is-dragging-panel");
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopDragging);
    };

    els.periodPanel.querySelector(".period-panel-heading")?.addEventListener("pointerdown", (event) => {
      if (window.innerWidth <= 1080) {
        return;
      }

      const rect = els.periodPanel.getBoundingClientRect();
      pointerOffsetX = event.clientX - rect.left;
      pointerOffsetY = event.clientY - rect.top;
      isDragging = true;
      document.body.classList.add("is-dragging-panel");
      window.addEventListener("pointermove", handlePointerMove);
      window.addEventListener("pointerup", stopDragging);
    });
  }

  // Reduce many rows within a year down to one representative yearly record.
  function buildYearlySeries(records) {
    const byYear = new Map();

    records.forEach((record) => {
      const key = String(record.year);
      if (!byYear.has(key)) {
        byYear.set(key, []);
      }
      byYear.get(key).push(record);
    });

    return Array.from(byYear.entries())
      .sort((a, b) => Number(a[0]) - Number(b[0]))
      .map(([year, yearRecords]) => {
        const annualRecords = yearRecords.filter((record) => !record.monthIndex);
        const monthlyRecords = yearRecords.filter((record) => record.monthIndex);
        // Prefer explicit annual rows; otherwise average the available monthly rows.
        const preferred = annualRecords.length ? annualRecords : monthlyRecords;
        const numericRecords = preferred.filter((record) => Number.isFinite(record.numericValue));
        const averageValue = numericRecords.length
          ? numericRecords.reduce((sum, record) => sum + record.numericValue, 0) / numericRecords.length
          : null;
        const sourceLabel = annualRecords.length
          ? `Annual reading${annualRecords.length > 1 ? `s (${annualRecords.length})` : ""}`
          : `Average of ${monthlyRecords.length} month${monthlyRecords.length === 1 ? "" : "s"}`;

        return {
          ...preferred[preferred.length - 1],
          rawValue: averageValue == null ? preferred[preferred.length - 1].rawValue : String(averageValue),
          numericValue: averageValue,
          timelineKey: Number(year) * 100,
          timelineLabel: String(year),
          timelineMeta: sourceLabel,
          dateLabel: String(year),
          sortKey: Number(year) * 100,
        };
      });
  }

  function isSewageTreatmentPlant(locationName) {
    return /stp|sewage treatment plant|diggian|3brd|chilla/i.test(String(locationName));
  }

  // Shared value formatter for popups, tooltips, summaries, and labels.
  function formatValue(record) {
    if (!record) {
      return "No value";
    }

    const parameterSuffix = state.selectedParameter && record.parameter && record.parameter !== state.selectedParameter
      ? ` (${record.parameter})`
      : "";

    if (Number.isFinite(record.numericValue)) {
      return `${formatCompactNumber(record.numericValue)} ${record.unit || ""}${parameterSuffix}`.trim();
    }

    return `${record.rawValue || "No value"} ${record.unit || ""}${parameterSuffix}`.trim();
  }

  function formatCompactNumber(value) {
    if (!Number.isFinite(value)) {
      return "NA";
    }

    if (Math.abs(value) >= 10000) {
      return formatScientificNumber(value);
    }

    if (Math.abs(value) >= 1000) {
      return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
    }

    if (Math.abs(value) >= 10) {
      return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
    }

    return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function formatScientificNumber(value) {
    return Number(value)
      .toExponential(2)
      .replace(/\.0+e/, "e")
      .replace(/(\.\d*?)0+e/, "$1e")
      .replace("e+", "E+")
      .replace("e-", "E-");
  }

  // Interpolation rasters are loaded once and reused as the selected parameter changes.
  // The library computes kriging on the first request and caches it per dataset.
  async function loadInterpolationData() {
    // Empty datasets do not need interpolation.
    if (dashboardData.records.length === 0) {
      return null;
    }

    if (interpolationData) {
      // Reuse the parsed payload if we already fetched it earlier in this session.
      return interpolationData;
    }

    if (!interpolationRequest) {
      // Keep one shared in-flight request so multiple UI refreshes do not fetch the same
      // dataset-specific interpolation again before the first request finishes.
      interpolationRequest = fetch(`/api/interpolation?id=${encodeURIComponent(dashboardData.datasetId || "")}`, { cache: "no-store" })
        .then((response) => {
          if (!response.ok) {
            throw new Error(`Interpolation data request failed with status ${response.status}`);
          }

          return response.json();
        })
        .then((payload) => {
          // Store the parsed interpolation payload for future parameter/year switches.
          interpolationData = payload;
          return payload;
        })
        .catch((error) => {
          // If loading fails, keep the dashboard usable and just skip the overlay.
          console.warn("Interpolation overlay could not be loaded.", error);
          interpolationData = null;
          interpolationRequest = null;
          document.getElementById("map-interpolation-status").textContent = "Interpolation could not load. Switch the interpolation toggle to retry.";
          return null;
        });
    }

    return interpolationRequest;
  }

  // Pick the raster surface that best matches the current parameter/year selection.
  // Each library surface represents one parameter for either:
  // 1. a specific year, or
  // 2. the all-years aggregate fallback.
  function getInterpolationSurface() {
    if (!interpolationData || !state.selectedParameter) {
      return null;
    }

    // Normalize the selected parameter name so frontend labels match backend surface names.
    const parameterFamily = getCanonicalInterpolationParameter(getParameterFamily(state.selectedParameter));
    const targetYear = getInterpolationTargetYear();
    const matchSurface = (surfaces) => surfaces.find((surface) =>
      getCanonicalInterpolationParameter(getParameterFamily(surface.parameterFamily || surface.parameter)) === parameterFamily
    ) || null;

    if (targetYear != null) {
      // Prefer a year-specific surface when the UI is focused on one year.
      const yearlyMatch = matchSurface((interpolationData?.surfaces?.yearly || []).filter((surface) => surface.year === targetYear));
      if (yearlyMatch) {
        return yearlyMatch;
      }
    }

    // Fall back to the all-years surface if no yearly match exists.
    return matchSurface(interpolationData?.surfaces?.allYears || []);
  }

  function getInterpolationEstimateAt(latlng) {
    const surface = getInterpolationSurface();
    const grid = surface?.grid;
    const extent = grid?.extent;
    if (!grid?.values?.length || !extent || !grid.rows || !grid.columns) return null;
    if (
      latlng.lat < extent.minLatitude || latlng.lat > extent.maxLatitude ||
      latlng.lng < extent.minLongitude || latlng.lng > extent.maxLongitude
    ) return null;

    const latitudeSpan = extent.maxLatitude - extent.minLatitude;
    const longitudeSpan = extent.maxLongitude - extent.minLongitude;
    const row = Math.max(0, Math.min(grid.rows - 1,
      Math.round(((extent.maxLatitude - latlng.lat) / (latitudeSpan || 1)) * (grid.rows - 1))));
    const column = Math.max(0, Math.min(grid.columns - 1,
      Math.round(((latlng.lng - extent.minLongitude) / (longitudeSpan || 1)) * (grid.columns - 1))));
    const value = grid.values[(row * grid.columns) + column];
    return Number.isFinite(value) ? { value, surface, row, column } : null;
  }

  function getInterpolationTargetYear() {
    if (state.selectedYear !== "all") {
      // If the user explicitly picked a year, use that year’s kriging surface.
      return state.selectedYear;
    }

    if (state.selectedPeriod === "annual") {
      // In annual mode with "all years" selected, use the currently highlighted trend point's
      // year when possible so the interpolation overlay stays in sync with the selected sample.
      const selectedRecord = getSelectedParameterScaleRecord();
      if (selectedRecord && Number.isFinite(selectedRecord.year) && selectedRecord.year > 0) {
        return selectedRecord.year;
      }
    }

    return null;
  }

  function getCanonicalInterpolationParameter(parameter) {
    const family = String(parameter || "").trim();

    // Normalize coliform naming so backend-generated surface names and frontend parameter
    // labels resolve to the same interpolation surface.
    if (/^t[.\s-]*coliform$/i.test(family) || /^total coliform$/i.test(family)) {
      return "Total Coliform";
    }

    if (/^faecal coliform$/i.test(family) || /^fecal coliform$/i.test(family)) {
      return "Faecal Coliform";
    }

    return family;
  }

  // Remove any old overlay and draw the current interpolation image on the map.
  // The backend provides a numeric grid; this function turns that grid into a temporary
  // image and stretches it over the interpolation extent on the Leaflet map.
  function refreshInterpolationOverlay() {
    if (interpolationOverlay) {
      map.removeLayer(interpolationOverlay);
      interpolationOverlay = null;
    }

    const status = document.getElementById("map-interpolation-status");
    const legend = document.getElementById("map-interpolation-legend");
    legend.hidden = true;
    if (!interpolationEnabled) {
      status.textContent = "Interpolation hidden.";
      return;
    }
    const surface = getInterpolationSurface();
    if (!surface?.grid?.values?.length) {
      status.textContent = !dashboardData.records.length ? "Import a CSV to view interpolation." : !interpolationData ? "Loading interpolation..." : "No interpolation for this parameter and year.";
      return;
    }

    const imageUrl = buildInterpolationImage(surface);
    if (!imageUrl) {
      status.textContent = "No numeric interpolation values available.";
      return;
    }

    const bounds = [
      [surface.grid.extent.minLatitude, surface.grid.extent.minLongitude],
      [surface.grid.extent.maxLatitude, surface.grid.extent.maxLongitude],
    ];

    const values = surface.grid.values.filter(Number.isFinite);
    const minimum = Math.min(...values);
    const maximum = Math.max(...values);
    legend.hidden = false;
    legend.textContent = `${formatCompactNumber(minimum)} \u2013 ${formatCompactNumber(maximum)} ${surface.unit || ""}`;
    status.textContent = `${surface.parameter} \u00b7 ${surface.year ?? "All years"}. ${surface.method}. Click the coloured area for an estimate.`;

    // Leaflet places the generated PNG over the geographic bounds of the kriging grid.
    interpolationOverlay = L.imageOverlay(imageUrl, bounds, {
      opacity: 0.88,
      pane: "interpolationPane",
      interactive: false,
    }).addTo(map);
  }

  // Convert numeric grid data into a semi-transparent PNG using an in-memory canvas.
  // Browser maps cannot directly render a raw 2D array of numbers, so we paint each grid
  // value into one pixel of an off-screen canvas and then export that canvas as an image.
  function buildInterpolationImage(surface) {
    const grid = surface.grid;
    const validValues = grid.values.filter((value) => Number.isFinite(value));
    if (!validValues.length || !grid.columns || !grid.rows) {
      return null;
    }

    // Compute the numeric range present in this surface so values can be normalized.
    const min = Math.min(...validValues);
    const max = Math.max(...validValues);
    const span = max - min || 1;
    const canvas = document.createElement("canvas");
    canvas.width = grid.columns;
    canvas.height = grid.rows;
    const context = canvas.getContext("2d");
    context.imageSmoothingEnabled = true;
    const imageData = context.createImageData(grid.columns, grid.rows);

    grid.values.forEach((value, index) => {
      const pixelOffset = index * 4;
      if (!Number.isFinite(value)) {
        // Transparent pixel for masked or unavailable cells.
        imageData.data[pixelOffset + 3] = 0;
        return;
      }

      // Normalize each grid value first, then map it into a color ramp.
      const normalized = getInterpolationNormalizedValue(value, min, max, span);
      const color = getInterpolationColor(normalized);
      imageData.data[pixelOffset] = color[0];
      imageData.data[pixelOffset + 1] = color[1];
      imageData.data[pixelOffset + 2] = color[2];
      imageData.data[pixelOffset + 3] = 210;
    });

    context.putImageData(imageData, 0, 0);
    return canvas.toDataURL("image/png");
  }

  // Uses log scaling for very wide positive ranges so extreme outliers do not flatten the map.
  // Without this, a few very large values could force almost the entire surface into the
  // same low-color band, making the overlay visually uninformative.
  function getInterpolationNormalizedValue(value, min, max, span) {
    if (!Number.isFinite(value)) {
      return 0;
    }

    const isPositiveRange = min > 0 && max > 0;
    const dynamicRange = isPositiveRange ? (max / min) : 0;
    if (isPositiveRange && dynamicRange >= 100) {
      const logMin = Math.log10(min);
      const logMax = Math.log10(max);
      const logSpan = logMax - logMin || 1;
      return clamp((Math.log10(value) - logMin) / logSpan, 0, 1);
    }

    return clamp((value - min) / span, 0, 1);
  }

  // Blue -> cyan -> green -> yellow -> red gradient for the interpolation surface.
  // Lower interpolated values appear cooler, while higher values move into warmer colors.
  function getInterpolationColor(normalized) {
    const stops = [
      { at: 0, color: [29, 78, 216, 88] },
      { at: 0.18, color: [8, 145, 178, 112] },
      { at: 0.42, color: [5, 150, 105, 138] },
      { at: 0.68, color: [234, 179, 8, 164] },
      { at: 1, color: [220, 38, 38, 188] },
    ];

    for (let index = 1; index < stops.length; index += 1) {
      const left = stops[index - 1];
      const right = stops[index];
      if (normalized <= right.at) {
        // Interpolate smoothly between the surrounding color stops.
        const amount = (normalized - left.at) / (right.at - left.at || 1);
        return [
          Math.round(left.color[0] + ((right.color[0] - left.color[0]) * amount)),
          Math.round(left.color[1] + ((right.color[1] - left.color[1]) * amount)),
          Math.round(left.color[2] + ((right.color[2] - left.color[2]) * amount)),
          Math.round(left.color[3] + ((right.color[3] - left.color[3]) * amount)),
        ];
      }
    }

    return stops[stops.length - 1].color;
  }

  function shortLabel(label) {
    const parts = String(label).split(" ");
    if (parts.length >= 2) {
      if (/^\d{4}$/.test(parts[0])) {
        return `${parts[0]} ${parts[1].slice(0, 3)}`;
      }
      return `${parts[0].slice(0, 3)} ${parts[1]}`;
    }
    return String(label);
  }

  // Parameter family strips suffixes like "(max)" and "(min)" so variants group together.
  function getParameterFamily(parameter) {
    const clean = fixTextValue(parameter);
    const variant = getParameterVariant(clean);
    return variant ? clean.replace(/\s*\([^)]*\)\s*$/, "").trim() : clean;
  }

  // Extracts max/min variant tags when present.
  function getParameterVariant(parameter) {
    const match = fixTextValue(parameter).match(/\(([^)]*)\)\s*$/);
    if (!match) {
      return "";
    }

    const variant = match[1].trim();
    return /^(max|min)$/i.test(variant) ? variant : "";
  }

  function compareParameterVariants(leftParameter, rightParameter) {
    const leftVariant = getParameterVariant(leftParameter);
    const rightVariant = getParameterVariant(rightParameter);

    if (!leftVariant && rightVariant) return -1;
    if (leftVariant && !rightVariant) return 1;
    return leftVariant.localeCompare(rightVariant);
  }

  function buildTrendLabel(record) {
    const variant = getParameterVariant(record.parameter);
    return variant ? `${record.year} ${variant}` : String(record.year || record.dateLabel);
  }

  function fixTextValue(value) {
    return String(value || "").trim();
  }

  // Any user/data text inserted into HTML should be escaped to avoid broken markup/XSS.
  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // Boot the dashboard by selecting the first mapped location (or first known location).
  selectLocation(defaultLocation?.name || "", { focusMap: false, openPopup: false });
})();
