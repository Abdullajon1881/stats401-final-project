"""Synthetic and committed-artifact regression tests for Phase 2F.

    python scripts/test_transit_bazaar_overlap.py

No test alters the real gitignored caches. Cache absence is exercised with
temporary paths, while the committed-artifact tests use only tracked outputs.
"""

from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze_transit_bazaar_overlap as analysis  # noqa: E402
import validate_phase2f_bazaar_transit_overlap as validator  # noqa: E402


def cell_fixture() -> pd.DataFrame:
    return pd.DataFrame({
        "cell_id": ["a", "b", "c"], "district_name": ["A", "A", "B"],
        "population": [10.0, 20.0, 30.0], "x_m": [1.0, 2.0, 3.0], "y_m": [1.0, 2.0, 3.0],
        "edge_index": [0, 1, 2], "edge_fraction": [0.0, 0.5, 1.0], "edge_connector_m": [0.0, 1.0, 2.0],
        "metro_distance_m": [800.0, 800.000001, np.inf], "bus_distance_m": [900.0, 800.0, np.inf],
    })


def committed_fixture() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    return validator.load_committed_frames()


def test_thresholds_and_unreachable_distance_are_classified_exactly():
    classes = analysis.classify_transit(cell_fixture(), 800.0)
    assert classes["metro"].tolist() == [True, False, False]
    assert classes["bus_only"].tolist() == [False, True, False]
    assert classes["underserved"].tolist() == [False, False, True]


def test_invalid_cell_cache_cases_fail_closed():
    cases = [
        (lambda frame: frame.assign(cell_id=["a", "a", "c"]), "duplicate cell identity"),
        (lambda frame: frame.assign(population=[10.0, -1.0, 30.0]), "negative population"),
        (lambda frame: frame.assign(population=[10.0, np.nan, 30.0]), "non-finite"),
        (lambda frame: frame.assign(metro_distance_m=[800.0, np.nan, np.inf]), "NaN"),
        (lambda frame: frame.assign(edge_fraction=[0.0, 1.1, 1.0]), "outside [0, 1]"),
    ]
    for mutation, expected in cases:
        errors = validator.validate_cell_frame(mutation(cell_fixture()))
        assert any(expected in error for error in errors), errors
    assert any("missing required columns" in error for error in validator.validate_cell_frame(cell_fixture().drop(columns="bus_distance_m")))


def test_committed_artifact_outputs_are_valid_without_caches():
    city, district, manifest = committed_fixture()
    assert validator.committed_table_errors(city, district) == []
    assert validator.frozen_baseline_table_errors(city, district) == []
    manifest_errors, notes = validator.manifest_errors(manifest, validator.cfg.REPO_ROOT, inspect_caches=False)
    assert manifest_errors == []
    assert len(notes) == 2 and all("recorded provenance only" in note for note in notes)


def test_tampered_intersections_and_wrong_denominators_fail_closed():
    city, district, _ = committed_fixture()
    bad_city = city.copy()
    bad_city.loc[0, "metro_and_bazaar_10min_population"] += 1.0
    assert validator.committed_table_errors(bad_city, district)
    bad_district = district.copy()
    bad_district.loc[0, "bus_only_and_bazaar_10min_pct"] += 1.0
    assert any("wrong denominator" in error for error in validator.committed_table_errors(city, bad_district))


def test_invalid_reordered_and_duplicated_district_identities_fail_closed():
    city, district, _ = committed_fixture()
    reordered = district.iloc[::-1].reset_index(drop=True)
    assert any("deterministic district-name order" in error for error in validator.committed_table_errors(city, reordered))
    duplicate = district.copy()
    duplicate.loc[1, "district_name"] = duplicate.loc[0, "district_name"]
    assert any("twelve unique rows" in error for error in validator.committed_table_errors(city, duplicate))


def test_altered_manifest_output_hash_fails_closed():
    _, _, manifest = committed_fixture()
    altered = copy.deepcopy(manifest)
    altered["output_files"]["data/processed/transit_bazaar_overlap_city.csv"]["sha256"] = "0" * 64
    errors, _ = validator.manifest_errors(altered, validator.cfg.REPO_ROOT, inspect_caches=False)
    assert any("output hash or size differs" in error for error in errors)


def test_mode_specific_missing_cache_behavior_is_explicit():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        population = root / "population_cells.parquet"
        network = root / "tashkent_walk_network.graphml"
        assert validator.mode_requirement_errors("committed", population, network) == []
        errors = validator.mode_requirement_errors("full", population, network)
    assert len(errors) == 2 and all("missing mandatory full-validation cache" in error for error in errors)


def test_frozen_guard_rejects_only_named_baseline_artifacts():
    frozen = validator.frozen_change_errors(["data/processed/city_access_summary.json"])
    assert frozen == ["data/processed/city_access_summary.json"]
    assert validator.frozen_change_errors(["site/js/future-phase.js", "docs/future_phase.md", "README.md"]) == []


TESTS = [
    ("thresholds and unreachable distances are exact", test_thresholds_and_unreachable_distance_are_classified_exactly),
    ("invalid cell caches fail closed", test_invalid_cell_cache_cases_fail_closed),
    ("valid committed artifacts pass without caches", test_committed_artifact_outputs_are_valid_without_caches),
    ("tampered intersections and denominators fail", test_tampered_intersections_and_wrong_denominators_fail_closed),
    ("invalid, reordered and duplicate districts fail", test_invalid_reordered_and_duplicated_district_identities_fail_closed),
    ("altered manifest hashes fail", test_altered_manifest_output_hash_fails_closed),
    ("missing-cache behavior is mode-specific", test_mode_specific_missing_cache_behavior_is_explicit),
    ("frozen guard allows future additions", test_frozen_guard_rejects_only_named_baseline_artifacts),
]


def main() -> int:
    print("=" * 74)
    print("Phase 2F bazaar--transit overlap - synthetic regression tests")
    print("=" * 74)
    failures = 0
    for title, function in TESTS:
        try:
            function()
        except Exception as error:  # noqa: BLE001 - standalone test runner
            failures += 1
            print(f"  FAIL  {title}\n        {type(error).__name__}: {error}")
        else:
            print(f"  PASS  {title}")
    print("-" * 74)
    print(f"  {len(TESTS) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
