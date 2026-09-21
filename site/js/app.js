/* Bootstrap: load the audited web data, render the story around it, then wire
 * the map, the ranking and the sidebar to one shared selection state.
 */

import { indexDistricts, loadAll } from './data.js';
import * as store from './state.js';
import * as mapModule from './map.js';
import { focusRanking, initRanking, syncRanking } from './ranking.js';
import { buildDensityLegend, initUI, renderContext } from './ui.js';
import { initStory } from './story.js';
import { initTemporal, prepareTemporal } from './temporal.js';
import { initDestinations, prepareDestinations } from './destinations.js';
import { el, replace } from './dom.js';
import { focusComposition, initComposition, updateCompositionState } from './composition.js';
import { initScatter, updateScatterState } from './scatter.js';
import { initParallel, updateComparisonUI, updateParallelState } from './parallel.js';
import {
  tooltipComposition, tooltipParallel, tooltipScatter,
} from './chart-utils.js';

/* Automated QA needs to wait for a genuinely rendered map and to drive the
 * hostile-text render probe. Neither belongs in the ordinary product, so the
 * hook exists only when the page is opened with ?qa=1. In normal use
 * window.__prototype is undefined and the MapLibre instance is not published. */
const QA = new URLSearchParams(window.location.search).get('qa') === '1';

if (QA) {
  window.__prototype = {
    mapLoaded: false,
    map: null,
    state: store,
    /* Render arbitrary text the way every OSM-sourced label is rendered, so a
     * test can prove a hostile name becomes literal text and never markup. */
    renderProbe(text) {
      const node = el('span', { class: 'tip-name', text });
      replace(tip, node);
      return { html: tip.innerHTML, text: tip.textContent };
    },
  };
}

/* Every section that carries a figure. They stay hidden until the data is in
 * and the story has accepted it, so none of them can show a placeholder as a
 * result, and all of them are hidden again if anything fails. */
const STORY_SECTIONS = ['hero', 'current-access', 'workspace', 'destination-access',
  'metric-bridge', 'temporal-story', 'district-analysis'];

function reveal(visible) {
  for (const id of STORY_SECTIONS) document.getElementById(id).hidden = !visible;
}

function fail(message) {
  document.getElementById('load-error-detail').textContent = message;
  document.getElementById('load-error').hidden = false;
  reveal(false);
}

/* ── tooltip, shared by the map and the ranking ───────────────────────── */
const tip = document.getElementById('tooltip');

function showTip(nodes, event) {
  replace(tip, nodes);
  tip.classList.add('is-on');
  tip.setAttribute('aria-hidden', 'false');
  moveTip(event);
}

function moveTip(event) {
  if (!tip.classList.contains('is-on')) return;
  const pad = 14;
  const box = tip.getBoundingClientRect();
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  if (x + box.width > window.innerWidth - 8) x = event.clientX - box.width - pad;
  if (y + box.height > window.innerHeight - 8) y = event.clientY - box.height - pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}

function hideTip() {
  tip.classList.remove('is-on');
  tip.setAttribute('aria-hidden', 'true');
}

/* ── announce selection changes to assistive technology ───────────────── */
function announce(state, index) {
  const live = document.getElementById('live');

  if (state.selectedStation) {
    const where = state.selectedStation.district_name
      ? `, ${state.selectedStation.district_name}` : '';
    live.textContent = `${state.selectedStation.name} metro station selected${where}.`;
    return;
  }

  if (!state.selectedDistrict) {
    live.textContent = 'Selection cleared. Showing the city overview.';
    return;
  }

  const p = index.byName.get(state.selectedDistrict).properties;
  live.textContent = `${p.label} selected. Metro access ${p.metro_access_pct.toFixed(1)} percent, `
    + `bus-only ${p.bus_only_pct.toFixed(1)} percent, `
    + `underserved ${p.underserved_pct.toFixed(1)} percent.`;
}

/* A comparison change is a real state change a screen-reader user has to hear;
 * without this, pressing "Add Chilanzar" would be silent. */
function announceComparison(state, index) {
  const live = document.getElementById('live');
  const names = state.comparisonDistricts
    .map((d) => index.byName.get(d)?.properties.label ?? d);
  live.textContent = names.length === 0
    ? 'Comparison cleared.'
    : `Comparing ${names.length} district${names.length === 1 ? '' : 's'}: ${names.join(', ')}.`;
}

/* ── go ───────────────────────────────────────────────────────────────── */
(async function start() {
  let data;
  try {
    data = await loadAll();
  } catch (error) {
    fail(error && error.message ? error.message : String(error));
    return;
  }

  if (typeof maplibregl === 'undefined' || typeof d3 === 'undefined') {
    fail('The mapping and charting libraries did not load from site/vendor.');
    return;
  }

  // Every chapter's inputs are checked before anything is shown, and before the
  // story writes a single figure, so a failure in any of them leaves nothing
  // rendered at all. The temporal and destination models are only prepared
  // here; they are drawn after the reveal, because their charts and maps
  // measure their containers and a hidden container has no size.
  let timeline;
  let destinations;
  try {
    timeline = prepareTemporal(data);
    destinations = prepareDestinations(data);
    initStory(data);
  } catch (error) {
    fail(error && error.message ? error.message : String(error));
    return;
  }

  // Revealed before the map is created, which needs a sized container.
  reveal(true);
  initDestinations(destinations);
  initTemporal(timeline);
  const index = indexDistricts(data.districts);

  initRanking(index.ranked, {
    onHover: (event, feature) => showTip(mapModule.tooltipRowsForDistrict(feature.properties), event),
    onMove: moveTip,
    onLeave: hideTip,
    onSelect: (feature) => {
      if (store.get().selectedDistrict === feature.properties.district_name) {
        mapModule.flyToDistrict(feature);
      }
    },
  });

  /* The three Week 6 views. Each writes hover and selection through the same
   * store the map and the ranking use, so a district hovered in any one of the
   * five is the same fact in all five rather than five copies. */
  initComposition(index.ranked, {
    onHover: (event, d) => showTip(tooltipComposition(d.properties), event),
    onMove: moveTip,
    onLeave: hideTip,
  });
  initScatter(index.ranked, {
    onHover: (event, d) => showTip(tooltipScatter(d.properties), event),
    onMove: moveTip,
    onLeave: hideTip,
  });
  initParallel(index.ranked, {
    onHover: (event, d) => showTip(tooltipParallel(d.properties), event),
    onMove: moveTip,
    onLeave: hideTip,
  });
  initUI(data, index, {
    fitCity: () => mapModule.fitCity(),
    focusRanking,
    focusComposition,
    flyToDistrict: (feature) => mapModule.flyToDistrict(feature),
    flyToStation: (station) => mapModule.flyToStation(station),
  });

  mapModule.initMap(data, () => {
    buildDensityLegend(mapModule.densityRampStops());
    mapModule.syncMap(store.get());
  }, QA);

  // Every view re-reads the one state; none of them keeps its own copy.
  let lastSelected = null;
  store.subscribe((state, changed) => {
    if (changed.includes('layers')) mapModule.applyLayerVisibility(state);
    mapModule.syncMap(state);
    // All five views re-read the one state. These are state-only updates: no
    // chart geometry is rebuilt for a hover or a selection.
    syncRanking(state);
    updateCompositionState(state);
    updateScatterState(state);
    updateParallelState(state);

    // Either mode changing re-renders the one context slot and announces once.
    if (changed.includes('selectedDistrict') || changed.includes('selectedStation')) {
      renderContext(state);
      announce(state, index);
      if (state.selectedDistrict !== lastSelected) {
        lastSelected = state.selectedDistrict;
        if (!state.selectedDistrict) mapModule.popupClose();
      }
    }
    // The comparison control and the sidebar action read the same set, so a
    // change from either has to refresh both.
    if (changed.includes('comparisonDistricts')) {
      updateComparisonUI(state);
      renderContext(state);
      announceComparison(state, index);
    }
  });

  document.getElementById('zoom-in').addEventListener('click', () => mapModule.zoomBy(1));
  document.getElementById('zoom-out').addEventListener('click', () => mapModule.zoomBy(-1));
  document.getElementById('zoom-reset').addEventListener('click', () => {
    store.clearSelection();
    mapModule.fitCity();
  });

  window.addEventListener('blur', hideTip);
}());
