"""Validate the Phase 2B standardized temporal metro-access analysis.

    python scripts/validate_phase2_accessibility.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
import temporal_accessibility as ta  # noqa: E402


EXPECTED_COUNTS = {
    2015: 29, 2016: 29, 2017: 29, 2018: 29, 2019: 29,
    2020: 43, 2021: 43, 2022: 43, 2023: 48,
    2024: 50, 2025: 50, 2026: 50,
}
EXPECTED_EVENT_ADDITIONS = {2020: 14, 2023: 5, 2024: 2}
EXPECTED_STATE_IDS = [
    "metro_state_29", "metro_state_43", "metro_state_48", "metro_state_50"
]
TOL = 1e-7

passed = 0
failed = 0


def check(condition: bool, label: str, detail: str | None = None) -> bool:
    global passed, failed
    if bool(condition):
        passed += 1
        print(f"  [PASS] {label}")
        return True
    failed += 1
    suffix = f" ({detail})" if detail else ""
    print(f"  [FAIL] {label}{suffix}")
    return False


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def read_bool(series: pd.Series) -> pd.Series:
    mapped = series.astype(str).str.strip().str.lower().map(
        {"true": True, "false": False}
    )
    if mapped.isna().any():
        raise ValueError("boolean column contains values other than true/false")
    return mapped.astype(bool)


def reconcile_populations(
    cells: pd.DataFrame, phase2: pd.DataFrame
) -> tuple[dict[int, np.ndarray], float]:
    lookup = phase2.set_index(["district_id", "year"])
    district_ids = cells.district_id.to_numpy(dtype=str)
    outputs: dict[int, np.ndarray] = {}
    factors: list[float] = []
    for year in cfg.TEMPORAL_YEARS:
        values = pd.to_numeric(cells[f"pop_{year}"], errors="coerce").to_numpy(float)
        values = values.copy()
        for district_id in sorted(cells.district_id.unique()):
            mask = (district_ids == district_id) & np.isfinite(values)
            serialized = float(values[mask].sum(dtype=np.float64))
            target = float(lookup.loc[(district_id, year)].population_modelled)
            factor = target / serialized
            values[mask] *= factor
            factors.append(factor)
        outputs[year] = values
    return outputs, max(abs(factor - 1.0) for factor in factors)


def main() -> int:  # noqa: PLR0915 - validator intentionally enumerates gates
    global passed, failed
    print("=" * 74)
    print("Phase 2B standardized temporal metro accessibility - validation")
    print("=" * 74)

    section("Input integrity")
    required = (
        cfg.PHASE2_SOURCE_MANIFEST_PATH,
        cfg.WORLDPOP_TEMPORAL_CELL_CACHE,
        cfg.METRO_STATION_HISTORY_FILE,
        cfg.WALK_GRAPH_FILE,
        cfg.WORLDPOP_DISTRICT_YEAR_FILE,
        cfg.PHASE2_ACCESS_CITY_FILE,
        cfg.PHASE2_ACCESS_DISTRICT_FILE,
        cfg.PHASE2_ACCESS_EVENTS_FILE,
        cfg.PHASE2_ACCESS_COUNTERFACTUAL_FILE,
        cfg.PHASE2_ROUTING_STATES_FILE,
        cfg.PHASE2_DISTANCE_CACHE,
        cfg.PHASE2_ANALYSIS_MANIFEST_PATH,
        cfg.PHASE2_ACCESS_METHODOLOGY_FILE,
    )
    for path in required:
        check(path.exists(), f"{path.name} exists")
    if any(not path.exists() for path in required):
        print("\nSummary\n-------")
        print(f"  passed: {passed}\n  failed: {failed}")
        return 1

    source_manifest = json.loads(
        cfg.PHASE2_SOURCE_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    analysis_manifest = json.loads(
        cfg.PHASE2_ANALYSIS_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    routing = json.loads(cfg.PHASE2_ROUTING_STATES_FILE.read_text(encoding="utf-8"))
    cells = pd.read_csv(
        cfg.WORLDPOP_TEMPORAL_CELL_CACHE,
        dtype={"cell_id": str, "district_id": str},
    ).sort_values("cell_id", kind="stable").reset_index(drop=True)
    stations = pd.read_csv(
        cfg.METRO_STATION_HISTORY_FILE, dtype={"station_id": str}
    ).sort_values("station_id", kind="stable").reset_index(drop=True)
    phase2 = pd.read_csv(
        cfg.WORLDPOP_DISTRICT_YEAR_FILE, dtype={"district_id": str}
    ).sort_values(["district_id", "year"], kind="stable").reset_index(drop=True)
    city = pd.read_csv(cfg.PHASE2_ACCESS_CITY_FILE)
    district = pd.read_csv(cfg.PHASE2_ACCESS_DISTRICT_FILE, dtype={"district_id": str})
    events = pd.read_csv(cfg.PHASE2_ACCESS_EVENTS_FILE)
    counterfactual = pd.read_csv(cfg.PHASE2_ACCESS_COUNTERFACTUAL_FILE)

    actual_cache_sha = cfg.sha256_file(cfg.WORLDPOP_TEMPORAL_CELL_CACHE)
    check(
        actual_cache_sha == source_manifest["worldpop"]["cell_cache"]["sha256"],
        "temporal cache SHA-256 matches Phase 2A manifest",
    )
    check(len(cells) == 65_169, "temporal cache has 65,169 rows")
    check(cells.cell_id.nunique() == 65_169, "temporal cell identities are unique")
    check(len(stations) == 50, "station history has 50 rows")
    check(stations.station_id.nunique() == 50, "station IDs are unique")
    check(cfg.WALK_GRAPH_FILE.exists(), "current pedestrian graph is available")
    input_hashes_ok = True
    for relative_path, metadata in analysis_manifest["input_files"].items():
        path = cfg.REPO_ROOT / relative_path
        input_hashes_ok &= path.exists() and cfg.sha256_file(path) == metadata["sha256"]
    check(input_hashes_ok, "all manifest input hashes match current source files")
    current_manifest = json.loads(cfg.ANALYSIS_MANIFEST_PATH.read_text(encoding="utf-8"))
    network_meta = analysis_manifest["pedestrian_network"]
    check(network_meta["fixed_current_snapshot"] is True, "manifest fixes the current network")
    check(
        network_meta["nodes"] == current_manifest["network"]["nodes"] == 111_386,
        "network node count matches current analysis",
    )
    check(
        network_meta["stored_edge_records"]
        == current_manifest["network"]["stored_edge_records"]
        == 308_272,
        "stored edge count matches current analysis",
    )
    check(
        network_meta["canonical_routing_edges"]
        == current_manifest["network"]["canonical_routing_edges"]
        == 154_133,
        "canonical edge count matches current analysis",
    )

    section("Source states")
    states, year_to_state = ta.derive_metro_states(stations, cfg.TEMPORAL_YEARS)
    state_ids = [state.state_id for state in states]
    state_by_id = {state.state_id: state for state in states}
    counts = {
        year: state_by_id[state_id].open_station_count
        for year, state_id in year_to_state.items()
    }
    check(len(states) == 4, "exactly four unique routing states")
    check(state_ids == EXPECTED_STATE_IDS, "routing state IDs are stable and expected")
    check(counts == EXPECTED_COUNTS, "annual station counts derive correctly")
    check(
        all(
            set(earlier.active_station_ids).issubset(later.active_station_ids)
            for earlier, later in zip(states, states[1:])
        ),
        "source sets are nested and no station disappears",
    )
    check(
        routing["dijkstra_runs"] == len(states) == 4,
        "routing diagnostic records one Dijkstra per unique state",
    )
    check(
        [row["state_id"] for row in routing["states"]] == state_ids,
        "routing-state diagnostic order matches derived states",
    )

    section("Routing distances and access masks")
    with np.load(cfg.PHASE2_DISTANCE_CACHE, allow_pickle=False) as cache:
        cached_cell_ids = cache["cell_id"].astype(str)
        cached_state_ids = cache["state_id"].astype(str).tolist()
        distance = {
            state_id: cache[f"distance_{state_id}"].astype(np.float64)
            for state_id in state_ids
        }
    check(np.array_equal(cached_cell_ids, cells.cell_id.to_numpy(str)), "cache cell order is exact")
    check(cached_state_ids == state_ids, "distance-cache state order is deterministic")
    for state_id in state_ids:
        values = distance[state_id]
        check(values.size == len(cells), f"{state_id} vector length equals cell count")
        check(not np.isnan(values).any(), f"{state_id} contains no NaN distances")
        check(np.all(values >= 0), f"{state_id} distances are non-negative or +inf")
    distance_violations = sum(
        int(np.count_nonzero(distance[later.state_id] > distance[earlier.state_id] + TOL))
        for earlier, later in zip(states, states[1:])
    )
    masks = {
        state_id: distance[state_id] <= cfg.PHASE2_ACCESS_DISTANCE_BUDGET_M
        for state_id in state_ids
    }
    access_violations = sum(
        int(np.count_nonzero(masks[earlier.state_id] & ~masks[later.state_id]))
        for earlier, later in zip(states, states[1:])
    )
    check(distance_violations == 0, "later-state distances never increase")
    check(access_violations == 0, "later-state accessibility masks are nested")
    check(
        routing["monotonic_distance_violations"] == 0,
        "routing diagnostic records zero distance violations",
    )
    check(
        routing["nested_access_mask_violations"] == 0,
        "routing diagnostic records zero access-mask violations",
    )
    routing_states = {row["state_id"]: row for row in routing["states"]}
    for state_id in state_ids:
        check(
            routing_states[state_id]["accessible_cell_count"] == int(masks[state_id].sum()),
            f"{state_id} accessible-cell count matches distance vector",
        )
        check(
            routing_states[state_id]["finite_distance_cell_count"]
            == int(np.isfinite(distance[state_id]).sum()),
            f"{state_id} finite-distance count matches distance vector",
        )

    section("City and district outputs")
    populations, max_factor_deviation = reconcile_populations(cells, phase2)
    check(max_factor_deviation < 2e-9, "serialization reconciliation is minute and bounded")
    check(len(city) == 12, "city output has exactly 12 rows")
    check(city.year.tolist() == list(cfg.TEMPORAL_YEARS), "city years are 2015-2026")
    check(len(district) == 144, "district output has exactly 144 rows")
    check(
        not district.duplicated(["district_id", "year"]).any(),
        "district/year key is unique",
    )
    check(
        set(district.groupby("year").size()) == {12},
        "every year contains 12 districts",
    )
    phase2_lookup = phase2.set_index(["district_id", "year"])
    city_lookup = city.set_index("year")
    district_ids = cells.district_id.to_numpy(str)
    city_ok = True
    district_ok = True
    for year in cfg.TEMPORAL_YEARS:
        state_id = year_to_state[year]
        pop = populations[year]
        mask = masks[state_id]
        year_rows = district[district.year == year].set_index("district_id")
        for district_id, row in year_rows.iterrows():
            cell_mask = district_ids == district_id
            denominator, numerator, _ = ta.weighted_access(pop[cell_mask], mask[cell_mask])
            denominator = round(denominator, 6)
            numerator = round(numerator, 6)
            expected_denominator = float(
                phase2_lookup.loc[(district_id, year)].population_modelled
            )
            recomputed_pct = 100.0 * float(row.metro_access_population_standardized) / float(
                row.population_modelled_available
            )
            district_ok &= (
                float(row.population_modelled_available) == expected_denominator
                and denominator == expected_denominator
                and abs(float(row.metro_access_population_standardized) - numerator) <= 1e-6
                and abs(float(row.metro_access_pct_standardized) - recomputed_pct) <= 5e-10
                and row.metro_state_id == state_id
                and int(row.open_station_count) == EXPECTED_COUNTS[year]
                and row.population_model_status == cfg.WORLDPOP_TEMPORAL_MODEL_STATUS
                and row.geography_version == cfg.TEMPORAL_GEOGRAPHY_VERSION
            )
        city_row = city_lookup.loc[year]
        district_denominator = round(year_rows.population_modelled_available.sum(), 6)
        district_numerator = round(year_rows.metro_access_population_standardized.sum(), 6)
        city_pct = 100.0 * float(city_row.metro_access_population_standardized) / float(
            city_row.population_modelled_available
        )
        city_ok &= (
            float(city_row.population_modelled_available) == district_denominator
            and abs(float(city_row.metro_access_population_standardized) - district_numerator) <= 1e-6
            and abs(float(city_row.metro_access_pct_standardized) - city_pct) <= 5e-10
            and city_row.metro_state_id == state_id
            and int(city_row.open_station_count) == EXPECTED_COUNTS[year]
            and city_row.population_model_status == cfg.WORLDPOP_TEMPORAL_MODEL_STATUS
            and str(city_row.temporal_reference) == cfg.WORLDPOP_TEMPORAL_REFERENCE_DATE
        )
    check(district_ok, "district denominators, numerators, percentages and states recompute")
    check(city_ok, "city totals reconcile with districts and percentages recompute")
    check(
        (district.metro_access_population_standardized >= 0).all()
        and (
            district.metro_access_population_standardized
            <= district.population_modelled_available + 1e-9
        ).all(),
        "district accessible populations are bounded",
    )
    check(
        city.metro_access_pct_standardized.between(0, 100).all()
        and district.metro_access_pct_standardized.between(0, 100).all(),
        "all access percentages are within 0-100",
    )
    projection_city = read_bool(city.population_projection_flag)
    projection_district = read_bool(district.population_projection_flag)
    check(
        city.loc[projection_city, "year"].tolist() == [2026],
        "city projection flag marks only 2026",
    )
    check(
        set(district.loc[projection_district, "year"]) == {2026}
        and int(projection_district.sum()) == 12,
        "district projection flags mark only the twelve 2026 rows",
    )

    section("Expansion events")
    expected_event_years = [
        year for year in cfg.TEMPORAL_YEARS[1:]
        if year_to_state[year] != year_to_state[year - 1]
    ]
    check(events.year.tolist() == expected_event_years == [2020, 2023, 2024], "event years derive correctly")
    events_ok = True
    for _, row in events.iterrows():
        year = int(row.year)
        added = stations.loc[
            stations.opening_year.astype(int) == year, "station_name_current"
        ].astype(str)
        names = " | ".join(sorted(added.tolist()))
        events_ok &= (
            int(row.stations_added) == EXPECTED_EVENT_ADDITIONS[year]
            and int(row.stations_after) - int(row.stations_before) == int(row.stations_added)
            and row.station_names_added == names
            and row.previous_metro_state_id == year_to_state[year - 1]
            and row.new_metro_state_id == year_to_state[year]
            and row.change_interpretation == "combined annual standardized change"
        )
    check(events_ok, "event deltas, station names, state transitions and label are correct")

    section("Counterfactual diagnostics")
    check(len(counterfactual) == 12, "counterfactual output has 12 rows")
    numeric = counterfactual[[
        "actual_standardized_pct",
        "network_change_on_2015_population_pct",
        "population_change_under_2015_network_pct",
    ]]
    check(np.isfinite(numeric.to_numpy(float)).all(), "all counterfactual percentages are finite")
    check(((numeric >= 0) & (numeric <= 100)).all().all(), "all counterfactual percentages are within 0-100")
    baseline = counterfactual[counterfactual.year == 2015].iloc[0]
    check(
        len({
            float(baseline.actual_standardized_pct),
            float(baseline.network_change_on_2015_population_pct),
            float(baseline.population_change_under_2015_network_pct),
        }) == 1,
        "all three counterfactual series are equal in 2015",
    )
    counter_ok = True
    pop2015 = populations[2015]
    baseline_mask = masks[year_to_state[2015]]
    for _, row in counterfactual.iterrows():
        year = int(row.year)
        _, _, network_only = ta.weighted_access(pop2015, masks[year_to_state[year]])
        _, _, population_only = ta.weighted_access(populations[year], baseline_mask)
        counter_ok &= (
            abs(float(row.actual_standardized_pct) - float(city_lookup.loc[year].metro_access_pct_standardized)) <= 1e-9
            and abs(float(row.network_change_on_2015_population_pct) - network_only) <= 5e-10
            and abs(float(row.population_change_under_2015_network_pct) - population_only) <= 5e-10
            and row.metro_state_id == year_to_state[year]
        )
    check(counter_ok, "all counterfactual series recompute from the intended state and weights")
    check(
        all(group.network_change_on_2015_population_pct.nunique() == 1
            for _, group in counterfactual.groupby("metro_state_id")),
        "network-on-2015-population percentage is identical within each state",
    )

    section("Manifest and methodology")
    check(
        analysis_manifest["analysis_version"] == cfg.PHASE2_ACCESS_ANALYSIS_VERSION,
        "manifest method version is correct",
    )
    check(
        "station-centre" in analysis_manifest["routing"]["station_source_rule"],
        "manifest records the station-centre source rule",
    )
    check(
        analysis_manifest["population_weighting"]["calibrated_to_siat"] is False,
        "manifest records raw annual WorldPop weighting without SIAT calibration",
    )
    check(analysis_manifest["bus_history_used"] is False, "manifest records no bus history")
    check(
        analysis_manifest["current_headline_bridge"]["forced_to_match"] is False,
        "manifest distinguishes rather than forces the current headline",
    )
    check(
        analysis_manifest["counterfactual_diagnostics"]["causal_decomposition"] is False,
        "manifest rejects additive causal decomposition",
    )
    output_hashes_ok = True
    for relative_path, metadata in analysis_manifest["output_files"].items():
        path = cfg.REPO_ROOT / relative_path
        output_hashes_ok &= path.exists() and cfg.sha256_file(path) == metadata["sha256"]
    check(output_hashes_ok, "all committed output hashes match the manifest")
    check(
        cfg.sha256_file(cfg.PHASE2_DISTANCE_CACHE)
        == analysis_manifest["distance_cache"]["sha256"],
        "distance-cache hash matches the manifest",
    )
    methodology = cfg.PHASE2_ACCESS_METHODOLOGY_FILE.read_text(encoding="utf-8")
    check("standardized temporal comparison" in methodology, "methodology uses standardized-comparison terminology")
    check("not a historical\nreconstruction" in methodology or "not a historical reconstruction" in methodology,
          "methodology rejects a literal historical-reconstruction claim")
    check("not an additive causal decomposition" in methodology,
          "methodology scopes counterfactual diagnostics correctly")
    check("13.563595724255597%" in methodology,
          "methodology distinguishes the frozen current headline")
    check("historical bus" in methodology and "No historical bus" in methodology,
          "methodology states that historical bus accessibility is excluded")

    print("\nSummary\n-------")
    print(f"  passed: {passed}")
    print(f"  failed: {failed}")
    if failed:
        print("\nVALIDATION FAILED")
        return 1
    print("\nVALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
