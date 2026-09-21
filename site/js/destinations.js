/* The current destination chapter: beyond metro access, which everyday
 * destinations lie within the same modelled ten-minute walk.
 *
 * Two stages, like the temporal chapter:
 *
 *   prepareDestinations(data)  before anything is rendered or revealed.
 *                              Validates every record it will use, checks the
 *                              city results against the current snapshot's
 *                              population and walking specification, and
 *                              reconciles every point layer with the analysis
 *                              and the web manifest. Anything inconsistent
 *                              throws; nothing is filtered or corrected.
 *   initDestinations(model)    after the reveal. Draws and wires.
 *
 * The three destination types are separate results. Nothing here combines
 * them, ranks them or derives a score. The healthcare-and-education figure is
 * the committed intersection, read as stored, never computed here.
 *
 * The map shows where the routing-source points are, one type at a time, on
 * one fixed projection. The shares do not come from those points: they come
 * from pedestrian-network routing over population cells. The chosen type is
 * local to this chapter and never touches the shared store, the current map or
 * the temporal chapter.
 *
 * Every figure is read from site/data. None is written here.
 */

import { el, replace } from './dom.js';
import { fmt } from './data.js';

/* ── validation ───────────────────────────────────────────────────────── */
const isInt = (v) => Number.isInteger(v);
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const isText = (v) => typeof v === 'string' && v.trim() !== '';
const isPct = (v) => isNum(v) && v >= 0 && v <= 100;
const isCount = (v) => isInt(v) && v >= 0;

function fail(file, message) {
  throw new Error(`${file} ${message}`);
}

const URBAN_RULES = [
  ['analysis', isText, 'non-empty'],
  ['population_total', (v) => isNum(v) && v > 0, 'positive'],
  ['population_cells', (v) => isInt(v) && v > 0, 'positive integer'],
  ['walking_speed_kmh', (v) => isNum(v) && v > 0, 'positive'],
  ['walking_time_minutes', (v) => isNum(v) && v > 0, 'positive'],
  ['distance_budget_m', (v) => isNum(v) && v > 0, 'positive'],
  ['healthcare_10min_population', (v) => isNum(v) && v >= 0, 'non-negative'],
  ['healthcare_10min_pct', isPct, '0-100'],
  ['education_10min_population', (v) => isNum(v) && v >= 0, 'non-negative'],
  ['education_10min_pct', isPct, '0-100'],
  ['bazaar_10min_population', (v) => isNum(v) && v >= 0, 'non-negative'],
  ['bazaar_10min_pct', isPct, '0-100'],
  ['healthcare_and_education_10min_population', (v) => isNum(v) && v >= 0, 'non-negative'],
  ['healthcare_and_education_10min_pct', isPct, '0-100'],
  ['walk_network_km', (v) => isNum(v) && v > 0, 'positive'],
  ['walk_network_density_km_per_km2', (v) => isNum(v) && v > 0, 'positive'],
  ['healthcare_routing_sources', isCount, 'non-negative integer'],
  ['healthcare_facilities_in_analysis_districts', isCount, 'non-negative integer'],
  ['healthcare_facilities_outside_analysis_districts', isCount, 'non-negative integer'],
  ['education_routing_sources', isCount, 'non-negative integer'],
  ['education_facilities_in_analysis_districts', isCount, 'non-negative integer'],
  ['education_facilities_outside_analysis_districts', isCount, 'non-negative integer'],
  ['bazaar_routing_sources', isCount, 'non-negative integer'],
  ['bazaar_facilities_in_analysis_districts', isCount, 'non-negative integer'],
];

// A stored share must agree with its stored population over the stored total
// to far better than any rounding the page shows. This checks consistency; the
// page still displays the stored share, never a recomputed one.
const SHARE_TOLERANCE = 1e-6;

const SHARES = [
  ['healthcare_10min_population', 'healthcare_10min_pct'],
  ['education_10min_population', 'education_10min_pct'],
  ['bazaar_10min_population', 'bazaar_10min_pct'],
  ['healthcare_and_education_10min_population', 'healthcare_and_education_10min_pct'],
];

function prepareUrban(payload, city) {
  const file = 'urban_dimensions_city.json';
  if (!payload || payload.role !== 'analytical' || !payload.record
      || typeof payload.record !== 'object') {
    fail(file, 'carries no analytical city record');
  }
  const r = payload.record;
  for (const [field, test, description] of URBAN_RULES) {
    if (!test(r[field])) fail(file, `has no ${description} ${field}`);
  }
  // One denominator and one walking specification for both current chapters.
  for (const [mine, theirs] of [
    ['population_total', 'analysis_population'],
    ['walking_speed_kmh', 'walking_speed_kmh'],
    ['walking_time_minutes', 'walking_time_minutes'],
    ['distance_budget_m', 'distance_budget_m'],
  ]) {
    if (!city || r[mine] !== city[theirs]) {
      fail(file, `${mine} does not match the current city summary's ${theirs}`);
    }
  }
  for (const [population, pct] of SHARES) {
    if (Math.abs((r[population] / r.population_total) * 100 - r[pct]) > SHARE_TOLERANCE) {
      fail(file, `${pct} does not agree with ${population} over population_total`);
    }
  }
  const both = r.healthcare_and_education_10min_population;
  const bothPct = r.healthcare_and_education_10min_pct;
  if (both > r.healthcare_10min_population || both > r.education_10min_population
      || bothPct > r.healthcare_10min_pct || bothPct > r.education_10min_pct) {
    fail(file, 'reports more residents near both healthcare and education than near one of them');
  }
  if (r.healthcare_facilities_in_analysis_districts
      + r.healthcare_facilities_outside_analysis_districts !== r.healthcare_routing_sources
      || r.education_facilities_in_analysis_districts
      + r.education_facilities_outside_analysis_districts !== r.education_routing_sources) {
    fail(file, 'routing-source counts do not add up inside and outside the analysis districts');
  }
  return r;
}

function manifestLayer(manifest, key, role) {
  const layer = manifest && manifest.layers && manifest.layers[key];
  if (!layer || layer.role !== role) fail('manifest.json', `does not record ${key} as ${role}`);
  return layer;
}

function tally(values) {
  const out = {};
  for (const v of values) out[v] = (out[v] || 0) + 1;
  return out;
}

function sameCounts(a, b) {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys].every((k) => a[k] === b[k]);
}

function pointOf(feature, file, i) {
  const g = feature && feature.geometry;
  if (!feature || !feature.properties || !g || g.type !== 'Point'
      || !Array.isArray(g.coordinates) || g.coordinates.length !== 2) {
    fail(file, `feature ${i} is not a point`);
  }
  const [lon, lat] = g.coordinates;
  if (!isNum(lon) || !isNum(lat) || Math.abs(lon) > 180 || Math.abs(lat) > 90) {
    fail(file, `feature ${i} has no finite longitude/latitude`);
  }
  if (feature.properties.role !== 'display_only') fail(file, `feature ${i} is not display_only`);
  return [lon, lat];
}

function featuresOf(collection, file) {
  if (!collection || collection.type !== 'FeatureCollection' || !Array.isArray(collection.features)
      || collection.features.length === 0) {
    fail(file, 'is not a non-empty FeatureCollection');
  }
  return collection.features;
}

/* Healthcare and education: routing-source points with a category and a
 * district assignment, reconciled with the analysis and the manifest. */
function prepareFacilities({ collection, file, key, categoryField, categories, urban, manifest }) {
  const features = featuresOf(collection, file);
  const layer = manifestLayer(manifest, `${key}_points`, 'display_only');
  const ids = new Set();
  const points = features.map((feature, i) => {
    const coordinates = pointOf(feature, file, i);
    const p = feature.properties;
    if (!isText(p.facility_id)) fail(file, `feature ${i} has no facility_id`);
    if (ids.has(p.facility_id)) fail(file, `repeats facility_id ${p.facility_id}`);
    ids.add(p.facility_id);
    if (!categories.includes(p[categoryField])) {
      fail(file, `feature ${i} has an unsupported ${categoryField} ${JSON.stringify(p[categoryField])}`);
    }
    if (p.district_assignment === 'within') {
      if (!isText(p.district_name)) fail(file, `feature ${i} is within a district but names none`);
    } else if (p.district_assignment === 'outside_analysis_districts') {
      if (p.district_name !== null) fail(file, `feature ${i} lies outside yet names a district`);
    } else {
      fail(file, `feature ${i} has an unsupported district_assignment`);
    }
    return { coordinates, category: p[categoryField], inside: p.district_assignment === 'within' };
  });
  const sources = urban[`${key}_routing_sources`];
  if (points.length !== sources || points.length !== layer.features) {
    fail(file, `carries ${points.length} points; the analysis records ${sources} routing `
      + `sources and the manifest ${layer.features}`);
  }
  const inside = points.filter((pt) => pt.inside).length;
  const outside = points.length - inside;
  if (inside !== urban[`${key}_facilities_in_analysis_districts`]
      || outside !== urban[`${key}_facilities_outside_analysis_districts`]
      || !sameCounts({ within: inside, outside_analysis_districts: outside },
        layer.by_district_assignment || {})) {
    fail(file, 'inside/outside counts do not reconcile with the analysis and the manifest');
  }
  const byCategory = tally(points.map((pt) => pt.category));
  if (!sameCounts(byCategory, layer.by_category || {})) {
    fail(file, 'category counts do not reconcile with the manifest');
  }
  return {
    points, inside, outside,
    categories: categories.map((c) => [c, byCategory[c] || 0]),
  };
}

function prepareBazaars(collection, urban, manifest) {
  const file = 'bazaars.geojson';
  const features = featuresOf(collection, file);
  const layer = manifestLayer(manifest, 'bazaars', 'display_only');
  const points = features.map((feature, i) => ({
    coordinates: pointOf(feature, file, i), category: 'bazaar', inside: true,
  }));
  if (points.length !== urban.bazaar_routing_sources
      || points.length !== urban.bazaar_facilities_in_analysis_districts
      || points.length !== layer.features) {
    fail(file, `carries ${points.length} points; the analysis records `
      + `${urban.bazaar_routing_sources} routing sources and the manifest ${layer.features}`);
  }
  return { points, inside: points.length, outside: 0, categories: [['bazaar', points.length]] };
}

function prepareDistricts(collection) {
  const features = featuresOf(collection, 'districts.geojson');
  if (features.some((f) => !f.geometry || !['Polygon', 'MultiPolygon'].includes(f.geometry.type))) {
    fail('districts.geojson', 'is not a set of district polygons');
  }
  return features;
}

/**
 * Validate and reconcile every input of the destination chapter and return
 * its model. Throws on anything malformed or inconsistent; renders nothing.
 */
export function prepareDestinations(data) {
  manifestLayer(data.manifest, 'urban_dimensions_city', 'analytical');
  const urban = prepareUrban(data.urbanCity, data.city);
  const healthcare = prepareFacilities({
    collection: data.healthcarePoints, file: 'healthcare_points.geojson', key: 'healthcare',
    categoryField: 'facility_category', categories: ['clinic', 'hospital'],
    urban, manifest: data.manifest,
  });
  const education = prepareFacilities({
    collection: data.educationPoints, file: 'education_points.geojson', key: 'education',
    categoryField: 'education_category',
    categories: ['school', 'kindergarten', 'college', 'university'],
    urban, manifest: data.manifest,
  });
  const bazaars = prepareBazaars(data.bazaars, urban, data.manifest);
  return {
    urban,
    districts: prepareDistricts(data.districts),
    dimensions: {
      healthcare: {
        ...healthcare, label: 'Healthcare', noun: 'healthcare',
        reach: 'a mapped clinic or hospital',
        pct: urban.healthcare_10min_pct, population: urban.healthcare_10min_population,
      },
      education: {
        ...education, label: 'Education', noun: 'education',
        reach: 'a mapped school, kindergarten, college or university',
        pct: urban.education_10min_pct, population: urban.education_10min_population,
      },
      bazaars: {
        ...bazaars, label: 'Bazaars', noun: 'bazaar',
        reach: 'a mapped bazaar',
        pct: urban.bazaar_10min_pct, population: urban.bazaar_10min_population,
      },
    },
  };
}

/* ── drawing ──────────────────────────────────────────────────────────── */
const ORDER = ['healthcare', 'education', 'bazaars'];
const CATEGORY_LABELS = {
  clinic: 'Clinics', hospital: 'Hospitals', school: 'Schools', kindergarten: 'Kindergartens',
  college: 'Colleges', university: 'Universities', bazaar: 'Bazaars',
};

// d3-geo is spherical: a ring wound the other way encloses the rest of the
// globe. Rings are rewound so each district is its own small area.
function rewound(feature) {
  const fix = (polygon) => (d3.geoArea({ type: 'Polygon', coordinates: polygon }) > 2 * Math.PI
    ? polygon.map((ring) => ring.slice().reverse()) : polygon);
  const g = feature.geometry;
  const geometry = g.type === 'Polygon'
    ? { type: 'Polygon', coordinates: fix(g.coordinates) }
    : { type: 'MultiPolygon', coordinates: g.coordinates.map(fix) };
  return { type: 'Feature', properties: {}, geometry };
}

/**
 * Draw and wire the chapter. Call only once #destination-access is visible.
 */
export function initDestinations(model) {
  const { urban, dimensions } = model;
  let active = 'healthcare';

  const hosts = {
    cards: document.getElementById('dest-cards'),
    overlap: document.getElementById('dest-overlap-value'),
    method: document.getElementById('dest-method'),
    map: document.getElementById('destination-map'),
    mapSub: document.getElementById('dest-map-sub'),
    legend: document.getElementById('dest-legend'),
    contextTitle: document.getElementById('dest-context-h'),
    context: document.getElementById('dest-context'),
  };

  /* ── the three results ─────────────────────────────────────────────── */
  const buttons = new Map();
  replace(hosts.cards, ORDER.map((key) => {
    const d = dimensions[key];
    const button = el('button', {
      type: 'button', class: `dest-card dest-card--${key}`, 'aria-pressed': 'false',
      'aria-labelledby': `dest-card-${key}`,
      'aria-describedby': `dest-card-${key}-share dest-card-${key}-detail`,
      onclick: () => select(key),
    }, [
      el('span', { class: 'dest-card-head' }, [
        el('span', { id: `dest-card-${key}`, class: 'dest-card-label', text: d.label }),
        el('span', { class: 'dest-card-state', text: 'On the map' }),
      ]),
      el('span', { id: `dest-card-${key}-share`, class: 'dest-card-share' }, [
        el('span', { class: 'dest-card-pct', text: fmt.pct(d.pct) }),
        el('span', {
          class: 'dest-card-measure',
          text: `of the current analysed population within a modelled `
            + `${fmt.int(urban.walking_time_minutes)}-minute walk of ${d.reach}`,
        }),
      ]),
      el('span', { id: `dest-card-${key}-detail`, class: 'dest-card-detail' }, [
        el('span', { text: `${fmt.people(d.population)} modelled residents` }),
        el('span', { text: `${fmt.int(d.points.length)} mapped routing-source points` }),
      ]),
    ]);
    buttons.set(key, button);
    return button;
  }));

  replace(hosts.overlap, [
    el('span', { class: 'dest-overlap-pct', text: fmt.pct(urban.healthcare_and_education_10min_pct) }),
    el('span', {
      class: 'dest-overlap-text',
      text: `of the current analysed population, about `
        + `${fmt.people(urban.healthcare_and_education_10min_population)} modelled residents`,
    }),
  ]);

  const item = (key, value) => el('div', { class: 'dest-method-item' }, [
    el('dt', { text: key }), el('dd', { text: value }),
  ]);
  replace(hosts.method, [
    item('Analysed population', `${fmt.people(urban.population_total)} residents`),
    item('Walking time', `${fmt.int(urban.walking_time_minutes)} minutes`),
    item('Walking speed', `${urban.walking_speed_kmh} km/h`),
    item('Distance budget', `${fmt.int(urban.distance_budget_m)} m`),
    item('Mapped walk network', `${fmt.int(urban.walk_network_km)} km`),
    item('Walk-network density', `${fmt.dec1(urban.walk_network_density_km_per_km2)} km per km²`),
  ]);

  /* ── the routing-source map ────────────────────────────────────────── */
  // One fitting collection for every mode: the district outlines and every
  // point of all three types. Switching type never moves the view, and the few
  // healthcare and education sources outside the districts stay in frame.
  const outlines = model.districts.map(rewound);
  const everyPoint = ORDER.flatMap((key) => dimensions[key].points.map((pt) => pt.coordinates));
  const fitting = {
    type: 'FeatureCollection',
    features: [...outlines, {
      type: 'Feature', properties: {}, geometry: { type: 'MultiPoint', coordinates: everyPoint },
    }],
  };

  let map = null;
  function drawMap() {
    const width = Math.max(260, Math.floor(hosts.map.clientWidth));
    const height = Math.round(Math.min(width * 0.9, 480, window.innerHeight * 0.78));
    const svg = d3.select(hosts.map).selectAll('svg').data([null]).join('svg')
      .attr('width', width).attr('height', height).attr('viewBox', `0 0 ${width} ${height}`)
      .attr('role', 'img');
    svg.selectAll('*').remove();
    const projection = d3.geoMercator().fitExtent([[10, 10], [width - 10, height - 10]], fitting);
    svg.append('g').selectAll('path').data(outlines).join('path')
      .attr('class', 'dm-district').attr('d', d3.geoPath(projection));
    map = { svg, projection, layer: svg.append('g') };
  }

  function syncMap() {
    if (!map) return;
    const d = dimensions[active];
    // Hollow points last, so a routing source outside the districts is never
    // hidden under a filled one.
    const ordered = [...d.points.filter((pt) => pt.inside), ...d.points.filter((pt) => !pt.inside)];
    map.layer.attr('class', `dm-points dm-points--${active}`)
      .selectAll('circle').data(ordered).join('circle')
      .attr('class', (pt) => (pt.inside ? 'dm-point' : 'dm-point is-outside'))
      .attr('cx', (pt) => map.projection(pt.coordinates)[0])
      .attr('cy', (pt) => map.projection(pt.coordinates)[1])
      .attr('r', (pt) => (pt.inside ? 2.4 : 3.8));
    map.svg.attr('aria-label', `Current ${d.noun} routing-source map. `
      + (d.outside > 0
        ? `${fmt.int(d.points.length)} points total; ${fmt.int(d.inside)} inside the analysis `
          + `districts and ${fmt.int(d.outside)} outside.`
        : `${fmt.int(d.points.length)} points, all inside the analysis districts.`));
  }

  /* ── the selected type, in words ───────────────────────────────────── */
  function renderContext() {
    const d = dimensions[active];
    hosts.mapSub.textContent = `${d.label} routing sources, drawn one type at a time on a fixed view.`;
    hosts.contextTitle.textContent = `${d.label} routing sources`;
    const key = (cls, text) => el('span', { class: 'lg' }, [
      el('i', { class: `dm-key ${cls}`, 'aria-hidden': 'true' }), text,
    ]);
    replace(hosts.legend, [
      key('', 'Inside the analysis districts'),
      d.outside > 0 ? key('is-outside', 'Outside the districts, kept as routing sources') : null,
    ]);
    hosts.legend.className = `dest-legend dest-legend--${active}`;

    const row = (label, value) => el('div', { class: 'dest-count' }, [
      el('dt', { text: label }), el('dd', { text: fmt.int(value) }),
    ]);
    const rows = d.categories.length > 1
      ? d.categories.map(([category, count]) => row(CATEGORY_LABELS[category], count))
      : [];
    replace(hosts.context, [
      el('dl', { class: 'dest-counts' }, [
        ...rows,
        row('Routing-source points', d.points.length),
        row('Inside the analysis districts', d.inside),
        row('Outside the analysis districts', d.outside),
      ]),
      el('p', {
        class: 'dest-context-note',
        text: `${fmt.pct(d.pct)} of the current analysed population is estimated to be within `
          + `a modelled ${fmt.int(urban.walking_time_minutes)}-minute walk of ${d.reach}. `
          + 'That share comes from routing along the pedestrian network from every population '
          + 'cell; these counts describe the mapped sources, not how many people each one serves.',
      }),
    ]);
  }

  function select(key) {
    active = key;
    for (const [k, button] of buttons) button.setAttribute('aria-pressed', String(k === active));
    renderContext();
    syncMap();
  }

  drawMap();
  select(active);

  if (typeof ResizeObserver !== 'undefined') {
    let last = hosts.map.clientWidth;
    new ResizeObserver((entries) => {
      const width = Math.floor(entries[0].contentRect.width);
      if (width !== last) { last = width; drawMap(); syncMap(); }
    }).observe(hosts.map);
  }
}
