"""Create audited current-period bazaar--transit overlap artifacts.

    python scripts/analyze_transit_bazaar_overlap.py

Phase 2F is additive.  It reads the frozen current accessibility cell cache
and routes only the already-audited marketplace layer with the same edge-aware
network method used by Phase 2C.  It never rewrites an existing analysis
artifact, cache, routing source, or web asset.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import accessibility_utils as au  # noqa: E402
import analyze_urban_dimensions as urban_analysis  # noqa: E402
import config as cfg  # noqa: E402
import urban_dimensions as ud  # noqa: E402
from pipeline_utils import enable_utf8_stdout, log, step  # noqa: E402


BASE_SHA = "8de17adca1f05b7e1a9647c33b71c7811cd84b91"
EXPECTED_HASHES = {
    cfg.POPULATION_CELLS_CACHE: (
        ud.HASH_BASIS_RAW_BYTES,
        "948871e538fd0de66c4d30cf5d6c8c0deef3071c8e59d41581f96548e54a7c3b",
    ),
    cfg.WALK_GRAPH_FILE: (
        ud.HASH_BASIS_RAW_BYTES,
        "948da22f9a608b8d795c07bb8c8b8d04ca5abcbc429b51b1c99f5546772e9c41",
    ),
    cfg.BAZAARS_FILE: (
        ud.HASH_BASIS_CANONICAL_TEXT,
        "fbfcbf422ac8edc171608c06b00346a9976e764601fc3642a094c6be821cf56c",
    ),
}
INPUT_FILES = (
    (cfg.POPULATION_CELLS_CACHE, ud.HASH_BASIS_RAW_BYTES),
    (cfg.WALK_GRAPH_FILE, ud.HASH_BASIS_RAW_BYTES),
    (cfg.BAZAARS_FILE, ud.HASH_BASIS_CANONICAL_TEXT),
    (cfg.DISTRICT_ACCESS_METRICS_FILE, ud.HASH_BASIS_CANONICAL_TEXT),
    (cfg.CITY_ACCESS_SUMMARY_FILE, ud.HASH_BASIS_CANONICAL_TEXT),
    (cfg.URBAN_DIMENSIONS_CITY_FILE, ud.HASH_BASIS_CANONICAL_TEXT),
    (cfg.URBAN_DIMENSIONS_DISTRICT_FILE, ud.HASH_BASIS_CANONICAL_TEXT),
    (cfg.ANALYSIS_MANIFEST_PATH, ud.HASH_BASIS_CANONICAL_TEXT),
    (cfg.PHASE2C_MANIFEST_PATH, ud.HASH_BASIS_CANONICAL_TEXT),
)
POP_TOL = 1e-3
PCT_TOL = 1e-6
REQUIRED_CELL_COLUMNS = {
    "cell_id", "district_name", "population", "x_m", "y_m",
    "edge_index", "edge_fraction", "edge_connector_m",
    "metro_distance_m", "bus_distance_m",
}


def relative(path: Path) -> str:
    """Return a repository-relative, slash-normalized path."""
    return str(path.relative_to(cfg.REPO_ROOT)).replace("\\", "/")


def fail(message: str) -> None:
    """Fail closed before any Phase 2F artifact is written."""
    raise SystemExit(f"Phase 2F validation failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load_json(path: Path) -> dict:
    return json.loads(ud.canonical_utf8_lf_bytes(path).decode("utf-8"))


def verify_source_provenance() -> tuple[dict, dict]:
    """Verify the exact pinned cache and marketplace bytes before routing."""
    for path, (basis, expected_hash) in EXPECTED_HASHES.items():
        require(path.exists(), f"mandatory input is missing: {relative(path)}")
        actual = ud.provenance_record(path, basis)
        require(
            actual["sha256"] == expected_hash,
            f"{relative(path)} hash does not match the Phase 2F pin",
        )

    analysis_manifest = load_json(cfg.ANALYSIS_MANIFEST_PATH)
    phase2c_manifest = load_json(cfg.PHASE2C_MANIFEST_PATH)
    phase2c_inputs = phase2c_manifest.get("input_files", {})
    for path, (basis, expected_hash) in EXPECTED_HASHES.items():
        key = relative(path)
        record = phase2c_inputs.get(key)
        require(record is not None, f"Phase 2C manifest omits {key}")
        require(record.get("hash_basis") == basis, f"Phase 2C hash basis differs for {key}")
        require(record.get("sha256") == expected_hash, f"Phase 2C hash differs for {key}")
    require(
        analysis_manifest.get("walking_model", {}).get("main_budget_m") == 800.0,
        "current analysis manifest does not declare the 800 m headline budget",
    )
    return analysis_manifest, phase2c_manifest


def load_cells() -> pd.DataFrame:
    """Load and validate the exact current-period per-cell surface."""
    require(cfg.POPULATION_CELLS_CACHE.exists(), "population cell cache is missing")
    cells = pd.read_parquet(cfg.POPULATION_CELLS_CACHE)
    missing = sorted(REQUIRED_CELL_COLUMNS - set(cells.columns))
    require(not missing, f"population cell cache misses columns: {missing}")
    require(cells.cell_id.is_unique, "population cell identities are not unique")
    population = cells.population.to_numpy(dtype=np.float64)
    require(np.isfinite(population).all(), "population cache has non-finite weights")
    require((population >= 0.0).all(), "population cache has negative weights")
    for column in ("x_m", "y_m", "edge_fraction", "edge_connector_m"):
        require(
            np.isfinite(cells[column].to_numpy(dtype=np.float64)).all(),
            f"population cache has non-finite {column}",
        )
    require(
        ((cells.edge_fraction.to_numpy(dtype=np.float64) >= 0.0)
         & (cells.edge_fraction.to_numpy(dtype=np.float64) <= 1.0)).all(),
        "population cache has edge fractions outside [0, 1]",
    )
    require(
        (cells.edge_connector_m.to_numpy(dtype=np.float64) >= 0.0).all(),
        "population cache has negative edge connectors",
    )
    for column in ("metro_distance_m", "bus_distance_m"):
        distance = cells[column].to_numpy(dtype=np.float64)
        require(not np.isnan(distance).any(), f"population cache has NaN {column}")
        require((distance >= 0.0).all(), f"population cache has negative {column}")
    return cells


def classify_transit(cells: pd.DataFrame, budget_m: float) -> dict[str, np.ndarray]:
    """Apply the frozen mutually exclusive current-period transit definitions."""
    metro_distance = cells.metro_distance_m.to_numpy(dtype=np.float64)
    bus_distance = cells.bus_distance_m.to_numpy(dtype=np.float64)
    metro = metro_distance <= budget_m
    bus_only = (metro_distance > budget_m) & (bus_distance <= budget_m)
    underserved = (metro_distance > budget_m) & (bus_distance > budget_m)
    memberships = metro.astype(np.int8) + bus_only.astype(np.int8) + underserved.astype(np.int8)
    require((memberships == 1).all(), "transit categories do not partition every cell once")
    return {"metro": metro, "bus_only": bus_only, "underserved": underserved}


def weighted_population(population: np.ndarray, mask: np.ndarray) -> float:
    return float(population[mask].sum(dtype=np.float64))


def percentage(numerator: float, denominator: float) -> float:
    require(denominator > 0.0, "a percentage denominator must be positive")
    return 100.0 * numerator / denominator


def overlap_masks(transit: dict[str, np.ndarray], bazaar: np.ndarray) -> dict[str, np.ndarray]:
    """Intersect each exclusive transit class with the bazaar mask."""
    return {
        "metro_and_bazaar": transit["metro"] & bazaar,
        "bus_only_and_bazaar": transit["bus_only"] & bazaar,
        "underserved_and_bazaar": transit["underserved"] & bazaar,
    }


def validate_overlap_masks(
    transit: dict[str, np.ndarray], bazaar: np.ndarray, overlaps: dict[str, np.ndarray],
    population: np.ndarray,
) -> None:
    """Verify conservation, disjointness, and parent bounds before output."""
    expected = {
        "metro_and_bazaar": transit["metro"],
        "bus_only_and_bazaar": transit["bus_only"],
        "underserved_and_bazaar": transit["underserved"],
    }
    union = np.zeros(len(population), dtype=bool)
    for label, mask in overlaps.items():
        require(mask.dtype == bool and len(mask) == len(population), f"invalid {label} mask")
        require(not (union & mask).any(), f"{label} is not disjoint from another overlap")
        require(not (mask & ~expected[label]).any(), f"{label} exceeds its transit parent")
        require(not (mask & ~bazaar).any(), f"{label} exceeds bazaar access")
        union |= mask
    require(np.array_equal(union, bazaar), "overlap masks do not conserve the bazaar mask")
    overlap_total = sum(weighted_population(population, mask) for mask in overlaps.values())
    bazaar_total = weighted_population(population, bazaar)
    require(abs(overlap_total - bazaar_total) <= POP_TOL, "overlap populations do not conserve bazaar population")


def baseline_reconciliation(
    cells: pd.DataFrame, transit: dict[str, np.ndarray], budget_m: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Reproduce frozen population and current transit outputs from cells."""
    district_metrics = pd.read_csv(cfg.DISTRICT_ACCESS_METRICS_FILE)
    city_summary = load_json(cfg.CITY_ACCESS_SUMMARY_FILE)
    urban_city = pd.read_csv(cfg.URBAN_DIMENSIONS_CITY_FILE)
    urban_district = pd.read_csv(cfg.URBAN_DIMENSIONS_DISTRICT_FILE)
    require(len(district_metrics) == cfg.EXPECTED_ANALYSIS_DISTRICTS,
            "district accessibility table does not hold twelve districts")
    require(district_metrics.district_name.is_unique, "district accessibility labels are not unique")
    require(len(urban_city) == 1, "Phase 2C city table does not hold one row")
    require(len(urban_district) == cfg.EXPECTED_ANALYSIS_DISTRICTS,
            "Phase 2C district table does not hold twelve rows")

    population = cells.population.to_numpy(dtype=np.float64)
    city_total = float(population.sum(dtype=np.float64))
    require(abs(city_total - 3_212_200.0) <= POP_TOL,
            "cell population does not reproduce the approved 3,212,200 denominator")
    require(abs(float(district_metrics.calibrated_population.sum()) - city_total) <= POP_TOL,
            "district accessibility totals do not reproduce the population cache")
    require(abs(float(city_summary["analysis_population"]) - city_total) <= POP_TOL,
            "city access summary denominator differs from the population cache")
    require(float(city_summary["distance_budget_m"]) == budget_m,
            "city access summary uses a different walking budget")

    city_labels = {
        "metro": "metro_access_population",
        "bus_only": "bus_only_population",
        "underserved": "underserved_population",
    }
    for label, output_name in city_labels.items():
        calculated = weighted_population(population, transit[label])
        require(abs(calculated - float(city_summary[output_name])) <= POP_TOL,
                f"{label} city total does not reproduce the frozen headline")

    calculated_rows = []
    for district_name, group in cells.groupby("district_name", sort=True):
        selector = cells.district_name.to_numpy(dtype=str) == district_name
        denominator = weighted_population(population, selector)
        calculated_rows.append({
            "district_name": district_name,
            "population": denominator,
            "metro_access_population": weighted_population(population, transit["metro"] & selector),
            "bus_only_population": weighted_population(population, transit["bus_only"] & selector),
            "underserved_population": weighted_population(population, transit["underserved"] & selector),
        })
    calculated_district = pd.DataFrame(calculated_rows).sort_values("district_name", kind="stable")
    expected_names = sorted(district_metrics.district_name.astype(str).tolist())
    require(calculated_district.district_name.tolist() == expected_names,
            "population cache district labels differ from the frozen metrics")
    merged = district_metrics.merge(calculated_district, on="district_name", suffixes=("_frozen", "_calculated"), validate="1:1")
    require(bool(np.allclose(merged.calibrated_population, merged.population,
                             atol=POP_TOL, rtol=0.0)),
            "district denominators do not reproduce frozen calibrated totals")
    for column in city_labels.values():
        require(bool(np.allclose(merged[f"{column}_frozen"], merged[f"{column}_calculated"],
                                 atol=POP_TOL, rtol=0.0)),
                f"district {column} does not reproduce frozen metrics")
    return district_metrics, urban_city, urban_district


def reconcile_bazaar(
    cells: pd.DataFrame, bazaar: np.ndarray, urban_city: pd.DataFrame,
    urban_district: pd.DataFrame,
) -> None:
    """Confirm the rerouted bazaar mask reproduces every Phase 2C total."""
    population = cells.population.to_numpy(dtype=np.float64)
    total = float(population.sum(dtype=np.float64))
    city_population = weighted_population(population, bazaar)
    city_pct = percentage(city_population, total)
    row = urban_city.iloc[0]
    require(abs(city_population - float(row.bazaar_10min_population)) <= POP_TOL,
            "bazaar city population does not reproduce Phase 2C")
    require(abs(city_pct - float(row.bazaar_10min_pct)) <= PCT_TOL,
            "bazaar city percentage does not reproduce Phase 2C")
    require(int(bazaar.sum()) == int(row.bazaar_accessible_cells),
            "bazaar accessible cell count does not reproduce Phase 2C")

    expected = urban_district.set_index("district_name")
    for district_name in sorted(cells.district_name.astype(str).unique()):
        selector = cells.district_name.to_numpy(dtype=str) == district_name
        denominator = weighted_population(population, selector)
        observed = weighted_population(population, bazaar & selector)
        require(district_name in expected.index, f"Phase 2C omits district {district_name}")
        source = expected.loc[district_name]
        require(abs(observed - float(source.bazaar_10min_population)) <= POP_TOL,
                f"bazaar population does not reproduce Phase 2C for {district_name}")
        require(abs(percentage(observed, denominator) - float(source.bazaar_10min_pct)) <= PCT_TOL,
                f"bazaar percentage does not reproduce Phase 2C for {district_name}")


def city_row(
    cells: pd.DataFrame, transit: dict[str, np.ndarray], bazaar: np.ndarray,
    overlaps: dict[str, np.ndarray], budget_m: float,
) -> dict[str, object]:
    population = cells.population.to_numpy(dtype=np.float64)
    denominator = float(population.sum(dtype=np.float64))
    row: dict[str, object] = {
        "analysis": "Phase 2F current bazaar-transit overlap",
        "analysis_version": cfg.PHASE2F_ANALYSIS_VERSION,
        "period": "current",
        "population_total": denominator,
        "population_cells": int(len(cells)),
        "walking_speed_kmh": cfg.MAIN_WALK_SPEED_KMH,
        "walking_time_minutes": cfg.WALK_TIME_LIMIT_MINUTES,
        "distance_budget_m": budget_m,
        "metro_access_population": weighted_population(population, transit["metro"]),
        "bus_only_population": weighted_population(population, transit["bus_only"]),
        "underserved_population": weighted_population(population, transit["underserved"]),
        "bazaar_10min_population": weighted_population(population, bazaar),
    }
    for label, mask in overlaps.items():
        value = weighted_population(population, mask)
        row[f"{label}_10min_population"] = value
        row[f"{label}_10min_pct"] = percentage(value, denominator)
    return row


def district_rows(
    cells: pd.DataFrame, transit: dict[str, np.ndarray], bazaar: np.ndarray,
    overlaps: dict[str, np.ndarray],
) -> list[dict[str, object]]:
    population = cells.population.to_numpy(dtype=np.float64)
    names = sorted(cells.district_name.astype(str).unique().tolist())
    rows = []
    district_ids = cells.district_name.to_numpy(dtype=str)
    for name in names:
        selector = district_ids == name
        denominator = weighted_population(population, selector)
        row: dict[str, object] = {
            "district_name": name,
            "population": denominator,
            "metro_access_population": weighted_population(population, transit["metro"] & selector),
            "bus_only_population": weighted_population(population, transit["bus_only"] & selector),
            "underserved_population": weighted_population(population, transit["underserved"] & selector),
            "bazaar_10min_population": weighted_population(population, bazaar & selector),
        }
        for label, mask in overlaps.items():
            value = weighted_population(population, mask & selector)
            row[f"{label}_10min_population"] = value
            row[f"{label}_10min_pct"] = percentage(value, denominator)
        rows.append(row)
    return rows


def format_value(column: str, value: object) -> str:
    """Use stable precision without rounding internal calculation inputs."""
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (np.floating, float)):
        if column.endswith("_pct"):
            return f"{float(value):.9f}"
        if "population" in column:
            return f"{float(value):.6f}"
        if column == "walking_speed_kmh":
            return f"{float(value):.1f}"
        if column == "distance_budget_m":
            return f"{float(value):.1f}"
        return f"{float(value):.6f}"
    return str(value)


def write_stable_csv(rows: list[dict[str, object]], path: Path, columns: list[str]) -> None:
    """Write UTF-8 CSV with LF line endings and fixed analytical precision."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: format_value(column, row[column]) for column in columns})


CITY_COLUMNS = [
    "analysis", "analysis_version", "period", "population_total", "population_cells",
    "walking_speed_kmh", "walking_time_minutes", "distance_budget_m",
    "metro_access_population", "bus_only_population", "underserved_population",
    "bazaar_10min_population", "metro_and_bazaar_10min_population",
    "metro_and_bazaar_10min_pct", "bus_only_and_bazaar_10min_population",
    "bus_only_and_bazaar_10min_pct", "underserved_and_bazaar_10min_population",
    "underserved_and_bazaar_10min_pct",
]
DISTRICT_COLUMNS = [
    "district_name", "population", "metro_access_population", "bus_only_population",
    "underserved_population", "bazaar_10min_population",
    "metro_and_bazaar_10min_population", "metro_and_bazaar_10min_pct",
    "bus_only_and_bazaar_10min_population", "bus_only_and_bazaar_10min_pct",
    "underserved_and_bazaar_10min_population", "underserved_and_bazaar_10min_pct",
]


def build_manifest(
    analysis_manifest: dict, phase2c_manifest: dict, city: dict[str, object],
    district: list[dict[str, object]], bazaar_diagnostics: dict, bazaar_placement: dict,
) -> dict:
    """Create an auditable, timestamp-free manifest after deterministic outputs exist."""
    return {
        "analysis": "Phase 2F current bazaar-transit overlap",
        "analysis_version": cfg.PHASE2F_ANALYSIS_VERSION,
        "period": "current",
        "base_main_sha": BASE_SHA,
        "composite_score_or_ranking": False,
        "historical_or_causal_claim": False,
        "analysis_geography": {
            "districts": cfg.EXPECTED_ANALYSIS_DISTRICTS,
            "excluded": "Yangi Toshkent Tumani has no matching official SIAT population row",
            "population_total": city["population_total"],
            "population_cells": city["population_cells"],
        },
        "walking_model": {
            "speed_kmh": city["walking_speed_kmh"],
            "threshold_minutes": city["walking_time_minutes"],
            "distance_budget_m": city["distance_budget_m"],
            "routing_crs": cfg.METRIC_CRS,
            "routing_method": "edge-aware augmented-network multi-source Dijkstra",
        },
        "source_provenance": {
            "analysis_manifest_version": analysis_manifest.get("analysis_version"),
            "phase2c_manifest_version": phase2c_manifest.get("analysis_version"),
            "bazaar_definition": "existing OSM amenity=marketplace layer only",
            "bazaar_routing_sources": int(bazaar_diagnostics["count"]),
            "bazaar_connector_diagnostics_m": bazaar_diagnostics,
            "bazaar_source_placement": bazaar_placement,
        },
        "transit_classes": {
            "metro": "metro_distance_m <= 800.0",
            "bus_only": "metro_distance_m > 800.0 and bus_distance_m <= 800.0",
            "underserved": "metro_distance_m > 800.0 and bus_distance_m > 800.0",
            "partition": "mutually exclusive and complete across current population cells; +inf is legitimate, NaN is forbidden",
        },
        "overlap_metrics": {
            "metro_and_bazaar": "metro and bazaar_distance_m <= 800.0",
            "bus_only_and_bazaar": "bus_only and bazaar_distance_m <= 800.0",
            "underserved_and_bazaar": "underserved and bazaar_distance_m <= 800.0",
            "percentage_denominator": "the entire current analysed city or named district population",
            "conditional_bazaar_shares_written": False,
        },
        "deterministic_generation": {
            "district_order": "ascending district_name",
            "population_precision": "six decimal places",
            "percentage_precision": "nine decimal places",
            "timestamps": "omitted",
        },
        "input_files": {
            relative(path): ud.provenance_record(path, basis) for path, basis in INPUT_FILES
        },
        "output_files": {
            relative(path): ud.provenance_record(path, ud.HASH_BASIS_CANONICAL_TEXT)
            for path in (cfg.TRANSIT_BAZAAR_OVERLAP_CITY_FILE, cfg.TRANSIT_BAZAAR_OVERLAP_DISTRICT_FILE)
        },
        "output_rows": {
            relative(cfg.TRANSIT_BAZAAR_OVERLAP_CITY_FILE): 1,
            relative(cfg.TRANSIT_BAZAAR_OVERLAP_DISTRICT_FILE): len(district),
        },
        "limitations": [
            "The OSM amenity=marketplace layer is a mapped lower bound, not a bazaar census.",
            "Population-cell and source connectors are straight-line approximations to a mapped walkable edge and can cross unmapped barriers.",
            "The result measures simultaneous modelled walking proximity to a transit class and a bazaar, not observed trips, transfers, service quality, fares, reliability, crowding or destination usefulness.",
            "The calibrated WorldPop R2025A surface supplies within-district weights and is not validated ground truth.",
            "Current metro and bus distances are not the standardized historical accessibility frame.",
        ],
    }


def main() -> int:  # noqa: PLR0915 - explicit validation gates are intentional
    enable_utf8_stdout()
    step("PHASE 2F  Current bazaar--transit overlap")
    budget_m = cfg.PHASE2F_ACCESS_DISTANCE_BUDGET_M
    require(budget_m == cfg.PHASE2C_ACCESS_DISTANCE_BUDGET_M == cfg.walk_budget_m(cfg.MAIN_WALK_SPEED_KMH),
            "Phase 2F budget differs from the frozen current model")

    step("STEP 1  Pinned source provenance")
    analysis_manifest, phase2c_manifest = verify_source_provenance()
    log("  required population, network and bazaar hashes match the committed manifests")

    step("STEP 2  Current population and transit baselines")
    cells = load_cells()
    transit = classify_transit(cells, budget_m)
    district_metrics, urban_city, urban_district = baseline_reconciliation(cells, transit, budget_m)
    log(f"  {len(cells):,} cells; {len(district_metrics)} districts; current transit totals reconcile")

    step("STEP 3  Reproduce bazaar network accessibility")
    network = au.load_walk_network(cfg.WALK_GRAPH_FILE)
    tree = au.build_edge_index(network)
    bazaars = urban_analysis.bazaar_points()
    bazaar_distance, bazaar_diagnostics, bazaar_placement = urban_analysis.route_class(
        network, tree, bazaars, cells, "bazaars"
    )
    require(not np.isnan(bazaar_distance).any(), "bazaar routing produced NaN distances")
    bazaar = bazaar_distance <= budget_m
    reconcile_bazaar(cells, bazaar, urban_city, urban_district)

    step("STEP 4  Population-weighted intersections")
    population = cells.population.to_numpy(dtype=np.float64)
    overlaps = overlap_masks(transit, bazaar)
    validate_overlap_masks(transit, bazaar, overlaps, population)
    city = city_row(cells, transit, bazaar, overlaps, budget_m)
    district = district_rows(cells, transit, bazaar, overlaps)
    log("  intersections are disjoint and conserve the existing bazaar-accessible population")

    step("STEP 5  Deterministic additive artifacts")
    write_stable_csv([city], cfg.TRANSIT_BAZAAR_OVERLAP_CITY_FILE, CITY_COLUMNS)
    write_stable_csv(district, cfg.TRANSIT_BAZAAR_OVERLAP_DISTRICT_FILE, DISTRICT_COLUMNS)
    manifest = build_manifest(
        analysis_manifest, phase2c_manifest, city, district, bazaar_diagnostics, bazaar_placement
    )
    ud.write_json_lf(cfg.PHASE2F_MANIFEST_PATH, manifest)
    log(f"  wrote {relative(cfg.TRANSIT_BAZAAR_OVERLAP_CITY_FILE)}")
    log(f"  wrote {relative(cfg.TRANSIT_BAZAAR_OVERLAP_DISTRICT_FILE)}")
    log(f"  wrote {relative(cfg.PHASE2F_MANIFEST_PATH)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
