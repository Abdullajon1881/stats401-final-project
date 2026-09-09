/* One authoritative interaction state.
 *
 * The map and the D3 ranking are two views over the same selection. Neither
 * owns it: both write through `set` and both re-render from `subscribe`, so a
 * district highlighted by a hover on the map and one highlighted by a hover on
 * the chart are the same fact rather than two copies that can drift.
 */

const state = {
  selectedDistrict: null,   // district_name, or null
  hoveredDistrict: null,    // district_name, or null
  selectedStation: null,    // { name, lon, lat, kind }, or null
  searchQuery: '',
  view: 'overview',         // overview | districts
  mapReady: false,
  layers: {
    population: true,
    access: true,
    metrolines: true,
    stations: true,
    bus: false,
    bazaars: false,
  },
};

const listeners = new Set();

export function get() {
  return state;
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Shallow-merge a patch and notify. `changed` names the touched keys. */
export function set(patch) {
  const changed = [];
  for (const [key, value] of Object.entries(patch)) {
    if (state[key] !== value) {
      state[key] = value;
      changed.push(key);
    }
  }
  if (changed.length) notify(changed);
}

export function setLayer(name, visible) {
  if (state.layers[name] === visible) return;
  state.layers[name] = visible;
  notify(['layers']);
}

/** Clicking an already-selected district releases it. */
export function toggleDistrict(name) {
  set({
    selectedDistrict: state.selectedDistrict === name ? null : name,
    selectedStation: null,
  });
}

export function clearSelection() {
  set({ selectedDistrict: null, selectedStation: null, hoveredDistrict: null });
}

function notify(changed) {
  for (const fn of listeners) fn(state, changed);
}
