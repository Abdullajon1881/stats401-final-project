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

export const fmt = {
  people: (v) => nf0.format(v),
  pct: (v) => `${nf1.format(v)}%`,
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
