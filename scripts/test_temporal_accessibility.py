"""Fast synthetic regression tests for Phase 2B temporal accessibility.

    python scripts/test_temporal_accessibility.py
    pytest scripts/test_temporal_accessibility.py

No repository data or network download is used.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parent))

import accessibility_utils as au  # noqa: E402
import temporal_accessibility as ta  # noqa: E402

TOL = 1e-6


def line_network() -> au.WalkNetwork:
    return au.network_from_arrays(
        node_xy=np.asarray([[0.0, 0.0], [1000.0, 0.0], [2000.0, 0.0]]),
        edge_u=np.asarray([0, 1]),
        edge_v=np.asarray([1, 2]),
        edge_cost=np.asarray([1000.0, 1000.0]),
        edge_geom=[
            LineString([(0.0, 0.0), (1000.0, 0.0)]),
            LineString([(1000.0, 0.0), (2000.0, 0.0)]),
        ],
    )


def distances(network: au.WalkNetwork, sources: np.ndarray, cells: np.ndarray) -> np.ndarray:
    tree = au.build_edge_index(network)
    source_snap = au.snap_points_to_edges(network, sources, tree=tree)
    cell_snap = au.snap_points_to_edges(network, cells, tree=tree)
    augmented = au.build_augmented_network(network, source_snap)
    node_distance = au.multi_source_distances(
        network, augmented, source_snap.connector_m
    )
    return cell_snap.connector_m + au.query_positions(
        augmented, node_distance, cell_snap.edge_index, cell_snap.fraction
    )


def test_adding_source_never_increases_distance():
    network = line_network()
    cells = np.asarray([[100.0, 0.0], [500.0, 0.0], [1500.0, 0.0], [1900.0, 0.0]])
    earlier = distances(network, np.asarray([[100.0, 0.0]]), cells)
    later = distances(network, np.asarray([[100.0, 0.0], [1900.0, 0.0]]), cells)
    assert np.all(later <= earlier + TOL), (earlier, later)
    assert np.any(later < earlier - TOL)
    return f"maximum later-minus-earlier distance = {(later - earlier).max():.3g} m"


def test_same_edge_distance_is_exact():
    network = line_network()
    result = distances(
        network,
        np.asarray([[400.0, 25.0]]),
        np.asarray([[550.0, 10.0]]),
    )
    # 25 m source connector + 150 m on-edge walk + 10 m cell connector.
    assert np.allclose(result, [185.0], atol=TOL), result
    return f"same-edge total = {result[0]:.1f} m"


def test_population_weights_can_change_pct_with_fixed_mask():
    accessible = np.asarray([True, False, False])
    denominator_a, numerator_a, pct_a = ta.weighted_access(
        np.asarray([80.0, 10.0, 10.0]), accessible
    )
    denominator_b, numerator_b, pct_b = ta.weighted_access(
        np.asarray([20.0, 40.0, 40.0]), accessible
    )
    assert denominator_a == denominator_b == 100.0
    assert numerator_a == 80.0 and numerator_b == 20.0
    assert pct_a == 80.0 and pct_b == 20.0
    assert accessible.tolist() == [True, False, False]
    return "fixed access mask yields 80% then 20% under different weights"


def test_missing_population_is_excluded():
    population = np.asarray([10.0, np.nan, 30.0])
    denominator, numerator, percentage = ta.weighted_access(
        population, np.asarray([True, True, False])
    )
    assert denominator == 40.0
    assert numerator == 10.0
    assert percentage == 25.0
    assert np.isnan(population[1])
    return "missing accessible cell is absent from both numerator and denominator"


def test_opening_year_selects_nested_states():
    stations = pd.DataFrame(
        {
            "station_id": ["a", "b", "c", "d"],
            "opening_year": [2010, 2020, 2020, 2023],
        }
    )
    states, mapping = ta.derive_metro_states(stations, (2019, 2020, 2021, 2023))
    assert [state.state_id for state in states] == [
        "metro_state_1", "metro_state_3", "metro_state_4"
    ]
    assert mapping == {
        2019: "metro_state_1",
        2020: "metro_state_3",
        2021: "metro_state_3",
        2023: "metro_state_4",
    }
    assert states[0].active_station_ids == ("a",)
    assert states[1].active_station_ids == ("a", "b", "c")
    assert states[2].active_station_ids == ("a", "b", "c", "d")
    return "opening years produce 1 -> 3 -> 4 nested station states"


TESTS = [
    ("adding a source cannot increase cell distance", test_adding_source_never_increases_distance),
    ("same-edge station and cell distance stays exact", test_same_edge_distance_is_exact),
    ("annual weights can change percentages with one mask", test_population_weights_can_change_pct_with_fixed_mask),
    ("annual missing population is excluded", test_missing_population_is_excluded),
    ("opening years select deterministic nested states", test_opening_year_selects_nested_states),
]


def main() -> int:
    print("=" * 74)
    print("Phase 2B temporal accessibility - synthetic regression tests")
    print("=" * 74)
    failures = 0
    for title, function in TESTS:
        try:
            detail = function()
        except Exception as error:  # noqa: BLE001 - standalone test runner
            failures += 1
            print(f"  FAIL  {title}\n        {type(error).__name__}: {error}")
        else:
            print(f"  PASS  {title}\n        {detail}")
    print("-" * 74)
    print(f"  {len(TESTS) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
