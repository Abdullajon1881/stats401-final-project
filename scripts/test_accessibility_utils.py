"""Focused routing tests for the edge-aware accessibility engine.

    python scripts/test_accessibility_utils.py      # standalone, exits non-zero on failure
    pytest scripts/test_accessibility_utils.py      # also works

Everything here is synthetic and deterministic: no repository data is read, so
these run in under a second and can gate the analysis.

Two defects in particular must stay caught.

  * Duplicate-edge doubling. `scipy.sparse.coo_matrix` SUMS duplicate
    (row, col) entries, and the OSMnx walk graph stores both directions of
    every way. An earlier implementation symmetrised the already-bidirectional
    records, so every weight was added to itself and the city metro share came
    out at 3.93 percent. TEST C builds that exact situation from a GraphML file
    and fails if a walking cost doubles.

  * Endpoint-only snapping. On the simplified OSM graph a point beside the
    middle of a long edge has no vertex near it, so snapping to the nearest
    VERTEX charged it the walk to the end of the edge. TEST A places a source
    and a cell 50 m apart in the middle of a 1000 m edge; an endpoint-only
    model returns 950 m or more and fails.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parent))

import accessibility_utils as au  # noqa: E402

INF = float("inf")
TOL = 1e-6


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def distances_from_sources(
    network: au.WalkNetwork,
    source_xy: np.ndarray,
    query_xy: np.ndarray,
) -> tuple[np.ndarray, au.EdgeSnap, au.EdgeSnap]:
    """Full pipeline: snap sources, splice them in, snap queries, answer them.

    Returns the TOTAL walking distance per query, which is
    query connector + network distance + source connector.
    """
    source_snap = au.snap_points_to_edges(network, np.asarray(source_xy, dtype=np.float64))
    aug = au.build_augmented_network(network, source_snap)
    node_distance = au.multi_source_distances(network, aug, source_snap.connector_m)
    query_snap = au.snap_points_to_edges(network, np.asarray(query_xy, dtype=np.float64))
    network_distance = au.query_positions(
        aug, node_distance, query_snap.edge_index, query_snap.fraction
    )
    return query_snap.connector_m + network_distance, source_snap, query_snap


def reference_distances(
    network: au.WalkNetwork,
    source_snap: au.EdgeSnap,
    query_snap: au.EdgeSnap,
) -> np.ndarray:
    """An independent brute-force answer, built without the augmented graph.

    A position in the interior of an edge can only be left through that edge's
    two endpoints, so the distance between a source position and a query
    position is the best of the four endpoint combinations, plus - when both
    sit on the same edge - the direct walk along it. Node-to-node distances
    come from a plain all-pairs Dijkstra over the canonical node graph.
    """
    n = network.n_nodes
    rows = np.concatenate([network.edge_u, network.edge_v])
    cols = np.concatenate([network.edge_v, network.edge_u])
    data = np.concatenate([network.edge_cost, network.edge_cost])
    rows, cols, data = au._min_by_pair(rows, cols, data, n)
    node_to_node = dijkstra(coo_matrix((data, (rows, cols)), shape=(n, n)).tocsr(),
                            directed=False)

    out = np.full(query_snap.count, INF, dtype=np.float64)
    for q in range(query_snap.count):
        qe = int(query_snap.edge_index[q])
        qu, qv = int(network.edge_u[qe]), int(network.edge_v[qe])
        best = INF
        for s in range(source_snap.count):
            se = int(source_snap.edge_index[s])
            su, sv = int(network.edge_u[se]), int(network.edge_v[se])
            entry = source_snap.connector_m[s]
            for s_end, s_cost in ((su, source_snap.cost_to_u[s]), (sv, source_snap.cost_to_v[s])):
                for q_end, q_cost in ((qu, query_snap.cost_to_u[q]), (qv, query_snap.cost_to_v[q])):
                    best = min(best, entry + s_cost + node_to_node[s_end, q_end] + q_cost)
            if se == qe:
                direct = abs(query_snap.fraction[q] - source_snap.fraction[s]) * network.edge_cost[se]
                best = min(best, entry + direct)
        out[q] = best + query_snap.connector_m[q]
    return out


def write_graphml(path: Path, nodes: list[tuple[int, float, float]],
                  edges: list[tuple[int, int, int, float, str | None]]) -> None:
    """Write a minimal OSMnx-shaped GraphML file."""
    parts = [
        "<?xml version='1.0' encoding='utf-8'?>",
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '<key id="d5" for="node" attr.name="x" attr.type="string"/>',
        '<key id="d4" for="node" attr.name="y" attr.type="string"/>',
        '<key id="d14" for="edge" attr.name="length" attr.type="string"/>',
        '<key id="d19" for="edge" attr.name="geometry" attr.type="string"/>',
        '<key id="d2" for="graph" attr.name="crs" attr.type="string"/>',
        '<graph edgedefault="directed"><data key="d2">epsg:4326</data>',
    ]
    for nid, lon, lat in nodes:
        parts.append(f'<node id="{nid}"><data key="d4">{lat!r}</data>'
                     f'<data key="d5">{lon!r}</data></node>')
    for src, tgt, key, length, geom in edges:
        body = f'<data key="d14">{length!r}</data>'
        if geom:
            body += f'<data key="d19">{geom}</data>'
        parts.append(f'<edge source="{src}" target="{tgt}" id="{key}">{body}</edge>')
    parts.append("</graph></graphml>")
    path.write_text("\n".join(parts), encoding="utf-8")


def straight_network(node_xy, edges) -> au.WalkNetwork:
    """Edges given as (u, v, cost); geometry is the straight chord."""
    node_xy = np.asarray(node_xy, dtype=np.float64)
    u = np.array([e[0] for e in edges], dtype=np.int64)
    v = np.array([e[1] for e in edges], dtype=np.int64)
    cost = np.array([e[2] for e in edges], dtype=np.float64)
    return au.network_from_arrays(node_xy, u, v, cost)


# ---------------------------------------------------------------------------
# TEST A - a source and a cell in the interior of the SAME edge
# ---------------------------------------------------------------------------
def test_a_same_edge():
    """1000 m edge, source at 500 m, cell at 550 m: the answer is 50 m.

    This is the test the previous nearest-node model could not pass. Its only
    vertices are at 0 m and 1000 m, so snapping to a vertex would charge the
    cell 450 m out to one end and the source 500 m back, or 500 + 550 the other
    way - never 50.
    """
    network = straight_network([(0.0, 0.0), (1000.0, 0.0)], [(0, 1, 1000.0)])

    source_xy = np.array([[500.0, 30.0]])     # 30 m off the network
    cell_xy = np.array([[550.0, 20.0]])       # 20 m off the network

    total, source_snap, cell_snap = distances_from_sources(network, source_xy, cell_xy)

    assert abs(source_snap.connector_m[0] - 30.0) < TOL, source_snap.connector_m
    assert abs(cell_snap.connector_m[0] - 20.0) < TOL, cell_snap.connector_m
    assert abs(source_snap.fraction[0] - 0.5) < TOL
    assert abs(cell_snap.fraction[0] - 0.55) < TOL

    # 30 m source connector + 50 m along the edge + 20 m cell connector
    assert abs(total[0] - 100.0) < TOL, f"expected 100.0, got {total[0]}"

    # and the network component on its own is exactly 50 m + the source connector
    assert abs((total[0] - cell_snap.connector_m[0]) - 80.0) < TOL

    # an endpoint-only model would have produced at least this much
    endpoint_only = 30.0 + min(500.0 + 550.0, 500.0 + 450.0) + 20.0
    assert total[0] < endpoint_only - 500.0, "result is indistinguishable from vertex snapping"
    return "same-edge source/cell = 100.0 m (30 connector + 50 network + 20 connector)"


# ---------------------------------------------------------------------------
# TEST B - a source sitting exactly on a vertex
# ---------------------------------------------------------------------------
def test_b_endpoint_equivalence():
    """A source on a vertex must reproduce ordinary graph shortest paths."""
    node_xy = [(0.0, 0.0), (100.0, 0.0), (300.0, 0.0), (600.0, 0.0)]
    network = straight_network(node_xy, [(0, 1, 100.0), (1, 2, 200.0), (2, 3, 300.0)])

    source_xy = np.array([[100.0, 0.0]])      # exactly node 1, connector 0
    query_xy = np.array([[0.0, 0.0], [300.0, 0.0], [600.0, 0.0]])

    total, source_snap, query_snap = distances_from_sources(network, source_xy, query_xy)
    assert abs(source_snap.connector_m[0]) < TOL
    assert np.all(query_snap.connector_m < TOL)

    # plain undirected Dijkstra from node 1
    n = network.n_nodes
    rows = np.concatenate([network.edge_u, network.edge_v])
    cols = np.concatenate([network.edge_v, network.edge_u])
    data = np.concatenate([network.edge_cost, network.edge_cost])
    plain = dijkstra(coo_matrix((data, (rows, cols)), shape=(n, n)).tocsr(),
                     directed=False, indices=1)
    expected = np.array([plain[0], plain[2], plain[3]])

    assert np.allclose(total, expected, atol=TOL), f"{total} vs {expected}"
    assert np.allclose(expected, [100.0, 200.0, 500.0], atol=TOL)

    # the source must NOT have created a duplicate vertex at distance zero
    assert source_snap.count == 1
    return f"endpoint source matches plain Dijkstra: {expected.tolist()}"


# ---------------------------------------------------------------------------
# TEST C - OSM-style directional duplicates must not double any cost
# ---------------------------------------------------------------------------
def test_c_directional_duplicates():
    """Both stored directions of a way collapse to ONE canonical edge.

    Regression for the coo_matrix duplicate-summing defect that produced the
    discarded 3.93 percent result.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "dup.graphml"
        # Three collinear nodes ~100 m apart at this latitude, each way stored
        # in both directions exactly as OSMnx does.
        nodes = [(1, 69.2000000, 41.3000000), (2, 69.2011963, 41.3000000),
                 (3, 69.2023926, 41.3000000)]
        edges = [
            (1, 2, 0, 100.0, None), (2, 1, 0, 100.0, None),
            (2, 3, 0, 100.0, None), (3, 2, 0, 100.0, None),
        ]
        write_graphml(path, nodes, edges)
        network = au.load_walk_network(path)

    assert network.stats["stored_edge_records"] == 4
    assert network.stats["usable_edge_records"] == 4
    assert network.stats["canonical_routing_edges"] == 2, network.stats
    assert network.stats["records_per_canonical_edge"] == {"2": 2}

    total, _, _ = distances_from_sources(
        network,
        np.array([[network.node_xy[0, 0], network.node_xy[0, 1]]]),
        np.array([[network.node_xy[2, 0], network.node_xy[2, 1]]]),
    )
    assert abs(total[0] - 200.0) < 1e-3, f"expected 200 m, got {total[0]} (cost doubled?)"

    # and the raw collapse helper itself keeps the minimum, never the sum
    rows = np.array([0, 0, 1])
    cols = np.array([1, 1, 0])
    data = np.array([100.0, 100.0, 100.0])
    _, _, d = au._min_by_pair(rows, cols, data, 2)
    assert sorted(d.tolist()) == [100.0, 100.0], d
    return "4 directional records -> 2 canonical edges, 1->3 costs 200 m (not 400 m)"


# ---------------------------------------------------------------------------
# TEST D - several sources spliced into the SAME edge
# ---------------------------------------------------------------------------
def test_d_multiple_sources_one_edge():
    """Cells between and outside two sources on one edge pick the nearer one."""
    network = straight_network([(0.0, 0.0), (1000.0, 0.0)], [(0, 1, 1000.0)])

    source_xy = np.array([[200.0, 0.0], [800.0, 0.0]])
    cell_xy = np.array([[100.0, 0.0],   # left of both  -> 100 from the 200 source
                        [300.0, 0.0],   # between       -> 100 from the 200 source
                        [500.0, 0.0],   # midway        -> 300 from either
                        [700.0, 0.0],   # between       -> 100 from the 800 source
                        [900.0, 0.0]])  # right of both -> 100 from the 800 source

    total, source_snap, _ = distances_from_sources(network, source_xy, cell_xy)
    expected = np.array([100.0, 100.0, 300.0, 100.0, 100.0])
    assert np.allclose(total, expected, atol=TOL), f"{total} vs {expected}"

    aug = au.build_augmented_network(network, source_snap)
    assert aug.stats["sources_inserted_in_edge_interior"] == 2
    assert aug.stats["augmented_nodes_added"] == 2
    # 1 canonical edge cut twice = 3 routing segments
    assert aug.break_offset[-1] - aug.break_offset[0] == 4
    return f"two sources on one edge -> {expected.tolist()}"


# ---------------------------------------------------------------------------
# TEST E - parallel edges keep their own geometry AND their own cost
# ---------------------------------------------------------------------------
def test_e_parallel_edges():
    """A cell beside the long parallel way must be costed with THAT way.

    Nodes 0 and 1 are joined twice: a 100 m straight link and a 500 m detour
    that bulges 120 m away. A cell at the apex of the detour is nearest to the
    detour, so its walk must be computed from the detour's 500 m cost. Charging
    it against the straight link's 100 m cost - the failure mode when snapping
    geometry and routing cost come from different records - would understate it
    fivefold.
    """
    node_xy = np.array([[0.0, 0.0], [100.0, 0.0]])
    detour = LineString([(0.0, 0.0), (25.0, 120.0), (50.0, 120.0),
                         (75.0, 120.0), (100.0, 0.0)])
    straight = LineString([(0.0, 0.0), (100.0, 0.0)])
    network = au.network_from_arrays(
        node_xy,
        np.array([0, 0], dtype=np.int64),
        np.array([1, 1], dtype=np.int64),
        np.array([100.0, 500.0], dtype=np.float64),
        [straight, detour],
    )

    source_xy = np.array([[0.0, 0.0]])                 # at node 0
    cell_xy = np.array([[50.0, 125.0]])                # 5 m above the detour apex

    total, _, cell_snap = distances_from_sources(network, source_xy, cell_xy)

    assert int(cell_snap.edge_index[0]) == 1, "cell did not snap to the detour geometry"
    assert abs(cell_snap.connector_m[0] - 5.0) < TOL
    # halfway along the detour geometry, so half of the detour's OWN 500 m cost
    assert abs(cell_snap.fraction[0] - 0.5) < 1e-9, cell_snap.fraction
    assert abs(cell_snap.cost_to_u[0] - 250.0) < TOL, cell_snap.cost_to_u
    assert abs(total[0] - 255.0) < TOL, f"expected 255.0, got {total[0]}"

    # routing still knows the straight link is the cheap way between the nodes
    ref = reference_distances(
        network,
        au.snap_points_to_edges(network, source_xy),
        cell_snap,
    )
    assert np.allclose(total, ref, atol=TOL), f"{total} vs reference {ref}"
    return "cell on the 500 m parallel way costs 255 m, not 55 m"


# ---------------------------------------------------------------------------
# TEST F - a component with no source stays unreachable
# ---------------------------------------------------------------------------
def test_f_disconnected_component():
    node_xy = [(0.0, 0.0), (100.0, 0.0), (5000.0, 0.0), (5100.0, 0.0)]
    network = straight_network(node_xy, [(0, 1, 100.0), (2, 3, 100.0)])

    source_xy = np.array([[50.0, 0.0]])        # on the first component only
    cell_xy = np.array([[50.0, 0.0], [5050.0, 0.0]])

    total, _, _ = distances_from_sources(network, source_xy, cell_xy)
    assert abs(total[0]) < TOL, total
    assert np.isinf(total[1]), f"expected +inf on the isolated component, got {total[1]}"
    assert total[1] > 0, "unreachable must be +inf, never 0 and never negative"
    return "isolated component returns +inf"


# ---------------------------------------------------------------------------
# TEST G - each off-network connector is paid exactly once
# ---------------------------------------------------------------------------
def test_g_connectors_counted_once():
    """Source connector + network + cell connector, with no double charging."""
    node_xy = [(0.0, 0.0), (400.0, 0.0), (900.0, 0.0)]
    network = straight_network(node_xy, [(0, 1, 400.0), (1, 2, 500.0)])

    source_xy = np.array([[100.0, 40.0]])      # 100 m along edge 0, 40 m off
    cell_xy = np.array([[700.0, 25.0]])        # 300 m along edge 1, 25 m off

    total, source_snap, cell_snap = distances_from_sources(network, source_xy, cell_xy)
    assert abs(source_snap.connector_m[0] - 40.0) < TOL
    assert abs(cell_snap.connector_m[0] - 25.0) < TOL
    # 40 + (300 to node 1) + (300 along edge 1) + 25
    assert abs(total[0] - (40.0 + 300.0 + 300.0 + 25.0)) < TOL, total

    # a source and a cell at the same spot pay both connectors and nothing else
    same = np.array([[700.0, 25.0]])
    total_same, _, _ = distances_from_sources(network, same, same)
    assert abs(total_same[0] - 50.0) < TOL, f"expected 25 + 0 + 25, got {total_same[0]}"
    return "connectors charged once each: 40 + 600 + 25 = 665 m"


# ---------------------------------------------------------------------------
# TEST H - a self-loop is walkable in both directions
# ---------------------------------------------------------------------------
def test_h_self_loop():
    """350 real self-loops exist in the city graph; they must route correctly."""
    # A 400 m square loop hanging off node 0, plus an unrelated spur so the
    # network is not a single self-loop.
    loop = LineString([(0.0, 0.0), (0.0, 100.0), (100.0, 100.0),
                       (100.0, 0.0), (0.0, 0.0)])
    spur = LineString([(0.0, 0.0), (0.0, -500.0)])
    network = au.network_from_arrays(
        np.array([[0.0, 0.0], [0.0, -500.0]]),
        np.array([0, 0], dtype=np.int64),
        np.array([0, 1], dtype=np.int64),
        np.array([400.0, 500.0], dtype=np.float64),
        [loop, spur],
    )
    source_xy = np.array([[0.0, 0.0]])          # at the loop's single vertex

    # (100, 25) is 275 m round the loop one way and 125 m the other;
    # (-5, 100) is 100 m one way and 300 m the other, 5 m off the network.
    cell_xy = np.array([[100.0, 25.0], [-5.0, 100.0]])

    total, _, cell_snap = distances_from_sources(network, source_xy, cell_xy)
    assert cell_snap.edge_index.tolist() == [0, 0], cell_snap.edge_index
    assert abs(cell_snap.fraction[0] - 0.6875) < 1e-9, cell_snap.fraction
    assert abs(cell_snap.fraction[1] - 0.25) < 1e-9, cell_snap.fraction
    assert np.allclose(total, [125.0, 105.0], atol=TOL), total
    return "self-loop walked the short way round: 125 m (not 275 m) and 105 m"


# ---------------------------------------------------------------------------
# TEST I - agreement with an independent brute-force reference
# ---------------------------------------------------------------------------
def test_i_matches_brute_force_reference():
    """Random networks, random sources, random queries, checked independently.

    The reference never uses the augmented graph: it does an all-pairs Dijkstra
    over the canonical vertices and enumerates the four endpoint combinations
    plus the same-edge shortcut. Agreement over many random cases is what makes
    the fast path trustworthy on the real 154,133-edge network.
    """
    rng = np.random.default_rng(20260909)
    worst = 0.0
    cases = 0
    for trial in range(40):
        n_nodes = int(rng.integers(6, 14))
        node_xy = rng.uniform(0, 1200, size=(n_nodes, 2))
        edges = set()
        for i in range(n_nodes):
            j = int(rng.integers(0, n_nodes))
            if i != j:
                edges.add((min(i, j), max(i, j)))
        for _ in range(int(rng.integers(3, 12))):
            i, j = rng.integers(0, n_nodes, size=2)
            if i != j:
                edges.add((int(min(i, j)), int(max(i, j))))
        edges = sorted(edges)
        if not edges:
            continue
        u = np.array([e[0] for e in edges], dtype=np.int64)
        v = np.array([e[1] for e in edges], dtype=np.int64)
        geoms = [LineString([tuple(node_xy[a]), tuple(node_xy[b])]) for a, b in edges]
        # routing cost deliberately differs from the projected geometry length,
        # the way a geodesic OSMnx length differs from a UTM length
        cost = np.array([g.length * float(rng.uniform(0.98, 1.02)) for g in geoms])
        network = au.network_from_arrays(node_xy, u, v, cost, geoms)

        source_xy = rng.uniform(-50, 1250, size=(int(rng.integers(1, 6)), 2))
        query_xy = rng.uniform(-50, 1250, size=(25, 2))

        total, source_snap, query_snap = distances_from_sources(network, source_xy, query_xy)
        reference = reference_distances(network, source_snap, query_snap)

        finite = np.isfinite(reference)
        assert np.array_equal(np.isfinite(total), finite), f"trial {trial}: reachability differs"
        if finite.any():
            gap = float(np.abs(total[finite] - reference[finite]).max())
            worst = max(worst, gap)
            assert gap < 1e-6, f"trial {trial}: worst gap {gap}"
        cases += int(query_snap.count)
    return f"{cases} random queries over 40 random networks, worst gap {worst:.2e} m"


# ---------------------------------------------------------------------------
# TEST J - a source mid-edge is reachable even when both endpoints are far
# ---------------------------------------------------------------------------
def test_j_long_edge_interior_source():
    """The exact geometry the blocker described: a 6 km edge with one stop.

    Both vertices are kilometres from the stop, so a vertex-based model reports
    the whole edge as unreachable. Edge-aware routing must show an 800 m
    walkable stretch centred on the stop.
    """
    network = straight_network([(0.0, 0.0), (6000.0, 0.0)], [(0, 1, 6000.0)])
    source_xy = np.array([[3000.0, 0.0]])
    cell_xy = np.array([[2300.0, 0.0], [2900.0, 0.0], [3000.0, 0.0],
                        [3700.0, 0.0], [3900.0, 0.0]])
    total, source_snap, _ = distances_from_sources(network, source_xy, cell_xy)
    expected = np.array([700.0, 100.0, 0.0, 700.0, 900.0])
    assert np.allclose(total, expected, atol=TOL), f"{total} vs {expected}"

    budget = 800.0
    within = total <= budget
    assert within.tolist() == [True, True, True, True, False]

    # and the display service area must exist around that mid-edge source
    aug = au.build_augmented_network(network, source_snap)
    node_distance = au.multi_source_distances(network, aug, source_snap.connector_m)
    area, info = au.build_service_area(network, aug, node_distance, budget,
                                       buffer_m=10.0, simplify_m=0.0)
    assert not area.geometry.iloc[0].is_empty
    assert abs(info["reachable_network_length_km"] - 1.6) < 1e-3, info
    return "6 km edge with a mid-edge stop yields a 1.6 km reachable stretch"


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------
TESTS = [
    ("TEST A  same edge, source and cell in the interior", test_a_same_edge),
    ("TEST B  source exactly on a vertex", test_b_endpoint_equivalence),
    ("TEST C  OSM directional duplicates do not double cost", test_c_directional_duplicates),
    ("TEST D  several sources on one edge", test_d_multiple_sources_one_edge),
    ("TEST E  parallel edges keep geometry and cost together", test_e_parallel_edges),
    ("TEST F  disconnected component stays +inf", test_f_disconnected_component),
    ("TEST G  off-network connectors charged once", test_g_connectors_counted_once),
    ("TEST H  self-loop routed the short way round", test_h_self_loop),
    ("TEST I  agreement with a brute-force reference", test_i_matches_brute_force_reference),
    ("TEST J  mid-edge source on a very long edge", test_j_long_edge_interior_source),
]


def main() -> int:
    print("=" * 74)
    print("Edge-aware routing - focused synthetic regression tests")
    print("=" * 74)
    failures = 0
    for title, function in TESTS:
        try:
            detail = function()
        except AssertionError as error:
            failures += 1
            print(f"  FAIL  {title}\n          {error}")
        except Exception as error:  # noqa: BLE001 - report, do not mask
            failures += 1
            print(f"  ERROR {title}\n          {type(error).__name__}: {error}")
        else:
            print(f"  PASS  {title}")
            if detail:
                print(f"          {detail}")
    print("-" * 74)
    print(f"  {len(TESTS) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
