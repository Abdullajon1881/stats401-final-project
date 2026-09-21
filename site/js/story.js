/* The narrative shell around the analytical workspace: the hero's current
 * answer, and the reconciliation of the two same-year metro-access numbers.
 *
 * Every figure here is read from site/data at runtime - the current snapshot
 * from city_summary.json, the standardized point from temporal_city.json - and
 * nothing here computes access. The inputs are checked before anything is
 * written, so a malformed file stops the page at the load-error path rather
 * than putting a wrong number in the hero.
 *
 * The two metrics are deliberately given identical treatment. They answer
 * different questions with different methods; neither is presented as the
 * better estimate, and their difference is never shown as a change in access.
 */

import { el, replace } from './dom.js';
import { fmt } from './data.js';
import { motion } from './ui.js';

const CITY_NUMBERS = [
  'metro_access_pct', 'metro_access_population', 'analysis_population',
  'walking_time_minutes', 'walking_speed_kmh',
];

function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function checkCity(city) {
  if (!city) throw new Error('city_summary.json is missing');
  const bad = CITY_NUMBERS.filter((key) => !isFiniteNumber(city[key]));
  if (bad.length > 0) {
    throw new Error(`city_summary.json has no usable value for ${bad.join(', ')}`);
  }
  if (typeof city.reference_period !== 'string' || city.reference_period === '') {
    throw new Error('city_summary.json has no reference period');
  }
}

/** The latest standardized record, chosen by year rather than by array order. */
export function latestStandardized(temporalCity) {
  const records = temporalCity && Array.isArray(temporalCity.records)
    ? temporalCity.records : [];
  const usable = records.filter((r) => r && Number.isInteger(r.year)
    && isFiniteNumber(r.metro_access_pct_standardized)
    && Number.isInteger(r.open_station_count));
  if (usable.length === 0) {
    throw new Error('temporal_city.json carries no usable standardized record');
  }
  const latest = usable.reduce((a, b) => (b.year > a.year ? b : a));
  if (usable.filter((r) => r.year === latest.year).length !== 1) {
    throw new Error(`temporal_city.json carries more than one record for ${latest.year}`);
  }
  return latest;
}

/* ── hero ─────────────────────────────────────────────────────────────── */
function renderHero(city) {
  replace(document.getElementById('hero-answer'), [
    el('span', { class: 'hero-pct', text: fmt.pct(city.metro_access_pct) }),
    ' ',
    el('span', {
      class: 'hero-answer-text',
      text: `of the analysed population is estimated to live within a modelled`
        + ` ${city.walking_time_minutes}-minute walk of metro access: about`
        + ` ${fmt.people(city.metro_access_population)} of`
        + ` ${fmt.people(city.analysis_population)} analysed residents.`,
    }),
  ]);

  const item = (key, value) => el('div', { class: 'hero-method-item' }, [
    el('dt', { text: key }),
    el('dd', { text: value }),
  ]);
  replace(document.getElementById('hero-method'), [
    item('Reference period', city.reference_period),
    item('Walking time', `${city.walking_time_minutes}-minute walk`),
    item('Walking speed', `${city.walking_speed_kmh} km/h`),
    item('Population', `${fmt.compact(city.analysis_population)} analysed residents`),
    item('Routing', `${city.snapping_method} pedestrian routing`),
  ]);
}

/* ── the two same-year numbers ────────────────────────────────────────── */
function metricCard({ id, label, value, measure, context, method, question }) {
  return el('article', { class: 'metric', 'aria-labelledby': `${id}-h` }, [
    el('h3', { id: `${id}-h`, class: 'metric-label', text: label }),
    el('p', { class: 'metric-value' }, [
      el('span', { class: 'metric-num', text: value }),
      el('span', { class: 'metric-measure', text: measure }),
    ]),
    el('p', { class: 'metric-context', text: context }),
    el('ul', { class: 'metric-method' }, method.map((text) => el('li', { text }))),
    el('p', { class: 'metric-question', text: question }),
  ]);
}

function renderBridge(city, latest) {
  // Name the year only when both figures really refer to it.
  const referenceYear = Number((/^(\d{4})/.exec(city.reference_period) || [])[1]);
  document.getElementById('bridge-h').textContent = referenceYear === latest.year
    ? `Why are there two ${latest.year} metro-access numbers?`
    : 'Why are there two metro-access numbers?';

  const measure = `of the analysed population within a modelled`
    + ` ${city.walking_time_minutes}-minute walk`;

  replace(document.getElementById('bridge-pair'), [
    metricCard({
      id: 'metric-current',
      label: 'Current snapshot',
      value: fmt.pct2(city.metro_access_pct),
      measure,
      context: `${city.reference_period} · current entrance-aware method`,
      method: [
        'Entrance-aware metro access: mapped entrances, station point only where none is mapped',
        'SIAT-calibrated current population',
        'Current pedestrian network',
      ],
      question: 'Answers: what does access look like now?',
    }),
    metricCard({
      id: 'metric-standardized',
      label: 'Standardized time series',
      value: fmt.pct2(latest.metro_access_pct_standardized),
      measure,
      context: `${latest.year} point · ${latest.temporal_reference} reference`
        + ` · ${fmt.int(latest.open_station_count)} stations open`,
      method: [
        'Station-centre proxy: fixed station coordinates, no entrances',
        'Annual WorldPop model weights, not SIAT-calibrated',
        'Standardized time-series method, network held fixed',
      ],
      question: 'Answers: how did access change under one comparable analytical frame?',
    }),
  ]);
}

/* ── moving into the workspace ────────────────────────────────────────── */
function wireCta() {
  const target = document.getElementById('current-access');
  document.getElementById('hero-cta').addEventListener('click', (event) => {
    event.preventDefault();
    target.scrollIntoView({ block: 'start', behavior: motion() });
    // Keyboard and screen-reader users land where they asked to go.
    target.focus({ preventScroll: true });
  });
}

/**
 * Check the story's inputs and render it. Throws, before writing anything, if
 * either source is unusable; the caller reveals the sections only on success.
 */
export function initStory(data) {
  checkCity(data.city);
  const latest = latestStandardized(data.temporalCity);
  renderHero(data.city);
  renderBridge(data.city, latest);
  wireCta();
}
