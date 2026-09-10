/* Parallel-coordinates district comparison — D3.
 *
 * Six axes, twelve districts. Left alone, a chart like this is decorative
 * spaghetti, so the comparison task is made explicit instead: all twelve
 * districts are drawn as quiet context, and up to four are deliberately pinned
 * to be read against each other.
 *
 * Two of the six axes are derived comparison ratios rather than audited Week 4
 * results — mapped bus stops per km² and mapped bazaars per 100k. They are
 * computed at runtime in chart-utils.js and labelled MAPPED everywhere,
 * because OpenStreetMap coverage varies and a low value can mean a thinly
 * surveyed district rather than a thinly served one.
 *
 * Every axis keeps its own scale and its own real-world units. Normalising all
 * six to 0-1 would draw the same lines and destroy the tick labels.
 */

import * as store from './state.js';
import {
  COMPARE_COLOURS, DIMENSIONS, comparisonColour, observeSize, resetHost, speakParallel,
} from './chart-utils.js';
import { el, replace } from './dom.js';

/* The first and last axes carry tick labels on their outer side, so the
 * horizontal margins have to hold a tick label plus half a caption. Without
 * that the rightmost caption is clipped by the panel edge. */
const MARGIN = { top: 30, right: 40, bottom: 26, left: 34 };

let districts = [];
let host = null;
let handlers = {};
let byName = new Map();

export function initParallel(features, hooks) {
  districts = features;
  handlers = hooks || {};
  host = document.getElementById('parallel');
  byName = new Map(features.map((f) => [f.properties.district_name, f]));
  if (!host) return;
  wireComparisonControls();
  renderParallel();
  observeSize(host, renderParallel);
  updateComparisonUI(store.get());
}

export function renderParallel() {
  if (!host || !districts.length) return;

  const width = Math.max(240, Math.floor(host.clientWidth));
  const height = Math.max(200, Math.floor(host.clientHeight));
  // Below this the six axis captions cannot be read side by side, so they are
  // abbreviated and stacked onto two lines rather than shrunk into noise.
  const narrow = width < 460;
  const margin = { ...MARGIN, top: narrow ? 34 : MARGIN.top };
  const innerW = Math.max(80, width - margin.left - margin.right);
  const innerH = Math.max(70, height - margin.top - margin.bottom);

  const xFor = d3.scalePoint()
    .domain(DIMENSIONS.map((d) => d.key))
    .range([0, innerW])
    .padding(0.06);

  // One scale per axis, each from the real extent of that measure, `.nice()`d
  // so the ticks land on readable numbers.
  const yFor = new Map(DIMENSIONS.map((dim) => [
    dim.key,
    d3.scaleLinear()
      .domain([0, d3.max(districts, (f) => dim.value(f.properties))])
      .nice()
      .range([innerH, 0]),
  ]));

  const line = (feature) => d3.line()(DIMENSIONS.map((dim) => [
    xFor(dim.key),
    yFor.get(dim.key)(dim.value(feature.properties)),
  ]));

  resetHost(host);
  const svg = d3.select(host).append('svg')
    .attr('viewBox', `0 0 ${width} ${height}`)
    .attr('width', width)
    .attr('height', height)
    .attr('role', 'list')
    .attr('aria-label', 'Twelve district profiles across population, density, '
      + 'metro access, bus-only share, mapped bus stops per square kilometre '
      + 'and mapped bazaars per hundred thousand residents');

  const plot = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

  /* axes */
  const axes = plot.append('g').attr('aria-hidden', 'true');
  for (const dim of DIMENSIONS) {
    const gx = xFor(dim.key);
    const scale = yFor.get(dim.key);
    const g = axes.append('g').attr('transform', `translate(${gx},0)`);
    g.append('line').attr('class', 'pc-axis').attr('y1', 0).attr('y2', innerH);

    // Ticks sit outside the last axis and inside the rest, so no tick label is
    // ever drawn on top of the lines it is meant to describe at the right edge.
    const last = dim === DIMENSIONS[DIMENSIONS.length - 1];
    const ticks = scale.ticks(narrow ? 3 : 4);
    g.selectAll('text.pc-tick').data(ticks).join('text')
      .attr('class', 'pc-tick')
      .attr('x', last ? -5 : 5).attr('y', (t) => scale(t) + 3)
      .attr('text-anchor', last ? 'end' : 'start')
      .text((t) => dim.tick(t));

    /* The caption names the measure, the second line its unit. The outer two
     * captions are anchored inward: centred, they would overhang the panel. */
    const anchor = dim === DIMENSIONS[0] ? 'start' : last ? 'end' : 'middle';
    const capX = anchor === 'start' ? -margin.left + 2
      : anchor === 'end' ? margin.right - 2 : 0;
    const caption = g.append('text')
      .attr('class', 'pc-cap')
      .attr('y', -16)
      .attr('text-anchor', anchor);
    caption.append('tspan')
      .attr('x', capX)
      .text(dim.short);
    caption.append('tspan')
      .attr('class', 'pc-unit')
      .attr('x', capX).attr('dy', '1.2em')
      .text(dim.unit);
  }

  /* lines: every district as context, pinned ones emphasised in update */
  const rows = plot.selectAll('g.pc-row')
    .data(districts, (d) => d.properties.district_name)
    .join('g')
    .attr('class', 'pc-row')
    .attr('role', 'listitem');

  rows.append('path').attr('class', 'pc-line').attr('d', line);

  // A wide invisible stroke over the same path makes a 1px line clickable and
  // hoverable without thickening what is drawn.
  rows.append('path')
    .attr('class', 'pc-hit')
    .attr('d', line)
    .attr('role', 'button')
    .attr('tabindex', 0)
    .attr('aria-pressed', 'false')
    .attr('aria-label', (d) => speakParallel(d.properties))
    .on('mouseenter', (event, d) => {
      store.set({ hoveredDistrict: d.properties.district_name });
      if (handlers.onHover) handlers.onHover(event, d);
    })
    .on('mousemove', (event, d) => { if (handlers.onMove) handlers.onMove(event, d); })
    .on('mouseleave', () => {
      store.set({ hoveredDistrict: null });
      if (handlers.onLeave) handlers.onLeave();
    })
    .on('focus', (event, d) => { store.set({ hoveredDistrict: d.properties.district_name }); })
    .on('blur', () => { store.set({ hoveredDistrict: null }); })
    // Click selects, exactly as it does in the other four views. Comparison
    // membership is never toggled from a line: it stays deliberate, through
    // the control below the chart.
    .on('click', (event, d) => store.toggleDistrict(d.properties.district_name))
    .on('keydown', (event, d) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        store.toggleDistrict(d.properties.district_name);
      } else if (event.key === 'Escape') {
        store.clearSelection();
      }
    });

  updateParallelState(store.get());
}

export function updateParallelState(state) {
  if (!host) return;
  const rows = d3.select(host).selectAll('g.pc-row');
  rows
    .classed('is-selected', (d) => d.properties.district_name === state.selectedDistrict)
    .classed('is-hovered', (d) => d.properties.district_name === state.hoveredDistrict
      && d.properties.district_name !== state.selectedDistrict)
    .classed('is-compared', (d) => state.comparisonDistricts.includes(d.properties.district_name));
  rows.select('.pc-line')
    // Colour is one of three cues on a pinned line; width and opacity carry it
    // too, in the stylesheet, so the encoding does not rest on colour alone.
    .style('stroke', (d) => comparisonColour(d.properties.district_name, state.comparisonDistricts));
  rows.select('.pc-hit')
    .attr('aria-pressed', (d) => String(d.properties.district_name === state.selectedDistrict));

  // Emphasised lines on top of the quiet ones.
  rows.filter((d) => state.comparisonDistricts.includes(d.properties.district_name)).raise();
  rows.filter((d) => d.properties.district_name === state.hoveredDistrict
    || d.properties.district_name === state.selectedDistrict).raise();

  updateComparisonUI(state);
}

/* ── comparison controls ──────────────────────────────────────────────────
 *
 * The one place comparison membership changes, aside from the matching action
 * in the district sidebar. Both call the same store functions.
 */
function wireComparisonControls() {
  const add = document.getElementById('compare-add');
  const clear = document.getElementById('compare-clear');
  if (add) {
    add.addEventListener('click', () => {
      const name = store.get().selectedDistrict;
      if (name) store.toggleComparison(name);
    });
  }
  if (clear) clear.addEventListener('click', () => store.clearComparison());
}

export function updateComparisonUI(state) {
  const add = document.getElementById('compare-add');
  const clear = document.getElementById('compare-clear');
  const chips = document.getElementById('compare-chips');
  const note = document.getElementById('compare-note');
  if (!add || !chips) return;

  const selected = state.selectedDistrict;
  const pinned = state.comparisonDistricts;
  const label = selected ? (byName.get(selected)?.properties.label ?? selected) : null;
  const isPinned = selected ? pinned.includes(selected) : false;
  const full = pinned.length >= store.MAX_COMPARISON;

  if (!selected) {
    add.disabled = true;
    add.textContent = 'Select a district to compare';
  } else if (isPinned) {
    add.disabled = false;
    add.textContent = `Remove ${label}`;
  } else if (full) {
    add.disabled = true;
    add.textContent = `Add ${label}`;
  } else {
    add.disabled = false;
    add.textContent = `Add ${label}`;
  }

  if (note) {
    note.textContent = full && !isPinned
      ? `Maximum ${store.MAX_COMPARISON} districts — remove one to add another.`
      : '';
    note.hidden = !note.textContent;
  }

  if (clear) clear.hidden = pinned.length === 0;

  // Chips are the labelled legend for the coloured lines: colour alone would
  // not say which district is which.
  replace(chips, pinned.map((name, i) => {
    const text = byName.get(name)?.properties.label ?? name;
    return el('span', { class: 'chip' }, [
      el('i', { class: 'chip-sw', style: { background: COMPARE_COLOURS[i % COMPARE_COLOURS.length] } }),
      el('span', { class: 'chip-t', text }),
      el('button', {
        type: 'button',
        class: 'chip-x',
        'aria-label': `Remove ${text} from the comparison`,
        onclick: () => store.removeFromComparison(name),
      }, '×'),
    ]);
  }));
  chips.hidden = pinned.length === 0;
}

export function focusParallel() {
  const first = host && host.querySelector('.pc-hit');
  if (first) first.focus();
}
