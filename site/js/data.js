/* Data loading and number formatting.
 *
 * Everything analytical is read from site/data at runtime. No city or district
 * figure is written into this application's source: scripts/build_web_data.py
 * copies them from the audited Week 4 outputs, and scripts/validate_prototype.py
 * fails if a literal ever appears here.
 */

const BASE = 'data/';

export const FILES = {
  city: 'city_summary.json',
  districts: 'districts.geojson',
  isochrone: 'metro_isochrone_10min.geojson',
  access: 'metro_access_points.geojson',
  stations: 'metro_stations.geojson',
  metroLines: 'metro_lines.geojson',
  bus: 'bus_stops.geojson',
  bazaars: 'bazaars.geojson',
  density: 'population_density.geojson',
  mask: 'analysis_mask.geojson',
  sensitivity: 'sensitivity.json',
  // The standardized temporal series, read only for its latest year so the
  // story can set it beside the current snapshot. The larger temporal and
  // facility layers are left for the sections that will actually use them.
  temporalCity: 'temporal_city.json',
  // The standardized temporal chapter: the network-state changes, the
  // descriptive diagnostics, and the station points with their opening years.
  temporalEvents: 'temporal_events.json',
  temporalCounterfactual: 'temporal_counterfactual.json',
  stationHistory: 'metro_station_history.geojson',
  manifest: 'manifest.json',
};

async function loadOne(name) {
  const url = BASE + name;
  let response;
  try {
    response = await fetch(url);
  } catch (cause) {
    throw new Error(`could not fetch ${url} (${cause && cause.message ? cause.message : cause})`);
  }
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
  try {
    return await response.json();
  } catch {
    throw new Error(`${url} did not contain valid JSON`);
  }
}

export async function loadAll() {
  const keys = Object.keys(FILES);
  const values = await Promise.all(keys.map((key) => loadOne(FILES[key])));
  return Object.fromEntries(keys.map((key, i) => [key, values[i]]));
}

/* ── formatting ──────────────────────────────────────────────────────── */
const nf0 = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat('en-GB', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
// en-US: millions read as 'M'; en-GB writes a lowercase 'm' that reads as metres.
const nfCompact = new Intl.NumberFormat('en-US', {
  notation: 'compact', maximumSignificantDigits: 3,
});

export const fmt = {
  people: (v) => nf0.format(v),
  pct: (v) => `${nf1.format(v)}%`,
  // Two places where two methods sit side by side and one place would blur them.
  pct2: (v) => `${nf2.format(v)}%`,
  // Signed percentage points, with a true minus sign. A value that rounds to
  // zero reads 0.00 pp rather than a signed zero.
  pp: (v) => {
    const rounded = Math.round(v * 100) / 100;
    if (rounded === 0) return `${nf2.format(0)} pp`;
    return `${rounded > 0 ? '+' : '−'}${nf2.format(Math.abs(rounded))} pp`;
  },
  compact: (v) => nfCompact.format(v),
  density: (v) => `${nf0.format(v)} /km²`,
  km2: (v) => `${nf1.format(v)} km²`,
  metres: (v) => `${nf1.format(v)} m`,
  int: (v) => nf0.format(v),
};

/** Index districts by name and produce the ranking order, from the data. */
export function indexDistricts(collection) {
  const byName = new Map();
  for (const feature of collection.features) {
    byName.set(feature.properties.district_name, feature);
  }
  const ranked = collection.features.slice().sort(
    (a, b) =>
      b.properties.metro_access_pct - a.properties.metro_access_pct ||
      a.properties.district_name.localeCompare(b.properties.district_name),
  );
  return { byName, ranked };
}
