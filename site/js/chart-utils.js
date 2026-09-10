/* Shared plumbing for the three Week 6 D3 district charts.
 *
 * The composition bars, the scatterplot and the parallel-coordinates chart are
 * three idioms over one set of twelve districts. Everything they genuinely
 * share lives here — the derived comparison ratios, the responsive re-render
 * trigger, the accessible-label vocabulary and the tooltip rows — so the three
 * renderers stay small and cannot drift into three different products.
 *
 * This is deliberately not a framework. Each chart still owns its own scales,
 * its own layout and its own DOM.
 */

import { fmt } from './data.js';
import { cell, el } from './dom.js';

/* ── derived comparison ratios ────────────────────────────────────────────
 *
 * These two are NOT Week 4 analytical results and must never be presented as
 * service provision. They are deterministic ratios computed at runtime from
 * audited district fields, and they exist only so the parallel-coordinates
 * chart can compare districts on more than access alone.
 *
 * OpenStreetMap completeness is not guaranteed and varies by district, so both
 * are labelled "mapped" everywhere they appear. A district with few mapped bus
 * stops may be under-surveyed rather than under-served, and this data cannot
 * tell the two apart.
 */

/** Mapped bus stops per square kilometre: count / area. */
export function mappedBusStopsPerKm2(p) {
  if (!p.area_km2) return 0;
  return p.bus_stops_in_district / p.area_km2;
}

/** Mapped bazaars per 100,000 residents: count / population * 100000. */
export function mappedBazaarsPer100k(p) {
  if (!p.official_population) return 0;
  return (p.bazaars_in_district / p.official_population) * 100000;
}

/* ── the six comparison dimensions ────────────────────────────────────────
 *
 * Each axis keeps its own real-world unit. Normalising all six to a unitless
 * 0-1 would make the lines draw correctly and the tick labels meaningless, so
 * the scale is per-axis and the labels stay in people, people/km², percent,
 * stops/km² and bazaars per 100k.
 */
export const DIMENSIONS = [
  {
    key: 'population',
    short: 'Pop.',
    unit: 'people',
    value: (p) => p.official_population,
    format: (v) => fmt.people(v),
    tick: (v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : String(Math.round(v))),
    speak: (v) => `${fmt.people(v)} residents`,
  },
  {
    key: 'density',
    short: 'Density',
    unit: 'people / km²',
    value: (p) => p.population_density_per_km2,
    format: (v) => fmt.density(v),
    tick: (v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : String(Math.round(v))),
    speak: (v) => `${fmt.people(v)} people per square kilometre`,
  },
  {
    key: 'metro',
    short: 'Metro',
    unit: '% access',
    value: (p) => p.metro_access_pct,
    format: (v) => fmt.pct(v),
    tick: (v) => `${Math.round(v)}%`,
    speak: (v) => `metro access ${v.toFixed(1)} percent`,
  },
  {
    key: 'bus',
    short: 'Bus',
    unit: '%',
    value: (p) => p.bus_only_pct,
    format: (v) => fmt.pct(v),
    tick: (v) => `${Math.round(v)}%`,
    speak: (v) => `bus-only ${v.toFixed(1)} percent`,
  },
  {
    key: 'busstops',
    short: 'Bus stops',
    // The unit line carries MAPPED so the qualifier sits on the axis itself,
    // not only in the panel footnote.
    unit: 'MAPPED / km²',
    derived: true,
    value: mappedBusStopsPerKm2,
    format: (v) => `${v.toFixed(1)} /km²`,
    tick: (v) => v.toFixed(v < 10 ? 1 : 0),
    speak: (v) => `${v.toFixed(1)} mapped bus stops per square kilometre`,
  },
  {
    key: 'bazaars',
    short: 'Bazaars',
    unit: 'MAPPED / 100k',
    derived: true,
    value: mappedBazaarsPer100k,
    format: (v) => `${v.toFixed(1)} /100k`,
    tick: (v) => v.toFixed(1),
    speak: (v) => `${v.toFixed(1)} mapped bazaars per hundred thousand residents`,
  },
];

/* ── comparison palette ───────────────────────────────────────────────────
 *
 * Deliberately not the semantic palette. Metro cyan, bus amber and underserved
 * slate each mean an access category everywhere else in this product; reusing
 * them here would say a pinned district *is* that category. These four are
 * chosen to stay legible on the dark ground and distinguishable from all three
 * semantic colours, and every one of them is also carried by a labelled chip,
 * because colour alone is not an accessible encoding.
 */
export const COMPARE_COLOURS = ['#e4eaf1', '#c98bdb', '#7ee787', '#f0a868'];

export function comparisonColour(name, comparison) {
  const i = comparison.indexOf(name);
  return i === -1 ? null : COMPARE_COLOURS[i % COMPARE_COLOURS.length];
}

/* ── accessible labels ────────────────────────────────────────────────────
 *
 * Twelve district entities per chart, each with one meaningful control. Not
 * hundreds of focusable SVG children.
 */
export function speakComposition(p) {
  return `${p.label}. Metro ${p.metro_access_pct.toFixed(1)} percent. `
    + `Bus-only ${p.bus_only_pct.toFixed(1)} percent. `
    + `Underserved ${p.underserved_pct.toFixed(1)} percent. `
    + 'Activate to select this district.';
}

export function speakScatter(p) {
  return `${p.label}. Density ${fmt.people(p.population_density_per_km2)} people per `
    + `square kilometre. Metro access ${p.metro_access_pct.toFixed(1)} percent. `
    + 'Activate to select this district.';
}

export function speakParallel(p) {
  return `${p.label} district profile. `
    + DIMENSIONS.map((d) => d.speak(d.value(p))).join('. ')
    + '. Activate to select this district.';
}

/* ── one tooltip vocabulary for all three charts ──────────────────────────
 *
 * Built with textContent only, through the same dom.js helpers the rest of the
 * product uses. Every one of these strings can originate in OpenStreetMap.
 */
export function tooltipComposition(p) {
  return [
    el('span', { class: 'tip-name', text: p.label }),
    el('div', { class: 'tip-grid' }, [
      cell('Metro', `${fmt.pct(p.metro_access_pct)} · ${fmt.people(p.metro_access_population)}`, 'is-metro'),
      cell('Bus-only', `${fmt.pct(p.bus_only_pct)} · ${fmt.people(p.bus_only_population)}`, 'is-bus'),
      cell('Underserved', `${fmt.pct(p.underserved_pct)} · ${fmt.people(p.underserved_population)}`, 'is-under'),
    ]),
  ];
}

export function tooltipScatter(p) {
  return [
    el('span', { class: 'tip-name', text: p.label }),
    el('div', { class: 'tip-grid' }, [
      cell('Density', fmt.density(p.population_density_per_km2)),
      cell('Population', fmt.people(p.official_population)),
      cell('Metro', fmt.pct(p.metro_access_pct), 'is-metro'),
      cell('Bus-only', fmt.pct(p.bus_only_pct), 'is-bus'),
      cell('Underserved', fmt.pct(p.underserved_pct), 'is-under'),
    ]),
  ];
}

export function tooltipParallel(p) {
  return [
    el('span', { class: 'tip-name', text: p.label }),
    el('div', { class: 'tip-grid' },
      DIMENSIONS.map((d) => cell(d.short, d.format(d.value(p))))),
  ];
}

/* ── responsive re-render ─────────────────────────────────────────────────
 *
 * The same shape the ranking already uses: re-render only when the container's
 * own box actually changes, with a band on the height so the height a render
 * sets cannot trigger the next render. Without that band a chart that sizes
 * itself to its panel oscillates forever.
 */
export function observeSize(host, render, { widthBand = 1, heightBand = 6 } = {}) {
  if (typeof ResizeObserver !== 'function') return () => {};
  let lastW = host.clientWidth;
  let lastH = host.clientHeight;
  let pending = null;
  const observer = new ResizeObserver(() => {
    if (pending) clearTimeout(pending);
    pending = setTimeout(() => {
      pending = null;
      if (Math.abs(host.clientWidth - lastW) > widthBand
          || Math.abs(host.clientHeight - lastH) > heightBand) {
        lastW = host.clientWidth;
        lastH = host.clientHeight;
        render();
      }
    }, 120);
  });
  observer.observe(host);
  return () => observer.disconnect();
}

/* Measure text the way the browser will draw it.
 *
 * The composition chart's label gutter has to hold the longest district name.
 * A width-percentage guess is wrong at some viewport by definition - at 320px
 * it clipped "Shaykhantakhur" - so the gutter is measured instead. One canvas
 * is reused for every call; it never touches the document.
 */
let measureCtx = null;

export function textWidth(text, font) {
  if (!measureCtx) {
    const canvas = document.createElement('canvas');
    measureCtx = canvas.getContext('2d');
  }
  if (!measureCtx) return text.length * 6.2;   // no canvas: fall back to an estimate
  measureCtx.font = font;
  return measureCtx.measureText(text).width;
}

/** Widest of many strings, in pixels, at one font. */
export function widestText(values, font) {
  return values.reduce((max, v) => Math.max(max, textWidth(String(v), font)), 0);
}

/** Clear an SVG host before a full re-render. */
export function resetHost(host) {
  d3.select(host).selectAll('svg').remove();
}
