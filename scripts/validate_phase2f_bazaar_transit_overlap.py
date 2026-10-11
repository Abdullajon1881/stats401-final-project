"""Validate Phase 2F bazaar--transit overlap artifacts.

    python scripts/validate_phase2f_bazaar_transit_overlap.py --committed
    python scripts/validate_phase2f_bazaar_transit_overlap.py --full

``--committed`` validates tracked evidence from a fresh clone. It never claims
that the gitignored population cache or walk network was checked. ``--full``
also requires those caches, hashes them, reroutes existing bazaars, and
independently reconstructs every overlap mask.
"""

from __future__ import annotations

import argparse
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
CSV_ROUND_TOL = 5e-6
POPULATION_CACHE_RELATIVE = "data/external/population_cells.parquet"
NETWORK_CACHE_RELATIVE = "data/external/tashkent_walk_network.graphml"
BAZAAR_RELATIVE = "data/processed/bazaars.geojson"
EXPECTED_HASHES = {
    POPULATION_CACHE_RELATIVE: (ud.HASH_BASIS_RAW_BYTES, "948871e538fd0de66c4d30cf5d6c8c0deef3071c8e59d41581f96548e54a7c3b"),
    NETWORK_CACHE_RELATIVE: (ud.HASH_BASIS_RAW_BYTES, "948da22f9a608b8d795c07bb8c8b8d04ca5abcbc429b51b1c99f5546772e9c41"),
    BAZAAR_RELATIVE: (ud.HASH_BASIS_CANONICAL_TEXT, "fbfcbf422ac8edc171608c06b00346a9976e764601fc3642a094c6be821cf56c"),
}
INPUT_SPECS = (
    ("data/analysis_manifest.json", ud.HASH_BASIS_CANONICAL_TEXT),
    (POPULATION_CACHE_RELATIVE, ud.HASH_BASIS_RAW_BYTES),
    (NETWORK_CACHE_RELATIVE, ud.HASH_BASIS_RAW_BYTES),
    ("data/phase2c_urban_dimensions_manifest.json", ud.HASH_BASIS_CANONICAL_TEXT),
    (BAZAAR_RELATIVE, ud.HASH_BASIS_CANONICAL_TEXT),
    ("data/processed/city_access_summary.json", ud.HASH_BASIS_CANONICAL_TEXT),
    ("data/processed/district_access_metrics.csv", ud.HASH_BASIS_CANONICAL_TEXT),
    ("data/processed/urban_dimensions_city.csv", ud.HASH_BASIS_CANONICAL_TEXT),
    ("data/processed/urban_dimensions_district.csv", ud.HASH_BASIS_CANONICAL_TEXT),
)
OUTPUT_SPECS = (
    ("data/processed/transit_bazaar_overlap_city.csv", ud.HASH_BASIS_CANONICAL_TEXT),
    ("data/processed/transit_bazaar_overlap_district.csv", ud.HASH_BASIS_CANONICAL_TEXT),
)
CACHE_RELATIVES = (POPULATION_CACHE_RELATIVE, NETWORK_CACHE_RELATIVE)

# Named artifacts predate Phase 2F. The permanent guard compares their actual
# content with the authorized base, but leaves later site/ and documentation
# additions free to evolve in separately authorized phases.
FROZEN_BASELINE_PATHS = (
    "data/analysis_manifest.json", "data/source_manifest.json", "data/phase2c_urban_dimensions_manifest.json",
    "data/processed/analysis_boundary.geojson", "data/processed/city_access_summary.json",
    "data/processed/district_access_metrics.csv", "data/processed/metro_access_points.csv",
    "data/processed/metro_isochrone_10min.geojson", "data/processed/bus_isochrone_10min.geojson",
    "data/processed/walking_speed_sensitivity.csv", "data/processed/population_surface_sensitivity.csv",
    "data/processed/bazaars.geojson", "data/processed/healthcare_facilities.geojson",
    "data/processed/education_facilities.geojson", "data/processed/urban_dimensions_city.csv",
    "data/processed/urban_dimensions_district.csv", "scripts/accessibility_utils.py",
    "scripts/analyze_accessibility.py", "scripts/analyze_urban_dimensions.py", "scripts/urban_dimensions.py",
)
CITY_COLUMNS = (
    "analysis", "analysis_version", "period", "population_total", "population_cells", "walking_speed_kmh", "walking_time_minutes", "distance_budget_m",
    "metro_access_population", "bus_only_population", "underserved_population", "bazaar_10min_population",
    "metro_and_bazaar_10min_population", "metro_and_bazaar_10min_pct", "bus_only_and_bazaar_10min_population",
    "bus_only_and_bazaar_10min_pct", "underserved_and_bazaar_10min_population", "underserved_and_bazaar_10min_pct",
)
DISTRICT_COLUMNS = (
    "district_name", "population", "metro_access_population", "bus_only_population", "underserved_population", "bazaar_10min_population",
    "metro_and_bazaar_10min_population", "metro_and_bazaar_10min_pct", "bus_only_and_bazaar_10min_population",
    "bus_only_and_bazaar_10min_pct", "underserved_and_bazaar_10min_population", "underserved_and_bazaar_10min_pct",
)
NUMERIC_CITY = tuple(column for column in CITY_COLUMNS if column not in {"analysis", "analysis_version", "period"})
NUMERIC_DISTRICT = tuple(column for column in DISTRICT_COLUMNS if column != "district_name")


class Reporter:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def check(self, condition: bool, label: str, detail: str | None = None) -> bool:
        if bool(condition):
            self.passed += 1
            print(f"  [PASS] {label}")
            return True
        self.failed += 1
        print(f"  [FAIL] {label}{f' ({detail})' if detail else ''}")
        return False

    def note(self, message: str) -> None:
        print(f"  [INFO] {message}")


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def path_from_relative(relative: str, root: Path = cfg.REPO_ROOT) -> Path:
    return root / relative


def canonical_json(path: Path) -> dict:
    return json.loads(ud.canonical_utf8_lf_bytes(path).decode("utf-8"))


def mode_requirement_errors(mode: str, population_cache: Path, network_cache: Path) -> list[str]:
    """Committed mode deliberately has no cache requirement; full mode does."""
    if mode == "committed":
        return []
    errors = []
    if not population_cache.exists():
        errors.append(f"missing mandatory full-validation cache: {population_cache}")
    if not network_cache.exists():
        errors.append(f"missing mandatory full-validation cache: {network_cache}")
    return errors


def frozen_change_errors(changed_paths: list[str]) -> list[str]:
    return sorted(path for path in changed_paths if path in set(FROZEN_BASELINE_PATHS))


def frozen_git_changes(root: Path = cfg.REPO_ROOT) -> tuple[bool, list[str]]:
    result = subprocess.run(["git", "diff", "--name-only", BASE_SHA, "--", *FROZEN_BASELINE_PATHS], cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        return False, ["git diff against the frozen baseline failed"]
    return True, frozen_change_errors([line for line in result.stdout.splitlines() if line.strip()])


def validate_cell_frame(cells: pd.DataFrame) -> list[str]:
    """Return hostile-case cache errors, allowing legitimate positive infinity."""
    required = {"cell_id", "district_name", "population", "x_m", "y_m", "edge_index", "edge_fraction", "edge_connector_m", "metro_distance_m", "bus_distance_m"}
    missing = sorted(required - set(cells.columns))
    if missing:
        return [f"missing required columns: {missing}"]
    errors = []
    if not cells.cell_id.is_unique:
        errors.append("duplicate cell identity")
    population = pd.to_numeric(cells.population, errors="coerce").to_numpy(float)
    if not np.isfinite(population).all() or (population < 0.0).any():
        errors.append("non-finite or negative population")
    for column in ("x_m", "y_m", "edge_fraction", "edge_connector_m"):
        if not np.isfinite(pd.to_numeric(cells[column], errors="coerce").to_numpy(float)).all():
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
    """Independently reconstruct full-mode values from cells and rerouting."""
    population = cells.population.to_numpy(float)
    metro_distance = cells.metro_distance_m.to_numpy(float)
    bus_distance = cells.bus_distance_m.to_numpy(float)
    metro = metro_distance <= BUDGET_M
    bus_only = (metro_distance > BUDGET_M) & (bus_distance <= BUDGET_M)
    underserved = (metro_distance > BUDGET_M) & (bus_distance > BUDGET_M)
    bazaar = bazaar_distance <= BUDGET_M
    overlaps = {"metro_and_bazaar": metro & bazaar, "bus_only_and_bazaar": bus_only & bazaar, "underserved_and_bazaar": underserved & bazaar}
    total = float(population.sum(dtype=float))

    def weighted(mask: np.ndarray) -> float:
        return float(population[mask].sum(dtype=float))

    city = {"analysis": "Phase 2F current bazaar-transit overlap", "analysis_version": cfg.PHASE2F_ANALYSIS_VERSION, "period": "current",
            "population_total": total, "population_cells": int(len(cells)), "walking_speed_kmh": cfg.MAIN_WALK_SPEED_KMH,
            "walking_time_minutes": cfg.WALK_TIME_LIMIT_MINUTES, "distance_budget_m": BUDGET_M,
            "metro_access_population": weighted(metro), "bus_only_population": weighted(bus_only),
            "underserved_population": weighted(underserved), "bazaar_10min_population": weighted(bazaar)}
    for label, mask in overlaps.items():
        value = weighted(mask)
        city[f"{label}_10min_population"] = value
        city[f"{label}_10min_pct"] = 100.0 * value / total
    district_ids = cells.district_name.to_numpy(dtype=str)
    rows = []
    for name in sorted(set(district_ids.tolist())):
        selector = district_ids == name
        denominator = weighted(selector)
        row = {"district_name": name, "population": denominator, "metro_access_population": weighted(metro & selector),
               "bus_only_population": weighted(bus_only & selector), "underserved_population": weighted(underserved & selector),
               "bazaar_10min_population": weighted(bazaar & selector)}
        for label, mask in overlaps.items():
            value = weighted(mask & selector)
            row[f"{label}_10min_population"] = value
            row[f"{label}_10min_pct"] = 100.0 * value / denominator
        rows.append(row)
    return city, rows, {"metro": metro, "bus_only": bus_only, "underserved": underserved, "bazaar": bazaar, **overlaps}


def committed_table_errors(city: pd.DataFrame, district: pd.DataFrame) -> list[str]:
    """Validate every quantitative invariant available from tracked artifacts."""
    if tuple(city.columns) != CITY_COLUMNS:
        return ["city columns differ from the Phase 2F contract"]
    if tuple(district.columns) != DISTRICT_COLUMNS:
        return ["district columns differ from the Phase 2F contract"]
    if len(city) != 1:
        return ["city output does not have exactly one row"]
    if len(district) != cfg.EXPECTED_ANALYSIS_DISTRICTS or not district.district_name.is_unique:
        return ["district output does not have exactly twelve unique rows"]
    if district.district_name.tolist() != sorted(district.district_name.astype(str).tolist()):
        return ["district rows are not in deterministic district-name order"]
    errors = []
    for frame, columns in ((city, NUMERIC_CITY), (district, NUMERIC_DISTRICT)):
        for column in columns:
            values = pd.to_numeric(frame[column], errors="coerce").to_numpy(float)
            if not np.isfinite(values).all() or (values < 0.0).any():
                errors.append(f"non-finite or negative output value in {column}")
    if errors:
        return errors
    row = city.iloc[0]
    if row.analysis != "Phase 2F current bazaar-transit overlap" or row.analysis_version != cfg.PHASE2F_ANALYSIS_VERSION or row.period != "current":
        errors.append("city analysis identity, version or period differs")
    if float(row.population_total) <= 0.0 or int(row.population_cells) <= 0:
        errors.append("city denominator is not explicit and positive")
    parents = {"metro_and_bazaar": "metro_access_population", "bus_only_and_bazaar": "bus_only_population", "underserved_and_bazaar": "underserved_population"}
    for prefix, parent in parents.items():
        value = float(row[f"{prefix}_10min_population"])
        if not np.isclose(float(row[f"{prefix}_10min_pct"]), 100.0 * value / float(row.population_total), atol=PCT_TOL, rtol=0.0):
            errors.append(f"city {prefix} percentage has the wrong denominator")
        if value > float(row[parent]) + CSV_ROUND_TOL or value > float(row.bazaar_10min_population) + CSV_ROUND_TOL:
            errors.append(f"city {prefix} exceeds a parent population")
    if not np.isclose(sum(float(row[f"{prefix}_10min_population"]) for prefix in parents), float(row.bazaar_10min_population), atol=CSV_ROUND_TOL, rtol=0.0):
        errors.append("city intersections do not conserve bazaar-accessible population")
    for _, district_row in district.iterrows():
        if float(district_row.population) <= 0.0:
            errors.append(f"district {district_row.district_name} has no positive denominator")
        for prefix, parent in parents.items():
            value = float(district_row[f"{prefix}_10min_population"])
            if not np.isclose(float(district_row[f"{prefix}_10min_pct"]), 100.0 * value / float(district_row.population), atol=PCT_TOL, rtol=0.0):
                errors.append(f"district {district_row.district_name} {prefix} percentage has the wrong denominator")
            if value > float(district_row[parent]) + CSV_ROUND_TOL or value > float(district_row.bazaar_10min_population) + CSV_ROUND_TOL:
                errors.append(f"district {district_row.district_name} {prefix} exceeds a parent population")
        if not np.isclose(sum(float(district_row[f"{prefix}_10min_population"]) for prefix in parents), float(district_row.bazaar_10min_population), atol=CSV_ROUND_TOL, rtol=0.0):
            errors.append(f"district {district_row.district_name} intersections do not conserve bazaar population")
    for prefix in parents:
        column = f"{prefix}_10min_population"
        if not np.isclose(float(district[column].sum()), float(row[column]), atol=CSV_ROUND_TOL, rtol=0.0):
            errors.append(f"district {column} does not sum to city")
    return errors


def frozen_baseline_table_errors(city: pd.DataFrame, district: pd.DataFrame) -> list[str]:
    """Reconcile output values to committed current and Phase 2C artifacts."""
    errors = []
    row = city.iloc[0]
    summary = canonical_json(cfg.CITY_ACCESS_SUMMARY_FILE)
    urban_city = pd.read_csv(cfg.URBAN_DIMENSIONS_CITY_FILE).iloc[0]
    metrics = pd.read_csv(cfg.DISTRICT_ACCESS_METRICS_FILE).set_index("district_name")
    urban_district = pd.read_csv(cfg.URBAN_DIMENSIONS_DISTRICT_FILE).set_index("district_name")
    if not np.isclose(float(row.population_total), float(summary["analysis_population"]), atol=POP_TOL, rtol=0.0):
        errors.append("city population denominator differs from frozen current summary")
    for column in ("metro_access_population", "bus_only_population", "underserved_population"):
        if not np.isclose(float(row[column]), float(summary[column]), atol=POP_TOL, rtol=0.0):
            errors.append(f"city {column} differs from frozen current summary")
    if not np.isclose(float(row.bazaar_10min_population), float(urban_city.bazaar_10min_population), atol=POP_TOL, rtol=0.0):
        errors.append("city bazaar population differs from Phase 2C")
    if district.district_name.tolist() != sorted(metrics.index.astype(str).tolist()):
        return [*errors, "district identities differ from frozen current metrics"]
    for _, district_row in district.iterrows():
        frozen = metrics.loc[district_row.district_name]
        phase2c = urban_district.loc[district_row.district_name]
        if not np.isclose(float(district_row.population), float(frozen.calibrated_population), atol=POP_TOL, rtol=0.0):
            errors.append(f"district {district_row.district_name} denominator differs from frozen metrics")
        for column in ("metro_access_population", "bus_only_population", "underserved_population"):
            if not np.isclose(float(district_row[column]), float(frozen[column]), atol=POP_TOL, rtol=0.0):
                errors.append(f"district {district_row.district_name} {column} differs from frozen metrics")
        if not np.isclose(float(district_row.bazaar_10min_population), float(phase2c.bazaar_10min_population), atol=POP_TOL, rtol=0.0):
            errors.append(f"district {district_row.district_name} bazaar population differs from Phase 2C")
    return errors


def full_table_errors(city: pd.DataFrame, district: pd.DataFrame, expected_city: dict, expected_district: list[dict]) -> list[str]:
    errors = committed_table_errors(city, district)
    if errors:
        return errors
    for column in CITY_COLUMNS:
        actual, expected = city.iloc[0][column], expected_city[column]
        if column in NUMERIC_CITY:
            tolerance = PCT_TOL if column.endswith("_pct") else POP_TOL
            if not np.isclose(float(actual), float(expected), atol=tolerance, rtol=0.0):
                errors.append(f"city {column} does not match independent calculation")
        elif str(actual) != str(expected):
            errors.append(f"city {column} label differs")
    for index, expected in enumerate(expected_district):
        actual = district.iloc[index]
        for column in NUMERIC_DISTRICT:
            tolerance = PCT_TOL if column.endswith("_pct") else POP_TOL
            if not np.isclose(float(actual[column]), float(expected[column]), atol=tolerance, rtol=0.0):
                errors.append(f"district {expected['district_name']} {column} differs")
    return errors


def manifest_errors(manifest: dict, root: Path, inspect_caches: bool) -> tuple[list[str], list[str]]:
    """Check manifest structure, actual tracked hashes, and recorded cache pins."""
    errors: list[str] = []
    notes: list[str] = []
    if manifest.get("analysis_version") != cfg.PHASE2F_ANALYSIS_VERSION or manifest.get("walking_model", {}).get("distance_budget_m") != BUDGET_M:
        errors.append("manifest methodology version or walking budget differs")
    if manifest.get("historical_or_causal_claim") is not False or manifest.get("composite_score_or_ranking") is not False:
        errors.append("manifest analytical-scope flags differ")
    records = manifest.get("input_files")
    if not isinstance(records, dict) or set(records) != {relative for relative, _ in INPUT_SPECS}:
        return [*errors, "manifest input-file identities differ"], notes
    for relative, basis in INPUT_SPECS:
        record = records[relative]
        if record.get("hash_basis") != basis or not isinstance(record.get("sha256"), str) or not isinstance(record.get("size_bytes"), int):
            errors.append(f"manifest metadata is malformed for {relative}")
            continue
        if relative in EXPECTED_HASHES and (record.get("hash_basis"), record.get("sha256")) != EXPECTED_HASHES[relative]:
            errors.append(f"manifest pinned hash differs for {relative}")
        if relative in CACHE_RELATIVES and not inspect_caches:
            notes.append(f"recorded provenance only, cache not inspected: {relative}")
            continue
        path = path_from_relative(relative, root)
        if not path.exists() or ud.provenance_record(path, basis) != record:
            errors.append(f"input hash or size differs: {relative}")
    outputs = manifest.get("output_files")
    if not isinstance(outputs, dict) or set(outputs) != {relative for relative, _ in OUTPUT_SPECS}:
        return [*errors, "manifest output-file identities differ"], notes
    for relative, basis in OUTPUT_SPECS:
        path = path_from_relative(relative, root)
        if not path.exists() or outputs[relative] != ud.provenance_record(path, basis):
            errors.append(f"output hash or size differs: {relative}")
    if manifest.get("output_rows") != {OUTPUT_SPECS[0][0]: 1, OUTPUT_SPECS[1][0]: 12}:
        errors.append("manifest output row counts differ")
    return errors, notes


def load_committed_frames(root: Path = cfg.REPO_ROOT) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    return (pd.read_csv(path_from_relative(OUTPUT_SPECS[0][0], root)), pd.read_csv(path_from_relative(OUTPUT_SPECS[1][0], root)),
            canonical_json(path_from_relative("data/phase2f_bazaar_transit_overlap_manifest.json", root)))


def run_committed_validation(reporter: Reporter) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    section("Committed-artifact validation")
    reporter.note("scope: tracked output integrity and consistency only; no network routing is performed")
    reporter.note("large population/network caches are recorded provenance only and are not inspected in --committed mode")
    city, district, manifest = load_committed_frames()
    errors = committed_table_errors(city, district)
    reporter.check(not errors, "city and district output contracts and arithmetic are valid", "; ".join(errors[:3]))
    baseline_errors = frozen_baseline_table_errors(city, district) if not errors else []
    reporter.check(not baseline_errors, "tracked outputs reconcile to frozen transit and Phase 2C baselines", "; ".join(baseline_errors[:3]))
    manifest_problems, notes = manifest_errors(manifest, cfg.REPO_ROOT, inspect_caches=False)
    for note in notes:
        reporter.note(note)
    reporter.check(not manifest_problems, "manifest hashes, metadata and recorded cache pins are internally consistent", "; ".join(manifest_problems[:3]))
    git_ok, frozen_changes = frozen_git_changes()
    reporter.check(git_ok, "authorized frozen baseline is available")
    reporter.check(not frozen_changes, "named frozen analytical artifacts match the authorized baseline", ", ".join(frozen_changes))
    return city, district, manifest


def run_full_validation(reporter: Reporter, city: pd.DataFrame, district: pd.DataFrame, manifest: dict) -> None:  # noqa: PLR0915
    section("Full rerouting validation")
    reporter.note("scope: cache hashes, independent edge-aware routing and overlap reconstruction")
    cache_errors = mode_requirement_errors("full", cfg.POPULATION_CELLS_CACHE, cfg.WALK_GRAPH_FILE)
    reporter.check(not cache_errors, "both mandatory full-validation caches are present", "; ".join(cache_errors))
    if cache_errors:
        reporter.note("full validation stopped before routing; it did not downgrade to committed-artifact validation")
        return
    manifest_problems, _ = manifest_errors(manifest, cfg.REPO_ROOT, inspect_caches=True)
    reporter.check(not manifest_problems, "all full-validation source hashes and sizes match the manifest", "; ".join(manifest_problems[:3]))
    cells = pd.read_parquet(cfg.POPULATION_CELLS_CACHE)
    cell_errors = validate_cell_frame(cells)
    reporter.check(not cell_errors, "population cache has valid identities, weights and distances", "; ".join(cell_errors))
    if cell_errors:
        return
    reporter.check(len(cells) == 65_169 and cells.cell_id.nunique() == 65_169, "population cache has 65,169 unique cells")
    reporter.check(cells.district_name.nunique() == cfg.EXPECTED_ANALYSIS_DISTRICTS, "population cache has exactly twelve districts")
    reporter.check(abs(float(cells.population.sum()) - 3_212_200.0) <= POP_TOL, "population cache reproduces 3,212,200 residents")
    network = au.load_walk_network(cfg.WALK_GRAPH_FILE)
    tree = au.build_edge_index(network)
    bazaar_distance, _, _ = urban_analysis.route_class(network, tree, urban_analysis.bazaar_points(), cells, "bazaars")
    reporter.check(not np.isnan(bazaar_distance).any(), "edge-aware bazaar routing has no NaN distances")
    city_expected, district_expected, masks = expected_results(cells, bazaar_distance)
    membership = masks["metro"].astype(np.int8) + masks["bus_only"].astype(np.int8) + masks["underserved"].astype(np.int8)
    reporter.check((membership == 1).all(), "metro, bus-only and underserved partition every cached cell")
    union = masks["metro_and_bazaar"] | masks["bus_only_and_bazaar"] | masks["underserved_and_bazaar"]
    reporter.check(np.array_equal(union, masks["bazaar"]), "independent intersections conserve the bazaar mask")
    errors = full_table_errors(city, district, city_expected, district_expected)
    reporter.check(not errors, "published city and district outputs match independent rerouting", "; ".join(errors[:3]))


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--committed", action="store_true", help="validate tracked artifacts without large caches")
    modes.add_argument("--full", action="store_true", help="require caches and independently reroute")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "committed" if args.committed else "full"
    reporter = Reporter()
    print(f"Phase 2F validator mode: {mode}")
    try:
        city, district, manifest = run_committed_validation(reporter)
        if mode == "full":
            run_full_validation(reporter, city, district, manifest)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, pd.errors.ParserError) as error:
        reporter.check(False, "validator could read a required committed artifact", f"{type(error).__name__}: {error}")
    print("\nSummary\n-------")
    print(f"  mode: {mode}\n  passed: {reporter.passed}\n  failed: {reporter.failed}")
    if reporter.failed:
        print("\nVALIDATION FAILED")
        return 1
    print("\nCOMMITTED-ARTIFACT VALIDATION PASSED" if mode == "committed" else "\nFULL VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
