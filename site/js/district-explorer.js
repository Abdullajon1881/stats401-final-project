/* Linked district explorer.  This module consumes already-audited browser
 * artifacts; it validates and displays them but never recomputes accessibility. */
import { fmt } from './data.js';
import * as store from './state.js';
import { el, replace } from './dom.js';

const PCT_TOL = 1e-5;
const VALUE_TOL = 1e-5;
const PROFILE = [
  ['Metro', 'metro_access_pct', 'metro_access_pct', 'metro'],
  ['Healthcare', 'healthcare_10min_pct', 'healthcare_10min_pct', 'healthcare'],
  ['Education', 'education_10min_pct', 'education_10min_pct', 'education'],
  ['Bazaars', 'bazaar_10min_pct', 'bazaar_10min_pct', 'bazaar'],
  ['Healthcare + education overlap', 'healthcare_and_education_10min_pct',
    'healthcare_and_education_10min_pct', 'overlap'],
];
const URBAN_NUMBERS = [
  'official_population', 'population', 'area_km2', 'population_density_per_km2',
  'metro_access_pct', 'bus_only_pct', 'underserved_pct', 'metro_stations',
  'metro_access_points', 'bus_stops', 'bus_stops_per_10k', 'hospitals', 'clinics',
  'healthcare_total', 'healthcare_facilities_per_10k', 'healthcare_10min_population',
  'healthcare_10min_pct', 'schools', 'colleges', 'universities', 'kindergartens',
  'education_total', 'education_facilities_per_10k', 'education_10min_population',
  'education_10min_pct', 'bazaars', 'bazaars_per_10k', 'bazaar_10min_population',
  'bazaar_10min_pct', 'healthcare_and_education_10min_population',
  'healthcare_and_education_10min_pct', 'walk_network_km',
  'walk_network_density_km_per_km2',
];

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const isText = (v) => typeof v === 'string' && v.trim() !== '';
const near = (a, b, tolerance = VALUE_TOL) => Math.abs(a - b) <= tolerance;
function fail(message) { throw new Error(`district explorer: ${message}`); }
function number(row, field, label) {
  if (!isNum(row[field])) fail(`${label} has no finite numeric ${field}`);
  return row[field];
}
function pct(row, field, label) {
  const value = number(row, field, label);
  if (value < 0 || value > 100) fail(`${label} has ${field} outside 0–100`);
  return value;
}
function sum(rows, field) { return rows.reduce((total, row) => total + row[field], 0); }
function manifestLayer(manifest, key, count) {
  const layer = manifest && manifest.layers && manifest.layers[key];
  if (!layer || layer.role !== 'analytical' || layer.features !== count) {
    fail(`manifest ${key} does not record ${count} analytical records`);
  }
}
function sameSet(a, b) {
  return a.size === b.size && [...a].every((value) => b.has(value));
}

/** Validate all explorer inputs and make an order-independent display model. */
export function prepareDistrictExplorer(data) {
  const geoFeatures = data.districts && Array.isArray(data.districts.features)
    ? data.districts.features : null;
  if (!geoFeatures || geoFeatures.length === 0) fail('districts.geojson has no features');
  const labels = new Map();
  const geoByName = new Map();
  for (const feature of geoFeatures) {
    const p = feature && feature.properties;
    if (!p || !isText(p.district_name) || !isText(p.label) || geoByName.has(p.district_name)) {
      fail('districts.geojson has invalid or duplicate district identity');
    }
    geoByName.set(p.district_name, p);
    labels.set(p.district_name, p.label);
  }

  const urbanPayload = data.urbanDistrict;
  const urbanRows = urbanPayload && Array.isArray(urbanPayload.records) ? urbanPayload.records : null;
  if (!urbanPayload || urbanPayload.role !== 'analytical' || !urbanRows || !urbanRows.length) {
    fail('urban_dimensions_district.json is not a non-empty analytical record set');
  }
  manifestLayer(data.manifest, 'urban_dimensions_district', urbanRows.length);
  const urbanByName = new Map();
  for (const row of urbanRows) {
    if (!row || !isText(row.district_name)) fail('urban district row has no district_name');
    if (urbanByName.has(row.district_name)) fail(`duplicate urban district ${row.district_name}`);
    for (const field of URBAN_NUMBERS) number(row, field, `urban ${row.district_name}`);
    for (const field of PROFILE.slice(0).map((item) => item[1])
      .concat(['bus_only_pct', 'underserved_pct'])) pct(row, field, `urban ${row.district_name}`);
    urbanByName.set(row.district_name, row);
  }
  if (!sameSet(new Set(urbanByName.keys()), new Set(geoByName.keys()))) {
    fail('urban district names do not exactly match districts.geojson');
  }
  for (const [name, row] of urbanByName) {
    const geo = geoByName.get(name);
    const comparisons = [
      ['official_population', 'official_population'], ['population', 'calibrated_population'],
      ['metro_access_pct', 'metro_access_pct'], ['bus_only_pct', 'bus_only_pct'],
      ['underserved_pct', 'underserved_pct'], ['metro_stations', 'metro_stations_in_district'],
      ['metro_access_points', 'metro_access_points_in_district'], ['bus_stops', 'bus_stops_in_district'],
      ['bazaars', 'bazaars_in_district'],
    ];
    for (const [urbanField, geoField] of comparisons) {
      if (!near(row[urbanField], geo[geoField])) fail(`${name} ${urbanField} disagrees with districts.geojson`);
    }
    if (!near(row.metro_access_pct + row.bus_only_pct + row.underserved_pct, 100, PCT_TOL)) {
      fail(`${name} current transit composition does not total 100`);
    }
    for (const [population, percentage] of [
      ['healthcare_10min_population', 'healthcare_10min_pct'],
      ['education_10min_population', 'education_10min_pct'], ['bazaar_10min_population', 'bazaar_10min_pct'],
      ['healthcare_and_education_10min_population', 'healthcare_and_education_10min_pct'],
    ]) {
      if (row.population > 0 && !near(row[population] / row.population * 100, row[percentage], PCT_TOL)) {
        fail(`${name} ${percentage} disagrees with its stored population`);
      }
    }
    if (row.healthcare_and_education_10min_population > row.healthcare_10min_population
        || row.healthcare_and_education_10min_population > row.education_10min_population
        || row.healthcare_and_education_10min_pct > row.healthcare_10min_pct
        || row.healthcare_and_education_10min_pct > row.education_10min_pct) fail(`${name} overlap exceeds a component`);
    if (row.healthcare_total !== row.hospitals + row.clinics) fail(`${name} healthcare supply does not add up`);
    if (row.education_total !== row.schools + row.colleges + row.universities + row.kindergartens) fail(`${name} education supply does not add up`);
    for (const [count, rate] of [
      ['bus_stops', 'bus_stops_per_10k'], ['healthcare_total', 'healthcare_facilities_per_10k'],
      ['education_total', 'education_facilities_per_10k'], ['bazaars', 'bazaars_per_10k'],
    ]) {
      if (!near(row[count] / row.official_population * 10000, row[rate], PCT_TOL)) fail(`${name} ${rate} does not reconcile`);
    }
    if (!near(row.walk_network_km / row.area_km2, row.walk_network_density_km_per_km2, PCT_TOL)) {
      fail(`${name} mapped walk-network density does not reconcile`);
    }
  }
  const city = data.urbanCity && data.urbanCity.record;
  if (!data.urbanCity || data.urbanCity.role !== 'analytical' || !city) fail('urban city record is unavailable');
  for (const field of ['population_total', 'healthcare_10min_population', 'education_10min_population',
    'bazaar_10min_population', 'healthcare_and_education_10min_population', 'walk_network_km',
    'healthcare_facilities_in_analysis_districts', 'education_facilities_in_analysis_districts',
    'bazaar_facilities_in_analysis_districts']) number(city, field, 'urban city');
  for (const field of ['healthcare_10min_pct', 'education_10min_pct', 'bazaar_10min_pct',
    'healthcare_and_education_10min_pct']) pct(city, field, 'urban city');
  for (const [population, percentage] of [
    ['healthcare_10min_population', 'healthcare_10min_pct'],
    ['education_10min_population', 'education_10min_pct'], ['bazaar_10min_population', 'bazaar_10min_pct'],
    ['healthcare_and_education_10min_population', 'healthcare_and_education_10min_pct'],
  ]) if (!near(city[population] / city.population_total * 100, city[percentage], PCT_TOL)) {
    fail(`urban city ${percentage} disagrees with its stored population`);
  }
  if (city.healthcare_and_education_10min_population > city.healthcare_10min_population
      || city.healthcare_and_education_10min_population > city.education_10min_population
      || city.healthcare_and_education_10min_pct > city.healthcare_10min_pct
      || city.healthcare_and_education_10min_pct > city.education_10min_pct) fail('urban city overlap exceeds a component');
  for (const [districtField, cityField] of [
    ['population', 'population_total'], ['healthcare_10min_population', 'healthcare_10min_population'],
    ['education_10min_population', 'education_10min_population'], ['bazaar_10min_population', 'bazaar_10min_population'],
    ['healthcare_and_education_10min_population', 'healthcare_and_education_10min_population'],
    ['walk_network_km', 'walk_network_km'], ['healthcare_total', 'healthcare_facilities_in_analysis_districts'],
    ['education_total', 'education_facilities_in_analysis_districts'], ['bazaars', 'bazaar_facilities_in_analysis_districts'],
  ]) if (!near(sum(urbanRows, districtField), city[cityField])) fail(`urban city ${cityField} does not aggregate from districts`);

  const temporalPayload = data.temporalDistrict;
  const temporalRows = temporalPayload && Array.isArray(temporalPayload.records) ? temporalPayload.records : null;
  const cityRows = data.temporalCity && Array.isArray(data.temporalCity.records) ? data.temporalCity.records : null;
  if (!temporalPayload || temporalPayload.role !== 'analytical' || !temporalRows || !temporalRows.length || !cityRows || !cityRows.length) {
    fail('temporal district or city records are unavailable');
  }
  manifestLayer(data.manifest, 'temporal_district', temporalRows.length);
  const cityByYear = new Map();
  for (const row of cityRows) {
    if (!Number.isInteger(row.year) || cityByYear.has(row.year)) fail('temporal city years are invalid');
    cityByYear.set(row.year, row);
  }
  const years = [...cityByYear.keys()].sort((a, b) => a - b);
  const temporalByName = new Map(); const ids = new Map(); const namesById = new Map(); const temporalKeys = new Set();
  for (const row of temporalRows) {
    const label = `temporal ${row && row.district_name ? row.district_name : 'row'}`;
    if (!row || !isText(row.district_name) || !Number.isInteger(row.year) || !Number.isInteger(row.district_id)) fail(`${label} has invalid identity`);
    const key = `${row.district_name}\u0000${row.year}`;
    if (temporalKeys.has(key)) fail(`duplicate temporal district/year ${row.district_name}/${row.year}`);
    temporalKeys.add(key);
    if (!cityByYear.has(row.year)) fail(`${label} uses a year absent from temporal city`);
    for (const field of ['population_modelled_available', 'population_growth_pct_from_2015',
      'metro_access_population_standardized', 'metro_access_pct_standardized',
      'metro_access_pct_change_from_2015_pp']) number(row, field, label);
    if (row.population_modelled_available < 0 || row.metro_access_population_standardized < 0) fail(`${label} has negative population`);
    pct(row, 'metro_access_pct_standardized', label);
    if (!isText(row.metro_state_id) || !Number.isInteger(row.open_station_count) || row.open_station_count < 0
        || !isText(row.population_model_status) || typeof row.population_projection_flag !== 'boolean'
        || !isText(row.geography_version)) fail(`${label} has malformed temporal fields`);
    if (ids.has(row.district_name) && ids.get(row.district_name) !== row.district_id) fail(`${label} has unstable district_id`);
    if (namesById.has(row.district_id) && namesById.get(row.district_id) !== row.district_name) fail(`${label} shares district_id`);
    ids.set(row.district_name, row.district_id); namesById.set(row.district_id, row.district_name);
    if (!temporalByName.has(row.district_name)) temporalByName.set(row.district_name, []);
    temporalByName.get(row.district_name).push(row);
  }
  if (!sameSet(new Set(temporalByName.keys()), new Set(geoByName.keys()))) fail('temporal district names do not match analysis districts');
  for (const [name, rows] of temporalByName) {
    rows.sort((a, b) => a.year - b.year);
    if (rows.length !== years.length || rows.some((row, i) => row.year !== years[i])) fail(`${name} does not cover every city year`);
    const base = rows[0];
    if (!near(base.population_growth_pct_from_2015, 0) || !near(base.metro_access_pct_change_from_2015_pp, 0)) fail(`${name} baseline fields are not zero`);
    for (const row of rows) {
      if (row.population_modelled_available > 0 && !near(row.metro_access_population_standardized / row.population_modelled_available * 100, row.metro_access_pct_standardized, PCT_TOL)) fail(`${name}/${row.year} temporal pct disagrees with population`);
      if (!near((row.population_modelled_available / base.population_modelled_available - 1) * 100, row.population_growth_pct_from_2015, PCT_TOL)
          || !near(row.metro_access_pct_standardized - base.metro_access_pct_standardized, row.metro_access_pct_change_from_2015_pp, PCT_TOL)) fail(`${name}/${row.year} temporal change fields do not reconcile`);
      const cityRow = cityByYear.get(row.year);
      for (const field of ['metro_state_id', 'open_station_count', 'population_projection_flag', 'geography_version']) {
        if (row[field] !== cityRow[field]) fail(`${name}/${row.year} ${field} differs from temporal city`);
      }
    }
  }
  for (const year of years) {
    const rows = temporalRows.filter((row) => row.year === year);
    const cityRow = cityByYear.get(year);
    const population = sum(rows, 'population_modelled_available');
    const access = sum(rows, 'metro_access_population_standardized');
    if (!near(population, cityRow.population_modelled_available) || !near(access, cityRow.metro_access_population_standardized)
        || !near(access / population * 100, cityRow.metro_access_pct_standardized, PCT_TOL)) fail(`temporal city aggregates do not reconcile for ${year}`);
  }
  const globalHistoryTop = Math.max(...temporalRows.map((r) => r.metro_access_pct_standardized),
    ...cityRows.map((r) => r.metro_access_pct_standardized));
  if (!data.city) fail('current city metro reference is unavailable');
  pct(data.city, 'metro_access_pct', 'current city');
  return { urbanByName, temporalByName, labels, years, cityHistory: years.map((year) => cityByYear.get(year)),
    city, currentCity: data.city, globalHistoryTop, districts: [...labels.keys()] };
}

let model; let hosts; let selected = null; let redraw = null;
const margin = { top: 24, right: 20, bottom: 32, left: 142 };
function makeFrame(host, height, label) {
  const width = Math.max(270, Math.floor(host.clientWidth));
  const svg = d3.select(host).selectAll('svg').data([null]).join('svg').attr('width', width)
    .attr('height', height).attr('viewBox', `0 0 ${width} ${height}`).attr('role', 'img').attr('aria-label', label);
  svg.selectAll('*').remove();
  return { svg, width, height, innerW: width - margin.left - margin.right, innerH: height - margin.top - margin.bottom };
}
function drawProfile(row) {
  const frame = makeFrame(hosts.profile, 235, `Current access profile for ${model.labels.get(row.district_name)}; five district percentages compared with current city references.`);
  const y = d3.scaleBand().domain(PROFILE.map((d) => d[0])).range([0, frame.innerH]).padding(0.35);
  const x = d3.scaleLinear().domain([0, 100]).range([0, frame.innerW]);
  const g = frame.svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);
  g.append('g').attr('class', 'de-grid').call(d3.axisBottom(x).ticks(5).tickFormat((v) => `${v}%`).tickSize(frame.innerH).tickSizeOuter(0))
    .call((axis) => axis.select('.domain').remove()).attr('transform', `translate(0,0)`);
  g.append('g').attr('class', 'de-axis').call(d3.axisLeft(y).tickSize(0));
  const marks = g.append('g').selectAll('g').data(PROFILE).join('g').attr('class', (d) => `de-profile-row de-${d[3]}`);
  marks.append('rect').attr('x', 0).attr('y', (d) => y(d[0]) + y.bandwidth() * .24).attr('height', y.bandwidth() * .52)
    .attr('width', (d) => x(row[d[1]])).attr('rx', 2);
  marks.append('path').attr('class', 'de-city-ref').attr('transform', (d) => `translate(${x(d[2] === 'metro_access_pct' ? model.currentCity.metro_access_pct : model.city[d[2]])},${y(d[0]) + y.bandwidth() / 2})`)
    .attr('d', d3.symbol().type(d3.symbolDiamond).size(42));
  marks.append('text').attr('class', 'de-value').attr('x', (d) => Math.min(frame.innerW - 3, x(row[d[1]]) + 5)).attr('y', (d) => y(d[0]) + y.bandwidth() / 2 + 4).text((d) => fmt.pct(row[d[1]]));
  frame.svg.append('text').attr('class', 'de-axis-title').attr('x', margin.left).attr('y', frame.height - 6).text('Share of analysed population (%)');
}
function drawHistory(rows) {
  const frame = makeFrame(hosts.history, hosts.history.clientWidth < 480 ? 255 : 290,
    `Standardized metro access history for ${model.labels.get(rows[0].district_name)}, with a dashed city reference from ${model.years[0]} to ${model.years.at(-1)}.`);
  const x = d3.scaleLinear().domain([model.years[0], model.years.at(-1)]).range([0, frame.innerW]);
  const y = d3.scaleLinear().domain([0, model.globalHistoryTop * 1.15]).nice().range([frame.innerH, 0]);
  const g = frame.svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);
  const ticks = model.years.filter((year, i) => frame.innerW >= 420 || i === 0 || i === model.years.length - 1 || i % 2 === 0);
  g.append('g').attr('class', 'de-grid').call(d3.axisLeft(y).ticks(5).tickFormat((v) => `${v}%`).tickSize(-frame.innerW).tickSizeOuter(0)).call((a) => a.select('.domain').remove());
  g.append('g').attr('class', 'de-axis').attr('transform', `translate(0,${frame.innerH})`).call(d3.axisBottom(x).tickValues(ticks).tickFormat(d3.format('d')).tickSizeOuter(0));
  const line = d3.line().x((d) => x(d.year)).y((d) => y(d.metro_access_pct_standardized));
  g.append('path').datum(model.cityHistory).attr('class', 'de-history-city').attr('d', line);
  g.append('path').datum(rows).attr('class', 'de-history-district').attr('d', line);
  g.selectAll('.de-history-point').data(rows).join('circle').attr('class', (d) => d.population_projection_flag ? 'de-history-point is-projection' : 'de-history-point')
    .attr('cx', (d) => x(d.year)).attr('cy', (d) => y(d.metro_access_pct_standardized)).attr('r', 3.4);
  frame.svg.append('text').attr('class', 'de-axis-title').attr('x', margin.left).attr('y', 12).text('Standardized metro access (%)');
}
function profileLegend() {
  replace(hosts.profileLegend, [
    el('span', { class: 'de-key de-key--district' }, [el('i'), 'Selected district']),
    el('span', { class: 'de-key de-key--city' }, [el('i'), 'Current city reference']),
  ]);
}
function renderSummary(row, history) {
  const first = history[0]; const latest = history.at(-1);
  const item = (label, value) => el('div', { class: 'de-stat' }, [el('dt', { text: label }), el('dd', { text: value })]);
  replace(hosts.summary, [
    el('h3', { class: 'de-selected-title', text: model.labels.get(row.district_name) }),
    el('dl', { class: 'de-summary-grid' }, [item('Official population', fmt.people(row.official_population)), item('Area', fmt.km2(row.area_km2)), item('Population density', fmt.density(row.population_density_per_km2))]),
    el('h3', { class: 'de-subhead', text: 'Current transit composition' }),
    el('dl', { class: 'de-summary-grid de-summary-grid--three' }, [item('Metro access', fmt.pct(row.metro_access_pct)), item('Bus-only', fmt.pct(row.bus_only_pct)), item('Underserved', fmt.pct(row.underserved_pct))]),
    el('p', { class: 'de-history-summary', text: `Within the standardized historical frame, metro access is ${fmt.pct2(first.metro_access_pct_standardized)} in ${first.year} and ${fmt.pct2(latest.metro_access_pct_standardized)} in ${latest.year} (${fmt.pp(latest.metro_access_pct_change_from_2015_pp)} stored change).` }),
  ]);
}
function renderSupply(row) {
  const rows = [['Bus stops', row.bus_stops, row.bus_stops_per_10k], ['Healthcare facilities', row.healthcare_total, row.healthcare_facilities_per_10k], ['Education facilities', row.education_total, row.education_facilities_per_10k], ['Bazaars', row.bazaars, row.bazaars_per_10k]];
  const head = (text, scope) => el('th', { scope, text });
  replace(hosts.supply, el('table', { class: 'de-table' }, [el('caption', { class: 'visually-hidden', text: `Mapped service counts for ${model.labels.get(row.district_name)}` }),
    el('thead', {}, el('tr', {}, [head('Service / context', 'col'), head('Mapped count', 'col'), head('Per 10,000 residents', 'col')])),
    el('tbody', {}, rows.map((r) => el('tr', {}, [head(r[0], 'row'), el('td', { text: fmt.int(r[1]) }), el('td', { text: fmt.dec1(r[2]) })]))),
  ]));
  replace(hosts.network, [el('dl', { class: 'de-summary-grid' }, [
    el('div', { class: 'de-stat' }, [el('dt', { text: 'Mapped walk-network length' }), el('dd', { text: `${fmt.dec1(row.walk_network_km)} km` })]),
    el('div', { class: 'de-stat' }, [el('dt', { text: 'Mapped walk-network density' }), el('dd', { text: `${fmt.dec1(row.walk_network_density_km_per_km2)} km/km²` })]),
  ])]);
}
function clear() {
  selected = null; hosts.select.value = ''; hosts.content.hidden = true; hosts.empty.hidden = false;
  replace(hosts.summary, []); replace(hosts.supply, []); replace(hosts.network, []); d3.select(hosts.profile).selectAll('*').remove(); d3.select(hosts.history).selectAll('*').remove();
}
function render(name) {
  const row = model.urbanByName.get(name); const history = model.temporalByName.get(name);
  if (!row || !history) { clear(); return; }
  selected = name; hosts.select.value = name; hosts.empty.hidden = true; hosts.content.hidden = false;
  renderSummary(row, history); drawProfile(row); drawHistory(history); renderSupply(row);
}
export function initDistrictExplorer(nextModel) {
  model = nextModel;
  hosts = { select: document.getElementById('district-explorer-select'), empty: document.getElementById('district-explorer-empty'), content: document.getElementById('district-explorer-content'), summary: document.getElementById('district-explorer-summary'), profile: document.getElementById('district-current-profile'), profileLegend: document.getElementById('district-profile-legend'), history: document.getElementById('district-history'), supply: document.getElementById('district-supply'), network: document.getElementById('district-network') };
  const options = model.districts.map((name) => ({ name, label: model.labels.get(name) })).sort((a, b) => a.label.localeCompare(b.label));
  replace(hosts.select, [el('option', { value: '', text: 'Select a district…' }), ...options.map((option) => el('option', { value: option.name, text: option.label }))]);
  hosts.select.addEventListener('change', () => { if (hosts.select.value) store.selectDistrict(hosts.select.value); else store.clearSelection(); });
  profileLegend(); clear();
  redraw = () => { if (selected) render(selected); };
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(redraw).observe(hosts.profile);
}
/** State-in only: this function deliberately never writes to the shared store. */
export function updateDistrictExplorerState(state) {
  if (!hosts) return;
  const next = state.selectedDistrict;
  if (next === selected) return;
  if (next === null) { clear(); return; }
  render(next);
}
