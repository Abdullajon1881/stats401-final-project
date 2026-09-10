/* Sidebar panels, search, layer menu, method dialog, tooltip.
 *
 * All text that originates outside this repository - every OSM name - reaches
 * the document through textContent via the helpers in dom.js. Nothing here
 * builds markup from a string.
 */

import { cell, el, replace, safeName } from './dom.js';
import { fmt } from './data.js';
import * as store from './state.js';

/* A district reporting no metro access at all earns a caution when its nearest
 * cell missed the budget by this little: at that range the result turns on
 * mapping and walking assumptions rather than on geography. The rule and the
 * wording are derived from each district's own audited numbers, so no district
 * is singled out in code. */
const TIGHT_MARGIN_M = 100;

let data = null;
let index = null;
let hooks = {};

export function initUI(loaded, districtIndex, callbacks) {
  data = loaded;
  index = districtIndex;
  hooks = callbacks || {};

  renderContext(store.get());
  buildDensityLegend();
  wireNav();
  wireLayerMenu();
  wireSearch();
  wireMethodDialog();
  wireClear();
}

/* ── context panel: city overview, or the selected district ───────────── */
export function renderContext(state) {
  const body = document.getElementById('context-body');
  const title = document.getElementById('context-h');
  const clear = document.getElementById('clear-selection');

  // One slot, three modes: city, district, station. The three are mutually
  // exclusive in the state, so this reads as a straight switch.
  if (state.selectedStation) {
    title.textContent = 'Metro station';
    clear.hidden = false;
    replace(body, stationDetail(state.selectedStation));
    return;
  }

  if (state.selectedDistrict) {
    const feature = index.byName.get(state.selectedDistrict);
    if (feature) {
      title.textContent = 'District';
      clear.hidden = false;
      replace(body, districtDetail(feature.properties));
      return;
    }
  }

  title.textContent = 'Tashkent at a glance';
  clear.hidden = true;
  replace(body, cityOverview());
}

/* Only what the station data actually carries. No line is shown: the audited
 * station layer has no reliable line assignment, and guessing one would put an
 * invented fact in the interface. */
function stationDetail(station) {
  const nodes = [
    el('div', { class: 'dd-name', text: station.name }),
    el('div', { class: 'dd-sub', text: 'Metro station' }),
  ];

  const rows = [cell('Type', 'Metro station')];
  if (station.district_name) rows.push(cell('District', station.district_name));
  nodes.push(el('div', { class: 'dd-grid' }, rows));

  // If the station sits in one of the twelve analysis districts, offer that
  // district's audited figures rather than stopping at a name.
  const feature = station.district_name ? index.byName.get(station.district_name) : null;
  if (feature) {
    const p = feature.properties;
    nodes.push(el('button', {
      type: 'button', class: 'linkrow',
      onclick: () => {
        store.selectDistrict(p.district_name);
        if (hooks.flyToDistrict) hooks.flyToDistrict(feature);
      },
    }, `View ${p.label} district — ${fmt.pct(p.metro_access_pct)} metro access`));
  }

  nodes.push(el('p', {
    class: 'dd-hint',
    text: 'Stations are shown for orientation. The reported shares are measured '
      + 'from metro entrances along the pedestrian network, not from station points.',
  }));
  return nodes;
}

function cityOverview() {
  const c = data.city;
  const total = c.metro_access_pct + c.bus_only_pct + c.underserved_pct;
  const pctOf = (v) => `${(v / total) * 100}%`;

  const stat = (cls, label, pct, people) => el('div', { class: 'stat' }, [
    el('div', { class: `stat-k ${cls}` }, [el('i', {}), label]),
    el('div', { class: 'stat-v', text: fmt.pct(pct) }),
    el('div', { class: 'stat-n', text: fmt.people(people) }),
  ]);

  return [
    el('div', { class: 'stats' }, [
      stat('k-metro', 'Metro', c.metro_access_pct, c.metro_access_population),
      stat('k-bus', 'Bus-only', c.bus_only_pct, c.bus_only_population),
      stat('k-under', 'Underserved', c.underserved_pct, c.underserved_population),
    ]),
    el('div', {
      class: 'compo', role: 'img',
      'aria-label': `Access composition: metro ${fmt.pct(c.metro_access_pct)}, `
        + `bus-only ${fmt.pct(c.bus_only_pct)}, underserved ${fmt.pct(c.underserved_pct)}`,
    }, [
      el('i', { class: 'c-metro', style: { width: pctOf(c.metro_access_pct) } }),
      el('i', { class: 'c-bus', style: { width: pctOf(c.bus_only_pct) } }),
      el('i', { class: 'c-under', style: { width: pctOf(c.underserved_pct) } }),
    ]),
    el('p', {
      class: 'denom',
      text: `${fmt.people(c.analysis_population)} analysed residents · ${c.reference_period}`
        + ` · ${c.walking_speed_kmh} km/h · ${c.walking_time_minutes} min`,
    }),
  ];
}

function districtDetail(p) {
  const nodes = [
    el('div', { class: 'dd-name', text: p.label }),
    el('div', {
      class: 'dd-sub',
      text: `${fmt.people(p.official_population)} residents · ${fmt.km2(p.area_km2)}`
        + ` · ${fmt.density(p.population_density_per_km2)}`,
    }),
    el('div', { class: 'dd-grid' }, [
      cell('Metro access', `${fmt.pct(p.metro_access_pct)} · ${fmt.people(p.metro_access_population)}`, 'is-metro'),
      cell('Bus-only', `${fmt.pct(p.bus_only_pct)} · ${fmt.people(p.bus_only_population)}`, 'is-bus'),
      cell('Underserved', `${fmt.pct(p.underserved_pct)} · ${fmt.people(p.underserved_population)}`, 'is-under'),
      cell('Metro + bus', fmt.pct(p.combined_walk_access_pct)),
      cell('Metro stations', fmt.int(p.metro_stations_in_district)),
      cell('Metro access points', fmt.int(p.metro_access_points_in_district)),
      cell('Bus stops', fmt.int(p.bus_stops_in_district)),
      cell('Bazaars', fmt.int(p.bazaars_in_district)),
    ]),
  ];
  const note = zeroAccessNote(p);
  if (note) nodes.push(el('p', { class: 'dd-note', text: note }));
  nodes.push(comparisonAction(p));
  return nodes;
}

/* One comparison action, in the district panel the reader is already looking
 * at. It drives the same store set the parallel chart's control does - there
 * is one comparison set, not one per panel. */
function comparisonAction(p) {
  const pinned = store.isCompared(p.district_name);
  const full = store.comparisonIsFull();
  const button = el('button', {
    type: 'button',
    class: 'linkbtn dd-compare',
    disabled: !pinned && full,
    onclick: () => store.toggleComparison(p.district_name),
  }, pinned ? 'Remove from comparison' : 'Add to comparison');
  const hint = !pinned && full
    ? el('span', {
      class: 'dd-compare-hint',
      text: `Maximum ${store.MAX_COMPARISON}`,
    })
    : null;
  return el('div', { class: 'dd-compare-row' }, hint ? [button, hint] : [button]);
}

function zeroAccessNote(p) {
  if (p.metro_access_pct > 0) return null;
  const budget = data.city.distance_budget_m;
  const base = `No analysed population cell falls within the ${fmt.people(budget)} m metro`
    + ` budget. The nearest is ${fmt.metres(p.min_cell_metro_distance_m)}`;
  if (p.min_cell_metro_margin_m <= TIGHT_MARGIN_M) {
    return `${base} — about ${fmt.people(p.min_cell_metro_margin_m)} m outside the threshold,`
      + ' so this result is sensitive to mapping and walking assumptions.';
  }
  return `${base}, ${fmt.people(p.min_cell_metro_margin_m)} m beyond the threshold.`;
}

/* ── density legend ───────────────────────────────────────────────────── */
export function buildDensityLegend(stops) {
  if (!stops) return;
  const ramp = document.getElementById('ramp');
  const scale = d3.scaleLinear().domain([0, 1]).range([0, 1]);
  const swatches = d3.range(20).map((i) => {
    const t = Math.sqrt((i + 0.5) / 20); // matches the map's sqrt ramp
    const colour = d3.interpolateRgbBasis(stops.ramp)(scale(t));
    return el('span', { style: { background: colour } });
  });
  replace(ramp, swatches);
  document.getElementById('ramp-hi').textContent = `${fmt.people(stops.max)}+`;
}

/* Someone who asked their system for reduced motion gets the same destination
 * without being scrolled across the page. */
function motion() {
  const reduced = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  return reduced ? 'auto' : 'smooth';
}

/* ── navigation ───────────────────────────────────────────────────────── */
function wireNav() {
  for (const button of document.querySelectorAll('.navbtn')) {
    button.addEventListener('click', () => {
      const view = button.dataset.view;
      if (view === 'method') { openMethod(); return; }
      for (const other of document.querySelectorAll('.navbtn')) {
        const current = other === button;
        other.classList.toggle('is-current', current);
        if (current) other.setAttribute('aria-current', 'page');
        else other.removeAttribute('aria-current');
      }
      store.set({ view });
      /* Navigation moves the reader; it does not throw away what they chose.
       * Overview used to call clearSelection(), so switching sections silently
       * deselected the district the reader was studying - a side effect of
       * navigating, not something they asked for. Selection is released only
       * through Clear, Escape, or re-clicking the same district. */
      if (view === 'overview') {
        document.getElementById('workspace')
          .scrollIntoView({ block: 'start', behavior: motion() });
      } else if (view === 'districts') {
        const deck = document.getElementById('district-analysis');
        deck.scrollIntoView({ block: 'start', behavior: motion() });
        // Focus the section itself rather than a chart control, so the reader
        // lands on the heading and can Tab into whichever chart they want.
        deck.focus({ preventScroll: true });
      }
    });
  }
}

function wireClear() {
  document.getElementById('clear-selection')
    .addEventListener('click', () => store.clearSelection());
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    // The native dialog handles its own Escape and restores focus on close.
    if (document.getElementById('method-dialog').open) return;
    const results = document.getElementById('search-results');
    if (!results.hidden) { hideResults(); return; }
    if (store.get().selectedDistrict || store.get().selectedStation) store.clearSelection();
  });
}

/* ── layer menu ───────────────────────────────────────────────────────── */
function wireLayerMenu() {
  const toggle = document.getElementById('layers-toggle');
  const menu = document.getElementById('layers-menu');

  toggle.addEventListener('click', () => {
    const open = menu.hidden;
    menu.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('click', (event) => {
    if (!menu.hidden && !menu.contains(event.target) && !toggle.contains(event.target)) {
      menu.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
    }
  });
  for (const input of menu.querySelectorAll('input[data-layer]')) {
    input.checked = store.get().layers[input.dataset.layer];
    input.addEventListener('change', () => {
      store.setLayer(input.dataset.layer, input.checked);
      const legend = document.getElementById('legend-density');
      if (input.dataset.layer === 'population') legend.style.opacity = input.checked ? '1' : '0.35';
    });
  }
}

/* ── search ───────────────────────────────────────────────────────────── */
let searchItems = [];
let activeIndex = -1;

function buildSearchIndex() {
  const items = [];
  for (const feature of index.ranked) {
    items.push({
      kind: 'district',
      label: feature.properties.label,
      key: feature.properties.district_name,
      feature,
    });
  }
  for (const feature of data.stations.features) {
    const p = feature.properties;
    /* The visible label is the CURRENT station name. Several name_en values
     * carry a historical Soviet-era alias in parentheses - "Milliy Bog
     * (Komsomolskaya)" - and showing that as the primary label puts a
     * superseded name in front of the reader. The English form is still
     * indexed below so either name finds the station. */
    const label = safeName(p.name, safeName(p.name_en, null));
    if (!label) continue;
    const alias = safeName(p.name_en, null);
    items.push({
      kind: 'station',
      label,
      // Matched against, never displayed: a search for "Komsomolskaya" or
      // "Chilanzar" still finds the station now labelled by its current name.
      alias: alias && alias !== label ? alias : null,
      key: `station:${p.osm_id}`,
      district_name: safeName(p.district_name, null),
      lon: feature.geometry.coordinates[0],
      lat: feature.geometry.coordinates[1],
    });
  }
  items.sort((a, b) => a.kind.localeCompare(b.kind) || a.label.localeCompare(b.label));
  return items;
}

/* Move the visual and the semantic active option together. DOM focus stays on
 * the combobox input during Arrow navigation, as the pattern requires, so the
 * input has to name the active option through aria-activedescendant and each
 * option has to carry its own aria-selected. Setting one without the other
 * would be an ARIA attribute that is never synchronised. */
function setActiveOption(nextIndex) {
  const results = document.getElementById('search-results');
  const input = document.getElementById('search-input');
  const options = [...results.querySelectorAll('.sr-item')];

  activeIndex = options.length ? nextIndex : -1;

  options.forEach((option, i) => {
    const isActive = i === activeIndex;
    option.classList.toggle('is-active', isActive);
    option.setAttribute('aria-selected', String(isActive));
  });

  if (activeIndex >= 0 && options[activeIndex]) {
    input.setAttribute('aria-activedescendant', options[activeIndex].id);
    options[activeIndex].scrollIntoView({ block: 'nearest' });
  } else {
    input.removeAttribute('aria-activedescendant');
  }
}

function clearActiveOption() {
  activeIndex = -1;
  document.getElementById('search-input').removeAttribute('aria-activedescendant');
}

function wireSearch() {
  searchItems = buildSearchIndex();
  const input = document.getElementById('search-input');
  const clear = document.getElementById('search-clear');

  input.addEventListener('input', () => {
    const query = input.value.trim();
    clear.hidden = query.length === 0;
    store.set({ searchQuery: query });
    showResults(query);
  });

  input.addEventListener('keydown', (event) => {
    const results = document.getElementById('search-results');
    const options = [...results.querySelectorAll('.sr-item')];
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!options.length) return;
      event.preventDefault();
      let next = activeIndex + (event.key === 'ArrowDown' ? 1 : -1);
      if (next < 0) next = options.length - 1;
      if (next >= options.length) next = 0;
      setActiveOption(next);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const target = options[activeIndex >= 0 ? activeIndex : 0];
      if (target) target.click();
    }
  });

  clear.addEventListener('click', () => {
    input.value = '';
    clear.hidden = true;
    store.set({ searchQuery: '' });
    hideResults();
    input.focus();
  });

  document.addEventListener('click', (event) => {
    const wrap = document.querySelector('.search');
    if (!wrap.contains(event.target)) hideResults();
  });

  /* The options are deliberately not tab stops, so Tab now carries focus out of
   * the search in one press. Close the popup when it does: an open listbox with
   * focus somewhere else on the page belongs to nobody. focusout fires before
   * focus lands, hence the deferred read of activeElement. */
  document.querySelector('.search').addEventListener('focusout', () => {
    setTimeout(() => {
      const wrap = document.querySelector('.search');
      if (!wrap.contains(document.activeElement)) hideResults();
    }, 0);
  });

  // Hovering a result makes it the active option too, so the pointer and the
  // keyboard can never disagree about which row is current.
  document.getElementById('search-results').addEventListener('mouseover', (event) => {
    const option = event.target.closest('.sr-item');
    if (!option) return;
    const options = [...document.querySelectorAll('#search-results .sr-item')];
    setActiveOption(options.indexOf(option));
  });
}

function showResults(query) {
  const results = document.getElementById('search-results');
  const input = document.getElementById('search-input');
  activeIndex = -1;

  if (query.length < 1) { hideResults(); return; }
  const needle = query.toLowerCase();
  const matches = searchItems
    .filter((item) => item.label.toLowerCase().includes(needle)
      || (item.alias && item.alias.toLowerCase().includes(needle)))
    .slice(0, 12);

  if (!matches.length) {
    replace(results, el('li', {}, el('div', { class: 'sr-empty', text: 'No district or station matches.' })));
    results.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    clearActiveOption();
    return;
  }

  replace(results, matches.map((item, i) => el('li', { role: 'presentation' }, [
    el('button', {
      // A stable id per visible option, so aria-activedescendant can name it.
      id: 'sr-opt-' + i,
      type: 'button', class: 'sr-item', role: 'option', 'aria-selected': 'false',
      // The combobox owns keyboard focus: DOM focus stays on the input and the
      // active option is named by aria-activedescendant. A natively tabbable
      // button here would be a second, competing focus model - Tab would walk
      // every result instead of leaving the search. It stays a button so a
      // pointer click keeps working unchanged.
      tabindex: '-1',
      onclick: () => choose(item),
    }, [
      el('span', { class: `sr-dot sr-dot--${item.kind}` }),
      el('span', { text: item.label }),
      el('span', { class: 'sr-kind', text: item.kind }),
    ]),
  ])));
  results.hidden = false;
  input.setAttribute('aria-expanded', 'true');
  clearActiveOption();
}

function hideResults() {
  const results = document.getElementById('search-results');
  results.hidden = true;
  results.replaceChildren();
  document.getElementById('search-input').setAttribute('aria-expanded', 'false');
  clearActiveOption();
}

function choose(item) {
  hideResults();
  const input = document.getElementById('search-input');
  input.value = item.label;
  document.getElementById('search-clear').hidden = false;

  if (item.kind === 'district') {
    store.selectDistrict(item.key);
    if (hooks.flyToDistrict) hooks.flyToDistrict(item.feature);
  } else {
    store.selectStation({
      name: item.label,
      district_name: item.district_name || null,
      lon: item.lon,
      lat: item.lat,
    });
    if (hooks.flyToStation) hooks.flyToStation(item);
  }
}

/* ── method dialog ────────────────────────────────────────────────────── */
/* A native <dialog> opened with showModal(). The browser then owns the hard
 * parts - top layer, background inertness, Tab containment and Escape - which
 * a div with role="dialog" only pretends to do. */
function wireMethodDialog() {
  const dialog = document.getElementById('method-dialog');
  document.getElementById('method-close').addEventListener('click', closeMethod);

  // Clicking the backdrop closes: the click lands on the dialog element itself
  // when it falls outside the dialog's own box.
  dialog.addEventListener('click', (event) => {
    if (event.target !== dialog) return;
    const box = dialog.getBoundingClientRect();
    const outside = event.clientX < box.left || event.clientX > box.right
      || event.clientY < box.top || event.clientY > box.bottom;
    if (outside) closeMethod();
  });

  // Escape fires the dialog's own close event; restore focus from there so
  // every close path behaves identically.
  dialog.addEventListener('close', () => {
    if (methodOpener && methodOpener.focus) methodOpener.focus();
    methodOpener = null;
  });

  /* showModal() makes the rest of the document inert, so Tab can never reach a
   * control behind the dialog. It does, however, pass through document.body on
   * each wrap - measured here as close button -> scrollable body -> body ->
   * close button - which is a dead stop for anyone navigating by keyboard.
   * Wrapping explicitly at both ends removes that stop. */
  dialog.addEventListener('keydown', (event) => {
    if (event.key !== 'Tab') return;
    const stops = focusableWithin(dialog);
    if (stops.length === 0) return;
    const first = stops[0];
    const last = stops[stops.length - 1];
    const active = document.activeElement;
    if (!event.shiftKey && (active === last || !dialog.contains(active))) {
      event.preventDefault();
      first.focus();
    } else if (event.shiftKey && (active === first || !dialog.contains(active))) {
      event.preventDefault();
      last.focus();
    }
  });

  buildMethodBody();
}

const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'input:not([disabled])',
  'select:not([disabled])', 'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function focusableWithin(root) {
  return [...root.querySelectorAll(FOCUSABLE)]
    .filter((node) => node.offsetWidth > 0 || node.offsetHeight > 0
      || node.getClientRects().length > 0);
}

let methodOpener = null;

function openMethod() {
  const dialog = document.getElementById('method-dialog');
  if (dialog.open) return;
  methodOpener = document.activeElement;
  dialog.showModal();
  document.getElementById('method-close').focus();
}

function closeMethod() {
  const dialog = document.getElementById('method-dialog');
  if (dialog.open) dialog.close();
}

export function methodIsOpen() {
  return document.getElementById('method-dialog').open === true;
}

function buildMethodBody() {
  const c = data.city;
  const body = document.getElementById('method-body');
  const param = (k, v) => el('div', {}, [el('dt', { text: k }), el('dd', { text: v })]);

  replace(body, [
    el('h3', { text: 'Model parameters' }),
    el('dl', { class: 'params' }, [
      param('Walking speed', `${c.walking_speed_kmh} km/h`),
      param('Time budget', `${c.walking_time_minutes} min`),
      param('Threshold', `${fmt.int(c.walking_time_seconds)} s`),
      param('Distance', `${fmt.int(c.distance_budget_m)} m`),
      param('Snapping', c.snapping_method),
      param('Districts', fmt.int(c.analysis_district_count)),
    ]),

    el('h3', { text: 'What is measured' }),
    el('p', {
      text: `Population is modelled at roughly 100 m cells, calibrated district by district`
        + ` to official ${c.reference_period} totals — ${fmt.people(c.analysis_population)}`
        + ` residents across the ${fmt.int(c.analysis_district_count)} districts with official`
        + ` statistics — then classified by walking distance along the OpenStreetMap`
        + ` pedestrian network to the nearest metro access point and to the nearest mapped`
        + ` bus stop. Routing is edge-aware: a cell is measured from its own position along`
        + ` the walkable edge it stands beside, not from the nearest graph vertex.`,
    }),
    el('ul', {}, [
      el('li', { text: `${c.definitions.metro_access}` }),
      el('li', { text: `Bus-only — ${c.definitions.bus_only}` }),
      el('li', { text: `Underserved — ${c.definitions.underserved}` }),
    ]),

    el('h3', { text: 'What is not measured' }),
    el('p', { text: `Physical walking access only. Nothing here reflects ${c.does_not_measure.join(', ')}.` }),

    el('h3', { text: 'Display layers are not evidence' }),
    el('p', { text: c.display_layer_note }),
    el('p', {
      text: 'The population grid on the map aggregates the audited cells into 500 m squares'
        + ' for display, and the metro lines come from OpenStreetMap route relations. Neither'
        + ' produces any figure reported here.',
    }),

    el('h3', { text: 'Known limits' }),
    el('ul', {}, [
      el('li', {
        text: 'The link from a cell centre to the network is a straight line to the nearest'
          + ' mapped walkable edge. It may not be physically walkable, so its effect on any'
          + ' individual cell is uncertain, in an unknown direction.',
      }),
      el('li', {
        text: 'Within-district population weights come from WorldPop R2025A, an alpha product'
          + ' whose within-district accuracy is unverified.',
      }),
      el('li', { text: 'Bus stops come from OpenStreetMap alone, with no official operator list.' }),
      el('li', {
        text: 'Ten of the fifty stations have no mapped entrance and fall back to the station'
          + ' point, which slightly flatters those stations.',
      }),
      el('li', { text: c.estimate_note }),
    ]),

    el('h3', { text: 'Provenance' }),
    el('p', {
      text: `Analysis version ${c.analysis_version}. Basemap © OpenFreeMap, © OpenMapTiles,`
        + ' data from OpenStreetMap. Transit and boundary data from OpenStreetMap (ODbL);'
        + ' population totals from the Statistics Agency of the Republic of Uzbekistan;'
        + ' population distribution from WorldPop.',
    }),
  ]);
}
