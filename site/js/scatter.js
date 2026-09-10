/* Population density vs metro access scatterplot — D3.
 *
 * The task: do denser districts have better modelled metro access? Twelve
 * points, one per district, both axes read straight off the audited district
 * fields. No new geographic computation happens here.
 *
 * The y axis starts at zero because it is a share and a truncated baseline
 * would exaggerate differences between districts. The upper extent is taken
 * from the data and `.nice()`d rather than fixed, so a future data revision
 * cannot silently push points off the top.
 *
 * The median guides are descriptive: they say where the middle of these twelve
 * districts happens to fall. They are not thresholds, and the quadrants they
 * make are deliberately unlabelled — naming them would assert a judgement
 * ("underserved quadrant", "priority") that this analysis does not support.
 */

import { fmt } from './data.js';
import * as store from './state.js';
import { comparisonColour, observeSize, resetHost, speakScatter } from './chart-utils.js';

const MARGIN = { top: 14, right: 16, bottom: 40, left: 46 };
const R = 5;
const R_SELECTED = 8;

let districts = [];
let host = null;
let handlers = {};

export function initScatter(features, hooks) {
  districts = features;
  handlers = hooks || {};
  host = document.getElementById('scatter');
  if (!host) return;
  renderScatter();
  observeSize(host, renderScatter);
}

export function renderScatter() {
  if (!host || !districts.length) return;

  const width = Math.max(220, Math.floor(host.clientWidth));
  const height = Math.max(200, Math.floor(host.clientHeight));
  const compact = width < 320;
  const margin = { ...MARGIN, left: compact ? 38 : MARGIN.left };
  const innerW = Math.max(60, width - margin.left - margin.right);
  const innerH = Math.max(60, height - margin.top - margin.bottom);

  const xValue = (p) => p.population_density_per_km2;
  const yValue = (p) => p.metro_access_pct;

  // A linear x scale reads correctly here: the densities span roughly one
  // order of magnitude, not several, so a log axis would add a reading cost
  // without separating anything the linear scale merges.
  const x = d3.scaleLinear()
    .domain([0, d3.max(districts, (d) => xValue(d.properties))])
    .nice()
    .range([0, innerW]);
  const y = d3.scaleLinear()
    .domain([0, d3.max(districts, (d) => yValue(d.properties))])
    .nice()
    .range([innerH, 0]);

  resetHost(host);
  const svg = d3.select(host).append('svg')
    .attr('viewBox', `0 0 ${width} ${height}`)
    .attr('width', width)
    .attr('height', height)
    .attr('role', 'list')
    .attr('aria-label', 'Twelve districts plotted by population density against '
      + 'modelled metro access within a ten-minute walk');

  const plot = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

  /* grid + axes */
  const grid = plot.append('g').attr('aria-hidden', 'true');
  const xTicks = x.ticks(compact ? 3 : 5);
  const yTicks = y.ticks(compact ? 4 : 5);

  grid.selectAll('line.sc-gy').data(yTicks).join('line')
    .attr('class', 'sc-grid')
    .attr('x1', 0).attr('x2', innerW)
    .attr('y1', y).attr('y2', y);
  grid.selectAll('line.sc-gx').data(xTicks).join('line')
    .attr('class', 'sc-grid')
    .attr('x1', x).attr('x2', x)
    .attr('y1', 0).attr('y2', innerH);

  const axes = plot.append('g').attr('aria-hidden', 'true');
  axes.selectAll('text.sc-tx').data(xTicks).join('text')
    .attr('class', 'sc-tick')
    .attr('x', x).attr('y', innerH + 14)
    .attr('text-anchor', 'middle')
    .text((d) => (d >= 1000 ? `${Math.round(d / 1000)}k` : String(d)));
  axes.selectAll('text.sc-ty').data(yTicks).join('text')
    .attr('class', 'sc-tick')
    .attr('x', -7).attr('y', (d) => y(d) + 3)
    .attr('text-anchor', 'end')
    .text((d) => `${d}%`);

  axes.append('text')
    .attr('class', 'sc-axis-title')
    .attr('x', innerW / 2).attr('y', innerH + 32)
    .attr('text-anchor', 'middle')
    .text(compact ? 'people / km²' : 'population density (people / km²)');
  axes.append('text')
    .attr('class', 'sc-axis-title')
    // Keyed to the margin rather than a constant: at -36 inside a 46px margin
    // the rotated glyph box started 1px outside the SVG and was clipped.
    .attr('transform', `translate(${-(margin.left - 13)},${innerH / 2}) rotate(-90)`)
    .attr('text-anchor', 'middle')
    .text('metro access');

  /* median guides, computed from the twelve districts on screen */
  const medX = d3.median(districts, (d) => xValue(d.properties));
  const medY = d3.median(districts, (d) => yValue(d.properties));
  const guides = plot.append('g').attr('aria-hidden', 'true');
  guides.append('line').attr('class', 'sc-median')
    .attr('x1', x(medX)).attr('x2', x(medX)).attr('y1', 0).attr('y2', innerH);
  guides.append('line').attr('class', 'sc-median')
    .attr('x1', 0).attr('x2', innerW).attr('y1', y(medY)).attr('y2', y(medY));
  /* No in-plot caption on the guides. Wherever it is anchored it eventually
   * lands on a district - the guides cross the middle of the data by
   * definition - and it collided with the transient district labels. The panel
   * footnote names the dashed lines and says what they are not, which is the
   * part that actually matters. */

  /* Two layers, and the split matters.
   *
   * Emphasis is expressed by paint order - the labelled point is drawn last so
   * nothing covers its text - and paint order in SVG means DOM order, so
   * emphasising a mark means moving its node. Moving a node that CONTAINS the
   * focused element blurs it, and re-appending it at the end also puts it last
   * in the tab order. With the hit targets inside the mark groups, focusing a
   * point raised it, which blurred it and left the next Tab exiting the chart:
   * one of twelve districts was reachable by keyboard.
   *
   * So the marks re-order freely in their own layer, and the focusable hit
   * targets sit in a second layer that is never touched. Tab order stays in
   * data order, focus survives every state change, and the visual result is
   * unchanged. */
  const markLayer = plot.append('g').attr('class', 'sc-marks').attr('aria-hidden', 'true');
  const hitLayer = plot.append('g').attr('class', 'sc-hits');

  const at = (d) => `translate(${x(xValue(d.properties))},${y(yValue(d.properties))})`;

  const points = markLayer.selectAll('g.sc-pt')
    .data(districts, (d) => d.properties.district_name)
    .join('g')
    .attr('class', 'sc-pt')
    .attr('transform', at);

  points.append('circle').attr('class', 'sc-halo').attr('r', R_SELECTED + 3);
  points.append('circle').attr('class', 'sc-dot').attr('r', R);

  // Labels are hidden by default and revealed on hover, selection or focus.
  // Twelve permanent labels at this size collide; a physics simulation to
  // avoid that would be motion for decoration's sake.
  /* Label placement.
   *
   * Only one label is ever visible, but it still has to avoid the marks around
   * it: Mirabad and Chilanzar plot about seven pixels apart, so a label centred
   * above either one lands on the other's dot and selection ring.
   *
   * Each point therefore picks its side once, at render, from where its
   * neighbours actually are. Four candidate placements are tried in a fixed
   * order and the first one clear of every other point wins; if none is clear,
   * the one furthest from the nearest neighbour wins. Deterministic, driven by
   * the data, and it names no district: the same input always produces the same
   * placement, and there is no simulation and no random offset.
   */
  const CLEAR_PX = 15;      // a label centre this close to another point reads as touching
  const OUT = R_SELECTED + 6;
  const placed = new Map();
  const coords = districts.map((d) => ({
    name: d.properties.district_name,
    px: x(xValue(d.properties)),
    py: y(yValue(d.properties)),
  }));

  for (const point of coords) {
    const candidates = [
      { dx: 0, dy: -OUT, anchor: 'middle', cx: 0, cy: -OUT },
      { dx: 0, dy: OUT + 7, anchor: 'middle', cx: 0, cy: OUT + 7 },
      { dx: OUT, dy: 4, anchor: 'start', cx: OUT + 18, cy: 4 },
      { dx: -OUT, dy: 4, anchor: 'end', cx: -(OUT + 18), cy: 4 },
    ].filter((c) => {
      // Never let a label leave the plot area.
      const left = point.px + c.cx - (c.anchor === 'start' ? 0 : 30);
      const right = point.px + c.cx + (c.anchor === 'end' ? 0 : 30);
      const top = point.py + c.cy - 6;
      const bottom = point.py + c.cy + 6;
      return left > -2 && right < innerW + 2 && top > -2 && bottom < innerH + 2;
    });

    const others = coords.filter((o) => o.name !== point.name);
    const nearest = (c) => others.reduce((min, o) => Math.min(
      min, Math.hypot(point.px + c.cx - o.px, point.py + c.cy - o.py),
    ), Infinity);

    const usable = candidates.length ? candidates
      : [{ dx: 0, dy: -OUT, anchor: 'middle', cx: 0, cy: -OUT }];
    const clear = usable.find((c) => nearest(c) > CLEAR_PX);
    placed.set(point.name, clear
      || usable.reduce((best, c) => (nearest(c) > nearest(best) ? c : best), usable[0]));
  }

  points.append('text')
    .attr('class', 'sc-plabel')
    .attr('x', (d) => placed.get(d.properties.district_name).dx)
    .attr('y', (d) => placed.get(d.properties.district_name).dy)
    .attr('text-anchor', (d) => placed.get(d.properties.district_name).anchor)
    .text((d) => d.properties.label);

  hitLayer.selectAll('g.sc-item')
    .data(districts, (d) => d.properties.district_name)
    .join('g')
    .attr('class', 'sc-item')
    .attr('role', 'listitem')
    .attr('transform', at)
    .append('circle')
    .attr('class', 'sc-hit')
    .attr('r', 13)
    .attr('role', 'button')
    .attr('tabindex', 0)
    .attr('aria-pressed', 'false')
    .attr('aria-label', (d) => speakScatter(d.properties))
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

  updateScatterState(store.get());
}

/* Which district, if any, owns the visible text label.
 *
 * Exactly one, or none. Hover outranks selection, so a transient hover takes
 * the label while the selected district keeps its ring and its place in the
 * store; letting go gives the label straight back. Comparison membership does
 * NOT earn a label: a pinned district is already identified by its colour, its
 * point styling and its chip in the profile panel, and a fourth cue costs more
 * in clutter than it returns.
 *
 * This used to be three independent CSS states - is-hovered, is-selected,
 * is-compared - each of which revealed a label. Three could be true on three
 * different points at once, and districts that plot close together then drew
 * their names through one another. Deciding here means the invariant is a
 * property of the code rather than of whichever combination happens to arise.
 */
function labelledDistrict(state) {
  return state.hoveredDistrict || state.selectedDistrict || null;
}

export function updateScatterState(state) {
  if (!host) return;
  const points = d3.select(host).selectAll('g.sc-pt');
  const labelled = labelledDistrict(state);
  points
    .classed('is-selected', (d) => d.properties.district_name === state.selectedDistrict)
    .classed('is-hovered', (d) => d.properties.district_name === state.hoveredDistrict
      && d.properties.district_name !== state.selectedDistrict)
    .classed('is-compared', (d) => state.comparisonDistricts.includes(d.properties.district_name))
    .classed('has-label', (d) => d.properties.district_name === labelled);
  points.select('.sc-dot')
    .attr('r', (d) => (d.properties.district_name === state.selectedDistrict ? R_SELECTED : R))
    // A pinned district carries its comparison colour here too, so the chips in
    // the profile panel and the points in this chart name the same districts.
    .style('fill', (d) => comparisonColour(d.properties.district_name, state.comparisonDistricts));
  d3.select(host).selectAll('.sc-hit')
    .attr('aria-pressed', (d) => String(d.properties.district_name === state.selectedDistrict));

  // Only marks move. The hit targets are in a separate layer and stay put, so
  // this cannot disturb keyboard focus or the tab order.
  points.filter((d) => d.properties.district_name === state.selectedDistrict).raise();
  points.filter((d) => d.properties.district_name === labelled).raise();
}

export function focusScatter() {
  const first = host && host.querySelector('.sc-hit');
  if (first) first.focus();
}
