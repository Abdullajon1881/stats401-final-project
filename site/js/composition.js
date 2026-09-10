/* 100% stacked access-composition bars — D3.
 *
 * The research question has two halves. The ranked dot plot answers the first
 * (what share reaches the metro); this chart answers the second (which
 * districts depend on buses), which is why it is sorted by bus-only share
 * rather than by metro access. The ordering is stated on the panel so it does
 * not look arbitrary, and it is derived from the data at runtime — no district
 * name or position is written into this file.
 *
 * The three categories are the audited mutually exclusive ones and they sum to
 * 100 by construction, so the bar is drawn from the audited percentages
 * directly rather than reconstructed from populations.
 *
 * Accessibility: the chart root is a list, each district is a listitem holding
 * one focusable button covering its whole row. Twelve controls, not hundreds.
 */

import { fmt } from './data.js';
import * as store from './state.js';
import { observeSize, resetHost, speakComposition, widestText } from './chart-utils.js';

const MARGIN = { top: 16, right: 52, bottom: 16, left: 92 };
const ROW_MIN = 18;
const ROW_MAX = 30;

const SEGMENTS = [
  { key: 'metro_access_pct', pop: 'metro_access_population', cls: 'cm-metro' },
  { key: 'bus_only_pct', pop: 'bus_only_population', cls: 'cm-bus' },
  { key: 'underserved_pct', pop: 'underserved_population', cls: 'cm-under' },
];

let districts = [];
let ordered = [];
let host = null;
let handlers = {};

export function initComposition(features, hooks) {
  districts = features;
  handlers = hooks || {};
  host = document.getElementById('composition');
  if (!host) return;

  // Sorted by bus-only share descending: this chart exists to show bus
  // reliance. Ties fall back to the name so the order is deterministic.
  ordered = features.slice().sort(
    (a, b) => b.properties.bus_only_pct - a.properties.bus_only_pct
      || a.properties.district_name.localeCompare(b.properties.district_name),
  );

  renderComposition();
  observeSize(host, renderComposition);
  renderLead();
}

/* A single data-derived sentence under the title. The district and the figure
 * both come from the sorted data, so this text cannot go stale or disagree
 * with the bars above it. It is descriptive: highest measured share, not a
 * judgement about the district. */
function renderLead() {
  const node = document.getElementById('composition-lead');
  if (!node || !ordered.length) return;
  const top = ordered[0].properties;
  node.textContent = `Highest modelled bus-only share: ${top.label} — `
    + `${fmt.pct(top.bus_only_pct)}.`;
}

export function renderComposition() {
  if (!host || !ordered.length) return;

  const width = Math.max(240, Math.floor(host.clientWidth));
  const available = host.clientHeight - MARGIN.top - MARGIN.bottom;
  const bounded = getComputedStyle(host).overflowY === 'auto';
  const rowH = bounded && available > 120
    ? Math.max(ROW_MIN, Math.min(ROW_MAX, Math.floor(available / ordered.length)))
    : 24;
  const height = MARGIN.top + ordered.length * rowH + MARGIN.bottom;

  /* The gutter is measured from the longest district name rather than taken as
   * a share of the width: a percentage is wrong at some viewport by definition,
   * and at 320px it clipped the longest name. The label font shrinks a little
   * on a narrow panel so the bar still gets most of the room. */
  const labelPx = width < 330 ? 10 : 11;
  const font = `${labelPx}px ${getComputedStyle(host).fontFamily}`;
  const longest = widestText(ordered.map((d) => d.properties.label), font);
  // + 9 for the gap between the label and the bar, + 2 so the glyph box has air.
  const labelRoom = Math.min(Math.round(longest) + 11, Math.round(width * 0.46));
  const valueRoom = width < 330 ? 40 : MARGIN.right;
  const margin = { ...MARGIN, left: labelRoom, right: valueRoom };
  const innerWidth = Math.max(50, width - margin.left - margin.right);

  resetHost(host);
  const svg = d3.select(host).append('svg')
    .attr('viewBox', `0 0 ${width} ${height}`)
    .attr('width', width)
    .attr('height', height)
    .attr('role', 'list')
    .attr('aria-label', 'Districts as a share of analysed population by modelled '
      + 'ten-minute walking access, sorted by bus-only share, highest first');

  const x = d3.scaleLinear().domain([0, 100]).range([0, innerWidth]);
  const plot = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

  // A 0 / 50 / 100 guide is enough orientation for a share chart.
  const guide = plot.append('g').attr('aria-hidden', 'true');
  guide.selectAll('line').data([0, 50, 100]).join('line')
    .attr('class', 'cm-guide')
    .attr('x1', x).attr('x2', x)
    .attr('y1', -6).attr('y2', ordered.length * rowH);
  guide.selectAll('text').data([0, 50, 100]).join('text')
    .attr('class', 'cm-guide-t')
    .attr('x', x).attr('y', -9)
    .attr('text-anchor', (d) => (d === 0 ? 'start' : d === 100 ? 'end' : 'middle'))
    .text((d) => `${d}%`);

  const rows = plot.selectAll('g.cm-row')
    .data(ordered, (d) => d.properties.district_name)
    .join('g')
    .attr('class', 'cm-row')
    .attr('role', 'listitem')
    .attr('transform', (d, i) => `translate(0,${i * rowH})`);

  // Full-width band behind the row, so selection reads as a row and not only
  // as a colour change inside the bar.
  rows.append('rect')
    .attr('class', 'cm-band')
    .attr('x', -margin.left).attr('y', 0)
    .attr('width', width).attr('height', rowH);

  const barH = Math.max(7, Math.min(14, rowH - 9));
  const barY = (rowH - barH) / 2;

  // One <g> of three segments per row, laid out by a running offset so the
  // three audited percentages are used as they are.
  rows.each(function stack(d) {
    const p = d.properties;
    let offset = 0;
    const row = d3.select(this);
    for (const seg of SEGMENTS) {
      const value = p[seg.key];
      row.append('rect')
        .attr('class', `cm-seg ${seg.cls}`)
        .attr('x', x(offset))
        .attr('y', barY)
        .attr('width', Math.max(0, x(value) - x(0)))
        .attr('height', barH);
      offset += value;
    }
  });

  rows.append('text')
    .attr('class', 'cm-label')
    .attr('x', -9).attr('y', rowH / 2)
    .attr('text-anchor', 'end')
    .style('font-size', `${labelPx}px`)
    .text((d) => d.properties.label);

  // The bus-only figure is the value this chart is ordered by, so it is the
  // one that earns a permanent direct label.
  rows.append('text')
    .attr('class', 'cm-val')
    .attr('x', innerWidth + 8).attr('y', rowH / 2)
    .text((d) => fmt.pct(d.properties.bus_only_pct));

  rows.append('rect')
    .attr('class', 'cm-hit')
    .attr('x', -margin.left).attr('y', 0)
    .attr('width', width).attr('height', rowH)
    .attr('role', 'button')
    .attr('tabindex', 0)
    .attr('aria-pressed', 'false')
    .attr('aria-label', (d) => speakComposition(d.properties))
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
    .on('click', (event, d) => store.toggleDistrict(d.properties.district_name))
    .on('keydown', (event, d) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        store.toggleDistrict(d.properties.district_name);
      } else if (event.key === 'Escape') {
        store.clearSelection();
      }
    });

  updateCompositionState(store.get());
}

/** Selection and hover only: no geometry is rebuilt for a state change. */
export function updateCompositionState(state) {
  if (!host) return;
  const rows = d3.select(host).selectAll('g.cm-row');
  rows
    .classed('is-selected', (d) => d.properties.district_name === state.selectedDistrict)
    .classed('is-hovered', (d) => d.properties.district_name === state.hoveredDistrict
      && d.properties.district_name !== state.selectedDistrict)
    .classed('is-compared', (d) => state.comparisonDistricts.includes(d.properties.district_name));
  rows.select('.cm-hit')
    .attr('aria-pressed', (d) => String(d.properties.district_name === state.selectedDistrict));
}

/** Move keyboard focus into the chart, for the Districts navigation item. */
export function focusComposition() {
  const first = host && host.querySelector('.cm-hit');
  if (first) first.focus();
}
