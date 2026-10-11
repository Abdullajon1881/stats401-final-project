"""Synthetic hostile-case tests for Phase 2F overlap contracts.

    python scripts/test_transit_bazaar_overlap.py

These tests use only in-memory fixtures.  They do not need a network, cache or
any Phase 2F output file.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyze_transit_bazaar_overlap as analysis  # noqa: E402
import validate_phase2f_bazaar_transit_overlap as validator  # noqa: E402


def cell_fixture() -> pd.DataFrame:
    return pd.DataFrame({
        "cell_id": ["a", "b", "c"],
        "district_name": ["A", "A", "B"],
        "population": [10.0, 20.0, 30.0],
        "x_m": [1.0, 2.0, 3.0], "y_m": [1.0, 2.0, 3.0],
        "edge_index": [0, 1, 2], "edge_fraction": [0.0, 0.5, 1.0],
        "edge_connector_m": [0.0, 1.0, 2.0],
        "metro_distance_m": [800.0, 800.000001, np.inf],
        "bus_distance_m": [900.0, 800.0, np.inf],
    })


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


def test_missing_cell_column_fails_closed():
    errors = validator.validate_cell_frame(cell_fixture().drop(columns="bus_distance_m"))
    assert any("missing required columns" in error for error in errors)


def test_overlapping_or_swapped_overlap_masks_are_rejected():
    cells = cell_fixture()
    transit = analysis.classify_transit(cells, 800.0)
    bazaar = np.array([True, True, True])
    bad = {
        "metro_and_bazaar": np.array([True, True, False]),
        "bus_only_and_bazaar": np.array([False, True, False]),
        "underserved_and_bazaar": np.array([False, False, True]),
    }
    try:
        analysis.validate_overlap_masks(transit, bazaar, bad, cells.population.to_numpy(float))
    except SystemExit as error:
        assert "not disjoint" in str(error) or "exceeds its transit parent" in str(error)
    else:
        raise AssertionError("invalid overlap masks were accepted")


def output_fixture() -> tuple[pd.DataFrame, pd.DataFrame, dict, list[dict]]:
    city = {column: 0.0 for column in validator.CITY_COLUMNS}
    city.update({
        "analysis": "Phase 2F current bazaar-transit overlap",
        "analysis_version": "phase2f-current-bazaar-transit-overlap-v1",
        "period": "current",
        "population_cells": 12,
    })
    names = [f"District {index:02d}" for index in range(12)]
    rows = []
    for name in names:
        row = {column: 0.0 for column in validator.DISTRICT_COLUMNS}
        row["district_name"] = name
        rows.append(row)
    return pd.DataFrame([city]), pd.DataFrame(rows), city, rows


def test_corrupted_or_reordered_output_fails_validation():
    city, district, expected_city, expected_district = output_fixture()
    assert validator.table_errors(city, district, expected_city, expected_district) == []

    corrupted = city.copy()
    corrupted.loc[0, "metro_and_bazaar_10min_population"] = 1.0
    assert validator.table_errors(corrupted, district, expected_city, expected_district)

    reordered = district.iloc[::-1].reset_index(drop=True)
    assert any("deterministic district-name order" in error
               for error in validator.table_errors(city, reordered, expected_city, expected_district))

    wrong_label = district.copy()
    wrong_label.loc[0, "district_name"] = "Unexpected district"
    assert any("deterministic district-name order" in error
               for error in validator.table_errors(city, wrong_label, expected_city, expected_district))


TESTS = [
    ("thresholds and unreachable distances are exact", test_thresholds_and_unreachable_distance_are_classified_exactly),
    ("invalid cell caches fail closed", test_invalid_cell_cache_cases_fail_closed),
    ("missing cache columns fail closed", test_missing_cell_column_fails_closed),
    ("overlapping or swapped masks fail closed", test_overlapping_or_swapped_overlap_masks_are_rejected),
    ("corrupted or reordered outputs fail validation", test_corrupted_or_reordered_output_fails_validation),
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
