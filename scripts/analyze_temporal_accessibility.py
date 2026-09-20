"""Phase 2B: standardized 2015-2026 metro-accessibility comparison.

Run from the repository root:

    python scripts/analyze_temporal_accessibility.py

The analysis holds the audited current pedestrian network, current station-
centre positions, routing method, walking speed and threshold fixed. Only the
source-backed set of open metro stations and the annual raw WorldPop model
weights change. This is a standardized temporal comparison, not a literal
historical reconstruction.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))

import accessibility_utils as au  # noqa: E402
import config as cfg  # noqa: E402
import temporal_accessibility as ta  # noqa: E402
from pipeline_utils import log, step  # noqa: E402


EXPECTED_ANNUAL_STATION_COUNTS = {
    2015: 29,
    2016: 29,
    2017: 29,
    2018: 29,
    2019: 29,
    2020: 43,
    2021: 43,
    2022: 43,
    2023: 48,
    2024: 50,
    2025: 50,
    2026: 50,
}
EXPECTED_EVENT_ADDITIONS = {2020: 14, 2023: 5, 2024: 2}
DISTANCE_TOLERANCE_M = 1e-7
CURRENT_HEADLINE_PCT = 13.563595724255597


def relative(path: Path) -> str:
    return str(path.relative_to(cfg.REPO_ROOT)).replace("\\", "/")


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def distance_diagnostics(values: np.ndarray) -> dict:
    finite = values[np.isfinite(values)]
    percentiles = np.percentile(finite, [50, 95, 99])
    return {
        "count": int(values.size),
        "finite_count": int(finite.size),
        "infinite_count": int(values.size - finite.size),
        "min_m": float(finite.min()),
        "median_m": float(percentiles[0]),
        "p95_m": float(percentiles[1]),
        "p99_m": float(percentiles[2]),
        "max_m": float(finite.max()),
    }


def load_inputs() -> tuple[dict, dict, dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    required = (
        cfg.PHASE2_SOURCE_MANIFEST_PATH,
        cfg.MANIFEST_PATH,
        cfg.ANALYSIS_MANIFEST_PATH,
        cfg.WORLDPOP_TEMPORAL_CELL_CACHE,
        cfg.WALK_GRAPH_FILE,
        cfg.METRO_STATION_HISTORY_FILE,
        cfg.WORLDPOP_DISTRICT_YEAR_FILE,
        cfg.DISTRICTS_FILE,
    )
    missing = [relative(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"required Phase 2B inputs are missing: {missing}. Rebuild them with the "
            "existing acquisition/analysis pipelines; do not synthesize replacements."
        )

    phase2 = json.loads(cfg.PHASE2_SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    source = json.loads(cfg.MANIFEST_PATH.read_text(encoding="utf-8"))
    current = json.loads(cfg.ANALYSIS_MANIFEST_PATH.read_text(encoding="utf-8"))
    expected_cache_sha = phase2["worldpop"]["cell_cache"]["sha256"]
    actual_cache_sha = cfg.sha256_file(cfg.WORLDPOP_TEMPORAL_CELL_CACHE)
    if actual_cache_sha != expected_cache_sha:
        raise ValueError(
            "temporal cell cache SHA-256 differs from the Phase 2A manifest; stop and "
            "rebuild it with scripts/acquire_temporal_population.py"
        )

    cells = pd.read_csv(
        cfg.WORLDPOP_TEMPORAL_CELL_CACHE,
        dtype={"cell_id": str, "district_id": str},
    ).sort_values("cell_id", kind="stable").reset_index(drop=True)
    stations = pd.read_csv(
        cfg.METRO_STATION_HISTORY_FILE,
        dtype={"station_id": str, "current_osm_id": str},
    ).sort_values("station_id", kind="stable").reset_index(drop=True)
    district_year = pd.read_csv(
        cfg.WORLDPOP_DISTRICT_YEAR_FILE,
        dtype={"district_id": str},
    ).sort_values(["district_id", "year"], kind="stable").reset_index(drop=True)
    return phase2, source, current, cells, stations, district_year


def district_name_map() -> dict[str, str]:
    districts = gpd.read_file(cfg.DISTRICTS_FILE)
    districts = districts[districts.in_siat.astype(bool)].copy()
    if len(districts) != cfg.EXPECTED_ANALYSIS_DISTRICTS:
        raise ValueError(f"expected 12 fixed-geography districts, got {len(districts)}")
    if districts.siat_code.astype(str).duplicated().any():
        raise ValueError("canonical district geometry contains duplicate SIAT codes")
    return dict(
        zip(districts.siat_code.astype(str), districts.district_name.astype(str))
    )


def verify_inputs(cells: pd.DataFrame, stations: pd.DataFrame) -> None:
    expected_columns = {
        "cell_id", "district_id", "lon", "lat",
        *(f"pop_{year}" for year in cfg.TEMPORAL_YEARS),
    }
    missing = sorted(expected_columns - set(cells.columns))
    if missing:
        raise ValueError(f"temporal cell cache missing columns: {missing}")
    if len(cells) != 65_169 or cells.cell_id.duplicated().any():
        raise ValueError(
            f"expected 65,169 unique temporal cells, got {len(cells):,} rows and "
            f"{cells.cell_id.nunique():,} unique IDs"
        )
    if len(stations) != 50 or stations.station_id.duplicated().any():
        raise ValueError("expected exactly 50 unique station-history rows")


def main() -> int:  # noqa: PLR0915 - linear analysis pipeline is intentional
    cfg.ensure_directories()
    step("STEP 1  Load and verify authoritative Phase 2 inputs")
    phase2, source, current, cells, stations, district_year = load_inputs()
    verify_inputs(cells, stations)
    names = district_name_map()
    if set(cells.district_id) != set(names):
        raise ValueError("temporal cells do not use exactly the fixed 12-district IDs")
    log(f"  temporal cells: {len(cells):,}")
    log(f"  station history: {len(stations):,}")
    log(f"  temporal cache SHA-256: {cfg.sha256_file(cfg.WORLDPOP_TEMPORAL_CELL_CACHE)}")

    step("STEP 2  Derive source-backed metro routing states")
    states, year_to_state = ta.derive_metro_states(stations, cfg.TEMPORAL_YEARS)
    counts = {
        year: next(s.open_station_count for s in states if s.state_id == state_id)
        for year, state_id in year_to_state.items()
    }
    if counts != EXPECTED_ANNUAL_STATION_COUNTS:
        raise ValueError(
            f"source-derived annual station counts differ from the audited expectation: {counts}"
        )
    if len(states) != 4:
        raise ValueError(f"expected four unique source states, got {len(states)}")
    for state in states:
        log(
            f"  {state.state_id}: {state.first_year}-{state.last_year}, "
            f"{state.open_station_count} stations"
        )

    step("STEP 3  Load the fixed current pedestrian network")
    recorded = source["walk_network"]
    network = au.load_walk_network(
        cfg.WALK_GRAPH_FILE,
        expected_nodes=recorded["nodes"],
        expected_edge_records=recorded["edges"],
    )
    current_network = current["network"]
    if (
        network.n_nodes != current_network["nodes"]
        or network.stats["stored_edge_records"] != current_network["stored_edge_records"]
        or network.n_edges != current_network["canonical_routing_edges"]
    ):
        raise ValueError("canonical network differs from the audited current analysis")
    graph_sha = cfg.sha256_file(cfg.WALK_GRAPH_FILE)
    log(f"  graph SHA-256: {graph_sha}")
    log(f"  nodes: {network.n_nodes:,}; canonical edges: {network.n_edges:,}")
    edge_tree = au.build_edge_index(network)

    step("STEP 4  Snap all station centres and fixed population cells once")
    transformer = Transformer.from_crs(
        cfg.GEOGRAPHIC_CRS, cfg.METRIC_CRS, always_xy=True
    )
    station_x, station_y = transformer.transform(
        stations.longitude.to_numpy(dtype=float),
        stations.latitude.to_numpy(dtype=float),
    )
    station_snap = au.snap_points_to_edges(
        network, np.column_stack([station_x, station_y]), tree=edge_tree
    )
    station_diag = au.connector_diagnostics(
        "all_station_centres", station_snap.connector_m
    )
    station_place = au.snap_placement_stats(
        station_snap, network, endpoint_tol_m=cfg.EDGE_ENDPOINT_TOLERANCE_M
    )

    cell_x, cell_y = transformer.transform(
        cells.lon.to_numpy(dtype=float), cells.lat.to_numpy(dtype=float)
    )
    cell_snap = au.snap_points_to_edges(
        network, np.column_stack([cell_x, cell_y]), tree=edge_tree
    )
    cell_diag = au.connector_diagnostics("temporal_population_cells", cell_snap.connector_m)
    ta.write_deterministic_npz(
        cfg.PHASE2_CELL_SNAP_CACHE,
        [
            ("cell_id", cells.cell_id.to_numpy(dtype=str)),
            ("edge_index", cell_snap.edge_index),
            ("edge_fraction", cell_snap.fraction),
            ("edge_connector_m", cell_snap.connector_m),
        ],
    )
    log(
        "  station connectors (m): "
        f"min {station_diag['min_m']:.3f}, median {station_diag['median_m']:.3f}, "
        f"p95 {station_diag['p95_m']:.3f}, p99 {station_diag['p99_m']:.3f}, "
        f"max {station_diag['max_m']:.3f}"
    )
    log(
        "  cell connectors (m): "
        f"min {cell_diag['min_m']:.3f}, median {cell_diag['median_m']:.3f}, "
        f"p95 {cell_diag['p95_m']:.3f}, p99 {cell_diag['p99_m']:.3f}, "
        f"max {cell_diag['max_m']:.3f}"
    )

    step("STEP 5  Run one multi-source Dijkstra per distinct source state")
    station_index = {station_id: i for i, station_id in enumerate(stations.station_id)}
    distances: dict[str, np.ndarray] = {}
    access_masks: dict[str, np.ndarray] = {}
    state_diagnostics: list[dict] = []
    for state in states:
        indices = np.asarray(
            [station_index[station_id] for station_id in state.active_station_ids],
            dtype=np.int64,
        )
        active_snap = ta.subset_edge_snap(station_snap, indices)
        augmented = au.build_augmented_network(network, active_snap)
        node_distances = au.multi_source_distances(
            network, augmented, active_snap.connector_m
        )
        total = cell_snap.connector_m + au.query_positions(
            augmented,
            node_distances,
            cell_snap.edge_index,
            cell_snap.fraction,
        )
        if np.isnan(total).any() or (total < 0).any():
            raise ValueError(f"{state.state_id} produced invalid cell distances")
        accessible = total <= cfg.PHASE2_ACCESS_DISTANCE_BUDGET_M
        distances[state.state_id] = total
        access_masks[state.state_id] = accessible
        state_diagnostics.append(
            {
                "state_id": state.state_id,
                "first_year": state.first_year,
                "last_year": state.last_year,
                "years": list(state.years),
                "open_station_count": state.open_station_count,
                "active_station_ids": list(state.active_station_ids),
                "active_station_ids_sha256": ta.active_station_ids_sha256(
                    state.active_station_ids
                ),
                "accessible_cell_count": int(accessible.sum()),
                "finite_distance_cell_count": int(np.isfinite(total).sum()),
                "station_connector_diagnostics": au.connector_diagnostics(
                    state.state_id, active_snap.connector_m
                ),
                "station_snap_placement": au.snap_placement_stats(
                    active_snap,
                    network,
                    endpoint_tol_m=cfg.EDGE_ENDPOINT_TOLERANCE_M,
                ),
                "distance_diagnostics": distance_diagnostics(total),
                "augmentation": augmented.stats,
            }
        )
        log(
            f"  {state.state_id}: accessible {int(accessible.sum()):,}; "
            f"finite distances {int(np.isfinite(total).sum()):,}/{len(total):,}"
        )

    distance_violations = 0
    access_violations = 0
    for earlier, later in zip(states, states[1:]):
        distance_violations += int(
            np.count_nonzero(
                distances[later.state_id]
                > distances[earlier.state_id] + DISTANCE_TOLERANCE_M
            )
        )
        access_violations += int(
            np.count_nonzero(
                access_masks[earlier.state_id] & ~access_masks[later.state_id]
            )
        )
    if distance_violations or access_violations:
        raise ValueError(
            "nested source states violated routing monotonicity: "
            f"{distance_violations} distance and {access_violations} access violations"
        )

    ta.write_deterministic_npz(
        cfg.PHASE2_DISTANCE_CACHE,
        [
            ("cell_id", cells.cell_id.to_numpy(dtype=str)),
            ("state_id", np.asarray([state.state_id for state in states], dtype=str)),
            *[
                (f"distance_{state.state_id}", distances[state.state_id])
                for state in states
            ],
        ],
    )

    routing_diagnostic = {
        "analysis_version": cfg.PHASE2_ACCESS_ANALYSIS_VERSION,
        "routing_crs": cfg.METRIC_CRS,
        "distance_threshold_m": cfg.PHASE2_ACCESS_DISTANCE_BUDGET_M,
        "walking_speed_kmh": cfg.MAIN_WALK_SPEED_KMH,
        "walking_time_minutes": cfg.WALK_TIME_LIMIT_MINUTES,
        "station_source_rule": (
            "current station-centre coordinates fixed for every year; include a station "
            "when opening_year <= analytical year"
        ),
        "population_cell_rule": (
            "fixed union-valid WorldPop cell centres snapped once; annual missing "
            "population remains missing"
        ),
        "network": {
            "source_file": relative(cfg.WALK_GRAPH_FILE),
            "sha256": graph_sha,
            "nodes": network.n_nodes,
            "stored_edge_records": network.stats["stored_edge_records"],
            "canonical_routing_edges": network.n_edges,
            "canonicalisation": network.stats["canonicalisation"],
        },
        "cell_order": {
            "sort": "cell_id ascending",
            "count": int(len(cells)),
            "first_cell_id": str(cells.cell_id.iloc[0]),
            "last_cell_id": str(cells.cell_id.iloc[-1]),
        },
        "dijkstra_runs": len(states),
        "station_connector_diagnostics_all_50": station_diag,
        "station_snap_placement_all_50": station_place,
        "population_cell_connector_diagnostics": cell_diag,
        "monotonic_distance_tolerance_m": DISTANCE_TOLERANCE_M,
        "monotonic_distance_violations": distance_violations,
        "nested_access_mask_violations": access_violations,
        "states": state_diagnostics,
    }
    ta.write_json_lf(cfg.PHASE2_ROUTING_STATES_FILE, routing_diagnostic)

    step("STEP 6  Aggregate annual city and district series")
    phase2_lookup = district_year.set_index(["district_id", "year"])
    cell_district_ids = cells.district_id.to_numpy(dtype=str)
    reconciled_population: dict[int, np.ndarray] = {}
    reconciliation_factors: list[float] = []
    for year in cfg.TEMPORAL_YEARS:
        values = pd.to_numeric(cells[f"pop_{year}"], errors="coerce").to_numpy(float)
        values = values.copy()
        for district_id in sorted(names):
            district_mask = cell_district_ids == district_id
            finite = district_mask & np.isfinite(values)
            serialized_total = float(values[finite].sum(dtype=np.float64))
            phase2_total = float(phase2_lookup.loc[(district_id, year)].population_modelled)
            if serialized_total <= 0:
                raise ValueError(f"{district_id}/{year} has no positive serialized population")
            factor = phase2_total / serialized_total
            values[finite] *= factor
            reconciliation_factors.append(factor)
        reconciled_population[year] = values
    max_reconciliation_deviation = max(
        abs(factor - 1.0) for factor in reconciliation_factors
    )
    log(
        "  reconciled six-decimal cell-cache serialization to Phase 2A district "
        f"totals (maximum multiplicative deviation {max_reconciliation_deviation:.3e})"
    )

    city_rows: list[dict] = []
    district_rows: list[dict] = []
    district_2015_pct: dict[str, float] = {}

    for year in cfg.TEMPORAL_YEARS:
        state_id = year_to_state[year]
        state = next(state for state in states if state.state_id == state_id)
        population = reconciled_population[year]
        accessible = access_masks[state_id]
        finite = np.isfinite(population)
        raw_denominator, raw_numerator, _ = ta.weighted_access(
            population, accessible
        )

        year_district_rows: list[dict] = []
        for district_id in sorted(names):
            district_mask = cell_district_ids == district_id
            denominator, numerator, _ = ta.weighted_access(
                population[district_mask], accessible[district_mask]
            )
            denominator = round(denominator, 6)
            numerator = round(numerator, 6)
            published = phase2_lookup.loc[(district_id, year)]
            published_denominator = float(published.population_modelled)
            if denominator != published_denominator:
                raise ValueError(
                    f"{district_id}/{year} denominator {denominator} does not equal "
                    f"Phase 2A {published_denominator} at committed precision"
                )
            percentage = 100.0 * numerator / denominator
            if year == cfg.TEMPORAL_START_YEAR:
                district_2015_pct[district_id] = percentage
            row = {
                "district_id": district_id,
                "district_name": names[district_id],
                "year": year,
                "metro_state_id": state_id,
                "open_station_count": state.open_station_count,
                "population_modelled_available": denominator,
                "population_growth_pct_from_2015": float(
                    published.population_growth_pct_from_2015
                ),
                "metro_access_population_standardized": numerator,
                "metro_access_pct_standardized": round(percentage, 9),
                "metro_access_pct_change_from_2015_pp": round(
                    percentage - district_2015_pct[district_id], 9
                ),
                "population_model_status": str(published.population_model_status),
                "population_projection_flag": year in phase2["worldpop"]["projected_years"],
                "geography_version": str(published.geography_version),
            }
            year_district_rows.append(row)
            district_rows.append(row)

        city_denominator = round(
            sum(row["population_modelled_available"] for row in year_district_rows), 6
        )
        city_numerator = round(
            sum(row["metro_access_population_standardized"] for row in year_district_rows),
            6,
        )
        if round(raw_denominator, 6) != city_denominator:
            raise ValueError(f"{year} city denominator does not reconcile with districts")
        if abs(round(raw_numerator, 6) - city_numerator) > 0.00001:
            raise ValueError(f"{year} city numerator does not reconcile with districts")
        city_pct = 100.0 * city_numerator / city_denominator
        baseline_pct = (
            city_pct if year == cfg.TEMPORAL_START_YEAR else city_rows[0]["_pct_unrounded"]
        )
        city_rows.append(
            {
                "year": year,
                "metro_state_id": state_id,
                "open_station_count": state.open_station_count,
                "population_modelled_available": city_denominator,
                "metro_access_population_standardized": city_numerator,
                "metro_access_pct_standardized": round(city_pct, 9),
                "metro_access_pct_change_from_2015_pp": round(city_pct - baseline_pct, 9),
                "population_model_status": cfg.WORLDPOP_TEMPORAL_MODEL_STATUS,
                "population_projection_flag": year in phase2["worldpop"]["projected_years"],
                "worldpop_release": cfg.WORLDPOP_TEMPORAL_RELEASE,
                "temporal_reference": cfg.WORLDPOP_TEMPORAL_REFERENCE_DATE,
                "geography_version": cfg.TEMPORAL_GEOGRAPHY_VERSION,
                "_pct_unrounded": city_pct,
            }
        )

    city = pd.DataFrame(city_rows).drop(columns="_pct_unrounded")
    district = pd.DataFrame(district_rows).sort_values(
        ["district_id", "year"], kind="stable"
    ).reset_index(drop=True)
    write_csv(city, cfg.PHASE2_ACCESS_CITY_FILE)
    write_csv(district, cfg.PHASE2_ACCESS_DISTRICT_FILE)
    log(f"  wrote {cfg.PHASE2_ACCESS_CITY_FILE.name}: {len(city)} rows")
    log(f"  wrote {cfg.PHASE2_ACCESS_DISTRICT_FILE.name}: {len(district)} rows")

    step("STEP 7  Metro expansion events and counterfactual diagnostics")
    city_by_year = city.set_index("year")
    event_rows: list[dict] = []
    for year in cfg.TEMPORAL_YEARS[1:]:
        previous_year = year - 1
        if year_to_state[year] == year_to_state[previous_year]:
            continue
        before = EXPECTED_ANNUAL_STATION_COUNTS[previous_year]
        after = EXPECTED_ANNUAL_STATION_COUNTS[year]
        additions = stations.loc[
            stations.opening_year.astype(int) == year, "station_name_current"
        ].astype(str).tolist()
        additions = sorted(additions)
        if len(additions) != EXPECTED_EVENT_ADDITIONS.get(year):
            raise ValueError(f"{year} station additions do not match the source-derived delta")
        previous_pct = float(city_by_year.loc[previous_year].metro_access_pct_standardized)
        event_pct = float(city_by_year.loc[year].metro_access_pct_standardized)
        event_rows.append(
            {
                "year": year,
                "previous_metro_state_id": year_to_state[previous_year],
                "new_metro_state_id": year_to_state[year],
                "stations_before": before,
                "stations_after": after,
                "stations_added": after - before,
                "station_names_added": " | ".join(additions),
                "city_access_pct_previous_year": previous_pct,
                "city_access_pct_event_year": event_pct,
                "city_access_change_pp": round(event_pct - previous_pct, 9),
                "change_interpretation": "combined annual standardized change",
            }
        )
    events = pd.DataFrame(event_rows)
    write_csv(events, cfg.PHASE2_ACCESS_EVENTS_FILE)

    population_2015 = reconciled_population[2015]
    baseline_mask = access_masks[year_to_state[2015]]
    counterfactual_rows: list[dict] = []
    for year in cfg.TEMPORAL_YEARS:
        population = reconciled_population[year]
        state_mask = access_masks[year_to_state[year]]
        _, _, network_fixed_population = ta.weighted_access(population_2015, state_mask)
        _, _, population_fixed_network = ta.weighted_access(population, baseline_mask)
        counterfactual_rows.append(
            {
                "year": year,
                "metro_state_id": year_to_state[year],
                "actual_standardized_pct": float(
                    city_by_year.loc[year].metro_access_pct_standardized
                ),
                "network_change_on_2015_population_pct": round(
                    network_fixed_population, 9
                ),
                "population_change_under_2015_network_pct": round(
                    population_fixed_network, 9
                ),
            }
        )
    counterfactual = pd.DataFrame(counterfactual_rows)
    write_csv(counterfactual, cfg.PHASE2_ACCESS_COUNTERFACTUAL_FILE)
    log(f"  wrote {cfg.PHASE2_ACCESS_EVENTS_FILE.name}: {len(events)} rows")
    log(
        f"  wrote {cfg.PHASE2_ACCESS_COUNTERFACTUAL_FILE.name}: "
        f"{len(counterfactual)} rows"
    )

    step("STEP 8  Deterministic Phase 2B analysis manifest")
    generated_outputs = (
        cfg.PHASE2_ACCESS_CITY_FILE,
        cfg.PHASE2_ACCESS_DISTRICT_FILE,
        cfg.PHASE2_ACCESS_EVENTS_FILE,
        cfg.PHASE2_ACCESS_COUNTERFACTUAL_FILE,
        cfg.PHASE2_ROUTING_STATES_FILE,
    )
    standardized_2026 = float(city_by_year.loc[2026].metro_access_pct_standardized)
    manifest = {
        "analysis": "Phase 2B standardized temporal metro accessibility",
        "analysis_version": cfg.PHASE2_ACCESS_ANALYSIS_VERSION,
        "comparison_design": "standardized temporal comparison",
        "input_files": {
            relative(path): {"sha256": cfg.sha256_file(path), "size_bytes": path.stat().st_size}
            for path in (
                cfg.PHASE2_SOURCE_MANIFEST_PATH,
                cfg.MANIFEST_PATH,
                cfg.ANALYSIS_MANIFEST_PATH,
                cfg.WORLDPOP_TEMPORAL_CELL_CACHE,
                cfg.WALK_GRAPH_FILE,
                cfg.METRO_STATION_HISTORY_FILE,
                cfg.WORLDPOP_DISTRICT_YEAR_FILE,
                cfg.DISTRICTS_FILE,
            )
        },
        "cell_cache": {
            "path": relative(cfg.WORLDPOP_TEMPORAL_CELL_CACHE),
            "sha256": cfg.sha256_file(cfg.WORLDPOP_TEMPORAL_CELL_CACHE),
            "rows": int(len(cells)),
            "annual_nodata_treatment": "exclude missing values from each annual denominator; never replace with numeric zero",
        },
        "pedestrian_network": {
            "path": relative(cfg.WALK_GRAPH_FILE),
            "sha256": graph_sha,
            "fixed_current_snapshot": True,
            "routing_crs": cfg.METRIC_CRS,
            "nodes": network.n_nodes,
            "stored_edge_records": network.stats["stored_edge_records"],
            "canonical_routing_edges": network.n_edges,
        },
        "routing": {
            "engine": "scripts/accessibility_utils.py edge-aware primitives",
            "walking_speed_kmh": cfg.MAIN_WALK_SPEED_KMH,
            "walking_time_minutes": cfg.WALK_TIME_LIMIT_MINUTES,
            "distance_budget_m": cfg.PHASE2_ACCESS_DISTANCE_BUDGET_M,
            "station_source_rule": "current station-centre coordinates fixed across years; opening_year <= year",
            "source_sets": [
                {
                    "state_id": state.state_id,
                    "years": list(state.years),
                    "open_station_count": state.open_station_count,
                    "active_station_ids_sha256": ta.active_station_ids_sha256(
                        state.active_station_ids
                    ),
                }
                for state in states
            ],
            "unique_routing_states": len(states),
            "dijkstra_runs": len(states),
            "routing_state_diagnostics": relative(cfg.PHASE2_ROUTING_STATES_FILE),
        },
        "population_weighting": {
            "source": "WorldPop Global 2 R2025A v1 annual modelled estimates",
            "calibrated_to_siat": False,
            "temporal_reference": cfg.WORLDPOP_TEMPORAL_REFERENCE_DATE,
            "fixed_geography": cfg.TEMPORAL_GEOGRAPHY_VERSION,
            "rule": "sum finite raw annual model weights; annual missing remains missing",
            "cell_cache_serialization_reconciliation": {
                "reason": (
                    "Phase 2A stores each cell value to six decimals while its district "
                    "table stores totals computed before that serialization. Within each "
                    "district-year, finite cached weights are multiplied by the Phase 2A "
                    "total divided by their serialized sum so committed denominators "
                    "reconcile exactly. This is not SIAT calibration."
                ),
                "maximum_absolute_multiplicative_deviation_from_one": max_reconciliation_deviation,
                "missing_values_preserved": True,
            },
        },
        "bus_history_used": False,
        "distance_cache": {
            "path": relative(cfg.PHASE2_DISTANCE_CACHE),
            "sha256": cfg.sha256_file(cfg.PHASE2_DISTANCE_CACHE),
            "tracked": False,
            "state_order": [state.state_id for state in states],
            "cell_order": "cell_id ascending",
        },
        "cell_snap_cache": {
            "path": relative(cfg.PHASE2_CELL_SNAP_CACHE),
            "sha256": cfg.sha256_file(cfg.PHASE2_CELL_SNAP_CACHE),
            "tracked": False,
        },
        "output_files": {
            relative(path): {"sha256": cfg.sha256_file(path), "rows": (
                len(city) if path == cfg.PHASE2_ACCESS_CITY_FILE else
                len(district) if path == cfg.PHASE2_ACCESS_DISTRICT_FILE else
                len(events) if path == cfg.PHASE2_ACCESS_EVENTS_FILE else
                len(counterfactual) if path == cfg.PHASE2_ACCESS_COUNTERFACTUAL_FILE else
                len(states)
            )}
            for path in generated_outputs
        },
        "counterfactual_diagnostics": {
            "actual": "network state for year Y weighted by population model Y",
            "network_change_on_2015_population": "network state for year Y weighted by fixed 2015 population model",
            "population_change_under_2015_network": "fixed 2015 network state weighted by population model Y",
            "causal_decomposition": False,
            "warning": "the three series are diagnostics and are not an additive causal decomposition",
        },
        "current_headline_bridge": {
            "current_entrance_aware_pct": CURRENT_HEADLINE_PCT,
            "standardized_2026_pct": standardized_2026,
            "absolute_difference_pp": abs(standardized_2026 - CURRENT_HEADLINE_PCT),
            "forced_to_match": False,
            "methodological_differences": [
                "current station centres instead of entrance-aware access points",
                "raw annual WorldPop model weights instead of SIAT-calibrated population",
                "standardized temporal comparison objective instead of current headline objective",
            ],
        },
        "limitations": [
            "This is not a literal reconstruction of historical streets or entrances.",
            "The current pedestrian network and current station-centre coordinates are held fixed.",
            "WorldPop values are modelled estimates, not observations, and are not calibrated to SIAT.",
            "Off-network connectors are straight-line approximations to the nearest mapped walkable edge.",
            "Annual access changes combine metro source-set expansion and changes in modelled population weights.",
            "No historical bus accessibility is computed.",
            "Counterfactual diagnostics are not an additive causal decomposition.",
        ],
    }
    ta.write_json_lf(cfg.PHASE2_ANALYSIS_MANIFEST_PATH, manifest)
    log(f"  wrote {relative(cfg.PHASE2_ANALYSIS_MANIFEST_PATH)}")
    step("Phase 2B analysis complete")
    log("  Next: python scripts/validate_phase2_accessibility.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
