/* The geographic workspace: MapLibre GL JS.
 *
 * MapLibre owns geography — the vector basemap, the camera, WebGL rendering of
 * thousands of marks, clustering and geographic hit-testing. D3 owns the
 * statistics. The split is deliberate: a static SVG projection cannot pan and
 * zoom through scales, and 2,163 bus stops as SVG nodes is the wrong tool.
 *
 * Nothing here computes an analytical value. Every layer it draws is display
 * data, and the access shading in particular is never intersected with anything.
 */

import { el, kv, safeName } from './dom.js';
import { fmt } from './data.js';
import * as store from './state.js';

const STYLE_URL = 'https://tiles.openfreemap.org/styles/dark';

/* What the reader is told about the basemap, by state. 'provisional' is
 * neutral on purpose: it is shown while the outcome is still open and is
 * withdrawn as soon as the map loads. 'unavailable' is reserved for a style
 * that genuinely cannot initialise. */
const BASEMAP_NOTICE = {
  none: '',
  provisional: 'The basemap is having trouble loading.',
  unavailable: 'The basemap is unavailable, so the map cannot be drawn. '
    + 'The district analysis below is unaffected — it reads only local data.',
};
/* How long an open outcome is given before a notice is settled: a style that
 * has still not arrived becomes 'unavailable'; a live style whose resources
 * keep failing becomes 'provisional'. */
const BASEMAP_GRACE_MS = 3000;

/* Tashkent only. Beyond these the city is off screen and the map is useless. */
const MIN_ZOOM = 8.5;
const MAX_ZOOM = 17.5;
const MAX_BOUNDS_PAD = 0.55; // degrees of slack around the districts

/* OSM tags each route relation with a colour name. The identity is OSM's; the
 * exact value is tuned here so a saturated CSS "red" does not glare on a dark
 * ground. A line whose relations disagree carries no colour and gets the
 * neutral network grey rather than an invented one. */
const NAMED_LINE_COLOURS = {
  red: '#e0574e',
  blue: '#4d92e8',
  green: '#4fb26e',
  purple: '#a76cf0',
  yellow: '#e0b64a',
};
const NEUTRAL_LINE = '#8fa3b8';

/* Deliberately dark at the low end and muted at the top: population is the
 * backdrop, never the subject. A light ramp turned the whole city into one
 * grey mass and buried both the access area and the district boundaries. */
const POP_RAMP = ['#0d131a', '#16202b', '#213040', '#334759', '#4a6478', '#6f8ca6'];

let map = null;
let data = null;
let bounds = null;
let popup = null;
let onReady = null;
let basemapNotice = 'none';

export function getMap() { return map; }

/* ── boot ─────────────────────────────────────────────────────────────── */
export function initMap(loaded, ready, qaMode = false) {
  data = loaded;
  onReady = ready;
  bounds = districtBounds(data.districts);

  map = new maplibregl.Map({
    container: 'map',
    style: STYLE_URL,
    bounds,
    fitBoundsOptions: { padding: mapPadding() },
    minZoom: MIN_ZOOM,
    maxZoom: MAX_ZOOM,
    maxBounds: padBounds(bounds, MAX_BOUNDS_PAD),
    attributionControl: false,
    dragRotate: false,
    pitchWithRotate: false,
    hash: false,
  });
  map.touchZoomRotate.disableRotation();

  // Attribution is required by OpenFreeMap and is not suppressed. The style's
  // own source attribution is added automatically; the compact form keeps it
  // visible without taking the corner of the map.
  map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
  map.addControl(new maplibregl.ScaleControl({ maxWidth: 108, unit: 'metric' }), 'bottom-left');

  popup = new maplibregl.Popup({
    closeButton: true, closeOnClick: true, offset: 12, maxWidth: '260px',
  });

  /* The analytical data on this page is local; the basemap is the one thing
   * that depends on a remote provider. MapLibre reports every problem through
   * the same 'error' event, so the handler has to tell three cases apart:
   *
   *   - The style document itself could not be fetched. MapLibre reports that
   *     as an AJAXError naming the style URL, whether the network refused the
   *     request or the server answered with an error. 'style.load' never
   *     fires, no layer is ever added, and the reader is left with an
   *     unexplained black rectangle while the district analysis below works
   *     perfectly. That is the one case that earns a persistent notice.
   *   - A resource inside a live style failed: a tile, a source's TileJSON, a
   *     sprite or a glyph range. MapLibre attaches `sourceId` to anything a
   *     source reports and `tile` to tile failures, and anything reported
   *     after 'style.load' is by definition inside a live style. These are
   *     transient and common on a slow connection, and the map keeps drawing
   *     everything else, so they raise nothing on their own. Only if the map
   *     still has not finished loading after the grace period does a neutral
   *     provisional notice appear - which 'load' withdraws.
   *   - Anything else before the style settled, such as a style document that
   *     arrived but failed validation. Not proof of a dead style, so the
   *     notice is provisional, and it only hardens into 'unavailable' if
   *     'style.load' still has not fired after the grace period.
   *
   * 'style.load' is the style-specific readiness signal: MapLibre fires it
   * synchronously once the style document has been parsed and its sources and
   * layers created, before any sprite, glyph or tile request completes. A
   * successful 'load' resets the notice unconditionally, so a transient error
   * can never leave a stale failure message on a working map.
   *
   * MapLibre's own error is always re-thrown to the console either way, so
   * nothing needed for debugging is swallowed. */
  let styleLoaded = false;
  let mapLoaded = false;
  let graceTimer = null;

  const cancelGrace = () => {
    if (graceTimer === null) return;
    window.clearTimeout(graceTimer);
    graceTimer = null;
  };
  const settleGrace = () => {
    graceTimer = null;
    if (mapLoaded) return;
    setBasemapNotice(styleLoaded ? 'provisional' : 'unavailable');
  };
  const startGrace = () => {
    if (graceTimer === null) graceTimer = window.setTimeout(settleGrace, BASEMAP_GRACE_MS);
  };

  map.on('error', (event) => {
    const detail = event && event.error ? event.error : event;
    console.error('[basemap]', detail);
    if (mapLoaded || basemapNotice === 'unavailable') return;
    if (styleLoaded || isResourceError(event)) {
      startGrace();
      return;
    }
    if (isStyleDocumentError(detail)) {
      cancelGrace();
      setBasemapNotice('unavailable');
      return;
    }
    setBasemapNotice('provisional');
    startGrace();
  });

  map.on('style.load', () => {
    styleLoaded = true;
    cancelGrace();
    setBasemapNotice('none');
  });

  map.on('load', () => {
    styleLoaded = true;
    mapLoaded = true;
    cancelGrace();
    setBasemapNotice('none');
    tuneBasemap();
    addLayers();
    wireInteraction();
    store.set({ mapReady: true });
    if (onReady) onReady();
    // Only under ?qa=1: automated visual QA needs to wait for a genuinely
    // rendered map instead of guessing with a timer. The ordinary product
    // publishes nothing, so the MapLibre instance is not reachable from the
    // page. See window.__prototype in app.js.
    if (qaMode && window.__prototype) {
      window.__prototype.map = map;
      map.once('idle', () => { window.__prototype.mapLoaded = true; });
    }
  });

  return map;
}

/* A source-scoped error names its source; a tile error carries the tile. Either
 * way the style is alive and the map keeps working. */
function isResourceError(event) {
  return Boolean(event && (event.sourceId || event.tile));
}

/* MapLibre's AJAXError records the URL of the request that failed, whether
 * the network refused it or the server answered with an error. When that URL
 * is the style document itself, the failure is definitive. */
function isStyleDocumentError(error) {
  return Boolean(error && typeof error.url === 'string' && error.url === STYLE_URL);
}

function setBasemapNotice(state) {
  basemapNotice = state;
  const notice = document.getElementById('basemap-error');
  if (!notice) return;
  notice.textContent = BASEMAP_NOTICE[state];
  notice.hidden = state === 'none';
}

function mapPadding() {
  const narrow = window.innerWidth < 940;
  return narrow ? { top: 54, right: 18, bottom: 56, left: 18 }
                : { top: 44, right: 28, bottom: 64, left: 28 };
}

function districtBounds(collection) {
  const b = new maplibregl.LngLatBounds();
  for (const feature of collection.features) {
    eachPosition(feature.geometry, ([lng, lat]) => b.extend([lng, lat]));
  }
  return b;
}

function padBounds(b, pad) {
  return [
    [b.getWest() - pad, b.getSouth() - pad],
    [b.getEast() + pad, b.getNorth() + pad],
  ];
}

function eachPosition(geometry, visit) {
  const walk = (coords, depth) => {
    if (depth === 0) return visit(coords);
    for (const part of coords) walk(part, depth - 1);
  };
  const depth = { Point: 0, LineString: 1, MultiLineString: 2, Polygon: 2, MultiPolygon: 3 };
  const d = depth[geometry.type];
  if (d !== undefined) walk(geometry.coordinates, d);
}

/* Bring the vendor style onto this application's ground so the overlays sit on
 * a surface rather than on an unrelated black. */
function tuneBasemap() {
  const set = (id, prop, value) => {
    if (map.getLayer(id)) {
      try { map.setPaintProperty(id, prop, value); } catch { /* style may differ */ }
    }
  };
  set('background', 'background-color', '#080b10');
  set('water', 'fill-color', '#0c1620');
  set('landcover_wood', 'fill-color', '#0d141a');
  set('park', 'fill-color', '#0d141a');
  set('landuse_park', 'fill-color', '#0d141a');
  set('building', 'fill-color', '#131a22');
  set('building', 'fill-opacity', 0.5);
}

/* ── layers ───────────────────────────────────────────────────────────── */
/* A point is emphasised while the pointer is on it. MapLibre insists that
 * ["zoom"] be the direct input of a top-level interpolate, so this branch
 * appears in each interpolate's output stops rather than wrapping it. */
const HOVERED = ['boolean', ['feature-state', 'hover'], false];

function addLayers() {
  const layers = store.get().layers;
  const vis = (on) => ({ visibility: on ? 'visible' : 'none' });
  const style = map.getStyle();
  // Fills and lines go under the basemap's own labels so street and place names
  // stay legible; transit points go on top of everything so they are never
  // occluded by a label.
  const firstSymbol = (style.layers || []).find((l) => l.type === 'symbol');
  const under = firstSymbol ? firstSymbol.id : undefined;

  const maxDensity = quantile(
    data.density.features.map((f) => f.properties.density_per_km2), 0.98,
  );

  map.addSource('mask', { type: 'geojson', data: data.mask });
  map.addSource('population', { type: 'geojson', data: data.density });
  map.addSource('districts', { type: 'geojson', data: data.districts, promoteId: 'district_name' });
  map.addSource('isochrone', { type: 'geojson', data: data.isochrone });
  map.addSource('metrolines', { type: 'geojson', data: data.metroLines });
  // generateId lets feature-state address an individual point, which is what
  // the hover emphasis below needs.
  map.addSource('stations', { type: 'geojson', data: data.stations, generateId: true });
  map.addSource('access', { type: 'geojson', data: data.access, generateId: true });
  map.addSource('bazaars', { type: 'geojson', data: data.bazaars });
  map.addSource('bus', {
    type: 'geojson', data: data.bus,
    cluster: true, clusterMaxZoom: 13, clusterRadius: 46,
  });

  /* 1. population — a neutral luminance ramp on purpose. It must read as
   *    "where people are" without competing with the metro semantics, and it
   *    fades out as the basemap's own detail takes over. */
  map.addLayer({
    id: 'population-fill', type: 'fill', source: 'population',
    layout: vis(layers.population),
    paint: {
      'fill-color': [
        'interpolate', ['linear'], ['sqrt', ['get', 'density_per_km2']],
        0, POP_RAMP[0],
        Math.sqrt(maxDensity) * 0.20, POP_RAMP[1],
        Math.sqrt(maxDensity) * 0.40, POP_RAMP[2],
        Math.sqrt(maxDensity) * 0.62, POP_RAMP[3],
        Math.sqrt(maxDensity) * 0.82, POP_RAMP[4],
        Math.sqrt(maxDensity), POP_RAMP[5],
      ],
      'fill-opacity': [
        'interpolate', ['linear'], ['zoom'],
        // Gone by street zoom: 500 m squares are honest at city scale and merely
        // blocky once the basemap is showing individual buildings.
        9, 0.72, 12, 0.6, 13.5, 0.3, 14.6, 0.1, 15.4, 0,
      ],
      'fill-antialias': false,
    },
  }, under);

  /* 2. district fill — carries hover and selection, and is otherwise invisible */
  map.addLayer({
    id: 'district-fill', type: 'fill', source: 'districts',
    paint: {
      'fill-color': [
        'case',
        ['boolean', ['feature-state', 'selected'], false], '#35c2d6',
        '#ffffff',
      ],
      'fill-opacity': [
        'case',
        ['boolean', ['feature-state', 'selected'], false], 0.10,
        ['boolean', ['feature-state', 'hover'], false], 0.055,
        0,
      ],
    },
  }, under);

  /* 3. the audited 10-minute access area — DISPLAY ONLY */
  map.addLayer({
    id: 'iso-fill', type: 'fill', source: 'isochrone',
    layout: vis(layers.access),
    paint: {
      'fill-color': '#35c2d6',
      'fill-opacity': [
        'interpolate', ['linear'], ['zoom'],
        // At city scale the filled shape IS the message. Close in, the viewer is
        // already inside it, so the fill recedes and the outline carries the
        // boundary instead of flooding every street in teal.
        9, 0.38, 12, 0.3, 13.5, 0.18, 15, 0.07, 16.5, 0.04,
      ],
    },
  }, under);
  map.addLayer({
    id: 'iso-line', type: 'line', source: 'isochrone',
    layout: vis(layers.access),
    paint: {
      'line-color': '#6fe0ef',
      'line-width': ['interpolate', ['linear'], ['zoom'], 10, 0.5, 12, 0.9, 14, 1.5, 16, 2],
      // Soft at city scale, where a hard jagged edge is only noise, and firmer
      // once the shape is large enough for its outline to mean something.
      'line-opacity': ['interpolate', ['linear'], ['zoom'], 9, 0.3, 12, 0.55, 14, 0.8, 16, 0.9],
    },
  }, under);

  /* 4. metro network */
  map.addLayer({
    id: 'metroline-casing', type: 'line', source: 'metrolines',
    layout: { 'line-cap': 'round', 'line-join': 'round', ...vis(layers.metrolines) },
    paint: {
      'line-color': '#05080c',
      'line-width': ['interpolate', ['linear'], ['zoom'], 9, 4.2, 12, 6.4, 15, 10],
      'line-opacity': 0.65,
    },
  }, under);
  map.addLayer({
    id: 'metroline', type: 'line', source: 'metrolines',
    layout: { 'line-cap': 'round', 'line-join': 'round', ...vis(layers.metrolines) },
    paint: {
      'line-color': lineColourExpression(),
      'line-width': ['interpolate', ['linear'], ['zoom'], 9, 2.2, 12, 3.6, 15, 6],
      'line-opacity': 0.92,
    },
  }, under);

  /* 5. district boundaries, then the selected one on top of them */
  /* Administrative structure has to be readable at city and district scale,
   * where it is the frame the analysis is reported in. At street scale it is
   * context rather than subject: leaving it at full strength put a heavy grey
   * line across the metro route, the entrances and the street grid the reader
   * has zoomed in to look at. So it thins and fades with zoom instead of
   * disappearing - the boundary is still findable at z15, just no longer
   * competing. The SELECTED district is drawn by the layer below and keeps its
   * full weight at every zoom. */
  map.addLayer({
    id: 'district-line', type: 'line', source: 'districts',
    paint: {
      'line-color': '#7b8ea3',
      'line-width': [
        'interpolate', ['linear'], ['zoom'],
        9, 1, 13, 1.4, 14.5, 1, 16, 0.7,
      ],
      'line-opacity': [
        'interpolate', ['linear'], ['zoom'],
        9, 0.9, 13, 0.9, 14.5, 0.5, 16, 0.32,
      ],
    },
  }, under);
  map.addLayer({
    id: 'district-line-active', type: 'line', source: 'districts',
    paint: {
      'line-color': [
        'case', ['boolean', ['feature-state', 'selected'], false], '#ffffff', '#cfe9ef',
      ],
      'line-width': [
        'case',
        ['boolean', ['feature-state', 'selected'], false], 2.4,
        ['boolean', ['feature-state', 'hover'], false], 1.6,
        0,
      ],
    },
  }, under);

  /* 5b. Everything outside the 12 analysis districts is dimmed so the eye goes
   *     to the ground the analysis actually covers. This sits above the whole
   *     basemap rather than under its first symbol layer: OpenFreeMap draws
   *     roads and place labels after that anchor, so a mask placed there left
   *     the surrounding road network at full brightness. Inside the study area
   *     the mask is a hole, so labels there stay legible. */
  map.addLayer({
    id: 'outside-mask', type: 'fill', source: 'mask',
    paint: { 'fill-color': '#070a0f', 'fill-opacity': 0.55 },
  });

  /* 6. bus — clustered so the city is not carpeted with 2,163 identical dots */
  map.addLayer({
    id: 'bus-cluster', type: 'circle', source: 'bus', filter: ['has', 'point_count'],
    layout: vis(layers.bus),
    paint: {
      'circle-color': 'rgba(221,154,65,0.22)',
      'circle-stroke-color': '#dd9a41',
      'circle-stroke-width': 1,
      'circle-stroke-opacity': 0.55,
      'circle-radius': ['interpolate', ['linear'], ['get', 'point_count'], 2, 8, 40, 15, 200, 24],
    },
  });
  map.addLayer({
    id: 'bus-cluster-count', type: 'symbol', source: 'bus', filter: ['has', 'point_count'],
    layout: {
      'text-field': ['get', 'point_count_abbreviated'],
      'text-size': 10,
      'text-font': ['Noto Sans Regular'],
      ...vis(layers.bus),
    },
    paint: { 'text-color': '#f0d5ae' },
  });
  map.addLayer({
    id: 'bus-point', type: 'circle', source: 'bus', filter: ['!', ['has', 'point_count']],
    layout: vis(layers.bus),
    paint: {
      'circle-color': '#dd9a41',
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, 2, 15, 3.4],
      'circle-opacity': 0.8,
    },
  });

  /* 7. bazaars */
  map.addLayer({
    id: 'bazaar-point', type: 'circle', source: 'bazaars', minzoom: 11,
    layout: vis(layers.bazaars),
    paint: {
      'circle-color': '#b9c6d4',
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, 2.2, 15, 4],
      'circle-opacity': 0.75,
      'circle-stroke-color': '#0a0e13',
      'circle-stroke-width': 0.6,
    },
  });

  /* 8. metro access points, then stations above them.
   *    Entrances are the analytical access points and appear once they can be
   *    told apart; the 10 station fallbacks are drawn hollow so the difference
   *    survives without depending on colour. */
  map.addLayer({
    id: 'access-point', type: 'circle', source: 'access', minzoom: 11.5,
    filter: ['==', ['get', 'access_type'], 'entrance'],
    layout: vis(layers.stations),
    paint: {
      'circle-color': '#35c2d6',
      'circle-radius': [
        'interpolate', ['linear'], ['zoom'],
        11.5, ['case', HOVERED, 3.4, 1.8],
        15, ['case', HOVERED, 8, 4.2],
      ],
      'circle-stroke-color': '#04262c',
      'circle-stroke-width': 0.8,
      'circle-opacity': 0.95,
    },
  });
  map.addLayer({
    id: 'access-fallback', type: 'circle', source: 'access', minzoom: 11.5,
    filter: ['==', ['get', 'access_type'], 'station_fallback'],
    layout: vis(layers.stations),
    paint: {
      'circle-color': 'rgba(0,0,0,0)',
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 11.5, 3, 15, 6],
      'circle-stroke-color': '#35c2d6',
      'circle-stroke-width': ['case', HOVERED, 2.8, 1.4],
    },
  });
  map.addLayer({
    id: 'station-point', type: 'circle', source: 'stations',
    layout: vis(layers.stations),
    paint: {
      'circle-color': '#ffffff',
      'circle-radius': [
        'interpolate', ['linear'], ['zoom'],
        9, ['case', HOVERED, 3.4, 2.2],
        12, ['case', HOVERED, 5.6, 3.6],
        15, ['case', HOVERED, 8.5, 5.5],
      ],
      'circle-stroke-color': '#0a0e13',
      'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 9, 0.8, 14, 1.6],
    },
  });
  map.addLayer({
    id: 'station-label', type: 'symbol', source: 'stations', minzoom: 12.4,
    layout: {
      // Current name first. Several name_en values carry a historical alias in
      // parentheses ("Milliy Bog (Komsomolskaya)"); the map should not put a
      // superseded name on the station. The search still indexes both.
      'text-field': ['coalesce', ['get', 'name'], ['get', 'name_en']],
      'text-font': ['Noto Sans Regular'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 12.4, 10, 15, 12],
      'text-offset': [0, 1.05],
      'text-anchor': 'top',
      'text-optional': true,
      ...vis(layers.stations),
    },
    paint: {
      'text-color': '#dfe8f1',
      'text-halo-color': '#05080c',
      'text-halo-width': 1.4,
    },
  });

  /* 9. a searched station, emphasised until the selection changes */
  map.addSource('station-focus', { type: 'geojson', data: emptyCollection() });
  map.addLayer({
    id: 'station-focus-ring', type: 'circle', source: 'station-focus',
    paint: {
      'circle-color': 'rgba(0,0,0,0)',
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 9, 15, 18],
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 2,
    },
  });

  applyLayerVisibility(store.get());
}

function lineColourExpression() {
  // Build a per-line match from the OSM colour each feature carries, so the
  // mapping is visible in the data rather than hidden in a stylesheet.
  const expr = ['match', ['get', 'ref']];
  for (const feature of data.metroLines.features) {
    expr.push(feature.properties.ref, tuneLineColour(feature.properties.colour));
  }
  expr.push(NEUTRAL_LINE);
  return expr;
}

function tuneLineColour(raw) {
  if (!raw) return NEUTRAL_LINE;
  const key = String(raw).trim().toLowerCase();
  if (NAMED_LINE_COLOURS[key]) return NAMED_LINE_COLOURS[key];
  if (/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(key)) return key;
  return NEUTRAL_LINE;
}

function emptyCollection() {
  return { type: 'FeatureCollection', features: [] };
}

function quantile(values, q) {
  const sorted = values.slice().sort((a, b) => a - b);
  if (!sorted.length) return 1;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

export function densityRampStops() {
  const max = quantile(data.density.features.map((f) => f.properties.density_per_km2), 0.98);
  return { ramp: POP_RAMP, max };
}

/* ── visibility ───────────────────────────────────────────────────────── */
const LAYER_GROUPS = {
  population: ['population-fill'],
  access: ['iso-fill', 'iso-line'],
  metrolines: ['metroline-casing', 'metroline'],
  stations: ['station-point', 'station-label', 'access-point', 'access-fallback'],
  bus: ['bus-cluster', 'bus-cluster-count', 'bus-point'],
  bazaars: ['bazaar-point'],
};

export function applyLayerVisibility(state) {
  /* Deliberately not gated on map.isStyleLoaded(): with nine GeoJSON sources it
   * reports false whenever any of them is still loading, long after the style
   * itself is ready, which silently swallowed every layer toggle. The real
   * precondition is that the layer exists, so that is what is checked. */
  if (!map) return;
  for (const [group, ids] of Object.entries(LAYER_GROUPS)) {
    const visible = state.layers[group] ? 'visible' : 'none';
    for (const id of ids) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible);
    }
  }
}

/* ── interaction ──────────────────────────────────────────────────────── */
let hoveredId = null;
let selectedId = null;
let hoveredPoint = null;

function wireInteraction() {
  map.on('mousemove', 'district-fill', (event) => {
    const feature = event.features && event.features[0];
    if (!feature) return;
    map.getCanvas().style.cursor = 'pointer';
    store.set({ hoveredDistrict: feature.id });
  });

  map.on('mouseleave', 'district-fill', () => {
    map.getCanvas().style.cursor = '';
    store.set({ hoveredDistrict: null });
  });

  map.on('click', 'district-fill', (event) => {
    const feature = event.features && event.features[0];
    if (feature) store.toggleDistrict(feature.id);
  });

  // A click on the map that hit no district releases the selection.
  map.on('click', (event) => {
    const hits = map.queryRenderedFeatures(event.point, { layers: ['district-fill'] });
    if (!hits.length) store.clearSelection();
  });

  for (const layer of ['station-point', 'access-point', 'access-fallback', 'bazaar-point']) {
    const source = layer === 'station-point' ? 'stations'
      : layer === 'bazaar-point' ? 'bazaars' : 'access';

    map.on('mousemove', layer, (event) => {
      map.getCanvas().style.cursor = 'pointer';
      const feature = event.features && event.features[0];
      if (!feature || source === 'bazaars') return;
      if (hoveredPoint && hoveredPoint.id !== feature.id) {
        map.setFeatureState(hoveredPoint, { hover: false });
      }
      hoveredPoint = { source, id: feature.id };
      map.setFeatureState(hoveredPoint, { hover: true });
    });

    map.on('mouseleave', layer, () => {
      map.getCanvas().style.cursor = '';
      if (hoveredPoint) map.setFeatureState(hoveredPoint, { hover: false });
      hoveredPoint = null;
    });

    map.on('click', layer, (event) => {
      const feature = event.features && event.features[0];
      if (feature) showFeaturePopup(layer, feature, event.lngLat);
    });
  }

  map.on('click', 'bus-cluster', (event) => {
    const feature = map.queryRenderedFeatures(event.point, { layers: ['bus-cluster'] })[0];
    if (!feature) return;
    map.getSource('bus').getClusterExpansionZoom(feature.properties.cluster_id)
      .then((zoom) => map.easeTo({ center: feature.geometry.coordinates, zoom }))
      .catch(() => { /* cluster gone after a re-render; nothing to do */ });
  });
  map.on('mouseenter', 'bus-cluster', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'bus-cluster', () => { map.getCanvas().style.cursor = ''; });
}

/* Popups are built as DOM nodes. Every name below is OSM-authored, so it is
 * assigned as text and never parsed as markup. */
function showFeaturePopup(layer, feature, lngLat) {
  const p = feature.properties || {};
  let title;
  let rows = [];
  let foot = null;

  if (layer === 'station-point') {
    title = safeName(p.name, safeName(p.name_en, 'Metro station'));
    rows = [kv('Type', 'Metro station')];
    if (p.district_name) rows.push(kv('District', safeName(p.district_name, '—')));
  } else if (layer === 'bazaar-point') {
    title = safeName(p.name, safeName(p.name_ru, 'Marketplace'));
    rows = [kv('Type', 'Bazaar')];
    if (p.district_name) rows.push(kv('District', safeName(p.district_name, '—')));
  } else {
    title = safeName(p.name, 'Metro access point');
    rows = [kv('Type', safeName(p.kind_label, 'Metro access point'))];
    if (p.district_name) rows.push(kv('District', safeName(p.district_name, '—')));
    foot = safeName(p.detail, null);
  }

  const node = el('div', {}, [
    el('span', { class: 'tip-name', text: title }),
    ...rows,
    foot ? el('span', { class: 'tip-foot', text: foot }) : null,
  ]);
  popup.setLngLat(lngLat).setDOMContent(node).addTo(map);
}

/* ── state -> map ─────────────────────────────────────────────────────── */
export function syncMap(state) {
  // Same reason as applyLayerVisibility: isStyleLoaded() is not a readiness
  // signal here. Each operation guards on the source it actually needs.
  if (!map || !map.getSource('districts')) return;

  if (hoveredId !== state.hoveredDistrict) {
    if (hoveredId) map.setFeatureState({ source: 'districts', id: hoveredId }, { hover: false });
    hoveredId = state.hoveredDistrict;
    if (hoveredId) map.setFeatureState({ source: 'districts', id: hoveredId }, { hover: true });
  }

  if (selectedId !== state.selectedDistrict) {
    if (selectedId) map.setFeatureState({ source: 'districts', id: selectedId }, { selected: false });
    selectedId = state.selectedDistrict;
    if (selectedId) map.setFeatureState({ source: 'districts', id: selectedId }, { selected: true });
  }

  const focus = map.getSource('station-focus');
  if (focus) {
    focus.setData(
      state.selectedStation
        ? {
            type: 'FeatureCollection',
            features: [{
              type: 'Feature', properties: {},
              geometry: { type: 'Point', coordinates: [state.selectedStation.lon, state.selectedStation.lat] },
            }],
          }
        : emptyCollection(),
    );
  }
}

/* ── camera ───────────────────────────────────────────────────────────── */
/* Someone who has asked their system for reduced motion should not be flown
 * across the city; they still get the same camera, just without the journey. */
function motionDuration(ms) {
  const reduced = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  return reduced ? 0 : ms;
}

export function fitCity(animate = true) {
  if (!map) return;
  map.fitBounds(bounds, { padding: mapPadding(), duration: animate ? motionDuration(700) : 0 });
}

export function flyToDistrict(feature) {
  if (!map || !feature) return;
  const b = new maplibregl.LngLatBounds();
  eachPosition(feature.geometry, ([lng, lat]) => b.extend([lng, lat]));
  map.fitBounds(b, { padding: mapPadding(), duration: motionDuration(800), maxZoom: 13.5 });
}

export function flyToStation(station) {
  if (!map || !station) return;
  map.flyTo({ center: [station.lon, station.lat], zoom: 14.4, duration: motionDuration(900) });
}

export function zoomBy(delta) {
  if (map) map.easeTo({ zoom: map.getZoom() + delta, duration: motionDuration(240) });
}

export function popupClose() {
  if (popup) popup.remove();
}

export function tooltipRowsForDistrict(p) {
  return [
    el('span', { class: 'tip-name', text: p.label }),
    kv('Population', fmt.people(p.official_population)),
    kv('Metro access', fmt.pct(p.metro_access_pct)),
    kv('Bus-only', fmt.pct(p.bus_only_pct)),
    kv('Underserved', fmt.pct(p.underserved_pct)),
    kv('Density', fmt.density(p.population_density_per_km2)),
  ];
}
