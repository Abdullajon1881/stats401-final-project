/* The standardized temporal chapter: how modelled metro walking access moved
 * across the annual series under one controlled analytical frame.
 *
 * Two stages, because D3 cannot measure a hidden container:
 *
 *   prepareTemporal(data)  before the page is revealed. Validates every record
 *                          it will use, cross-checks the four inputs against
 *                          one another, and returns a normalized model. Any
 *                          malformed or inconsistent input throws, so the page
 *                          falls to its load-error path instead of drawing a
 *                          partial or silently corrected history.
 *   initTemporal(model)    after the reveal. Measures, draws and wires.
 *
 * The chapter keeps its own active year. It is deliberately not in the shared
 * store: the map and district views above answer "what does access look like
 * now?", and moving through the years must never change them.
 *
 * Spatially it claims only which audited station-centre proxy points were in
 * the standardized source set by the active year, drawn inside today's
 * district outlines. It reads nothing but the district outlines and the station
 * history for that view: no line, street or service-area geometry exists for
 * any past year, so none is drawn or implied.
 *
 * Every figure is read from site/data. No year, share or count is written here.
 */

import { el, replace } from './dom.js';
import { fmt } from './data.js';

/* ── validation ───────────────────────────────────────────────────────── */
const isInt = (v) => Number.isInteger(v);
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const isText = (v) => typeof v === 'string' && v.trim() !== '';

function fail(file, message) {
  throw new Error(`${file} ${message}`);
}

function recordsOf(payload, file) {
  const records = payload && Array.isArray(payload.records) ? payload.records : null;
  if (!records || records.length === 0) fail(file, 'carries no records');
  return records;
}

/* Each rule is [field, test, description]. A record failing any one of them
 * invalidates the file: nothing is filtered or skipped. */
function checkRecords(records, file, rules) {
  records.forEach((record, i) => {
    if (!record || typeof record !== 'object') fail(file, `record ${i} is not a record`);
    for (const [field, test, description] of rules) {
      if (!test(record[field])) fail(file, `record ${i} has no ${description} ${field}`);
    }
  });
}

function uniqueByYear(records, file) {
  const byYear = new Map();
  for (const record of records) {
    if (byYear.has(record.year)) fail(file, `carries more than one record for ${record.year}`);
    byYear.set(record.year, record);
  }
  return byYear;
}

const CITY_RULES = [
  ['year', isInt, 'integer'],
  ['metro_state_id', isText, 'non-empty'],
  ['open_station_count', (v) => isInt(v) && v >= 0, 'non-negative integer'],
  ['population_modelled_available', (v) => isNum(v) && v >= 0, 'finite non-negative'],
  ['metro_access_population_standardized', (v) => isNum(v) && v >= 0, 'finite non-negative'],
  ['metro_access_pct_standardized', isNum, 'finite'],
  ['metro_access_pct_change_from_2015_pp', isNum, 'finite'],
  ['population_model_status', isText, 'non-empty'],
  ['population_projection_flag', (v) => typeof v === 'boolean', 'boolean'],
  ['worldpop_release', isText, 'non-empty'],
  ['temporal_reference', isText, 'non-empty'],
  ['geography_version', isText, 'non-empty'],
];

const EVENT_RULES = [
  ['year', isInt, 'integer'],
  ['previous_metro_state_id', isText, 'non-empty'],
  ['new_metro_state_id', isText, 'non-empty'],
  ['stations_before', (v) => isInt(v) && v >= 0, 'non-negative integer'],
  ['stations_after', (v) => isInt(v) && v >= 0, 'non-negative integer'],
  ['stations_added', (v) => isInt(v) && v > 0, 'positive integer'],
  ['station_names_added', isText, 'non-empty'],
  ['city_access_pct_previous_year', isNum, 'finite'],
  ['city_access_pct_event_year', isNum, 'finite'],
  ['city_access_change_pp', isNum, 'finite'],
  ['change_interpretation', isText, 'non-empty'],
];

const DIAGNOSTIC_RULES = [
  ['year', isInt, 'integer'],
  ['metro_state_id', isText, 'non-empty'],
  ['actual_standardized_pct', isNum, 'finite'],
  ['network_change_on_2015_population_pct', isNum, 'finite'],
  ['population_change_under_2015_network_pct', isNum, 'finite'],
];

// The recorded change must equal the difference of the two recorded shares,
// up to the rounding of the committed nine-decimal values.
const CHANGE_TOLERANCE = 1e-6;

function prepareCity(payload) {
  const file = 'temporal_city.json';
  const records = recordsOf(payload, file);
  checkRecords(records, file, CITY_RULES);
  const byYear = uniqueByYear(records, file);
  const years = [...byYear.keys()].sort((a, b) => a - b);
  years.forEach((year, i) => {
    if (year !== years[0] + i) fail(file, `skips a year: ${years[i - 1]} is followed by ${year}`);
  });
  const base = byYear.get(years[0]);
  if (base.metro_access_pct_change_from_2015_pp !== 0) {
    fail(file, `does not start at its baseline: the first year's change is not zero`);
  }
  return { byYear, years, series: years.map((y) => byYear.get(y)) };
}

function prepareStations(collection, manifest) {
  const file = 'metro_station_history.geojson';
  if (!collection || collection.type !== 'FeatureCollection' || !Array.isArray(collection.features)
      || collection.features.length === 0) {
    fail(file, 'is not a non-empty FeatureCollection');
  }
  const declared = manifest && manifest.layers && manifest.layers.metro_station_history;
  if (!declared || declared.features !== collection.features.length) {
    fail(file, 'does not carry the feature count the web manifest records');
  }
  const ids = new Set();
  return collection.features.map((feature, i) => {
    const p = feature && feature.properties;
    const g = feature && feature.geometry;
    if (!p || !g || g.type !== 'Point' || !Array.isArray(g.coordinates)
        || g.coordinates.length !== 2) {
      fail(file, `feature ${i} is not a point`);
    }
    const [lon, lat] = g.coordinates;
    if (!isNum(lon) || !isNum(lat) || Math.abs(lon) > 180 || Math.abs(lat) > 90) {
      fail(file, `feature ${i} has no finite longitude/latitude`);
    }
    if (!isText(p.station_id)) fail(file, `feature ${i} has no station_id`);
    if (ids.has(p.station_id)) fail(file, `repeats station_id ${p.station_id}`);
    ids.add(p.station_id);
    if (!isInt(p.opening_year)) fail(file, `feature ${i} has no integer opening_year`);
    if (!isText(p.station_name_current)) fail(file, `feature ${i} has no station_name_current`);
    if (!isText(p.line)) fail(file, `feature ${i} has no line`);
    return {
      id: p.station_id,
      name: p.station_name_current,
      line: p.line,
      openingYear: p.opening_year,
      coordinates: [lon, lat],
    };
  });
}

function openBy(stations, year) {
  return stations.filter((s) => s.openingYear <= year);
}

const sortedNames = (names) => names.slice().sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));

function prepareEvents(payload, city, stations) {
  const file = 'temporal_events.json';
  const records = recordsOf(payload, file);
  checkRecords(records, file, EVENT_RULES);
  const byYear = uniqueByYear(records, file);
  for (const [year, ev] of byYear) {
    const now = city.byYear.get(year);
    const before = city.byYear.get(year - 1);
    if (!now || !before) fail(file, `event ${year} has no consecutive pair of annual records`);
    if (ev.stations_after !== now.open_station_count
        || ev.stations_before !== before.open_station_count
        || ev.stations_added !== ev.stations_after - ev.stations_before) {
      fail(file, `event ${year} station counts do not reconcile with the annual series`);
    }
    if (ev.new_metro_state_id !== now.metro_state_id
        || ev.previous_metro_state_id !== before.metro_state_id) {
      fail(file, `event ${year} network states do not reconcile with the annual series`);
    }
    if (ev.city_access_pct_event_year !== now.metro_access_pct_standardized
        || ev.city_access_pct_previous_year !== before.metro_access_pct_standardized
        || Math.abs(ev.city_access_pct_event_year - ev.city_access_pct_previous_year
          - ev.city_access_change_pp) > CHANGE_TOLERANCE) {
      fail(file, `event ${year} shares do not reconcile with the annual series`);
    }
    const names = ev.station_names_added.split('|').map((n) => n.trim());
    const opened = stations.filter((s) => s.openingYear === year).map((s) => s.name);
    const a = sortedNames(names);
    const b = sortedNames(opened);
    if (names.length !== ev.stations_added || a.length !== b.length
        || a.some((name, i) => name !== b[i])) {
      fail(file, `event ${year} station names do not match the stations that opened that year`);
    }
  }
  // Complete in the other direction too: every change of source state in the
  // annual series is one of the events.
  city.years.slice(1).forEach((year) => {
    const changed = city.byYear.get(year).metro_state_id
      !== city.byYear.get(year - 1).metro_state_id;
    if (changed !== byYear.has(year)) {
      fail(file, `does not list exactly the years in which the source state changes (${year})`);
    }
  });
  return byYear;
}

function prepareDiagnostics(payload, city) {
  const file = 'temporal_counterfactual.json';
  const records = recordsOf(payload, file);
  checkRecords(records, file, DIAGNOSTIC_RULES);
  const byYear = uniqueByYear(records, file);
  if (byYear.size !== city.years.length || city.years.some((y) => !byYear.has(y))) {
    fail(file, 'does not cover exactly the years of the annual series');
  }
  const baseYear = city.years[0];
  const baseState = city.byYear.get(baseYear).metro_state_id;
  const baseNetworkValue = new Map();
  for (const year of city.years) {
    const row = byYear.get(year);
    const annual = city.byYear.get(year);
    if (row.actual_standardized_pct !== annual.metro_access_pct_standardized
        || row.metro_state_id !== annual.metro_state_id) {
      fail(file, `year ${year} does not match the annual standardized series`);
    }
    // The two properties the chapter's wording relies on, checked rather than
    // assumed: the network diagnostic is one value per source state, and the
    // population diagnostic is the actual series while the baseline state holds.
    const seen = baseNetworkValue.get(row.metro_state_id);
    if (seen === undefined) baseNetworkValue.set(row.metro_state_id, row.network_change_on_2015_population_pct);
    else if (seen !== row.network_change_on_2015_population_pct) {
      fail(file, `the network-state diagnostic varies within ${row.metro_state_id}`);
    }
    if (row.metro_state_id === baseState
        && row.population_change_under_2015_network_pct !== row.actual_standardized_pct) {
      fail(file, `year ${year} population diagnostic differs from the actual series in the baseline state`);
    }
  }
  const base = byYear.get(baseYear);
  if (base.network_change_on_2015_population_pct !== base.actual_standardized_pct
      || base.population_change_under_2015_network_pct !== base.actual_standardized_pct) {
    fail(file, 'does not share one baseline value across the three series');
  }
  return byYear;
}

function prepareDistricts(collection) {
  if (!collection || !Array.isArray(collection.features) || collection.features.length === 0
      || collection.features.some((f) => !f || !f.geometry
        || !['Polygon', 'MultiPolygon'].includes(f.geometry.type))) {
    fail('districts.geojson', 'is not a non-empty set of district polygons');
  }
  return collection.features;
}

/**
 * Validate and cross-check every temporal input, and return the chapter's
 * model. Throws on anything malformed or inconsistent; renders nothing.
 */
export function prepareTemporal(data) {
  const city = prepareCity(data.temporalCity);
  const stations = prepareStations(data.stationHistory, data.manifest);
  for (const year of city.years) {
    const open = openBy(stations, year).length;
    if (open !== city.byYear.get(year).open_station_count) {
      fail('metro_station_history.geojson', `opens ${open} stations by ${year}, `
        + `but the annual series records ${city.byYear.get(year).open_station_count}`);
    }
  }
  const events = prepareEvents(data.temporalEvents, city, stations);
  const diagnostics = prepareDiagnostics(data.temporalCounterfactual, city);
  return {
    city,
    stations,
    events,
    diagnostics,
    districts: prepareDistricts(data.districts),
    minYear: city.years[0],
    maxYear: city.years[city.years.length - 1],
  };
}

/* ── shared chart pieces ──────────────────────────────────────────────── */
const SERIES = [
  {
    key: 'actual_standardized_pct', cls: 'cf-actual', symbol: 'symbolCircle',
    label: () => 'Actual standardized',
  },
  {
    key: 'network_change_on_2015_population_pct', cls: 'cf-network', symbol: 'symbolSquare',
    label: (base) => `Changing network state, ${base} population weights`,
  },
  {
    key: 'population_change_under_2015_network_pct', cls: 'cf-population', symbol: 'symbolTriangle',
    label: (base) => `Changing population weights, ${base} network state`,
  },
];

const MARGIN = { top: 26, right: 16, bottom: 30, left: 44 };

function yearAxis(x, width, years) {
  // Every year where there is room; otherwise every second one, with the last
  // year kept and its crowded neighbour dropped.
  const every = width < 460 ? 2 : 1;
  const last = years.length - 1;
  const ticks = years.filter((y, i) => i === last
    || (i % every === 0 && !(every > 1 && i === last - 1)));
  return d3.axisBottom(x).tickValues(ticks).tickFormat(d3.format('d')).tickSizeOuter(0);
}

function pctAxis(y, width) {
  return d3.axisLeft(y).ticks(width < 460 ? 4 : 5).tickFormat((v) => `${v}%`)
    .tickSize(-width).tickSizeOuter(0);
}

function chartFrame(host, height, label) {
  const width = Math.max(260, Math.floor(host.clientWidth));
  const svg = d3.select(host).selectAll('svg').data([null]).join('svg')
    .attr('width', width).attr('height', height)
    .attr('viewBox', `0 0 ${width} ${height}`)
    .attr('role', 'img').attr('aria-label', label);
  svg.selectAll('*').remove();
  return { svg, width, innerW: width - MARGIN.left - MARGIN.right,
    innerH: height - MARGIN.top - MARGIN.bottom };
}

/* Redraw a view when its container really changes width. */
function onWidthChange(host, draw) {
  let last = host.clientWidth;
  if (typeof ResizeObserver === 'undefined') return;
  new ResizeObserver((entries) => {
    const width = Math.floor(entries[0].contentRect.width);
    if (width !== last) { last = width; draw(); }
  }).observe(host);
}

/* ── the chapter ──────────────────────────────────────────────────────── */
/**
 * Draw and wire the chapter. Call only once #temporal-story is visible.
 */
export function initTemporal(model) {
  const { city, events, diagnostics, stations, minYear, maxYear } = model;
  let activeYear = minYear;

  const hosts = {
    heading: document.getElementById('temporal-h'),
    range: document.getElementById('year-range'),
    output: document.getElementById('year-output'),
    prev: document.getElementById('year-prev'),
    next: document.getElementById('year-next'),
    live: document.getElementById('year-live'),
    summary: document.getElementById('temporal-summary'),
    context: document.getElementById('temporal-context'),
    line: document.getElementById('temporal-line'),
    lineNote: document.getElementById('temporal-line-note'),
    map: document.getElementById('temporal-map'),
    events: document.getElementById('temporal-events'),
    cf: document.getElementById('temporal-cf'),
    cfLegend: document.getElementById('cf-legend'),
    cfSummary: document.getElementById('cf-summary'),
    cfExplain: document.getElementById('cf-explain'),
  };

  hosts.heading.textContent = `How did standardized metro access change from ${minYear} to ${maxYear}?`;
  Object.assign(hosts.range, { min: String(minYear), max: String(maxYear), step: '1',
    value: String(minYear) });

  const flagged = city.series.filter((r) => r.population_projection_flag);
  hosts.lineNote.textContent = flagged.length === 0
    ? 'Dashed guides mark years in which the station source set changed.'
    : 'Dashed guides mark years in which the station source set changed. A hollow point marks '
      + `a year whose population weight is flagged as a projection (${flagged.map((r) => r.year).join(', ')}).`;

  /* ── view 1: access over time ─────────────────────────────────────── */
  let line = null;
  function drawLine() {
    const height = hosts.line.clientWidth < 460 ? 230 : 270;
    const first = city.series[0];
    const last = city.series[city.series.length - 1];
    const f = chartFrame(hosts.line, height,
      `Line chart of standardized metro access by year, ${minYear} to ${maxYear}: `
      + `${fmt.pct2(first.metro_access_pct_standardized)} to `
      + `${fmt.pct2(last.metro_access_pct_standardized)}.`);
    const x = d3.scaleLinear().domain([minYear, maxYear]).range([0, f.innerW]);
    const top = d3.max(city.series, (r) => r.metro_access_pct_standardized);
    const y = d3.scaleLinear().domain([0, top * 1.18]).nice().range([f.innerH, 0]);
    const g = f.svg.append('g').attr('transform', `translate(${MARGIN.left},${MARGIN.top})`);

    g.append('g').attr('class', 'tc-grid').call(pctAxis(y, f.innerW))
      .call((axis) => axis.select('.domain').remove());
    g.append('g').attr('class', 'tc-axis').attr('transform', `translate(0,${f.innerH})`)
      .call(yearAxis(x, f.innerW, city.years));
    g.append('text').attr('class', 'tc-axis-title').attr('x', -MARGIN.left + 2).attr('y', -12)
      .text('Standardized metro access (%)');

    const eventGroup = g.append('g').attr('class', 'tc-events');
    for (const [year, ev] of events) {
      eventGroup.append('line').attr('class', 'tc-event-guide')
        .attr('x1', x(year)).attr('x2', x(year)).attr('y1', 0).attr('y2', f.innerH);
      eventGroup.append('text').attr('class', 'tc-event-label')
        .attr('x', x(year) + 3).attr('y', 9).text(`+${ev.stations_added}`);
    }

    g.append('path').datum(city.series).attr('class', 'tc-line')
      .attr('d', d3.line().x((r) => x(r.year)).y((r) => y(r.metro_access_pct_standardized)));
    const marker = g.append('line').attr('class', 'tc-marker').attr('y1', 0).attr('y2', f.innerH);
    const points = g.append('g').selectAll('circle').data(city.series).join('circle')
      .attr('class', (r) => (r.population_projection_flag ? 'tc-point is-projection' : 'tc-point'))
      .attr('cx', (r) => x(r.year)).attr('cy', (r) => y(r.metro_access_pct_standardized))
      .attr('r', 3.5);
    line = { x, points, marker };
  }

  function syncLine() {
    if (!line) return;
    line.marker.attr('x1', line.x(activeYear)).attr('x2', line.x(activeYear));
    line.points.classed('is-active', (r) => r.year === activeYear)
      .attr('r', (r) => (r.year === activeYear ? 6 : 3.5))
      .filter((r) => r.year === activeYear).raise();
  }

  /* ── view 2: station source state ─────────────────────────────────── */
  // d3-geo works on the sphere, where a ring wound the other way encloses the
  // rest of the globe. Rings are rewound so each district is its own small area.
  const outlines = model.districts.map((feature) => {
    const fix = (polygon) => (d3.geoArea({ type: 'Polygon', coordinates: polygon }) > 2 * Math.PI
      ? polygon.map((ring) => ring.slice().reverse()) : polygon);
    const geometry = feature.geometry.type === 'Polygon'
      ? { type: 'Polygon', coordinates: fix(feature.geometry.coordinates) }
      : { type: 'MultiPolygon', coordinates: feature.geometry.coordinates.map(fix) };
    return { type: 'Feature', properties: {}, geometry };
  });
  const outlineCollection = { type: 'FeatureCollection', features: outlines };

  let map = null;
  function drawMap() {
    const width = Math.max(260, Math.floor(hosts.map.clientWidth));
    // Never taller than most of the screen, so a short landscape view keeps
    // the whole map in sight.
    const height = Math.round(Math.min(width * 0.92, 440, window.innerHeight * 0.78));
    const svg = d3.select(hosts.map).selectAll('svg').data([null]).join('svg')
      .attr('width', width).attr('height', height).attr('viewBox', `0 0 ${width} ${height}`)
      .attr('role', 'img');
    svg.selectAll('*').remove();
    const projection = d3.geoMercator().fitExtent([[10, 10], [width - 10, height - 10]],
      outlineCollection);
    const path = d3.geoPath(projection);
    svg.append('g').selectAll('path').data(outlines).join('path')
      .attr('class', 'tm-district').attr('d', path);
    const layer = svg.append('g').attr('class', 'tm-stations');
    map = { svg, projection, layer };
  }

  function syncMap() {
    if (!map) return;
    const open = openBy(stations, activeYear);
    const opened = open.filter((s) => s.openingYear === activeYear);
    map.layer.selectAll('circle').data(open, (s) => s.id).join('circle')
      .attr('class', (s) => (s.openingYear === activeYear ? 'tm-station is-new' : 'tm-station'))
      .attr('cx', (s) => map.projection(s.coordinates)[0])
      .attr('cy', (s) => map.projection(s.coordinates)[1])
      .attr('r', (s) => (s.openingYear === activeYear ? 5.5 : 3.4));
    map.layer.selectAll('circle.is-new').raise();
    map.svg.attr('aria-label', `Selected year ${activeYear}. ${fmt.int(open.length)} metro `
      + 'stations open in the standardized source state'
      + (opened.length > 0 ? `, ${fmt.int(opened.length)} of them opened that year.` : '.'));
  }

  /* ── view 3: descriptive diagnostics ──────────────────────────────── */
  const rows = city.years.map((year) => diagnostics.get(year));
  replace(hosts.cfExplain, [
    el('p', {
      text: `The network-state line keeps the ${minYear} population weights and changes only `
        + 'the station source set, so by construction it moves only in years when that set '
        + `changes. The population line keeps the ${minYear} network state and changes only the `
        + 'annual WorldPop model weights.',
    }),
    el('p', {
      class: 'cf-caution',
      text: 'These are comparison diagnostics, not components that add up to the actual '
        + 'series, and they do not establish what caused any change.',
    }),
  ]);
  replace(hosts.cfLegend, SERIES.map((s) => el('span', { class: 'cf-key' }, [
    sampleLine(s.cls),
    s.label(minYear),
  ])));

  let cf = null;
  function drawDiagnostics() {
    const height = hosts.cf.clientWidth < 460 ? 230 : 270;
    const f = chartFrame(hosts.cf, height,
      `Three descriptive diagnostic series by year, ${minYear} to ${maxYear}: `
      + SERIES.map((s) => s.label(minYear)).join('; ') + '.');
    const x = d3.scaleLinear().domain([minYear, maxYear]).range([0, f.innerW]);
    const top = d3.max(rows, (r) => d3.max(SERIES, (s) => r[s.key]));
    const y = d3.scaleLinear().domain([0, top * 1.18]).nice().range([f.innerH, 0]);
    const g = f.svg.append('g').attr('transform', `translate(${MARGIN.left},${MARGIN.top})`);
    g.append('g').attr('class', 'tc-grid').call(pctAxis(y, f.innerW))
      .call((axis) => axis.select('.domain').remove());
    g.append('g').attr('class', 'tc-axis').attr('transform', `translate(0,${f.innerH})`)
      .call(yearAxis(x, f.innerW, city.years));
    g.append('text').attr('class', 'tc-axis-title').attr('x', -MARGIN.left + 2).attr('y', -12)
      .text('Standardized metro access (%)');
    const marker = g.append('line').attr('class', 'tc-marker').attr('y1', 0).attr('y2', f.innerH);
    for (const s of SERIES) {
      g.append('path').datum(rows).attr('class', `cf-line ${s.cls}`)
        .attr('d', d3.line().x((r) => x(r.year)).y((r) => y(r[s.key])));
    }
    const symbols = g.append('g').selectAll('path').data(SERIES).join('path')
      .attr('class', (s) => `cf-symbol ${s.cls}`)
      .attr('d', (s) => d3.symbol(d3[s.symbol], 46)());
    cf = { x, y, marker, symbols };
  }

  function syncDiagnostics() {
    if (!cf) return;
    const row = diagnostics.get(activeYear);
    cf.marker.attr('x1', cf.x(activeYear)).attr('x2', cf.x(activeYear));
    cf.symbols.attr('transform', (s) => `translate(${cf.x(activeYear)},${cf.y(row[s.key])})`);
  }

  function renderDiagnosticSummary() {
    const row = diagnostics.get(activeYear);
    replace(hosts.cfSummary, el('dl', { class: 'cf-values' }, SERIES.map((s) => el('div', {
      class: 'cf-value',
    }, [
      el('dt', {}, [sampleLine(s.cls), s.label(minYear)]),
      el('dd', { text: fmt.pct2(row[s.key]) }),
    ]))));
  }

  /* ── events ───────────────────────────────────────────────────────── */
  const eventButtons = new Map();
  replace(hosts.events, [...events.values()].sort((a, b) => a.year - b.year).map((ev) => {
    const names = ev.station_names_added.split('|').map((n) => n.trim());
    const button = el('button', {
      type: 'button', class: 'btn btn--sm tev-show', 'aria-pressed': 'false',
      onclick: () => select(ev.year),
    }, `Show ${ev.year}`);
    eventButtons.set(ev.year, button);
    return el('article', { class: 'tev', 'aria-labelledby': `tev-${ev.year}` }, [
      el('div', { class: 'tev-head' }, [
        el('h4', { id: `tev-${ev.year}`, class: 'tev-year', text: String(ev.year) }),
        button,
      ]),
      el('p', {
        class: 'tev-count',
        text: `+${fmt.int(ev.stations_added)} stations · ${fmt.int(ev.stations_before)} → `
          + `${fmt.int(ev.stations_after)}`,
      }),
      el('p', {
        class: 'tev-change',
        text: `${fmt.pp(ev.city_access_change_pp)} ${ev.change_interpretation}, `
          + `${ev.year - 1} to ${ev.year}`,
      }),
      el('details', { class: 'tev-names' }, [
        el('summary', { text: `Stations added (${fmt.int(names.length)})` }),
        el('ul', {}, names.map((name) => el('li', { text: name }))),
      ]),
    ]);
  }));

  /* ── selected-year text ───────────────────────────────────────────── */
  function renderSummary() {
    const r = city.byYear.get(activeYear);
    const isBase = activeYear === minYear;
    const item = (key, value) => el('div', { class: 'tsum-item' }, [
      el('dt', { text: key }), el('dd', { text: value }),
    ]);
    const nodes = [
      el('dl', { class: 'tsum-grid' }, [
        item('Year', String(activeYear)),
        item('Standardized metro access', fmt.pct2(r.metro_access_pct_standardized)),
        item('Open stations', fmt.int(r.open_station_count)),
        item('Modelled population', fmt.compact(r.population_modelled_available)),
        item(`Change from ${minYear}`, isBase ? 'Baseline year'
          : fmt.pp(r.metro_access_pct_change_from_2015_pp)),
      ]),
      el('p', {
        class: 'tsum-meta',
        text: `Population weights: ${r.population_model_status.replace(/_/g, ' ')}, WorldPop `
          + `${r.worldpop_release}, ${r.temporal_reference} reference.`,
      }),
    ];
    if (r.population_projection_flag) {
      nodes.push(el('p', {
        class: 'tsum-flag',
        text: `Population weight flagged as projection for ${activeYear}.`,
      }));
    }
    replace(hosts.summary, nodes);

    const ev = events.get(activeYear);
    let context;
    if (isBase) {
      context = `Baseline year: the ${fmt.int(r.open_station_count)} stations open in `
        + `${activeYear} form the starting source set.`;
    } else if (ev) {
      context = `The station source set changed in ${activeYear}: ${fmt.int(ev.stations_added)} `
        + `stations were added (${fmt.int(ev.stations_before)} → ${fmt.int(ev.stations_after)}). `
        + `The ${fmt.pp(ev.city_access_change_pp)} move from ${activeYear - 1} is a `
        + `${ev.change_interpretation}: the station set and the annual population weights `
        + 'both changed, so the move cannot be attributed to the new stations alone.';
    } else {
      context = `The station source set is unchanged from ${activeYear - 1} `
        + `(${fmt.int(r.open_station_count)} stations). Within the standardized model the `
        + 'percentage can still move, because the annual WorldPop model weights change.';
    }
    hosts.context.textContent = context;
  }

  function select(year, { announce = true } = {}) {
    activeYear = Math.min(maxYear, Math.max(minYear, year));
    hosts.range.value = String(activeYear);
    hosts.output.textContent = String(activeYear);
    hosts.prev.disabled = activeYear === minYear;
    hosts.next.disabled = activeYear === maxYear;
    for (const [year2, button] of eventButtons) {
      button.setAttribute('aria-pressed', String(year2 === activeYear));
    }
    renderSummary();
    renderDiagnosticSummary();
    syncLine();
    syncMap();
    syncDiagnostics();
    if (announce) {
      const r = city.byYear.get(activeYear);
      hosts.live.textContent = `${activeYear}: standardized metro access `
        + `${fmt.pct2(r.metro_access_pct_standardized)}, ${fmt.int(r.open_station_count)} `
        + 'stations open.';
    }
  }

  hosts.range.addEventListener('input', () => select(Number(hosts.range.value)));
  hosts.prev.addEventListener('click', () => select(activeYear - 1));
  hosts.next.addEventListener('click', () => select(activeYear + 1));

  drawLine();
  drawMap();
  drawDiagnostics();
  select(minYear, { announce: false });

  onWidthChange(hosts.line, () => { drawLine(); syncLine(); });
  onWidthChange(hosts.map, () => { drawMap(); syncMap(); });
  onWidthChange(hosts.cf, () => { drawDiagnostics(); syncDiagnostics(); });
}

/* A short line sample in a series' own stroke, for legends. */
function sampleLine(cls) {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('class', 'cf-sample');
  svg.setAttribute('width', '26');
  svg.setAttribute('height', '10');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const stroke = document.createElementNS(NS, 'line');
  stroke.setAttribute('class', `cf-line ${cls}`);
  stroke.setAttribute('x1', '1');
  stroke.setAttribute('x2', '25');
  stroke.setAttribute('y1', '5');
  stroke.setAttribute('y2', '5');
  svg.append(stroke);
  return svg;
}
