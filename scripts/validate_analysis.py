"""Validate the Week 4 accessibility outputs.

    python scripts/validate_analysis.py

Exits 0 when every critical check passes, 1 otherwise. This checks internal
consistency and invariants; it does not certify that the modelling assumptions
are right. The results remain PRELIMINARY until independently audited.

Two habits are deliberate. First, wherever the cached per-cell table is
available the validator re-derives the answer from it rather than trusting an
aggregate that the same script wrote. Second, the off-network connector
distributions are REPORTED in full and checked only for properties that cannot
be tuned - finiteness, sign, ordering of percentiles, and agreement with the
cell table - because a generous pass threshold on a connector distribution
would hide exactly the kind of defect this file exists to catch.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
from pipeline_utils import enable_utf8_stdout  # noqa: E402

CRITICAL: list[str] = []
WARNINGS: list[str] = []
PASSED: list[str] = []

# Populations are floats scaled by per-district calibration factors, so exact
# equality is not achievable. One person over a 3.2 million denominator is a
# far tighter bound than any modelling assumption here.
POP_TOL = 1.0
PCT_TOL = 1e-6
EXPECTED_SNAPPING_METHOD = "edge-aware"


def check(condition: bool, description: str, *, critical: bool = True) -> bool:
    if condition:
        PASSED.append(description)
        print(f"  PASS  {description}")
    elif critical:
        CRITICAL.append(description)
        print(f"  FAIL  {description}")
    else:
        WARNINGS.append(description)
        print(f"  WARN  {description}")
    return condition


def section(title: str) -> None:
    print("\n" + "-" * 74)
    print(title)
    print("-" * 74)


REQUIRED_FILES = [
    cfg.ANALYSIS_BOUNDARY_FILE,
    cfg.METRO_ACCESS_POINTS_FILE,
    cfg.TRANSIT_SNAP_DIAGNOSTICS_FILE,
    cfg.DISTRICT_ACCESS_METRICS_FILE,
    cfg.CITY_ACCESS_SUMMARY_FILE,
    cfg.WALK_SPEED_SENSITIVITY_FILE,
    cfg.POPULATION_SURFACE_SENSITIVITY_FILE,
    cfg.METRO_ISOCHRONE_FILE,
    cfg.BUS_ISOCHRONE_FILE,
    cfg.ANALYSIS_MANIFEST_PATH,
]


def validate_files() -> bool:
    section("1. Required Week 4 outputs")
    ok = True
    for path in REQUIRED_FILES:
        ok &= check(path.exists(), f"{path.name} exists")
    return ok


# ---------------------------------------------------------------------------
# 2. the routing model itself
# ---------------------------------------------------------------------------
def validate_routing_model(manifest: dict) -> None:
    section("2. Edge-aware routing model")

    check(manifest.get("snapping_method") == EXPECTED_SNAPPING_METHOD,
          f"manifest records snapping_method = '{EXPECTED_SNAPPING_METHOD}' "
          f"(got {manifest.get('snapping_method')!r})")

    summary = json.loads(cfg.CITY_ACCESS_SUMMARY_FILE.read_text(encoding="utf-8"))
    check(summary.get("snapping_method") == EXPECTED_SNAPPING_METHOD,
          f"city summary records snapping_method = '{EXPECTED_SNAPPING_METHOD}' "
          f"(got {summary.get('snapping_method')!r})")

    network = manifest.get("network", {})
    for key in ("stored_edge_records", "usable_edge_records", "canonical_routing_edges"):
        value = network.get(key)
        check(isinstance(value, int) and value > 0,
              f"network.{key} recorded ({value})")

    stored = network.get("stored_edge_records", 0)
    usable = network.get("usable_edge_records", 0)
    canonical = network.get("canonical_routing_edges", 0)
    check(usable <= stored,
          f"usable edge records do not exceed stored records ({usable:,} <= {stored:,})")
    check(canonical < stored,
          f"canonical routing edges are fewer than stored records - directional copies "
          f"were collapsed ({canonical:,} < {stored:,})")
    check(canonical <= usable,
          f"canonical routing edges do not exceed usable records ({canonical:,} <= {usable:,})")
    print(f"    stored edge records            : {stored:,}")
    print(f"    usable edge records            : {usable:,}")
    print(f"    canonical undirected routing edges: {canonical:,}")
    print(f"      self-loops                   : {network.get('canonical_self_loop_edges')}")
    print(f"      distinct node pairs          : {network.get('distinct_node_pairs')}")
    print(f"      pairs carrying parallel edges: {network.get('node_pairs_with_parallel_edges')}")
    print(f"      records per canonical edge   : {network.get('records_per_canonical_edge')}")

    # Every usable record must be accounted for by exactly the canonical edges.
    per_edge = network.get("records_per_canonical_edge", {})
    if per_edge:
        accounted = sum(int(k) * int(v) for k, v in per_edge.items())
        edges = sum(int(v) for v in per_edge.values())
        check(accounted == usable,
              f"canonical edges account for every usable record ({accounted:,} vs {usable:,})")
        check(edges == canonical,
              f"records-per-edge histogram covers every canonical edge ({edges:,} vs {canonical:,})")
        check(min(int(k) for k in per_edge) >= 2,
              "no canonical edge is backed by a single directional record "
              f"(minimum backing count {min(int(k) for k in per_edge)})")

    routing = manifest.get("routing_model", {})
    for key in ("edge_snap_method", "source_insertion_method",
                "population_edge_query_method", "same_edge_handling",
                "directional_duplicate_handling", "position_units"):
        value = routing.get(key)
        check(isinstance(value, str) and len(value) > 20, f"routing_model.{key} recorded")
    check(routing.get("snapping_method") == EXPECTED_SNAPPING_METHOD,
          "routing_model.snapping_method is edge-aware")
    check(routing.get("shortest_path_passes") == 2,
          f"exactly one shortest-path pass per mode ({routing.get('shortest_path_passes')})")

    for mode in ("metro_sources", "bus_sources"):
        block = manifest.get(mode, {})
        placement = block.get("placement", {})
        augmentation = block.get("augmentation", {})
        for key in ("inserted_in_edge_interior", "effectively_at_an_endpoint",
                    "distinct_edges_containing_sources"):
            check(isinstance(placement.get(key), int),
                  f"{mode}.placement.{key} recorded ({placement.get(key)})")
        for key in ("augmented_nodes_added", "sources_inserted_in_edge_interior",
                    "augmented_routing_edges", "canonical_routing_edges"):
            check(isinstance(augmentation.get(key), int),
                  f"{mode}.augmentation.{key} recorded ({augmentation.get(key)})")
        interior = placement.get("inserted_in_edge_interior", 0)
        endpoint = placement.get("effectively_at_an_endpoint", 0)
        total = placement.get("count", 0)
        check(interior + endpoint == total,
              f"{mode}: interior + endpoint placements equal the source count "
              f"({interior} + {endpoint} = {total})")
        check(augmentation.get("augmented_routing_edges", 0)
              >= augmentation.get("canonical_routing_edges", 0),
              f"{mode}: splitting never reduces the routing-segment count")
        check(augmentation.get("augmented_nodes_added", -1)
              == augmentation.get("sources_inserted_in_edge_interior", -2),
              f"{mode}: one augmented node per interior source "
              f"({augmentation.get('augmented_nodes_added')} vs "
              f"{augmentation.get('sources_inserted_in_edge_interior')})")
        print(f"    {mode}: {total} sources, {interior} spliced into edge interiors, "
              f"{endpoint} at existing endpoints, over "
              f"{placement.get('distinct_edges_containing_sources')} distinct canonical edges")


def validate_synthetic_tests() -> None:
    section("3. Synthetic routing regression tests")
    try:
        import test_accessibility_utils as suite
    except Exception as error:  # noqa: BLE001 - report, do not mask
        check(False, f"synthetic routing tests importable ({type(error).__name__}: {error})")
        return
    failures = []
    for title, function in suite.TESTS:
        try:
            function()
        except Exception as error:  # noqa: BLE001 - report, do not mask
            failures.append(f"{title}: {error}")
    for failure in failures:
        print(f"      {failure}")
    check(not failures,
          f"all {len(suite.TESTS)} synthetic routing tests pass "
          f"({len(failures)} failed)")


# ---------------------------------------------------------------------------
# 4. off-network connector diagnostics
# ---------------------------------------------------------------------------
def _report_distribution(label: str, block: dict) -> None:
    print(f"    {label:26s} n={int(block.get('count', 0)):>6,}  "
          f"min={block.get('min_m', float('nan')):7.1f}  "
          f"mean={block.get('mean_m', float('nan')):7.1f}  "
          f"median={block.get('median_m', float('nan')):7.1f}  "
          f"p95={block.get('p95_m', float('nan')):8.1f}  "
          f"p99={block.get('p99_m', float('nan')):8.1f}  "
          f"max={block.get('max_m', float('nan')):9.1f} m")


def validate_connectors(manifest: dict) -> None:
    section("4. Off-network connector diagnostics (distance to the nearest walkable EDGE)")
    block = manifest.get("connector_diagnostics", {})
    definition = str(block.get("definition", ""))
    check("EDGE" in definition or "edge" in definition,
          "connector diagnostics state that they measure distance to the nearest EDGE")
    interpretation = str(block.get("interpretation", ""))
    check("uncertain" in interpretation,
          "connector interpretation states the effect on individual cells is uncertain")
    for word in ("overstat", "understat"):
        check(word not in interpretation.lower(),
              f"connector interpretation makes no directional bias claim ('{word}')")

    print()
    for key, label in (("metro", "metro sources"),
                       ("bus", "bus sources"),
                       ("population_cells", "population cells 2026"),
                       ("population_cells_2020_surface", "population cells 2020")):
        stats = block.get(key)
        if not isinstance(stats, dict) or not stats.get("count"):
            check(False, f"{label} connector diagnostics present")
            continue
        _report_distribution(label, stats)
        values = [stats.get(name) for name in
                  ("min_m", "mean_m", "median_m", "p95_m", "p99_m", "max_m")]
        check(all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in values),
              f"{label} connector statistics are all finite")
        check(all(float(v) >= 0 for v in values if isinstance(v, (int, float))),
              f"{label} connector statistics are non-negative")
        ordered = [float(stats["min_m"]), float(stats["median_m"]), float(stats["p95_m"]),
                   float(stats["p99_m"]), float(stats["max_m"])]
        check(all(a <= b + 1e-9 for a, b in zip(ordered, ordered[1:])),
              f"{label} connector percentiles are ordered min<=median<=p95<=p99<=max")
        check(float(stats["min_m"]) <= float(stats["mean_m"]) <= float(stats["max_m"]) + 1e-9,
              f"{label} connector mean lies inside [min, max]")

    counts = {
        "metro": manifest.get("metro_sources", {}).get("access_points_total"),
        "bus": manifest.get("bus_sources", {}).get("stops_used"),
        "population_cells": manifest.get("population_cells", {}).get("count"),
    }
    for key, expected in counts.items():
        actual = block.get(key, {}).get("count")
        check(expected is not None and actual == expected,
              f"{key} connector count matches the source count ({actual} vs {expected})")

    csv = pd.read_csv(cfg.TRANSIT_SNAP_DIAGNOSTICS_FILE)
    check(set(csv.label) == {"metro", "bus", "population_cells"},
          f"snap diagnostics CSV covers metro, bus and population cells "
          f"(got {sorted(set(csv.label))})")
    numeric = csv[["min_m", "mean_m", "median_m", "p95_m", "p99_m", "max_m"]].to_numpy()
    check(bool(np.isfinite(numeric).all()), "snap diagnostics CSV values all finite")
    check(bool((numeric >= 0).all()), "snap diagnostics CSV values all non-negative")


def validate_connectors_from_cells(manifest: dict) -> None:
    """Re-derive the cell connector distribution from the cached per-cell table."""
    section("5. Connector diagnostics re-derived from the per-cell table")
    if not cfg.POPULATION_CELLS_CACHE.exists():
        check(False, f"{cfg.POPULATION_CELLS_CACHE.name} present for an independent check",
              critical=False)
        return
    cells = pd.read_parquet(cfg.POPULATION_CELLS_CACHE)
    check("edge_connector_m" in cells.columns,
          "per-cell table carries the edge connector, not a node offset")
    check("edge_index" in cells.columns and "edge_fraction" in cells.columns,
          "per-cell table carries the canonical edge and the position along it")
    if "edge_connector_m" not in cells.columns:
        return

    connector = cells.edge_connector_m.to_numpy()
    check(bool(np.isfinite(connector).all()), "every cell connector is finite")
    check(bool((connector >= 0).all()), "every cell connector is non-negative")
    check(bool(((cells.edge_fraction >= 0) & (cells.edge_fraction <= 1)).all()),
          "every cell position lies within its edge (fraction in [0, 1])")

    # A total distance is the connector plus a non-negative network distance,
    # so the connector can never exceed it. This is the invariant that would
    # break if a connector were counted twice or dropped.
    for mode in ("metro_distance_m", "bus_distance_m"):
        finite = np.isfinite(cells[mode].to_numpy())
        gap = cells[mode].to_numpy()[finite] - connector[finite]
        check(bool((gap >= -1e-6).all()),
              f"{mode} is never smaller than the cell's own connector "
              f"(worst {float(gap.min()):.6f} m)")

    recorded = manifest.get("connector_diagnostics", {}).get("population_cells", {})
    percentiles = np.percentile(connector, [50, 95, 99])
    derived = {
        "count": int(connector.size),
        "min_m": float(connector.min()),
        "mean_m": float(connector.mean()),
        "median_m": float(percentiles[0]),
        "p95_m": float(percentiles[1]),
        "p99_m": float(percentiles[2]),
        "max_m": float(connector.max()),
    }
    _report_distribution("re-derived from cells", derived)
    drift = max(abs(derived[k] - float(recorded.get(k, np.nan)))
                for k in ("min_m", "mean_m", "median_m", "p95_m", "p99_m", "max_m"))
    check(drift < 1e-6,
          f"manifest cell connector statistics match the per-cell table (drift {drift:.2e})")

    # Reported, not thresholded: the tail is evidence for the audit, not a gate.
    for cut in (50, 100, 250, 500):
        share = float((connector > cut).mean())
        print(f"    cells with a connector over {cut:4d} m: "
              f"{int((connector > cut).sum()):6,}  ({share:.3%})")
    worst = float(connector.max())
    check(math.isfinite(worst), f"worst cell connector is a finite number ({worst:.1f} m)")


# ---------------------------------------------------------------------------
# 6. district and city results
# ---------------------------------------------------------------------------
def validate_districts() -> pd.DataFrame | None:
    section("6. District access metrics")
    table = pd.read_csv(cfg.DISTRICT_ACCESS_METRICS_FILE)
    official = pd.read_csv(cfg.SIAT_POPULATION_FILE, dtype={"siat_code": str})

    check(len(table) == cfg.EXPECTED_ANALYSIS_DISTRICTS,
          f"exactly {cfg.EXPECTED_ANALYSIS_DISTRICTS} district rows (got {len(table)})")
    check(table.district_name.is_unique, "district names unique")
    check(set(table.district_name) == set(official.district_name),
          "district names match the SIAT population table")

    numeric = table.select_dtypes(include=[np.number])
    check(bool(np.isfinite(numeric.to_numpy()).all()),
          "no NaN or inf in numeric district metrics")

    population_columns = [
        "calibrated_population", "metro_access_population",
        "bus_only_population", "underserved_population",
        "combined_walk_access_population",
    ]
    check(bool((table[population_columns] >= 0).all().all()),
          "no negative population values")

    merged = table.merge(
        official[["district_name", "population"]].rename(
            columns={"population": "siat_population"}),
        on="district_name", how="left",
    )
    worst = float((merged.calibrated_population - merged.siat_population).abs().max())
    check(worst <= POP_TOL,
          f"every calibrated district total matches its SIAT total "
          f"(max difference {worst:.6f})")
    check(bool((merged.official_population == merged.siat_population).all()),
          "official_population column equals the SIAT table")

    city_total = float(table.calibrated_population.sum())
    check(abs(city_total - 3_212_200) <= POP_TOL,
          f"calibrated city population is 3,212,200 (got {city_total:,.4f})")

    parts = (table.metro_access_population + table.bus_only_population
             + table.underserved_population)
    residual = float((parts - table.calibrated_population).abs().max())
    check(residual <= POP_TOL,
          f"category populations partition each district (max residual {residual:.6f})")

    pct = table.metro_access_pct + table.bus_only_pct + table.underserved_pct
    pct_residual = float((pct - 100.0).abs().max())
    check(pct_residual <= 1e-4,
          f"category percentages sum to 100 per district (max drift {pct_residual:.8f})")

    check(bool((table.metro_access_population <= table.calibrated_population + POP_TOL).all()),
          "metro access population never exceeds district population")
    combined = table.metro_access_population + table.bus_only_population
    check(bool((combined <= table.calibrated_population + POP_TOL).all()),
          "metro + bus-only never exceeds district population")
    check(bool((table.combined_walk_access_population - combined).abs().max() <= POP_TOL),
          "combined_walk_access_population equals metro + bus-only")

    # A zero metro share must be backed by a nearest-cell distance beyond the
    # budget, and a positive share by one inside it. This is what turns a
    # 0.00 percent from an assertion into a checkable statement.
    budget = cfg.walk_budget_m(cfg.MAIN_WALK_SPEED_KMH)
    check("min_cell_metro_distance_m" in table.columns,
          "district table reports the nearest population cell's metro distance")
    if "min_cell_metro_distance_m" in table.columns:
        zero = table[table.metro_access_pct == 0]
        nonzero = table[table.metro_access_pct > 0]
        check(bool((zero.min_cell_metro_distance_m > budget).all()),
              f"every district with a 0.00% metro share has its nearest cell beyond "
              f"{budget:.0f} m ({len(zero)} such districts)")
        check(bool((nonzero.min_cell_metro_distance_m <= budget + 1e-6).all()),
              "every district with a positive metro share has a cell inside the budget")
        drift = float((table.min_cell_metro_margin_m
                       - (table.min_cell_metro_distance_m - budget)).abs().max())
        check(drift <= 1e-4, f"min_cell_metro_margin_m is the distance minus the budget "
                             f"(drift {drift:.8f})")

    print("\n  district metrics:")
    print(f"    {'district':26s} {'population':>11s} {'metro%':>8s} "
          f"{'bus-only%':>10s} {'unserved%':>10s} {'min metro m':>12s}")
    for _, r in table.iterrows():
        print(f"    {r.district_name:26s} {r.calibrated_population:11,.0f} "
              f"{r.metro_access_pct:8.2f} {r.bus_only_pct:10.2f} {r.underserved_pct:10.2f} "
              f"{r.min_cell_metro_distance_m:12.1f}")
    return table


def validate_city_summary(table: pd.DataFrame | None) -> dict | None:
    section("7. City summary")
    summary = json.loads(cfg.CITY_ACCESS_SUMMARY_FILE.read_text(encoding="utf-8"))

    check(summary.get("walking_speed_kmh") == cfg.MAIN_WALK_SPEED_KMH,
          f"main walking speed is {cfg.MAIN_WALK_SPEED_KMH} km/h "
          f"(got {summary.get('walking_speed_kmh')})")
    check(summary.get("walking_time_minutes") == cfg.WALK_TIME_LIMIT_MINUTES,
          f"threshold is {cfg.WALK_TIME_LIMIT_MINUTES} minutes "
          f"(got {summary.get('walking_time_minutes')})")
    check(summary.get("walking_time_seconds") == cfg.WALK_TIME_LIMIT_SECONDS,
          f"threshold is {cfg.WALK_TIME_LIMIT_SECONDS} seconds")
    check(abs(float(summary.get("walking_speed_ms", 0)) - cfg.kmh_to_ms(4.8)) < 1e-9,
          "walking speed in m/s is consistent with 4.8 km/h")
    check(abs(float(summary.get("distance_budget_m", 0))
              - cfg.walk_budget_m(cfg.MAIN_WALK_SPEED_KMH)) < 1e-9,
          f"distance budget is {cfg.walk_budget_m(cfg.MAIN_WALK_SPEED_KMH):.1f} m")
    check(str(summary.get("status", "")).startswith("PRELIMINARY"),
          "summary is labelled PRELIMINARY")
    check(summary.get("analysis_district_count") == cfg.EXPECTED_ANALYSIS_DISTRICTS,
          f"summary reports {cfg.EXPECTED_ANALYSIS_DISTRICTS} analysis districts")

    for key in ("metro_access_pct", "bus_only_pct", "underserved_pct",
                "analysis_population", "metro_access_population"):
        value = summary.get(key)
        check(isinstance(value, (int, float)) and math.isfinite(float(value)),
              f"summary.{key} is finite ({value})")

    total_pct = (float(summary["metro_access_pct"]) + float(summary["bus_only_pct"])
                 + float(summary["underserved_pct"]))
    check(abs(total_pct - 100.0) <= 1e-4,
          f"city percentages sum to 100 (got {total_pct:.8f})")

    if table is not None:
        for key, column in (
            ("analysis_population", "calibrated_population"),
            ("metro_access_population", "metro_access_population"),
            ("bus_only_population", "bus_only_population"),
            ("underserved_population", "underserved_population"),
        ):
            expected = float(table[column].sum())
            actual = float(summary[key])
            check(abs(actual - expected) <= POP_TOL,
                  f"summary.{key} matches the district sum "
                  f"({actual:,.2f} vs {expected:,.2f})")
        check(abs(float(summary["metro_access_population"])
                  - float(summary["analysis_population"])) <= 0
              or float(summary["metro_access_population"])
              <= float(summary["analysis_population"]) + POP_TOL,
              "city metro population never exceeds the city total")
        check(float(summary["combined_walk_access_population"])
              <= float(summary["analysis_population"]) + POP_TOL,
              "city metro + bus-only never exceeds the city total")
    return summary


def validate_speed_sensitivity() -> None:
    section("8. Walking-speed sensitivity")
    table = pd.read_csv(cfg.WALK_SPEED_SENSITIVITY_FILE)
    city = table[table.scope == "city"].sort_values("speed_kmh").reset_index(drop=True)

    check(sorted(city.speed_kmh.tolist()) == sorted(cfg.WALK_SPEED_SCENARIOS_KMH),
          f"city rows cover {list(cfg.WALK_SPEED_SCENARIOS_KMH)} km/h")
    budgets = [cfg.walk_budget_m(s) for s in sorted(cfg.WALK_SPEED_SCENARIOS_KMH)]
    check(np.allclose(city.budget_m.to_numpy(), budgets, atol=1e-6),
          f"budgets follow the speeds ({[round(b, 1) for b in budgets]} m)")

    metro = city.metro_access_pct.to_numpy()
    combined = city.combined_pct.to_numpy()
    underserved = city.underserved_pct.to_numpy()
    bus_only = city.bus_only_pct.to_numpy()
    print(f"    {'speed':>6s} {'budget m':>9s} {'metro%':>8s} {'bus-only%':>10s} "
          f"{'unserved%':>10s} {'combined%':>10s}")
    for _, r in city.iterrows():
        print(f"    {r.speed_kmh:6.1f} {r.budget_m:9.1f} {r.metro_access_pct:8.2f} "
              f"{r.bus_only_pct:10.2f} {r.underserved_pct:10.2f} {r.combined_pct:10.2f}")

    check(bool(np.all(np.diff(metro) >= -PCT_TOL)),
          f"metro access does not fall as walking speed rises ({metro.round(4).tolist()})")
    check(bool(np.all(np.diff(combined) >= -PCT_TOL)),
          f"combined transit access does not fall as speed rises ({combined.round(4).tolist()})")
    check(bool(np.all(np.diff(underserved) <= PCT_TOL)),
          f"underserved share does not rise as speed rises ({underserved.round(4).tolist()})")
    # Bus-only is a residual between two rising quantities and is NOT required
    # to be monotonic. Recorded so nobody later mistakes a dip for a defect.
    print(f"    bus-only across speeds (monotonicity NOT required): "
          f"{bus_only.round(4).tolist()}")

    districts = table[table.scope == "district"]
    check(districts.district_name.nunique() == cfg.EXPECTED_ANALYSIS_DISTRICTS,
          f"district sensitivity covers all {cfg.EXPECTED_ANALYSIS_DISTRICTS} districts")
    bad_metro, bad_combined, bad_under = [], [], []
    for name, group in districts.groupby("district_name"):
        ordered = group.sort_values("speed_kmh")
        if np.any(np.diff(ordered.metro_access_pct.to_numpy()) < -PCT_TOL):
            bad_metro.append(name)
        if np.any(np.diff(ordered.combined_pct.to_numpy()) < -PCT_TOL):
            bad_combined.append(name)
        if np.any(np.diff(ordered.underserved_pct.to_numpy()) > PCT_TOL):
            bad_under.append(name)
    check(not bad_metro, f"district metro access is monotonic in speed (violations: {bad_metro or 'none'})")
    check(not bad_combined, f"district combined access is monotonic (violations: {bad_combined or 'none'})")
    check(not bad_under, f"district underserved share is monotonic (violations: {bad_under or 'none'})")


def validate_surface_sensitivity() -> None:
    section("9. Population-surface sensitivity (2020 vs 2026)")
    table = pd.read_csv(cfg.POPULATION_SURFACE_SENSITIVITY_FILE)
    required = {
        "scope", "district_name",
        "metro_access_pct_using_2020_surface",
        "metro_access_pct_using_2026_surface",
        "percentage_point_difference",
    }
    check(required.issubset(table.columns),
          f"comparison columns present (missing: {sorted(required - set(table.columns)) or 'none'})")
    check((table.scope == "city").sum() == 1, "exactly one city row")
    check((table.scope == "district").sum() == cfg.EXPECTED_ANALYSIS_DISTRICTS,
          f"{cfg.EXPECTED_ANALYSIS_DISTRICTS} district rows")

    numeric = table.select_dtypes(include=[np.number]).to_numpy()
    check(bool(np.isfinite(numeric).all()), "all sensitivity values finite")
    pct_columns = ["metro_access_pct_using_2020_surface", "metro_access_pct_using_2026_surface"]
    check(bool(((table[pct_columns] >= 0) & (table[pct_columns] <= 100)).all().all()),
          "both surfaces give percentages within [0, 100]")

    difference = (table.metro_access_pct_using_2026_surface
                  - table.metro_access_pct_using_2020_surface)
    drift = float((difference - table.percentage_point_difference).abs().max())
    check(drift <= 1e-4, f"percentage_point_difference is 2026 minus 2020 (drift {drift:.8f})")

    city = table[table.scope == "city"].iloc[0]
    print(f"    city: 2020 surface {city.metro_access_pct_using_2020_surface:.4f}%  "
          f"2026 surface {city.metro_access_pct_using_2026_surface:.4f}%  "
          f"difference {city.percentage_point_difference:+.4f} pp")


def validate_geometry(manifest: dict) -> None:
    section("10. Boundary and service-area geometry")
    boundary = gpd.read_file(cfg.ANALYSIS_BOUNDARY_FILE)
    districts = gpd.read_file(cfg.DISTRICTS_FILE)
    analysis = districts[districts.in_siat.astype(bool)]

    check(boundary.crs is not None and boundary.crs.to_epsg() == 4326,
          f"analysis boundary is EPSG:4326 (got {boundary.crs})")
    check(bool(boundary.geometry.is_valid.all()), "analysis boundary geometry valid")
    check(len(boundary) == 1, f"analysis boundary is a single feature (got {len(boundary)})")
    check(int(boundary.district_count.iloc[0]) == cfg.EXPECTED_ANALYSIS_DISTRICTS,
          f"boundary records {cfg.EXPECTED_ANALYSIS_DISTRICTS} districts")

    boundary_m = boundary.to_crs(cfg.METRIC_CRS).geometry.iloc[0]
    union_m = analysis.to_crs(cfg.METRIC_CRS).union_all()
    symmetric = boundary_m.symmetric_difference(union_m).area
    check(symmetric / union_m.area < 1e-9,
          f"boundary equals the union of the 12 SIAT districts "
          f"(symmetric difference {symmetric:.6f} m2)")
    excluded = districts[~districts.in_siat.astype(bool)]
    for _, row in excluded.iterrows():
        inside = row.geometry.centroid.within(boundary.geometry.iloc[0])
        check(not inside, f"'{row.district_name}' is outside the analysis boundary")

    service = manifest.get("service_areas", {})
    check("AUGMENTED" in str(service.get("method", "")).upper(),
          "service areas are recorded as built from the augmented (edge-aware) segments")
    check("visualisation only" in str(service.get("purpose", "")),
          "service areas are recorded as visualisation only")

    for path, label, key in ((cfg.METRO_ISOCHRONE_FILE, "metro", "metro"),
                             (cfg.BUS_ISOCHRONE_FILE, "bus", "bus")):
        iso = gpd.read_file(path)
        check(len(iso) > 0, f"{label} service area is non-empty")
        check(iso.crs is not None and iso.crs.to_epsg() == 4326,
              f"{label} service area is EPSG:4326 (got {iso.crs})")
        check(bool(iso.geometry.is_valid.all()), f"{label} service area geometry valid")
        check(not bool(iso.geometry.is_empty.any()), f"{label} service area has no empty geometry")
        area = float(iso.to_crs(cfg.METRIC_CRS).area.sum() / 1e6)
        size = cfg.file_size_bytes(path)
        info = service.get(key, {})
        print(f"    {label}: {area:,.2f} km2, {cfg.human_size(size)}, "
              f"reachable network {info.get('reachable_network_length_km')} km, "
              f"segments full/partial {info.get('segments_fully_reachable')}/"
              f"{info.get('segments_partially_reachable')}")
        check(area > 1.0, f"{label} service area covers a plausible area ({area:,.2f} km2)")
        check(size < 5_000_000, f"{label} service area file is web-sized ({cfg.human_size(size)})")
        check(abs(area - float(service.get(f"{key}_area_km2", -1))) < 0.5,
              f"{label} service-area file area matches the manifest "
              f"({area:.2f} vs {service.get(f'{key}_area_km2')} km2)")
        check(int(info.get("segments_partially_reachable", 0)) > 0,
              f"{label} service area cuts partially reachable segments "
              f"({info.get('segments_partially_reachable')})")


def validate_access_points(manifest: dict) -> None:
    section("11. Metro access points")
    access = pd.read_csv(cfg.METRO_ACCESS_POINTS_FILE)
    check(set(access.access_type) <= {"entrance", "station_fallback"},
          f"access_type values are entrance/station_fallback (got {sorted(set(access.access_type))})")
    entrances = int((access.access_type == "entrance").sum())
    fallbacks = int((access.access_type == "station_fallback").sum())
    print(f"    entrances used: {entrances}   station fallbacks: {fallbacks}   "
          f"total: {len(access)}")
    check(entrances > 0, "at least one mapped entrance is used")
    check(access.access_id.is_unique, "access point ids unique")

    stations = gpd.read_file(cfg.METRO_STATIONS_FILE)
    check(fallbacks <= len(stations),
          f"fallback count does not exceed the station count ({fallbacks} <= {len(stations)})")
    fallback_rows = access[access.access_type == "station_fallback"]
    check(bool(fallback_rows.fallback_reason.notna().all()),
          "every fallback records why it was needed")
    check(bool((fallback_rows.nearest_entrance_distance_m
                > cfg.ENTRANCE_ASSOCIATION_RADIUS_M).all()),
          f"every fallback really has no entrance within "
          f"{cfg.ENTRANCE_ASSOCIATION_RADIUS_M:.0f} m")

    stats = manifest.get("metro_sources", {})
    check(stats.get("entrances_total") == entrances,
          f"manifest entrance count matches the file ({stats.get('entrances_total')} vs {entrances})")
    check(stats.get("stations_fallback") == fallbacks,
          f"manifest fallback count matches the file ({stats.get('stations_fallback')} vs {fallbacks})")
    check(stats.get("access_points_total") == len(access),
          f"manifest access-point total matches the file "
          f"({stats.get('access_points_total')} vs {len(access)})")

    for column in ("snap_edge_index", "snap_edge_fraction", "off_network_connector_m",
                   "snapped_into_edge_interior"):
        check(column in access.columns, f"access points record {column}")
    if "off_network_connector_m" in access.columns:
        check(bool(np.isfinite(access.off_network_connector_m).all()),
              "every access point has a finite off-network connector")
        check(bool((access.off_network_connector_m >= 0).all()),
              "every access point connector is non-negative")
        check(bool(((access.snap_edge_fraction >= 0) & (access.snap_edge_fraction <= 1)).all()),
              "every access point position lies within its edge")
        interior = int(access.snapped_into_edge_interior.astype(bool).sum())
        print(f"    access points spliced into edge interiors: {interior} / {len(access)}")


def validate_manifest_counts(manifest: dict) -> None:
    section("12. Analysis manifest")
    check(str(manifest.get("status", "")).startswith("PRELIMINARY"),
          "manifest is labelled PRELIMINARY")
    correction = manifest.get("correction", {})
    check("edge-aware" in str(correction.get("reason", "")),
          "manifest records why the nearest-node model was replaced")
    check(str(correction.get("supersedes", "")) != "",
          f"manifest records what this supersedes ({correction.get('supersedes')})")

    walking = manifest.get("walking_model", {})
    check(walking.get("main_speed_kmh") == cfg.MAIN_WALK_SPEED_KMH,
          f"manifest main speed is {cfg.MAIN_WALK_SPEED_KMH} km/h")
    check(walking.get("threshold_seconds") == cfg.WALK_TIME_LIMIT_SECONDS,
          f"manifest threshold is {cfg.WALK_TIME_LIMIT_SECONDS} s")
    check(list(walking.get("sensitivity_speeds_kmh", [])) == list(cfg.WALK_SPEED_SCENARIOS_KMH),
          f"manifest sensitivity speeds are {list(cfg.WALK_SPEED_SCENARIOS_KMH)}")
    boundary = manifest.get("analysis_boundary", {})
    check(boundary.get("district_count") == cfg.EXPECTED_ANALYSIS_DISTRICTS,
          f"manifest boundary has {cfg.EXPECTED_ANALYSIS_DISTRICTS} districts")

    counts = manifest.get("output_counts", {})
    expectations = {
        "district_rows": len(pd.read_csv(cfg.DISTRICT_ACCESS_METRICS_FILE)),
        "walking_speed_sensitivity_rows": len(pd.read_csv(cfg.WALK_SPEED_SENSITIVITY_FILE)),
        "population_surface_sensitivity_rows":
            len(pd.read_csv(cfg.POPULATION_SURFACE_SENSITIVITY_FILE)),
        "metro_access_point_rows": len(pd.read_csv(cfg.METRO_ACCESS_POINTS_FILE)),
        "transit_snap_rows": len(pd.read_csv(cfg.TRANSIT_SNAP_DIAGNOSTICS_FILE)),
    }
    for key, actual in expectations.items():
        check(counts.get(key) == actual,
              f"manifest {key} matches the file ({counts.get(key)} vs {actual})")

    factors = manifest.get("calibration_factors", [])
    check(len(factors) == cfg.EXPECTED_ANALYSIS_DISTRICTS,
          f"manifest records {cfg.EXPECTED_ANALYSIS_DISTRICTS} calibration factors")
    if factors:
        worst = max(abs(f["calibrated_population"] - f["official_population"]) for f in factors)
        check(worst <= POP_TOL,
              f"manifest calibration reproduces official totals (max difference {worst:.6f})")
        check(all(f["calibration_factor"] > 0 for f in factors),
              "all calibration factors positive")
        spread = max(f["calibration_factor"] for f in factors) / min(
            f["calibration_factor"] for f in factors)
        check(spread > 1.0,
              f"calibration factors are per-district, not one city-wide factor "
              f"(spread {spread:.2f}x)")

    stranded_metro = float(manifest.get("population_cells", {})
                           .get("population_without_metro_source", 0.0))
    stranded_bus = float(manifest.get("population_cells", {})
                         .get("population_without_bus_source", 0.0))
    print(f"    population on components with no metro source: {stranded_metro:,.1f}")
    print(f"    population on components with no bus source  : {stranded_bus:,.1f}")
    check(math.isfinite(stranded_metro) and stranded_metro >= 0,
          "disconnected metro population is a finite non-negative number")
    check(math.isfinite(stranded_bus) and stranded_bus >= 0,
          "disconnected bus population is a finite non-negative number")

    focus = manifest.get("district_focus", {})
    check(len(focus) == cfg.EXPECTED_ANALYSIS_DISTRICTS,
          f"manifest records a nearest-cell trace for all "
          f"{cfg.EXPECTED_ANALYSIS_DISTRICTS} districts (got {len(focus)})")

    for path in manifest.get("outputs", []):
        check((cfg.REPO_ROOT / path).exists(), f"manifest output exists: {path}")


def validate_cell_partition() -> None:
    """Re-derive the partition from the cached per-cell table."""
    section("13. Cell-level partition (from the cached per-cell table)")
    if not cfg.POPULATION_CELLS_CACHE.exists():
        check(False,
              f"{cfg.POPULATION_CELLS_CACHE.name} present for an independent cell-level "
              f"check (run scripts/analyze_accessibility.py)", critical=False)
        return
    cells = pd.read_parquet(cfg.POPULATION_CELLS_CACHE)
    speed_ms = cfg.kmh_to_ms(cfg.MAIN_WALK_SPEED_KMH)
    limit = cfg.WALK_TIME_LIMIT_SECONDS
    metro_ok = (cells.metro_distance_m / speed_ms) <= limit
    bus_ok = (cells.bus_distance_m / speed_ms) <= limit
    metro = metro_ok
    bus_only = (~metro_ok) & bus_ok
    underserved = (~metro_ok) & (~bus_ok)

    counts = metro.astype(int) + bus_only.astype(int) + underserved.astype(int)
    check(bool((counts == 1).all()),
          "every cell belongs to exactly one access category")
    check(int((metro & bus_only).sum()) == 0, "no cell is both metro and bus-only")
    check(int((metro & underserved).sum()) == 0, "no cell is both metro and underserved")
    check(int((bus_only & underserved).sum()) == 0, "no cell is both bus-only and underserved")
    check(bool((cells.population >= 0).all()), "no negative cell population")
    check(bool(np.isfinite(cells.population).all()), "all cell populations finite")
    check(bool((cells.metro_distance_m >= 0).all()), "no negative metro distance")
    check(bool((cells.bus_distance_m >= 0).all()), "no negative bus distance")
    check(cells.cell_id.is_unique, "cell ids unique - no cell counted twice")
    check(int(cells.district_name.nunique()) == cfg.EXPECTED_ANALYSIS_DISTRICTS,
          f"cells span exactly {cfg.EXPECTED_ANALYSIS_DISTRICTS} districts "
          f"({cells.district_name.nunique()})")

    table = pd.read_csv(cfg.DISTRICT_ACCESS_METRICS_FILE)
    recomputed = cells.population.where(metro, 0.0).sum()
    check(abs(recomputed - table.metro_access_population.sum()) <= POP_TOL,
          f"recomputed metro population matches the district table ({recomputed:,.2f})")
    recomputed_bus = cells.population.where(bus_only, 0.0).sum()
    check(abs(recomputed_bus - table.bus_only_population.sum()) <= POP_TOL,
          f"recomputed bus-only population matches the district table ({recomputed_bus:,.2f})")

    # Independent re-derivation of the district nearest-cell distances.
    nearest = cells.groupby("district_name", sort=True).metro_distance_m.min()
    merged = table.set_index("district_name").min_cell_metro_distance_m.reindex(nearest.index)
    drift = float((nearest - merged).abs().max())
    check(drift <= 1e-3,
          f"district nearest-cell metro distances match the cell table (drift {drift:.6f} m)")

    print(f"    cells: {len(cells):,}   metro {int(metro.sum()):,}  "
          f"bus-only {int(bus_only.sum()):,}  underserved {int(underserved.sum()):,}")


def main() -> int:
    print("=" * 74)
    print("Week 4 accessibility analysis - validation")
    print("PRELIMINARY RESULTS - pending independent audit")
    print("=" * 74)

    if not validate_files():
        section("Summary")
        print(f"  critical: {len(CRITICAL)}")
        print("\nVALIDATION FAILED - run scripts/analyze_accessibility.py first")
        return 1

    manifest = json.loads(cfg.ANALYSIS_MANIFEST_PATH.read_text(encoding="utf-8"))
    validate_routing_model(manifest)
    validate_synthetic_tests()
    validate_connectors(manifest)
    validate_connectors_from_cells(manifest)
    table = validate_districts()
    validate_city_summary(table)
    validate_speed_sensitivity()
    validate_surface_sensitivity()
    validate_geometry(manifest)
    validate_access_points(manifest)
    validate_manifest_counts(manifest)
    validate_cell_partition()

    section("Summary")
    print(f"  passed  : {len(PASSED)}")
    print(f"  warnings: {len(WARNINGS)}")
    print(f"  critical: {len(CRITICAL)}")
    for item in WARNINGS:
        print(f"    WARN  {item}")
    for item in CRITICAL:
        print(f"    FAIL  {item}")

    if CRITICAL:
        print("\nVALIDATION FAILED")
        return 1
    print("\nVALIDATION PASSED (results remain PRELIMINARY pending independent audit)")
    return 0


if __name__ == "__main__":
    enable_utf8_stdout()
    raise SystemExit(main())
