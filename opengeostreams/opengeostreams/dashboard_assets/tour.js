/* Quick tour of the dashboard and the "hover a parameter" tip.
 *
 * The tour opens once on a visitor's first visit (remembered in localStorage) and
 * again from the ? button in the top bar. Each step highlights one control and
 * says what it does. The parameter tip appears once, the first time parameters are
 * listed, and goes away when the user hovers a parameter, closes it, or after a while.
 */
(function () {
  "use strict";

  const TOUR_KEY = "ogs-tour-v1";
  const TIP_KEY = "ogs-parameter-tip-v1";
  const TIP_SECONDS = 15;

  const storage = {
    get(key) { try { return window.localStorage.getItem(key); } catch (_error) { return null; } },
    set(key, value) { try { window.localStorage.setItem(key, value); } catch (_error) { /* private mode */ } },
  };

  const STATION_PIN = '<svg class="tour-pin" viewBox="0 0 24 34" aria-hidden="true"><path d="M12 1.2C6 1.2 1.2 6 1.2 12c0 7.6 9 18.4 10.1 19.7a.9.9 0 0 0 1.4 0C13.8 30.4 22.8 19.6 22.8 12 22.8 6 18 1.2 12 1.2z"/><circle cx="12" cy="12" r="4.2"/></svg>';
  const STP_PIN = '<svg class="tour-pin" viewBox="0 0 24 34" aria-hidden="true"><path d="M12 1.6Q13 1.6 13.8 2.4L21.6 10.2Q23 11.6 21.6 13L13.4 30.6Q12 32.6 10.6 30.6L2.4 13Q1 11.6 2.4 10.2L10.2 2.4Q11 1.6 12 1.6z"/><circle cx="12" cy="11.6" r="3.6"/></svg>';

  // target: a selector, or a function returning an element; no target = centred card.
  const STEPS = [
    {
      title: "Welcome to OpenGeoStreams",
      text: "This quick tour shows what each part of the dashboard does. It takes about a minute. " +
        "You can skip it now and replay it any time from the <b>?</b> button at the top.",
    },
    {
      target: "#add-data-toggle",
      title: "Add your data",
      text: "Import one or more water-quality files (CSV, Excel, TSV or JSON). Each file becomes a data layer " +
        "in this list: click a layer to make it active, or use its download button to save it as a CSV.",
    },
    {
      target: () => visible(document.querySelector("#parameter-tabs .tab-button")) ? "#parameter-tabs" : "#parameter-search",
      title: "Choose a parameter",
      text: "Pick a parameter such as BOD, DO or pH to show it on the map and in the charts. " +
        "<b>Tip: hover over any parameter to see what it means.</b>",
    },
    {
      target: "#station-search",
      title: "Find a station",
      text: "Search for a station, or pick one from the list, to zoom to it and open its analysis.",
    },
    {
      target: () => document.querySelector(".leaflet-marker-icon.station-pin"),
      title: "Stations on the map",
      text: `<span class="tour-pins">${STATION_PIN} Sampling station</span>` +
        `<span class="tour-pins">${STP_PIN} Sewage treatment plant (STP)</span>` +
        "Pin colours show <b>Pass</b>, <b>Caution</b> or <b>Fail</b> for the selected use. Click a pin to see its latest values.",
    },
    {
      target: ".suitability-panel",
      title: "Use-case screening",
      text: "Choose a use: agriculture, aquatic life or bathing. " +
        "Each station is checked against that use's limits, and the pins change colour to match.",
    },
    {
      target: "#period-panel",
      title: "Time filters",
      text: "Show the annual picture or a single month, for all years or just one.",
    },
    {
      target: "#legend-card",
      title: "Layers",
      text: "Turn the station pins and the coloured river (the interpolated values between stations) on or off. " +
        "<b>Zoom to surface</b> jumps to the coloured stretch of river.",
    },
    {
      target: ".map-controls",
      title: "Map controls",
      text: "Zoom in and out, fit the map to all stations, or switch the background map: OpenStreetMap, minimal or satellite.",
    },
    {
      target: "#toggle-analysis",
      title: "Analysis",
      text: "Charts for the selected station and parameter: <b>Trend</b> (values over time with rainfall), " +
        "<b>Distribution</b> (spread of values by year or month) and <b>Stream</b> (all stations along the river, year by year).",
    },
    {
      target: "#open-watershed",
      title: "Watershed analysis",
      text: "Click a stream, drag a box or draw an area to see which land drains into it, " +
        "the likely pollution sources and the best places to take samples.",
    },
    {
      target: "#theme-toggle",
      title: "Theme and help",
      text: "Switch between the dark and light theme. The <b>?</b> button replays this tour, and the <b>i</b> button explains the methods.",
    },
  ];

  let index = 0;
  let nodes = null;
  let opener = null;

  function visible(element) {
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) return false;
    if (rect.bottom < 0 || rect.right < 0 || rect.top > window.innerHeight || rect.left > window.innerWidth) return false;
    return window.getComputedStyle(element).visibility !== "hidden";
  }

  function resolveTarget(step) {
    let target = typeof step.target === "function" ? step.target() : step.target;
    if (typeof target === "string") target = document.querySelector(target);
    if (target && !visible(target)) {
      target.scrollIntoView?.({block: "nearest", inline: "nearest"});
    }
    return visible(target) ? target : null;
  }

  function build() {
    const backdrop = document.createElement("div");
    backdrop.className = "tour-backdrop";
    const spotlight = document.createElement("div");
    spotlight.className = "tour-spotlight";
    const card = document.createElement("div");
    card.className = "tour-card";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-modal", "true");
    card.setAttribute("aria-labelledby", "tour-title");
    card.setAttribute("aria-describedby", "tour-text");
    card.innerHTML = `
      <p class="tour-count" id="tour-count"></p>
      <h2 class="tour-title" id="tour-title"></h2>
      <p class="tour-text" id="tour-text"></p>
      <div class="tour-actions">
        <button type="button" class="tour-skip">Skip tour</button>
        <span class="tour-nav">
          <button type="button" class="btn btn-ghost btn-sm tour-back">Back</button>
          <button type="button" class="btn btn-primary btn-sm tour-next">Next</button>
        </span>
      </div>`;
    document.body.append(backdrop, spotlight, card);
    card.querySelector(".tour-skip").addEventListener("click", close);
    card.querySelector(".tour-back").addEventListener("click", () => go(index - 1));
    card.querySelector(".tour-next").addEventListener("click", () => (index === STEPS.length - 1 ? close() : go(index + 1)));
    return {backdrop, spotlight, card};
  }

  function place() {
    if (!nodes) return;
    const {backdrop, spotlight, card} = nodes;
    const target = resolveTarget(STEPS[index]);
    const margin = 12;
    const viewW = window.innerWidth;
    const viewH = window.innerHeight;
    const cardW = card.offsetWidth;
    const cardH = card.offsetHeight;
    backdrop.classList.toggle("is-dimmed", !target);
    spotlight.hidden = !target;
    if (!target) {
      card.style.left = `${Math.max(margin, (viewW - cardW) / 2)}px`;
      card.style.top = `${Math.max(margin, (viewH - cardH) / 2)}px`;
      return;
    }
    const rect = target.getBoundingClientRect();
    const pad = 6;
    Object.assign(spotlight.style, {
      left: `${rect.left - pad}px`, top: `${rect.top - pad}px`,
      width: `${rect.width + pad * 2}px`, height: `${rect.height + pad * 2}px`,
    });
    // Below, above, right, then left of the highlighted control; clamped to the window.
    const options = [
      {left: rect.left + rect.width / 2 - cardW / 2, top: rect.bottom + pad + margin, fits: rect.bottom + pad + margin + cardH <= viewH},
      {left: rect.left + rect.width / 2 - cardW / 2, top: rect.top - pad - margin - cardH, fits: rect.top - pad - margin - cardH >= 0},
      {left: rect.right + pad + margin, top: rect.top, fits: rect.right + pad + margin + cardW <= viewW},
      {left: rect.left - pad - margin - cardW, top: rect.top, fits: rect.left - pad - margin - cardW >= 0},
    ];
    const choice = options.find(option => option.fits) || {left: (viewW - cardW) / 2, top: viewH - cardH - margin};
    card.style.left = `${Math.min(Math.max(margin, choice.left), viewW - cardW - margin)}px`;
    card.style.top = `${Math.min(Math.max(margin, choice.top), viewH - cardH - margin)}px`;
  }

  function go(next) {
    if (!nodes || next < 0 || next >= STEPS.length) return;
    index = next;
    const step = STEPS[index];
    const {card} = nodes;
    card.querySelector("#tour-count").textContent = index ? `Step ${index} of ${STEPS.length - 1}` : "Quick tour";
    card.querySelector("#tour-title").textContent = step.title;
    card.querySelector("#tour-text").innerHTML = step.text;
    card.querySelector(".tour-back").hidden = index === 0;
    const nextButton = card.querySelector(".tour-next");
    nextButton.textContent = index === 0 ? "Start" : index === STEPS.length - 1 ? "Done" : "Next";
    place();
    // The card's height depends on its text, so place again once it has laid out.
    window.requestAnimationFrame(place);
    nextButton.focus({preventScroll: true});
  }

  function onKey(event) {
    if (!nodes) return;
    if (event.key === "Escape") { event.preventDefault(); close(); }
    else if (event.key === "ArrowRight") { event.preventDefault(); go(index + 1); }
    else if (event.key === "ArrowLeft") { event.preventDefault(); go(index - 1); }
    else if (event.key === "Tab") {
      // Keep keyboard focus inside the tour card.
      const buttons = Array.from(nodes.card.querySelectorAll("button")).filter(button => !button.hidden);
      const position = buttons.indexOf(document.activeElement);
      event.preventDefault();
      buttons[(position + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length]?.focus();
    }
  }

  function open() {
    if (nodes) return;
    opener = document.activeElement;
    hideTip();
    nodes = build();
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", place);
    document.addEventListener("scroll", place, true);
    go(0);
  }

  function close() {
    if (!nodes) return;
    storage.set(TOUR_KEY, "done");
    Object.values(nodes).forEach(node => node.remove());
    nodes = null;
    document.removeEventListener("keydown", onKey, true);
    window.removeEventListener("resize", place);
    document.removeEventListener("scroll", place, true);
    opener?.focus?.({preventScroll: true});
    window.setTimeout(maybeShowTip, 400);
  }

  // ---------- "hover a parameter" tip ----------
  let tip = null;
  let tipTimer = 0;

  function hideTip() {
    window.clearTimeout(tipTimer);
    if (!tip) return;
    tip.remove();
    tip = null;
    storage.set(TIP_KEY, "done");
  }

  // Automated browsers (tests) skip the first-visit tour and tip unless ?tour is in the URL.
  const automated = navigator.webdriver && !new URLSearchParams(window.location.search).has("tour");

  function maybeShowTip() {
    const tabs = document.getElementById("parameter-tabs");
    if (tip || nodes || automated || storage.get(TIP_KEY) || !tabs || !tabs.querySelector(".tab-button")) return;
    tip = document.createElement("div");
    tip.className = "parameter-tip";
    tip.setAttribute("role", "status");
    tip.innerHTML = '<span><b>Tip:</b> hover over a parameter to see what it means.</span>' +
      '<button type="button" class="parameter-tip-close" aria-label="Dismiss tip">&times;</button>';
    tabs.parentNode.insertBefore(tip, tabs);
    tip.querySelector("button").addEventListener("click", hideTip);
    tipTimer = window.setTimeout(hideTip, TIP_SECONDS * 1000);
  }

  function init() {
    document.getElementById("tour-open")?.addEventListener("click", open);
    const tabs = document.getElementById("parameter-tabs");
    if (tabs) {
      new MutationObserver(maybeShowTip).observe(tabs, {childList: true});
      // Hovering a parameter shows its meaning, so the tip has done its job.
      tabs.addEventListener("mouseover", event => { if (tip && event.target.closest(".tab-button")) hideTip(); });
    }
    // Let the map and panels lay out before the first-visit tour measures them.
    if (!automated && !storage.get(TOUR_KEY)) window.setTimeout(open, 900);
    else maybeShowTip();
  }

  window.OGSTour = {open, close};
  if (document.readyState === "complete") init();
  else window.addEventListener("load", init);
})();
