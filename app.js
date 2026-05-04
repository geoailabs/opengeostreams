(function () {
  const dashboardData = window.NCHOE_DASHBOARD_DATA;

  if (!dashboardData || !Array.isArray(dashboardData.records)) {
    document.getElementById("location-name").textContent = "Dashboard data not found";
    document.getElementById("location-meta").textContent = "Run build-dashboard-data.ps1 to generate dashboard-data.js.";
    return;
  }

  const state = {
    selectedLocation: null,
    selectedParameter: null,
    selectedTimelineKey: null,
    selectedWeatherMonthKey: null,
    selectedPeriod: "annual",
    selectedYear: "all",
    baseMap: "osm",
    selectedUseCase: "human_consumption",
  };

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

  const CHART_Y_AXIS_WIDTH = 54;
  const USE_CASES = [
    { key: "human_consumption", label: "Human Consumption" },
    { key: "agriculture", label: "Agriculture" },
    { key: "aquatic_life", label: "Aquatic Life" },
    { key: "bathing", label: "Bathing" },
  ];
  const SUITABILITY_COLORS = {
    safe: "#16a34a",
    caution: "#d97706",
    unsafe: "#dc2626",
    unknown: "#64748b",
  };
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
  const CORE_KEYS_BY_USE_CASE = {
    human_consumption: ["pH", "turbidity_ntu", "tds_mg_l", "nitrate_mg_l", "fluoride_mg_l", "total_coliform_mpn_100ml", "e_coli_present"],
    agriculture: ["pH", "ec_us_cm", "sar", "boron_mg_l"],
    aquatic_life: ["pH", "dissolved_oxygen_mg_l", "free_ammonia_mg_l_as_n"],
    bathing: ["pH", "dissolved_oxygen_mg_l", "bod_mg_l", "total_coliform_mpn_100ml", "fecal_coliform_mpn_100ml", "e_coli_present"],
  };
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
      total_coliform: { label: "Total Coliform", type: "max", safeMax: 500, unit: "MPN/100mL", domainMin: 0, domainMax: 2000 },
      fecal_coliform: { label: "Faecal Coliform", type: "max", safeMax: 500, unit: "MPN/100mL", domainMin: 0, domainMax: 2000 },
      turbidity: { label: "Turbidity", type: "max", safeMax: 10, unit: "NTU" },
    },
  };

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
    weatherChart: document.getElementById("weather-chart"),
    weatherEmpty: document.getElementById("weather-empty"),
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

  const locationIndex = new Map();
  const groupedRecords = new Map();
  const markers = new Map();
  const weatherCache = new Map();
  let trendChartInstance = null;
  let weatherChartInstance = null;
  let streamTooltipEl = null;

  dashboardData.locations.forEach((location) => {
    locationIndex.set(location.name, location);
  });

  dashboardData.records.forEach((record) => {
    const key = record.locationGroup;
    if (!groupedRecords.has(key)) {
      groupedRecords.set(key, []);
    }
    groupedRecords.get(key).push(record);
  });

  groupedRecords.forEach((records) => {
    records.sort((a, b) => a.sortKey - b.sortKey || a.fileName.localeCompare(b.fileName));
  });

  const mappedLocations = dashboardData.locations.filter((location) => location.hasCoordinates);
  const defaultLocation = mappedLocations[0] || dashboardData.locations[0];
  populateLocationSelect(mappedLocations);

  const inferredLocationCount = dashboardData.locations.filter((location) => location.coordinateInferred).length;
  els.mappedCount.textContent = String(dashboardData.summary.mappedLocationCount);
  els.mapNote.textContent = `${dashboardData.summary.mappedLocationCount} mapped locations come directly from the latitude/longitude fields in the dataset CSVs. ${inferredLocationCount} location(s) currently use inferred coordinates pending verification. ${dashboardData.summary.unmappedLocationCount} location(s) remain off-map because no coordinates were available.`;

  const map = L.map("map", {
    zoomControl: true,
    scrollWheelZoom: true,
  });

  const baseLayers = {
    osm: L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }),
    minimal: L.tileLayer("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png", {
      maxZoom: 20,
      subdomains: "abcd",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
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

  function refreshBaseMapButtons() {
    els.basemapToggle.querySelectorAll("[data-basemap]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.basemap === state.baseMap);
    });
  }

  refreshBaseMapButtons();
  renderUseCaseTabs();
  initializeStreamTooltip();
  if (mappedLocations.length) {
    const bounds = L.latLngBounds(mappedLocations.map((location) => [location.latitude, location.longitude]));
    map.fitBounds(bounds, {
      paddingTopLeft: [28, 24],
      paddingBottomRight: [28, 150],
      maxZoom: 11,
    });
  } else {
    map.setView([30.7, 76.75], 10);
  }

  mappedLocations.forEach((location) => {
    const isStp = isSewageTreatmentPlant(location.name);
    const marker = L.circleMarker([location.latitude, location.longitude], {
      radius: 8,
      weight: 2,
      color: "#ffffff",
      fillColor: isStp ? "#d97706" : "#0f766e",
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

    marker.on("click", () => {
      selectLocation(location.name, { focusMap: true });
    });

    markers.set(location.name, marker);
  });

  refreshSuitabilitySummary();
  refreshParameterScale();

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

  function getSuitabilityFilterLabel() {
    const yearLabel = state.selectedYear === "all" ? "all sampled years" : String(state.selectedYear);
    if (state.selectedPeriod === "annual") {
      return yearLabel;
    }

    const selectedMonth = MONTH_OPTIONS.find((month) => month.key === state.selectedPeriod);
    return selectedMonth ? `${selectedMonth.label} within ${yearLabel}` : yearLabel;
  }

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

  function selectLocation(locationName, options = {}) {
    state.selectedLocation = locationName;
    state.selectedYear = "all";
    const parameters = getLocationParameters(locationName);

    if (!parameters.length) {
      state.selectedParameter = null;
      renderLocation();
      refreshStreamVisualization();
      renderParameterTabs([]);
      renderPeriodFilter();
      renderEmptyChart("No parameter data is available for this location.");
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

  function getParameterRecords() {
    const records = groupedRecords.get(state.selectedLocation) || [];
    return records.filter((record) => getParameterFamily(record.parameter) === state.selectedParameter);
  }

  function getLocationParameters(locationName = state.selectedLocation) {
    const records = groupedRecords.get(locationName) || [];
    return Array.from(new Set(
      records
        .filter((record) => record.parameter && (record.rawValue || Number.isFinite(record.numericValue)))
        .map((record) => getParameterFamily(record.parameter))
    )).sort((a, b) => a.localeCompare(b));
  }

  function getAvailableParameters(locationName = state.selectedLocation) {
    const records = filterRecordsBySelectedYear(groupedRecords.get(locationName) || []);

    return Array.from(new Set(
      records
        .filter((record) => {
          if (!record.parameter || (!record.rawValue && !Number.isFinite(record.numericValue))) {
            return false;
          }

          if (state.selectedPeriod === "annual") {
            return true;
          }

          const option = MONTH_OPTIONS.find((month) => month.key === state.selectedPeriod);
          return option ? record.monthIndex === option.monthIndex : true;
        })
        .map((record) => getParameterFamily(record.parameter))
    )).sort((a, b) => a.localeCompare(b));
  }

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

  function refreshTrendChart() {
    const trendRecords = getTimelineRecords();
    if (!trendRecords.some((record) => record.timelineKey === state.selectedTimelineKey)) {
      state.selectedTimelineKey = trendRecords[trendRecords.length - 1]?.timelineKey ?? null;
    }
    renderTrendChart(trendRecords);
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

  function refreshStreamVisualization() {
    if (!els.streamVisualization || !els.streamStatus) {
      return;
    }

    hideStreamTooltip();
    if (!state.selectedParameter) {
      renderStreamVisualizationEmpty("Select a parameter to compare yearly values along the stream.", "Select parameter");
      return;
    }

    const years = getAllAvailableYears();
    const locations = getStreamVisualizationLocations();
    const rows = locations
      .map((location) => buildStreamVisualizationRow(location.name, years))
      .filter((row) => row.cells.some((cell) => Number.isFinite(cell.value)));

    if (!rows.length) {
      renderStreamVisualizationEmpty("No yearly values are available for this parameter across the mapped points.", state.selectedParameter);
      return;
    }

    const values = rows.flatMap((row) => row.cells.map((cell) => cell.value)).filter((value) => Number.isFinite(value));
    const min = values.length ? Math.min(...values) : 0;
    const max = values.length ? Math.max(...values) : 0;

    const headerCells = [
      '<div class="stream-axis stream-axis-corner">Point</div>',
      ...years.map((year) => `<div class="stream-axis">${escapeHtml(String(year))}</div>`),
    ];

    const bodyCells = rows.flatMap((row) => {
      const rowLabelClass = row.name === state.selectedLocation ? "stream-row-label is-active" : "stream-row-label";
      const rowLabel = `<div class="${rowLabelClass}">${escapeHtml(getMapLabelName(row.name))}</div>`;
      const valueCells = row.cells.map((cell) => {
        const intensity = getHeatmapIntensity(cell.value, min, max);
        const tooltip = cell.record
          ? `${row.name} | ${cell.year}: ${formatValue(cell.record)}`
          : `${row.name} | ${cell.year}: No data`;
        return `<div class="stream-cell${cell.record ? "" : " is-empty"}" style="--stream-intensity:${intensity}" data-tooltip="${escapeHtml(tooltip)}" aria-label="${escapeHtml(tooltip)}" tabindex="0"></div>`;
      });
      return [rowLabel, ...valueCells];
    });

    els.streamVisualization.style.setProperty("--stream-year-count", String(years.length));
    els.streamVisualization.innerHTML = [...headerCells, ...bodyCells].join("");
    els.streamStatus.textContent = state.selectedParameter;
  }

  function renderStreamVisualizationEmpty(message, status = "Select parameter") {
    if (!els.streamVisualization || !els.streamStatus) {
      return;
    }

    hideStreamTooltip();
    els.streamVisualization.style.removeProperty("--stream-year-count");
    els.streamVisualization.innerHTML = `<div class="stream-empty">${escapeHtml(message)}</div>`;
    els.streamStatus.textContent = status;
  }

  function initializeStreamTooltip() {
    if (!els.streamVisualization) {
      return;
    }

    streamTooltipEl = document.createElement("div");
    streamTooltipEl.className = "stream-hover-tooltip";
    streamTooltipEl.setAttribute("role", "tooltip");
    document.body.appendChild(streamTooltipEl);

    els.streamVisualization.addEventListener("mousemove", (event) => {
      const cell = event.target.closest(".stream-cell");
      if (!cell || !els.streamVisualization.contains(cell)) {
        hideStreamTooltip();
        return;
      }

      showStreamTooltip(cell.dataset.tooltip || "", {
        x: event.clientX,
        y: event.clientY,
      });
    });

    els.streamVisualization.addEventListener("mouseleave", hideStreamTooltip);

    els.streamVisualization.addEventListener("focusin", (event) => {
      const cell = event.target.closest(".stream-cell");
      if (!cell || !els.streamVisualization.contains(cell)) {
        return;
      }

      const rect = cell.getBoundingClientRect();
      showStreamTooltip(cell.dataset.tooltip || "", {
        x: rect.left + (rect.width / 2),
        y: rect.top,
      });
    });

    els.streamVisualization.addEventListener("focusout", hideStreamTooltip);
    window.addEventListener("scroll", hideStreamTooltip, { passive: true });
    window.addEventListener("resize", hideStreamTooltip);
  }

  function showStreamTooltip(text, point) {
    if (!streamTooltipEl || !text) {
      return;
    }

    streamTooltipEl.textContent = text;
    streamTooltipEl.classList.add("is-visible");

    const tooltipRect = streamTooltipEl.getBoundingClientRect();
    const margin = 12;
    const desiredLeft = point.x + 14;
    const maxLeft = window.innerWidth - tooltipRect.width - margin;
    const left = Math.min(Math.max(margin, desiredLeft), Math.max(margin, maxLeft));

    let top = point.y - tooltipRect.height - 14;
    if (top < margin) {
      top = Math.min(window.innerHeight - tooltipRect.height - margin, point.y + 18);
    }

    streamTooltipEl.style.left = `${left}px`;
    streamTooltipEl.style.top = `${Math.max(margin, top)}px`;
  }

  function hideStreamTooltip() {
    if (!streamTooltipEl) {
      return;
    }

    streamTooltipEl.classList.remove("is-visible");
  }

  function getAllAvailableYears() {
    return Array.from(new Set(
      dashboardData.records
        .map((record) => record.year)
        .filter((year) => Number.isFinite(year) && year > 0)
    )).sort((a, b) => a - b);
  }

  function getStreamVisualizationLocations() {
    return dashboardData.locations
      .filter((location) => location.hasCoordinates)
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  function buildStreamVisualizationRow(locationName, years) {
    const records = groupedRecords.get(locationName) || [];
    const parameterRecords = records.filter((record) => getParameterFamily(record.parameter) === state.selectedParameter);
    const yearlySeries = buildYearlySeries(parameterRecords);
    const yearlyMap = new Map(yearlySeries.map((record) => [record.year, record]));

    return {
      name: locationName,
      cells: years.map((year) => {
        const record = yearlyMap.get(year) || null;
        return {
          year,
          record,
          value: record?.numericValue ?? null,
        };
      }),
    };
  }

  async function refreshWeatherChart() {
    const location = locationIndex.get(state.selectedLocation);
    if (!location?.hasCoordinates || !els.weatherChart || !els.weatherStatus || !els.weatherEmpty) {
      renderWeatherChartEmpty("Weather coordinates are not available for this location.", "No coordinates");
      return;
    }

    const years = getAvailableYears(state.selectedLocation);
    if (!years.length) {
      renderWeatherChartEmpty("No sampled years are available for this location.", "No years");
      return;
    }

    const cacheKey = `${location.latitude}|${location.longitude}|${years[0]}|${years[years.length - 1]}`;
    els.weatherStatus.textContent = "Loading";
    renderWeatherChartEmpty("Loading historical weather data...");

    try {
      let data = weatherCache.get(cacheKey);
      if (!data) {
        data = await fetchWeatherChartData(location, years);
        weatherCache.set(cacheKey, data);
      }

      renderWeatherChart(data);
    } catch (error) {
      renderWeatherChartEmpty("Unable to load weather data from the historical API.", "Weather unavailable");
    }
  }

  async function fetchWeatherChartData(location, years) {
    const startYear = years[0];
    const endYear = years[years.length - 1];
    const params = new URLSearchParams({
      latitude: String(location.latitude),
      longitude: String(location.longitude),
      start_date: `${startYear}-01-01`,
      end_date: `${endYear}-12-31`,
      daily: "precipitation_sum",
      timezone: "auto",
    });

    const response = await fetch(`/weather-history?${params.toString()}`);
    if (!response.ok) {
      throw new Error(`Weather API request failed with status ${response.status}`);
    }

    const payload = await response.json();
    return buildWeatherChartData(payload, years);
  }

  function buildWeatherChartData(payload, years) {
    const daily = payload?.daily;
    if (!daily || !Array.isArray(daily.time)) {
      throw new Error("Weather API did not return daily data.");
    }

    const byYear = new Map();
    years.forEach((year) => {
      byYear.set(year, new Map(WEATHER_MONTHS.map((month) => [month.key, []])));
    });

    daily.time.forEach((dateText, index) => {
      const year = Number.parseInt(String(dateText).slice(0, 4), 10);
      const month = Number.parseInt(String(dateText).slice(5, 7), 10);
      if (!byYear.has(year)) {
        return;
      }

      const precipitationSeries = daily.precipitation_sum;
      const value = Array.isArray(precipitationSeries) ? precipitationSeries[index] : null;
      if (Number.isFinite(value) && byYear.get(year).has(month)) {
        byYear.get(year).get(month).push(value);
      }
    });

    return {
      monthlyAverage: WEATHER_MONTHS.map((month) => ({
        ...month,
        value: aggregateWeatherMetric(
          years.map((year) => aggregateWeatherMetric(byYear.get(year).get(month.key), "sum")).filter((value) => Number.isFinite(value)),
          "mean"
        ),
      })),
      rows: years.map((year) => ({
        year,
        months: WEATHER_MONTHS.map((month) => ({
          ...month,
          value: aggregateWeatherMetric(byYear.get(year).get(month.key), "sum"),
        })),
      })),
    };
  }

  function aggregateWeatherMetric(values, mode) {
    if (!values.length) {
      return null;
    }

    if (mode === "sum") {
      return values.reduce((sum, value) => sum + value, 0);
    }

    return values.reduce((sum, value) => sum + value, 0) / values.length;
  }

  function renderWeatherChart(data) {
    if (!els.weatherChart || !els.weatherStatus || !els.weatherEmpty) {
      return;
    }

    const rows = data?.rows || [];
    if (!rows.length) {
      renderWeatherChartEmpty("No weather data available for the sampled years.", "No weather");
      return;
    }

    const chartSeries = getWeatherChartSeries(data);
    const chartPoints = chartSeries.filter((point) => Number.isFinite(point.value));

    if (!chartPoints.length) {
      renderWeatherChartEmpty("No monthly precipitation data is available for the selected year.", "No weather");
      return;
    }

    if (!chartPoints.some((point) => point.key === state.selectedWeatherMonthKey)) {
      state.selectedWeatherMonthKey = chartPoints[chartPoints.length - 1]?.key ?? null;
    }

    const selectedPoint = chartPoints.find((point) => point.key === state.selectedWeatherMonthKey) || chartPoints[chartPoints.length - 1];
    const pointRadii = chartSeries.map((point) => (point.key === selectedPoint.key ? 7 : 5));
    const pointColors = chartSeries.map((point) => (point.key === selectedPoint.key ? "#d97706" : "#0f766e"));

    if (weatherChartInstance) {
      weatherChartInstance.destroy();
    }

    els.weatherEmpty.textContent = "";
    els.weatherEmpty.classList.add("is-hidden");
    els.weatherChart.style.visibility = "visible";

    const context = els.weatherChart.getContext("2d");
    weatherChartInstance = new window.Chart(context, {
      type: "line",
      data: {
        labels: chartSeries.map((point) => point.label),
        datasets: [
          {
            data: chartSeries.map((point) => point.value),
            borderColor: "#0f766e",
            backgroundColor: "rgba(15, 118, 110, 0.14)",
            borderWidth: 4,
            fill: true,
            tension: 0.32,
            pointRadius: pointRadii,
            pointHoverRadius: pointRadii.map((radius) => radius + 2),
            pointHitRadius: 18,
            pointBackgroundColor: pointColors,
            pointBorderColor: "#ffffff",
            pointBorderWidth: 3,
            spanGaps: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: {
          mode: "nearest",
          intersect: true,
        },
        onClick(_event, elements) {
          const pointIndex = elements[0]?.index;
          const point = pointIndex == null ? null : chartSeries[pointIndex];
          if (!point || !Number.isFinite(point.value)) {
            return;
          }

          state.selectedWeatherMonthKey = point.key;
          renderWeatherChart(data);
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(22, 32, 32, 0.92)",
            titleColor: "#f7fffe",
            bodyColor: "#f7fffe",
            displayColors: false,
            callbacks: {
              title(items) {
                const index = items[0]?.dataIndex ?? 0;
                return chartSeries[index]?.label || "";
              },
              label(item) {
                const point = chartSeries[item.dataIndex];
                if (!point || !Number.isFinite(point.value)) {
                  return "No data";
                }
                return `${formatRainfall(point.value)} precipitation`;
              },
              afterLabel() {
                if (state.selectedPeriod === "annual") {
                  return state.selectedYear === "all"
                    ? "Average across available years"
                    : `Year ${state.selectedYear}`;
                }

                const selectedMonth = MONTH_OPTIONS.find((month) => month.key === state.selectedPeriod);
                return selectedMonth ? `${selectedMonth.label} precipitation` : "Monthly precipitation";
              },
            },
          },
        },
        scales: buildSharedChartScales((value) => formatRainfall(value, true)),
      },
    });

    els.weatherStatus.textContent = `${formatRainfall(selectedPoint.value)} in ${selectedPoint.label}`;
  }

  function getWeatherChartSeries(data) {
    const rows = data?.rows || [];

    if (state.selectedPeriod === "annual") {
      const trendRecords = getTimelineRecords();
      return trendRecords.map((record) => ({
        key: record.timelineKey,
        label: record.timelineLabel || record.dateLabel || String(record.year || ""),
        value: getWeatherValueForTrendRecord(rows, record),
      }));
    }

    const selectedMonth = MONTH_OPTIONS.find((month) => month.key === state.selectedPeriod);
    if (!selectedMonth) {
      return [];
    }

    return rows
      .filter((row) => state.selectedYear === "all" || row.year === state.selectedYear)
      .map((row) => {
        const monthPoint = row.months.find((month) => month.key === selectedMonth.monthIndex);
        return {
          key: row.year,
          label: String(row.year),
          value: monthPoint?.value ?? null,
        };
      });
  }

  function getWeatherValueForTrendRecord(rows, record) {
    if (!record || !Number.isFinite(record.year)) {
      return null;
    }

    const row = rows.find((candidate) => candidate.year === record.year);
    if (!row) {
      return null;
    }

    if (record.monthIndex > 0) {
      return row.months.find((month) => month.key === record.monthIndex)?.value ?? null;
    }

    const monthlyValues = row.months
      .map((month) => month.value)
      .filter((value) => Number.isFinite(value));

    if (!monthlyValues.length) {
      return null;
    }

    return aggregateWeatherMetric(monthlyValues, "mean");
  }

  function renderWeatherChartEmpty(message, status = "No data") {
    if (!els.weatherChart || !els.weatherStatus || !els.weatherEmpty) {
      return;
    }

    if (weatherChartInstance) {
      weatherChartInstance.destroy();
      weatherChartInstance = null;
    }
    els.weatherChart.style.visibility = "hidden";
    els.weatherEmpty.textContent = message;
    els.weatherEmpty.classList.remove("is-hidden");
    els.weatherStatus.textContent = status;
  }

  function getHeatmapIntensity(value, min, max) {
    if (!Number.isFinite(value)) {
      return 0;
    }
    if (max === min) {
      return 0.55;
    }
    return 0.2 + ((value - min) / (max - min)) * 0.75;
  }

  function formatRainfall(value, compact = false) {
    if (!Number.isFinite(value)) {
      return "NA";
    }

    const digits = compact ? 0 : 1;
    return `${value.toLocaleString(undefined, { maximumFractionDigits: digits })}${compact ? "" : " mm"}`;
  }

  function refreshParameterScale() {
    if (!els.parameterScale) {
      return;
    }

    if (!state.selectedParameter) {
      els.parameterScale.innerHTML = '<div class="parameter-scale-empty">Select a parameter to see its safety scale.</div>';
      return;
    }

    const parameterKey = getParameterScaleKey(state.selectedParameter);
    const definition = PARAMETER_SCALE_DEFINITIONS[state.selectedUseCase]?.[parameterKey];
    const useCaseLabel = USE_CASES.find((item) => item.key === state.selectedUseCase)?.label || "Selected use case";
    if (!definition) {
      els.parameterScale.innerHTML = `<div class="parameter-scale-empty">${escapeHtml(state.selectedParameter)} has no configured screening scale for ${escapeHtml(useCaseLabel.toLowerCase())}.</div>`;
      return;
    }

    const selectedRecord = getSelectedParameterScaleRecord();
    const currentValue = selectedRecord?.numericValue ?? null;
    const scaleDomain = buildParameterScaleDomain(definition, currentValue);
    const markerPosition = Number.isFinite(currentValue)
      ? clamp(((currentValue - scaleDomain.min) / (scaleDomain.max - scaleDomain.min || 1)) * 100, 0, 100)
      : null;
    const safeStart = getScalePercent(definition.type === "min" ? definition.safeMin : scaleDomain.min, scaleDomain);
    const safeEnd = getScalePercent(
      definition.type === "range"
        ? definition.safeMax
        : definition.type === "max"
          ? definition.safeMax
          : scaleDomain.max,
      scaleDomain
    );
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
        <span class="parameter-scale-band is-safe" style="left:${safeStart}%; width:${Math.max(0, safeEnd - safeStart)}%"></span>
        ${definition.type !== "max" ? `<span class="parameter-scale-band is-unsafe-right" style="left:${safeEnd}%; width:${Math.max(0, 100 - safeEnd)}%"></span>` : ""}
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

  function buildSharedChartScales(yTickFormatter) {
    return {
      x: {
        offset: false,
        grid: { display: false },
        ticks: {
          color: "#5a6968",
          font: { size: 11, weight: "700" },
        },
        border: { display: false },
      },
      y: {
        beginAtZero: false,
        afterFit(scale) {
          scale.width = CHART_Y_AXIS_WIDTH;
        },
        ticks: {
          color: "#5a6968",
          font: { size: 11 },
          callback(value) {
            return yTickFormatter(Number(value));
          },
        },
        grid: {
          color: "rgba(22, 32, 32, 0.09)",
          borderDash: [4, 6],
        },
        border: { display: false },
      },
    };
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
      if (fecal_coliform_mpn_100ml > 500) coreReasons.push(`Fecal coliform ${fecal_coliform_mpn_100ml} MPN/100mL exceeds 500`);
    } else if (total_coliform_mpn_100ml != null && total_coliform_mpn_100ml > 500) {
      coreReasons.push(`Total coliform ${total_coliform_mpn_100ml} MPN/100mL exceeds 500`);
    }

    if (turbidity_ntu != null && turbidity_ntu > 10) extendedReasons.push(`Turbidity ${turbidity_ntu} NTU is high for safe/pleasant bathing`);
    if (e_coli_present === true) extendedReasons.push("E. coli detected");

    return buildScreeningResult("bathing", coreReasons.length === 0, coreReasons.length === 0 && extendedReasons.length === 0, coreReasons, extendedReasons, checked);
  }

  function renderParameterTabs(parameters) {
    els.parameterTabs.innerHTML = "";
    const availableParameters = new Set(getAvailableParameters());

    parameters.forEach((parameter) => {
      const isAvailable = availableParameters.has(parameter);
      const button = document.createElement("button");
      button.type = "button";
      button.className = `tab-button${parameter === state.selectedParameter ? " is-active" : ""}`;
      button.textContent = parameter;
      button.disabled = !isAvailable;
      button.addEventListener("click", () => {
        if (!isAvailable) {
          return;
        }
        state.selectedParameter = parameter;
        syncPeriodSelection();
        refreshStreamVisualization();
        renderParameterTabs(parameters);
        renderPeriodFilter();
        refreshTrendChart();
        refreshParameterScale();
        updateMapLabels();
      });
      els.parameterTabs.appendChild(button);
    });

    const activeRecord = getParameterRecords()[0];
    els.parameterUnit.textContent = activeRecord?.unit || "No unit";
  }

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
    annualButton.className = `period-button${state.selectedPeriod === "annual" ? " is-active" : ""}`;
    annualButton.textContent = "Annual";
    annualButton.disabled = !hasAnnual;
    annualButton.addEventListener("click", () => {
      state.selectedPeriod = "annual";
      const parameters = getAvailableParameters();
      if (!parameters.includes(state.selectedParameter)) {
        state.selectedParameter = parameters[0] ?? null;
      }
      renderParameterTabs(getLocationParameters());
      renderPeriodFilter();
      refreshTrendChart();
      refreshSuitabilitySummary();
      refreshParameterScale();
      refreshMarkerStyles(false);
      updateMapLabels();
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
        const parameters = getAvailableParameters();
        if (!parameters.includes(state.selectedParameter)) {
          state.selectedParameter = parameters[0] ?? null;
        }
        renderParameterTabs(getLocationParameters());
        renderPeriodFilter();
        refreshTrendChart();
        refreshSuitabilitySummary();
        refreshParameterScale();
        refreshMarkerStyles(false);
        updateMapLabels();
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

  function syncYearSelection() {
    const availableYears = getAvailableYears();
    if (state.selectedYear === "all" || availableYears.includes(state.selectedYear)) {
      return;
    }

    state.selectedYear = "all";
  }

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
      renderPeriodFilter();
      refreshTrendChart();
      refreshWeatherChart();
      refreshSuitabilitySummary();
      refreshParameterScale();
      refreshMarkerStyles(false);
      updateMapLabels();
    });
    els.yearFilter.appendChild(allButton);

    availableYears.forEach((year) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `period-button${state.selectedYear === year ? " is-active" : ""}`;
      button.textContent = String(year);
      button.addEventListener("click", () => {
        state.selectedYear = year;
        renderPeriodFilter();
        refreshTrendChart();
        refreshWeatherChart();
        refreshSuitabilitySummary();
        refreshParameterScale();
        refreshMarkerStyles(false);
        updateMapLabels();
      });
      els.yearFilter.appendChild(button);
    });
  }

  function renderTrendChart(records) {
    if (!records.length) {
      renderEmptyChart("No trend data available.");
      return;
    }

    const chartRecords = records.filter((record) => Number.isFinite(record.numericValue));
    if (!chartRecords.length) {
      renderEmptyChart("Values exist, but they are not numeric enough to plot.");
      return;
    }
    const selectedKey = state.selectedTimelineKey ?? chartRecords[chartRecords.length - 1].timelineKey;
    const selectedPoint = chartRecords.find((point) => point.timelineKey === selectedKey) || chartRecords[chartRecords.length - 1];
    const pointRadii = chartRecords.map((point) => (point.timelineKey === selectedPoint.timelineKey ? 7 : 5));
    const pointColors = chartRecords.map((point) => (point.timelineKey === selectedPoint.timelineKey ? "#d97706" : "#0f766e"));

    if (trendChartInstance) {
      trendChartInstance.destroy();
    }

    els.trendEmpty.textContent = "";
    els.trendEmpty.classList.add("is-hidden");
    els.trendChart.style.visibility = "visible";

    const context = els.trendChart.getContext("2d");
    trendChartInstance = new window.Chart(context, {
      type: "line",
      data: {
        labels: chartRecords.map((record) => shortLabel(record.timelineLabel || record.dateLabel)),
        datasets: [
          {
            data: chartRecords.map((record) => record.numericValue),
            borderColor: "#0f766e",
            backgroundColor: "rgba(15, 118, 110, 0.14)",
            borderWidth: 4,
            fill: true,
            tension: 0.32,
            pointRadius: pointRadii,
            pointHoverRadius: pointRadii.map((radius) => radius + 2),
            pointHitRadius: 18,
            pointBackgroundColor: pointColors,
            pointBorderColor: "#ffffff",
            pointBorderWidth: 3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: {
          mode: "nearest",
          intersect: true,
        },
        onClick(_event, elements) {
          const pointIndex = elements[0]?.index;
          if (pointIndex == null) {
            return;
          }

          state.selectedTimelineKey = chartRecords[pointIndex].timelineKey;
          renderTrendChart(records);
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(22, 32, 32, 0.92)",
            titleColor: "#f7fffe",
            bodyColor: "#f7fffe",
            displayColors: false,
            callbacks: {
              title(items) {
                const index = items[0]?.dataIndex ?? 0;
                return chartRecords[index].timelineLabel || chartRecords[index].dateLabel;
              },
              label(item) {
                return formatValue(chartRecords[item.dataIndex]);
              },
            },
          },
        },
        scales: buildSharedChartScales((value) => formatRainfall(value, true)),
      },
    });

    els.valueSummary.textContent = `${formatValue(selectedPoint)} on ${selectedPoint.timelineLabel || selectedPoint.dateLabel}`;
    refreshParameterScale();
  }

  function renderEmptyChart(message) {
    if (trendChartInstance) {
      trendChartInstance.destroy();
      trendChartInstance = null;
    }
    els.trendChart.style.visibility = "hidden";
    els.trendEmpty.textContent = message;
    els.trendEmpty.classList.remove("is-hidden");
    els.valueSummary.textContent = "No numeric trend";
    refreshParameterScale();
  }

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

  function updateMapLabels() {
    const selectedParameter = state.selectedParameter;

    markers.forEach((marker, locationName) => {
      const periodRecords = getRecordsForLocationPeriod(locationName, selectedParameter);
      const latestRecord = periodRecords[periodRecords.length - 1];
      const labelName = getMapLabelName(locationName);

      if (!latestRecord) {
        marker.unbindTooltip();
        marker.bindTooltip(`<span class="point-value-name">${escapeHtml(labelName)}</span>`, {
          permanent: true,
          direction: "top",
          offset: [0, -14],
          className: "point-value-tooltip",
          opacity: 1,
        });
        return;
      }

      const labelValue = Number.isFinite(latestRecord.numericValue)
        ? formatCompactNumber(latestRecord.numericValue)
        : latestRecord.rawValue || "NA";

      marker.unbindTooltip();
      marker.bindTooltip([
        `<span class="point-value-name">${escapeHtml(labelName)}</span>`,
        `<span class="point-value-text">${escapeHtml(labelValue)}</span>`,
      ].join(""), {
        permanent: true,
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

  function getParameterFamily(parameter) {
    const clean = fixTextValue(parameter);
    const variant = getParameterVariant(clean);
    return variant ? clean.replace(/\s*\([^)]*\)\s*$/, "").trim() : clean;
  }

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

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  selectLocation(defaultLocation?.name || "", { focusMap: false, openPopup: false });
})();
