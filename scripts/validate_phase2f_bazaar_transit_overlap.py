"""Fail-closed validator for the Phase 2F bazaar--transit overlap artifacts.

    python scripts/validate_phase2f_bazaar_transit_overlap.py

The arithmetic below intentionally does not call Phase 2F's classification or
aggregation helpers.  It independently rebuilds the masks from the cached
distances and checks the committed CSVs against that calculation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import accessibility_utils as au  # noqa: E402
import analyze_urban_dimensions as urban_analysis  # noqa: E402
import config as cfg  # noqa: E402
import urban_dimensions as ud  # noqa: E402


BASE_SHA = "8de17adca1f05b7e1a9647c33b71c7811cd84b91"
BUDGET_M = 800.0
POP_TOL = 1e-3
PCT_TOL = 1e-6
EXPECTED_HASHES = {
    "data/external/population_cells.parquet": (
        ud.HASH_BASIS_RAW_BYTES,
        "948871e538fd0de66c4d30cf5d6c8c0deef3071c8e59d41581f96548e54a7c3b",
    ),
    "data/external/tashkent_walk_network.graphml": (
        ud.HASH_BASIS_RAW_BYTES,
        "948da22f9a608b8d795c07bb8c8b8d04ca5abcbc429b51b1c99f5546772e9c41",
    ),
    "data/processed/bazaars.geojson": (
        ud.HASH_BASIS_CANONICAL_TEXT,
        "fbfcbf422ac8edc171608c06b00346a9976e764601fc3642a094c6be821cf56c",
    ),
}
CITY_COLUMNS = (
    "analysis", "analysis_version", "period", "population_total", "population_cells",
    "walking_speed_kmh", "walking_time_minutes", "distance_budget_m",
    "metro_access_population", "bus_only_population", "underserved_population",
    "bazaar_10min_population", "metro_and_bazaar_10min_population",
    "metro_and_bazaar_10min_pct", "bus_only_and_bazaar_10min_population",
    "bus_only_and_bazaar_10min_pct", "underserved_and_bazaar_10min_population",
    "underserved_and_bazaar_10min_pct",
)
DISTRICT_COLUMNS = (
    "district_name", "population", "metro_access_population", "bus_only_population",
    "underserved_population", "bazaar_10min_population",
    "metro_and_bazaar_10min_population", "metro_and_bazaar_10min_pct",
    "bus_only_and_bazaar_10min_population", "bus_only_and_bazaar_10min_pct",
    "underserved_and_bazaar_10min_population", "underserved_and_bazaar_10min_pct",
)
NUMERIC_CITY = tuple(column for column in CITY_COLUMNS if column not in {
    "analysis", "analysis_version", "period"
})
NUMERIC_DISTRICT = tuple(column for column in DISTRICT_COLUMNS if column != "district_name")
ALLOWED_CHANGED_FILES = {
    "scripts/config.py",
    "scripts/analyze_transit_bazaar_overlap.py",
    "scripts/validate_phase2f_bazaar_transit_overlap.py",
    "scripts/test_transit_bazaar_overlap.py",
    "data/processed/transit_bazaar_overlap_city.csv",
    "data/processed/transit_bazaar_overlap_district.csv",
    "data/phase2f_bazaar_transit_overlap_manifest.json",
    "docs/phase2f_bazaar_transit_overlap.md",
}

passed = 0
failed = 0


def check(condition: bool, label: str, detail: str | None = None) -> bool:
    """Record one validation gate without masking later failures."""
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


def canonical_json(path: Path) -> dict:
    return json.loads(ud.canonical_utf8_lf_bytes(path).decode("utf-8"))


def path_from_relative(relative: str) -> Path:
    return cfg.REPO_ROOT / relative


def validate_cell_frame(cells: pd.DataFrame) -> list[str]:
    """Return errors for cell-cache hostile cases, allowing only +inf distances."""
    required = {
        "cell_id", "district_name", "population", "x_m", "y_m",
        "edge_index", "edge_fraction", "edge_connector_m",
        "metro_distance_m", "bus_distance_m",
    }
    errors = []
    missing = sorted(required - set(cells.columns))
    if missing:
        errors.append(f"missing required columns: {missing}")
        return errors
    if not cells.cell_id.is_unique:
        errors.append("duplicate cell identity")
    population = pd.to_numeric(cells.population, errors="coerce").to_numpy(float)
    if not np.isfinite(population).all() or (population < 0.0).any():
        errors.append("non-finite or negative population")
    for column in ("x_m", "y_m", "edge_fraction", "edge_connector_m"):
        values = pd.to_numeric(cells[column], errors="coerce").to_numpy(float)
        if not np.isfinite(values).all():
            errors.append(f"non-finite {column}")
    fraction = pd.to_numeric(cells.edge_fraction, errors="coerce").to_numpy(float)
    connector = pd.to_numeric(cells.edge_connector_m, errors="coerce").to_numpy(float)
    if not ((fraction >= 0.0) & (fraction <= 1.0)).all():
        errors.append("edge fraction outside [0, 1]")
    if (connector < 0.0).any():
        errors.append("negative edge connector")
    for column in ("metro_distance_m", "bus_distance_m"):
        distance = pd.to_numeric(cells[column], errors="coerce").to_numpy(float)
        if np.isnan(distance).any() or (distance < 0.0).any():
            errors.append(f"NaN or negative {column}")
    return errors


def expected_results(cells: pd.DataFrame, bazaar_distance: np.ndarray) -> tuple[dict, list[dict], dict]:
    """Independently calculate expected city, district and mask values."""
    population = cells.population.to_numpy(dtype=float)
    metro_distance = cells.metro_distance_m.to_numpy(dtype=float)
    bus_distance = cells.bus_distance_m.to_numpy(dtype=float)
    metro = metro_distance <= BUDGET_M
    bus_only = (metro_distance > BUDGET_M) & (bus_distance <= BUDGET_M)
    underserved = (metro_distance > BUDGET_M) & (bus_distance > BUDGET_M)
    bazaar = bazaar_distance <= BUDGET_M
    overlaps = {
        "metro_and_bazaar": metro & bazaar,
        "bus_only_and_bazaar": bus_only & bazaar,
        "underserved_and_bazaar": underserved & bazaar,
    }
    total = float(population.sum(dtype=float))

    def weighted(mask: np.ndarray) -> float:
        return float(population[mask].sum(dtype=float))

    def pct(value: float, denominator: float) -> float:
        return 100.0 * value / denominator

    city = {
        "analysis": "Phase 2F current bazaar-transit overlap",
        "analysis_version": cfg.PHASE2F_ANALYSIS_VERSION,
        "period": "current",
        "population_total": total,
        "population_cells": int(len(cells)),
        "walking_speed_kmh": cfg.MAIN_WALK_SPEED_KMH,
        "walking_time_minutes": cfg.WALK_TIME_LIMIT_MINUTES,
        "distance_budget_m": BUDGET_M,
        "metro_access_population": weighted(metro),
        "bus_only_population": weighted(bus_only),
        "underserved_population": weighted(underserved),
        "bazaar_10min_population": weighted(bazaar),
    }
    for label, mask in overlaps.items():
        value = weighted(mask)
        city[f"{label}_10min_population"] = value
        city[f"{label}_10min_pct"] = pct(value, total)

    rows = []
    district_ids = cells.district_name.to_numpy(dtype=str)
    for district_name in sorted(set(district_ids.tolist())):
        selector = district_ids == district_name
        denominator = weighted(selector)
        row = {
            "district_name": district_name,
            "population": denominator,
            "metro_access_population": weighted(metro & selector),
            "bus_only_population": weighted(bus_only & selector),
            "underserved_population": weighted(underserved & selector),
            "bazaar_10min_population": weighted(bazaar & selector),
        }
        for label, mask in overlaps.items():
            value = weighted(mask & selector)
            row[f"{label}_10min_population"] = value
            row[f"{label}_10min_pct"] = pct(value, denominator)
        rows.append(row)
    return city, rows, {
        "metro": metro, "bus_only": bus_only, "underserved": underserved,
        "bazaar": bazaar, **overlaps,
    }


def table_errors(city: pd.DataFrame, district: pd.DataFrame, expected_city: dict,
                 expected_district: list[dict]) -> list[str]:
    """Independently validate schemas, ordering, values and denominators."""
    errors = []
    if tuple(city.columns) != CITY_COLUMNS:
        errors.append("city columns differ from the Phase 2F contract")
        return errors
    if tuple(district.columns) != DISTRICT_COLUMNS:
        errors.append("district columns differ from the Phase 2F contract")
        return errors
    if len(city) != 1:
        errors.append("city output does not have exactly one row")
        return errors
    if len(district) != cfg.EXPECTED_ANALYSIS_DISTRICTS or not district.district_name.is_unique:
        errors.append("district output does not have exactly twelve unique rows")
        return errors
    expected_names = [row["district_name"] for row in expected_district]
    if district.district_name.tolist() != expected_names:
        errors.append("district rows are not in deterministic district-name order")
        return errors
    for column in (*NUMERIC_CITY, *NUMERIC_DISTRICT):
        frame = city if column in city.columns else district
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(float)
        if not np.isfinite(values).all():
            errors.append(f"non-finite output value in {column}")
    if errors:
        return errors

    city_row = city.iloc[0]
    for column in CITY_COLUMNS:
        expected = expected_city[column]
        actual = city_row[column]
        if column in NUMERIC_CITY:
            tolerance = PCT_TOL if column.endswith("_pct") else POP_TOL
            if not np.isclose(float(actual), float(expected), atol=tolerance, rtol=0.0):
                errors.append(f"city {column} does not match independent calculation")
        elif str(actual) != str(expected):
            errors.append(f"city {column} label differs")
    for index, expected in enumerate(expected_district):
        actual = district.iloc[index]
        for column in DISTRICT_COLUMNS:
            if column == "district_name":
                continue
            tolerance = PCT_TOL if column.endswith("_pct") else POP_TOL
            if not np.isclose(float(actual[column]), float(expected[column]), atol=tolerance, rtol=0.0):
                errors.append(f"district {expected['district_name']} {column} differs")
    return errors


def git_changed_paths() -> tuple[bool, list[str]]:
    result = subprocess.run(
        ["git", "diff", "--name-only", BASE_SHA, "--"], cwd=cfg.REPO_ROOT,
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False, ["git diff failed"]
    return True, [line for line in result.stdout.splitlines() if line.strip()]


def main() -> int:  # noqa: PLR0915 - every required gate is explicit
    section("Phase 2F source provenance")
    manifest = canonical_json(cfg.PHASE2F_MANIFEST_PATH)
    phase2c = canonical_json(cfg.PHASE2C_MANIFEST_PATH)
    input_records = manifest.get("input_files", {})
    for relative, (basis, expected_hash) in EXPECTED_HASHES.items():
        path = path_from_relative(relative)
        record = ud.provenance_record(path, basis) if path.exists() else None
        check(record is not None, f"mandatory source exists: {relative}")
        if record is None:
            continue
        check(record["sha256"] == expected_hash, f"pinned hash matches: {relative}")
        check(input_records.get(relative) == record, f"manifest records current source: {relative}")
        check(phase2c.get("input_files", {}).get(relative, {}).get("sha256") == expected_hash,
              f"Phase 2C agrees on source hash: {relative}")
    check(manifest.get("analysis_version") == cfg.PHASE2F_ANALYSIS_VERSION,
          "manifest has the expected methodology version")
    check(manifest.get("walking_model", {}).get("distance_budget_m") == BUDGET_M,
          "manifest records the exact 800 m budget")
    check(manifest.get("historical_or_causal_claim") is False,
          "manifest rejects historical and causal claims")
    check(manifest.get("composite_score_or_ranking") is False,
          "manifest rejects composite scores and rankings")
    manifest_inputs_ok = True
    manifest_input_problems = []
    for relative, recorded in input_records.items():
        path = path_from_relative(relative)
        basis = recorded.get("hash_basis")
        if basis not in (ud.HASH_BASIS_CANONICAL_TEXT, ud.HASH_BASIS_RAW_BYTES):
            manifest_inputs_ok = False
            manifest_input_problems.append(f"{relative}: unknown hash basis")
            continue
        if not path.exists() or ud.provenance_record(path, basis) != recorded:
            manifest_inputs_ok = False
            manifest_input_problems.append(f"{relative}: missing or changed")
    check(manifest_inputs_ok, "every recorded Phase 2F input hash and size matches",
          "; ".join(manifest_input_problems))

    section("Cell cache and frozen transit baselines")
    cells = pd.read_parquet(cfg.POPULATION_CELLS_CACHE)
    cell_errors = validate_cell_frame(cells)
    check(not cell_errors, "cell cache has valid identities, weights and distances", "; ".join(cell_errors))
    if cell_errors:
        print("\nVALIDATION FAILED")
        return 1
    check(len(cells) == 65_169 and cells.cell_id.nunique() == 65_169,
          "population cache has 65,169 unique cells")
    check(cells.district_name.nunique() == cfg.EXPECTED_ANALYSIS_DISTRICTS,
          "population cache has exactly twelve districts")
    check(abs(float(cells.population.sum()) - 3_212_200.0) <= POP_TOL,
          "population cache reproduces 3,212,200 residents")
    current = pd.read_csv(cfg.DISTRICT_ACCESS_METRICS_FILE).set_index("district_name")
    summary = canonical_json(cfg.CITY_ACCESS_SUMMARY_FILE)

    section("Independent bazaar routing and output arithmetic")
    network = au.load_walk_network(cfg.WALK_GRAPH_FILE)
    tree = au.build_edge_index(network)
    bazaar_distance, _, _ = urban_analysis.route_class(
        network, tree, urban_analysis.bazaar_points(), cells, "bazaars"
    )
    check(not np.isnan(bazaar_distance).any(), "bazaar routing has no NaN distances")
    city_expected, district_expected, masks = expected_results(cells, bazaar_distance)
    memberships = masks["metro"].astype(np.int8) + masks["bus_only"].astype(np.int8) + masks["underserved"].astype(np.int8)
    check((memberships == 1).all(), "metro, bus-only and underserved partition every cell")
    check(not (masks["metro_and_bazaar"] & masks["bus_only_and_bazaar"]).any()
          and not (masks["metro_and_bazaar"] & masks["underserved_and_bazaar"]).any()
          and not (masks["bus_only_and_bazaar"] & masks["underserved_and_bazaar"]).any(),
          "the three intersection masks are pairwise disjoint")
    overlap_union = masks["metro_and_bazaar"] | masks["bus_only_and_bazaar"] | masks["underserved_and_bazaar"]
    check(np.array_equal(overlap_union, masks["bazaar"]), "intersections conserve every bazaar-accessible cell")
    overlap_total = sum(city_expected[f"{label}_10min_population"] for label in (
        "metro_and_bazaar", "bus_only_and_bazaar", "underserved_and_bazaar"))
    check(abs(overlap_total - city_expected["bazaar_10min_population"]) <= POP_TOL,
          "weighted intersections conserve bazaar-accessible population")
    for output, summary_key in (
        ("metro_access_population", "metro_access_population"),
        ("bus_only_population", "bus_only_population"),
        ("underserved_population", "underserved_population"),
    ):
        check(abs(city_expected[output] - float(summary[summary_key])) <= POP_TOL,
              f"independent {output} matches the frozen city headline")
    urban_city = pd.read_csv(cfg.URBAN_DIMENSIONS_CITY_FILE).iloc[0]
    check(abs(city_expected["bazaar_10min_population"] - float(urban_city.bazaar_10min_population)) <= POP_TOL,
          "independent bazaar population matches Phase 2C")
    check(abs(city_expected["bazaar_10min_population"] / city_expected["population_total"] * 100.0
              - float(urban_city.bazaar_10min_pct)) <= PCT_TOL,
          "independent bazaar percentage matches Phase 2C")
    urban_district = pd.read_csv(cfg.URBAN_DIMENSIONS_DISTRICT_FILE).set_index("district_name")
    for row in district_expected:
        frozen = current.loc[row["district_name"]]
        for column in ("metro_access_population", "bus_only_population", "underserved_population"):
            check(abs(row[column] - float(frozen[column])) <= POP_TOL,
                  f"{row['district_name']} {column} matches frozen district metric")
        phase2c_row = urban_district.loc[row["district_name"]]
        check(abs(row["bazaar_10min_population"] - float(phase2c_row.bazaar_10min_population)) <= POP_TOL,
              f"{row['district_name']} bazaar population matches Phase 2C")
        check(abs(row["bazaar_10min_population"] / row["population"] * 100.0
                  - float(phase2c_row.bazaar_10min_pct)) <= PCT_TOL,
              f"{row['district_name']} bazaar percentage matches Phase 2C")

    city = pd.read_csv(cfg.TRANSIT_BAZAAR_OVERLAP_CITY_FILE)
    district = pd.read_csv(cfg.TRANSIT_BAZAAR_OVERLAP_DISTRICT_FILE)
    errors = table_errors(city, district, city_expected, district_expected)
    check(not errors, "published city and district tables match independent arithmetic", "; ".join(errors[:3]))
    if not errors:
        for label in ("metro_and_bazaar", "bus_only_and_bazaar", "underserved_and_bazaar"):
            value = float(city.iloc[0][f"{label}_10min_population"])
            check(value <= float(city.iloc[0]["bazaar_10min_population"]) + POP_TOL,
                  f"{label} is bounded by bazaar-accessible population")
            parent = "metro_access_population" if label == "metro_and_bazaar" else (
                "bus_only_population" if label == "bus_only_and_bazaar" else "underserved_population"
            )
            check(value <= float(city.iloc[0][parent]) + POP_TOL,
                  f"{label} is bounded by its transit parent")
        for column in ("metro_and_bazaar_10min_population", "bus_only_and_bazaar_10min_population",
                       "underserved_and_bazaar_10min_population"):
            check(abs(float(district[column].sum()) - float(city.iloc[0][column])) <= POP_TOL,
                  f"district {column} sums to city value")

    section("Manifest output provenance and freeze")
    for relative in (
        "data/processed/transit_bazaar_overlap_city.csv",
        "data/processed/transit_bazaar_overlap_district.csv",
    ):
        path = path_from_relative(relative)
        record = ud.provenance_record(path, ud.HASH_BASIS_CANONICAL_TEXT)
        check(manifest.get("output_files", {}).get(relative) == record,
              f"manifest output hash matches: {relative}")
        raw = path.read_bytes()
        check(b"\r" not in raw, f"{path.name} is UTF-8 LF-only")
    manifest_raw = cfg.PHASE2F_MANIFEST_PATH.read_bytes()
    check(b"\r" not in manifest_raw, "Phase 2F manifest is LF-only")
    check(str(cfg.REPO_ROOT) not in manifest_raw.decode("utf-8"), "manifest has no machine-specific path")
    git_ok, changed = git_changed_paths()
    check(git_ok, "git diff against the authorized base is available")
    check(set(changed) <= ALLOWED_CHANGED_FILES, "only Phase 2F scoped files changed",
          ", ".join(sorted(set(changed) - ALLOWED_CHANGED_FILES)))
    check(not any(path.startswith("site/") for path in changed), "no web asset changed")

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
