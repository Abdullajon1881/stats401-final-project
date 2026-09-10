/* One authoritative interaction state.
 *
 * The map and the D3 ranking are two views over the same selection. Neither
 * owns it: both write through `set` and both re-render from `subscribe`, so a
 * district highlighted by a hover on the map and one highlighted by a hover on
 * the chart are the same fact rather than two copies that can drift.
 *
 * Selection has exactly three modes, and they are mutually exclusive:
 *
 *   CITY      selectedDistrict === null  &&  selectedStation === null
 *   DISTRICT  selectedDistrict !== null  &&  selectedStation === null
 *   STATION   selectedDistrict === null  &&  selectedStation !== null
 *
 * That is enforced inside `set` rather than left to each caller to remember.
 * The previous version cleared the station when a district was chosen but not
 * the reverse, so searching for a station while a district was selected left
 * the map ringing the station while the sidebar still described the district.
 * Normalising centrally means no future caller can reintroduce that.
 *
 * `comparisonDistricts` is a SEPARATE axis and deliberately not part of that
 * invariant. Selection is "the one district the whole application is currently
 * about"; comparison is "the handful of districts pinned side by side in the
 * profile chart". Selecting a district must not silently pin it, and clearing
 * the comparison set must not deselect anything - they answer different
 * questions and a user has to ask for each one explicitly.
 */

/** A profile comparison stops being readable well before this; four lines on
 *  six axes is already dense. The cap is enforced in the store so no caller
 *  can exceed it. */
export const MAX_COMPARISON = 4;

const state = {
  selectedDistrict: null,   // district_name, or null
  hoveredDistrict: null,    // district_name, or null
  selectedStation: null,    // { name, district_name, lon, lat }, or null
  comparisonDistricts: [],  // 0..MAX_COMPARISON district_names, pinned deliberately
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

/**
 * Apply a patch, enforce the selection invariant, notify.
 * `changed` names every key that actually moved, including keys the invariant
 * cleared rather than the caller.
 */
export function set(patch) {
  const next = { ...patch };

  if ('selectedStation' in next && next.selectedStation !== null) {
    // Entering station mode. A district left selected here would put the map
    // and the sidebar in two different modes at once.
    next.selectedDistrict = null;
    next.hoveredDistrict = null;
  } else if ('selectedDistrict' in next && next.selectedDistrict !== null) {
    next.selectedStation = null;
  }

  const changed = [];
  for (const [key, value] of Object.entries(next)) {
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

/** Enter district mode. The invariant in `set` clears any selected station. */
export function selectDistrict(name) {
  set({ selectedDistrict: name, selectedStation: null });
}

/** Enter station mode. The invariant in `set` clears any selected district. */
export function selectStation(station) {
  set({ selectedStation: station, selectedDistrict: null, hoveredDistrict: null });
}

/** Clicking an already-selected district releases it. */
export function toggleDistrict(name) {
  if (state.selectedDistrict === name) clearSelection();
  else selectDistrict(name);
}

/** Back to city mode. */
export function clearSelection() {
  set({ selectedDistrict: null, selectedStation: null, hoveredDistrict: null });
}

/* ── comparison set ───────────────────────────────────────────────────────
 *
 * Membership is replaced rather than mutated in place, so a subscriber can
 * compare by identity to know whether the set actually moved.
 */

export function isCompared(name) {
  return state.comparisonDistricts.includes(name);
}

export function comparisonIsFull() {
  return state.comparisonDistricts.length >= MAX_COMPARISON;
}

/** Pin a district. No-op when already pinned or when the set is full. */
export function addToComparison(name) {
  if (!name || isCompared(name) || comparisonIsFull()) return false;
  state.comparisonDistricts = [...state.comparisonDistricts, name];
  notify(['comparisonDistricts']);
  return true;
}

export function removeFromComparison(name) {
  if (!isCompared(name)) return false;
  state.comparisonDistricts = state.comparisonDistricts.filter((d) => d !== name);
  notify(['comparisonDistricts']);
  return true;
}

export function toggleComparison(name) {
  return isCompared(name) ? removeFromComparison(name) : addToComparison(name);
}

/** Empty the comparison set. Selection is a different axis and is untouched. */
export function clearComparison() {
  if (state.comparisonDistricts.length === 0) return;
  state.comparisonDistricts = [];
  notify(['comparisonDistricts']);
}

/** True when the three-mode invariant holds. Exercised by the QA suite. */
export function invariantHolds() {
  return !(state.selectedDistrict !== null && state.selectedStation !== null);
}

/** True when the comparison set is within its bound and free of duplicates. */
export function comparisonInvariantHolds() {
  const set = state.comparisonDistricts;
  return set.length <= MAX_COMPARISON && new Set(set).size === set.length;
}

function notify(changed) {
  for (const fn of listeners) fn(state, changed);
}
