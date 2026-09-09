/* Ranked district dot plot — D3.
 *
 * D3 keeps the analytical charts. This is the first of them; Week 6 adds the
 * stacked composition, the density/access scatterplot and the parallel
 * coordinates alongside it, on the same shared selection.
 *
 * Accessibility: the chart root is a list, not an image. The previous version
 * put role="img" on an SVG that contained role="button" descendants, which
 * hides the very controls it exposes. Here the SVG is role="list", each row is
 * a role="listitem" carrying a focusable button, and the values are also in the
 * sidebar so nothing is reachable only by hovering the chart.
 */

import { fmt } from './data.js';
import * as store from './state.js';

const MARGIN = { top: 18, right: 46, bottom: 6, left: 96 };
const ROW_MIN = 22;
const ROW_MAX = 66;   // tall screens: the rows breathe rather than leaving a dead band
const ROW_DEFAULT = 26;

let ranked = [];
let host = null;
let handlers = {};

export function initRanking(rankedFeatures, hooks) {
  ranked = rankedFeatures;
  handlers = hooks || {};
  host = document.getElementById('ranking');
  render();

  if (typeof ResizeObserver === 'function') {
    let lastW = host.clientWidth;
    let lastH = host.clientHeight;
    let pending = null;
    new ResizeObserver(() => {
      if (pending) clearTimeout(pending);
      pending = setTimeout(() => {
        pending = null;
        // Height matters as much as width: the rows are sized to fill the panel.
        // The 6px band avoids re-rendering on the height the render itself sets.
        if (Math.abs(host.clientWidth - lastW) > 1 || Math.abs(host.clientHeight - lastH) > 6) {
          lastW = host.clientWidth;
          lastH = host.clientHeight;
          render();
        }
      }, 120);
    }).observe(host);
  }
}

export function render() {
  if (!host) return;
  const width = Math.max(240, Math.floor(host.clientWidth));

  /* On the desktop layout the ranking owns the rest of the sidebar, so the rows
   * grow to fill it rather than leaving a dead band under the chart. Below that
   * breakpoint the panel is content-sized and measuring it would feed back into
   * itself, so a fixed row height is used. */
  const fillsPanel = window.innerWidth > 940;
  const available = host.clientHeight - MARGIN.top - MARGIN.bottom;
  const rowH = fillsPanel && available > 140
    ? Math.max(ROW_MIN, Math.min(ROW_MAX, Math.floor(available / ranked.length)))
    : ROW_DEFAULT;
  const height = MARGIN.top + ranked.length * rowH + MARGIN.bottom;

  const labelRoom = Math.min(Math.round(width * 0.42), 130);
  const margin = { ...MARGIN, left: labelRoom };
  const innerWidth = Math.max(60, width - margin.left - margin.right);

  d3.select(host).selectAll('svg').remove();
  const svg = d3.select(host).append('svg')
    .attr('viewBox', `0 0 ${width} ${height}`)
    .attr('width', width)
    .attr('height', height)
    .attr('role', 'list')
    .attr('aria-label', 'Districts ranked by modelled share of population within a '
      + 'ten-minute walk of metro access, highest first');

  const maxValue = d3.max(ranked, (d) => d.properties.metro_access_pct) || 1;
  const x = d3.scaleLinear()
    .domain([0, Math.max(5, maxValue * 1.1)])
    .range([0, innerWidth])
    .nice();

  const plot = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

  // axis
  const ticks = x.ticks(width < 320 ? 3 : 5);
  const axis = plot.append('g').attr('aria-hidden', 'true');
  axis.selectAll('text').data(ticks).join('text')
    .attr('class', 'rk-axis-t')
    .attr('x', x).attr('y', -7)
    .attr('text-anchor', 'middle')
    .text((d) => `${d}%`);
  axis.append('line')
    .attr('class', 'rk-axis-line')
    .attr('x1', 0).attr('x2', 0)
    .attr('y1', -2).attr('y2', ranked.length * rowH - rowH / 2);

  const rows = plot.selectAll('g.rk-row')
    .data(ranked, (d) => d.properties.district_name)
    .join('g')
    .attr('class', 'rk-row')
    .attr('role', 'listitem')
    .attr('transform', (d, i) => `translate(0,${i * rowH})`);

  rows.append('rect')
    .attr('class', 'rk-band')
    .attr('x', -margin.left).attr('y', -rowH / 2)
    .attr('width', width).attr('height', rowH);

  rows.append('line')
    .attr('class', 'rk-track')
    .attr('x1', 0).attr('y1', 0)
    .attr('x2', (d) => x(d.properties.metro_access_pct)).attr('y2', 0);

  rows.append('text')
    .attr('class', 'rk-label')
    .attr('x', -10).attr('y', 0)
    .attr('text-anchor', 'end')
    .text((d) => d.properties.label);

  rows.append('circle')
    .attr('class', 'rk-dot')
    .attr('cx', (d) => x(d.properties.metro_access_pct))
    .attr('cy', 0)
    .attr('r', 4);

  rows.append('text')
    .attr('class', 'rk-val')
    .attr('x', (d) => x(d.properties.metro_access_pct) + 9)
    .attr('y', 0)
    .text((d) => fmt.pct(d.properties.metro_access_pct));

  // One focusable control per row, covering the whole row.
  rows.append('rect')
    .attr('class', 'rk-row-hit')
    .attr('x', -margin.left).attr('y', -rowH / 2)
    .attr('width', width).attr('height', rowH)
    .attr('role', 'button')
    .attr('tabindex', 0)
    .attr('aria-pressed', 'false')
    .attr('aria-label', (d) => `${d.properties.label} district, metro access `
      + `${fmt.pct(d.properties.metro_access_pct)}. Activate to select it on the map.`)
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
    .on('click', (event, d) => {
      store.toggleDistrict(d.properties.district_name);
      if (handlers.onSelect) handlers.onSelect(d);
    })
    .on('keydown', (event, d) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        store.toggleDistrict(d.properties.district_name);
        if (handlers.onSelect) handlers.onSelect(d);
      } else if (event.key === 'Escape') {
        store.clearSelection();
      }
    });

  syncRanking(store.get());
}

export function syncRanking(state) {
  if (!host) return;
  d3.select(host).selectAll('g.rk-row')
    .classed('is-selected', (d) => d.properties.district_name === state.selectedDistrict)
    .classed('is-hovered', (d) => d.properties.district_name === state.hoveredDistrict
      && d.properties.district_name !== state.selectedDistrict);
  d3.select(host).selectAll('g.rk-row').select('.rk-dot')
    .attr('r', (d) => (d.properties.district_name === state.selectedDistrict ? 6 : 4));
  d3.select(host).selectAll('.rk-row-hit')
    .attr('aria-pressed', (d) => String(d.properties.district_name === state.selectedDistrict));
}

/** Move keyboard focus to the ranking, for the "Districts" navigation item. */
export function focusRanking() {
  const first = host && host.querySelector('.rk-row-hit');
  if (first) first.focus();
}
