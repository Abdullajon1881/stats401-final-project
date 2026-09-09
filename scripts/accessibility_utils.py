"""Network and raster primitives for the Week 4 accessibility analysis.

Everything metric happens in EPSG:32642. Nothing here computes a project
result; it provides the canonical pedestrian network, edge-aware snapping,
shortest-path and service-area building blocks that `analyze_accessibility.py`
composes.

Why edge-aware. The OSM walk network is a SIMPLIFIED graph: its vertices sit at
intersections and endpoints, not continuously along every path. Snapping a
population cell or a transit stop to the nearest graph VERTEX therefore charges
it the distance to the end of a long edge even when it stands beside the middle
of that edge. The longest single edge here is 6.8 km and 672 edge records are
longer than the entire 800 m walking budget, so that artefact can decide the
10-minute classification on its own. Every snap in this module is to the nearest
walkable EDGE, and both transit sources and population cells are placed at their
true positions along that edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import iterparse

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import LineString, MultiLineString
from shapely.ops import substring, unary_union

import config as cfg
from pipeline_utils import log

GRAPHML_NS = "{http://graphml.graphdrawing.org/xmlns}"

# Two positions on the same edge closer than this are treated as one insertion
# point. Well below any distance that can change a 600 s classification.
POSITION_EPS_M = 1e-6


# ---------------------------------------------------------------------------
# Canonical pedestrian network
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WalkNetwork:
    """Canonical undirected pedestrian network, projected to the metric CRS.

    One entry per canonical walk edge. `edge_cost` is the routing weight in
    metres (OSMnx `length`, computed geodesically on the WGS84 graph).
    `edge_geom` is the SAME edge's geometry, projected and oriented u -> v, so
    a position found by projecting onto the geometry can be converted into a
    routing cost without ever mixing one edge's shape with another's cost.

    `edge_geom_len` is the projected length of that geometry, which differs
    from `edge_cost` by the UTM scale factor (measured here: 0.9984 to 1.0022).
    Positions are therefore converted through the dimensionless fraction along
    the geometry rather than by subtracting metres from metres.

    Self-loops (u == v) are kept: 350 of them are real closed walkable paths up
    to 1.6 km long, and a population cell can legitimately snap to one.
    """

    node_ids: np.ndarray        # (n,)  int64 OSM node ids, ascending
    node_xy: np.ndarray         # (n,2) float64 projected metres
    edge_u: np.ndarray          # (m,)  int64 node index
    edge_v: np.ndarray          # (m,)  int64 node index
    edge_cost: np.ndarray       # (m,)  float64 routing metres
    edge_geom: np.ndarray       # (m,)  object array of projected LineStrings
    edge_geom_len: np.ndarray   # (m,)  float64 projected metres
    crs: str
    stats: dict

    @property
    def n_nodes(self) -> int:
        return int(self.node_ids.size)

    @property
    def n_edges(self) -> int:
        return int(self.edge_cost.size)


def _reverse_linestring_wkt(wkt: str) -> str:
    """Reverse the vertex order of a WKT LINESTRING without parsing floats.

    Both directional copies of one OSM way are serialised by the same writer
    from geometries that are exact reverses, so reversing the text yields a
    byte-identical signature for the pair. Verified on this graph: every
    canonical non-self-loop edge is backed by exactly two records and none by
    one, which could not happen if the signatures failed to match up.
    """
    open_at = wkt.index("(")
    close_at = wkt.rindex(")")
    parts = [part.strip() for part in wkt[open_at + 1:close_at].split(",")]
    return f"{wkt[:open_at].strip()} (" + ", ".join(reversed(parts)) + ")"


def _linestring_wkt_coords(wkt: str) -> list[tuple[float, float]]:
    open_at = wkt.index("(")
    close_at = wkt.rindex(")")
    out = []
    for part in wkt[open_at + 1:close_at].split(","):
        x_text, y_text = part.split()
        out.append((float(x_text), float(y_text)))
    return out


def _parse_graphml(path: Path) -> tuple[dict, list]:
    """Stream the OSMnx GraphML into plain arrays.

    Streamed rather than loaded through networkx because the analysis needs the
    edge GEOMETRY as well as the endpoints, and holding a full MultiDiGraph plus
    a projected copy of it does not fit in the memory available here. The parse
    is checked against the node and edge counts recorded in Week 3, so a silent
    divergence from the validated snapshot cannot pass unnoticed.
    """
    key_name: dict[str, str] = {}
    node_ids: list[int] = []
    node_lon: list[float] = []
    node_lat: list[float] = []
    edges: list[tuple[int, int, float, str | None]] = []
    graph_attrs: dict[str, str] = {}

    for _, elem in iterparse(str(path), events=("end",)):
        tag = elem.tag
        if tag == GRAPHML_NS + "key":
            key_name[elem.get("id")] = elem.get("attr.name")
            elem.clear()
        elif tag == GRAPHML_NS + "node":
            data = {key_name[c.get("key")]: c.text for c in elem if c.tag == GRAPHML_NS + "data"}
            node_ids.append(int(elem.get("id")))
            node_lon.append(float(data["x"]))
            node_lat.append(float(data["y"]))
            elem.clear()
        elif tag == GRAPHML_NS + "edge":
            data = {key_name[c.get("key")]: c.text for c in elem if c.tag == GRAPHML_NS + "data"}
            length_text = data.get("length")
            edges.append((
                int(elem.get("source")),
                int(elem.get("target")),
                float("nan") if length_text is None else float(length_text),
                data.get("geometry"),
            ))
            elem.clear()
        elif tag == GRAPHML_NS + "data" and elem.get("key") in key_name:
            # graph-level <data> elements appear before any node
            name = key_name[elem.get("key")]
            if name in ("crs", "simplified", "created_with"):
                graph_attrs.setdefault(name, elem.text)

    meta = {
        "node_ids": node_ids,
        "node_lon": node_lon,
        "node_lat": node_lat,
        "graph_attrs": graph_attrs,
    }
    return meta, edges


def load_walk_network(
    path: Path,
    *,
    expected_nodes: int | None = None,
    expected_edge_records: int | None = None,
) -> WalkNetwork:
    """Build the canonical undirected walk network from the OSMnx GraphML.

    Canonicalisation. OSMnx stores every undirected way twice, once per
    direction. Each record is first re-oriented so that u <= v (reversing the
    geometry with it), then records are deduplicated on
    (u, v, length, geometry). Two directional copies of one way collapse into a
    single canonical edge; two genuinely different ways between the same node
    pair keep their own geometry AND their own cost, so an edge's shape can
    never be paired with another edge's routing weight.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"walk graph missing at {path}. Run: python scripts/acquire_data.py"
        )

    meta, records = _parse_graphml(path)
    node_ids_raw = meta["node_ids"]
    stored_edge_records = len(records)
    log(f"    streamed GraphML: {len(node_ids_raw):,} nodes, "
        f"{stored_edge_records:,} stored edge records")
    log(f"    graph attributes: {meta['graph_attrs']}")

    if expected_nodes is not None and len(node_ids_raw) != expected_nodes:
        raise ValueError(
            f"walk graph has {len(node_ids_raw):,} nodes but the Week 3 manifest "
            f"records {expected_nodes:,}. The source snapshot has changed; stop and report."
        )
    if expected_edge_records is not None and stored_edge_records != expected_edge_records:
        raise ValueError(
            f"walk graph has {stored_edge_records:,} stored edge records but the Week 3 "
            f"manifest records {expected_edge_records:,}. The source snapshot has changed; "
            f"stop and report."
        )

    # --- nodes -------------------------------------------------------------
    order = np.argsort(np.asarray(node_ids_raw, dtype=np.int64), kind="stable")
    node_ids = np.asarray(node_ids_raw, dtype=np.int64)[order]
    lon = np.asarray(meta["node_lon"], dtype=np.float64)[order]
    lat = np.asarray(meta["node_lat"], dtype=np.float64)[order]
    if not (np.isfinite(lon).all() and np.isfinite(lat).all()):
        raise ValueError("walk graph contains non-finite node coordinates")

    from pyproj import Transformer
    transformer = Transformer.from_crs(cfg.GEOGRAPHIC_CRS, cfg.METRIC_CRS, always_xy=True)
    node_x, node_y = transformer.transform(lon, lat)
    node_xy = np.column_stack([node_x, node_y]).astype(np.float64)
    index_of = {int(nid): i for i, nid in enumerate(node_ids)}

    # --- canonical edges ---------------------------------------------------
    usable = 0
    dropped_bad_length = 0
    canonical: dict[tuple, tuple[int, int, float, str | None]] = {}
    backing_records: dict[tuple, int] = {}

    for src, tgt, length, geometry in records:
        if not np.isfinite(length) or length <= 0:
            dropped_bad_length += 1
            continue
        usable += 1
        u_idx = index_of[src]
        v_idx = index_of[tgt]
        if u_idx <= v_idx:
            u, v, geom = u_idx, v_idx, geometry
        else:
            u, v = v_idx, u_idx
            geom = _reverse_linestring_wkt(geometry) if geometry else None
        if u == v and geom is not None:
            # A self-loop has no natural direction; pick one deterministically.
            geom = min(geom, _reverse_linestring_wkt(geom))
        signature = (u, v, round(length, 6), geom)
        if signature not in canonical:
            canonical[signature] = (u, v, length, geom)
        backing_records[signature] = backing_records.get(signature, 0) + 1

    if not canonical:
        raise ValueError("walk graph has no usable edges")

    # Deterministic edge order: by endpoints, then cost, then geometry text.
    keys = sorted(canonical, key=lambda s: (s[0], s[1], s[2], s[3] or ""))
    edge_u = np.fromiter((canonical[k][0] for k in keys), dtype=np.int64, count=len(keys))
    edge_v = np.fromiter((canonical[k][1] for k in keys), dtype=np.int64, count=len(keys))
    edge_cost = np.fromiter((canonical[k][2] for k in keys), dtype=np.float64, count=len(keys))

    # --- projected geometry, built in one bulk transform --------------------
    flat_xy: list[tuple[float, float]] = []
    part_index: list[int] = []
    for position, key in enumerate(keys):
        u, v, _, geom = canonical[key]
        if geom:
            coords = _linestring_wkt_coords(geom)
        else:
            coords = [(lon[u], lat[u]), (lon[v], lat[v])]
        flat_xy.extend(coords)
        part_index.extend([position] * len(coords))

    flat = np.asarray(flat_xy, dtype=np.float64)
    gx, gy = transformer.transform(flat[:, 0], flat[:, 1])
    edge_geom = shapely.linestrings(
        np.column_stack([gx, gy]), indices=np.asarray(part_index, dtype=np.int64)
    )
    edge_geom_len = shapely.length(edge_geom)

    degenerate = int((edge_geom_len <= 0).sum())
    if degenerate:
        log(f"    ! {degenerate} canonical edges have zero projected geometry length")

    backing = np.fromiter((backing_records[k] for k in keys), dtype=np.int64, count=len(keys))
    self_loops = int((edge_u == edge_v).sum())
    pair_key = edge_u.astype(np.int64) * np.int64(node_ids.size) + edge_v
    _, pair_counts = np.unique(pair_key, return_counts=True)

    stats = {
        "graph_file": path.name,
        "graph_attributes": meta["graph_attrs"],
        "stored_edge_records": stored_edge_records,
        "usable_edge_records": usable,
        "dropped_edge_records_bad_length": dropped_bad_length,
        "canonical_routing_edges": int(len(keys)),
        "canonical_self_loop_edges": self_loops,
        "distinct_node_pairs": int(pair_counts.size),
        "node_pairs_with_parallel_edges": int((pair_counts > 1).sum()),
        "max_canonical_edges_on_one_pair": int(pair_counts.max()),
        "records_per_canonical_edge": {
            str(k): int(v) for k, v in zip(*np.unique(backing, return_counts=True))
        },
        "canonical_edges_with_degenerate_geometry": degenerate,
        "edge_cost_m": {
            "min": float(edge_cost.min()),
            "median": float(np.median(edge_cost)),
            "max": float(edge_cost.max()),
            "over_800m": int((edge_cost > 800).sum()),
        },
        "projected_geometry_over_routing_length": {
            "min": float(np.min(edge_geom_len / edge_cost)),
            "median": float(np.median(edge_geom_len / edge_cost)),
            "max": float(np.max(edge_geom_len / edge_cost)),
        },
        "canonicalisation": (
            "each stored record re-oriented to u <= v (reversing its geometry with it), "
            "then deduplicated on (u, v, length, geometry); parallel ways between the "
            "same node pair are kept as separate canonical edges, each with its own "
            "geometry and its own routing cost"
        ),
    }

    if usable != int(backing.sum()):
        raise ValueError("canonical edge backing counts do not account for every usable record")

    log(f"    usable edge records            : {usable:,}")
    log(f"    canonical undirected routing edges: {len(keys):,}")
    log(f"      of which self-loops          : {self_loops:,}")
    log(f"      distinct node pairs          : {pair_counts.size:,} "
        f"({int((pair_counts > 1).sum()):,} carry parallel edges)")
    log(f"      records per canonical edge   : {stats['records_per_canonical_edge']}")
    log(f"    longest canonical edge         : {edge_cost.max():,.1f} m "
        f"({stats['edge_cost_m']['over_800m']:,} exceed the 800 m budget)")

    return WalkNetwork(
        node_ids=node_ids,
        node_xy=node_xy,
        edge_u=edge_u,
        edge_v=edge_v,
        edge_cost=edge_cost,
        edge_geom=edge_geom,
        edge_geom_len=edge_geom_len,
        crs=cfg.METRIC_CRS,
        stats=stats,
    )


def network_from_arrays(
    node_xy: np.ndarray,
    edge_u: np.ndarray,
    edge_v: np.ndarray,
    edge_cost: np.ndarray,
    edge_geom: list | None = None,
) -> WalkNetwork:
    """Build a WalkNetwork directly, for synthetic regression tests."""
    node_xy = np.asarray(node_xy, dtype=np.float64)
    edge_u = np.asarray(edge_u, dtype=np.int64)
    edge_v = np.asarray(edge_v, dtype=np.int64)
    edge_cost = np.asarray(edge_cost, dtype=np.float64)
    if edge_geom is None:
        edge_geom = [
            LineString([tuple(node_xy[u]), tuple(node_xy[v])])
            for u, v in zip(edge_u, edge_v)
        ]
    geoms = np.empty(len(edge_geom), dtype=object)
    geoms[:] = edge_geom
    return WalkNetwork(
        node_ids=np.arange(len(node_xy), dtype=np.int64),
        node_xy=node_xy,
        edge_u=edge_u,
        edge_v=edge_v,
        edge_cost=edge_cost,
        edge_geom=geoms,
        edge_geom_len=shapely.length(geoms),
        crs=cfg.METRIC_CRS,
        stats={"synthetic": True},
    )


# ---------------------------------------------------------------------------
# Edge-aware snapping
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EdgeSnap:
    """Where a set of points attaches to the walk network.

    `connector_m` is the straight-line distance from the point to the nearest
    walkable edge. It is an approximation of an off-network link: it may or may
    not describe a physically walkable connection, so it is reported, never
    hidden, and never used to drop a point.
    """

    edge_index: np.ndarray      # (k,) canonical edge index
    connector_m: np.ndarray     # (k,) straight-line metres to that edge
    fraction: np.ndarray        # (k,) position along the edge geometry, 0..1
    cost_to_u: np.ndarray       # (k,) routing metres from the position to u
    cost_to_v: np.ndarray       # (k,) routing metres from the position to v
    snapped_xy: np.ndarray      # (k,2) the projected point on the edge

    @property
    def count(self) -> int:
        return int(self.edge_index.size)


def build_edge_index(network: WalkNetwork) -> shapely.STRtree:
    """Spatial index over the canonical edge geometries.

    Built once and reused: the tree over 154k linestrings is the expensive part
    of snapping, and metro sources, bus sources and both population surfaces all
    query the same network.
    """
    return shapely.STRtree(network.edge_geom)


def snap_points_to_edges(
    network: WalkNetwork,
    points_xy: np.ndarray,
    tree: shapely.STRtree | None = None,
) -> EdgeSnap:
    """Attach points to the nearest canonical walk EDGE, not the nearest vertex.

    The position along the edge is found by projecting onto the edge geometry,
    then expressed as a dimensionless fraction. Routing costs come from that
    fraction and the edge's OWN routing cost:

        cost_to_u = fraction       * edge_cost
        cost_to_v = (1 - fraction) * edge_cost

    Going through the fraction rather than subtracting projected metres keeps
    snapping consistent with routing even though the projected geometry and the
    geodesic routing length differ by the UTM scale factor.
    """
    points_xy = np.asarray(points_xy, dtype=np.float64)
    if points_xy.size == 0:
        empty_f = np.empty(0, dtype=np.float64)
        return EdgeSnap(np.empty(0, dtype=np.int64), empty_f, empty_f,
                        empty_f, empty_f, np.empty((0, 2), dtype=np.float64))

    if tree is None:
        tree = build_edge_index(network)
    points = shapely.points(points_xy)
    edge_index = tree.nearest(points).astype(np.int64)
    lines = network.edge_geom[edge_index]

    connector = shapely.distance(points, lines)
    along = shapely.line_locate_point(lines, points)
    geom_len = network.edge_geom_len[edge_index]

    # A zero-length geometry has no interior; the position is its start point.
    safe_len = np.where(geom_len > 0, geom_len, 1.0)
    fraction = np.clip(np.where(geom_len > 0, along / safe_len, 0.0), 0.0, 1.0)

    cost = network.edge_cost[edge_index]
    snapped = shapely.get_coordinates(shapely.line_interpolate_point(lines, along))

    return EdgeSnap(
        edge_index=edge_index,
        connector_m=connector.astype(np.float64),
        fraction=fraction.astype(np.float64),
        cost_to_u=(fraction * cost).astype(np.float64),
        cost_to_v=((1.0 - fraction) * cost).astype(np.float64),
        snapped_xy=snapped.astype(np.float64),
    )


def connector_diagnostics(label: str, connectors: np.ndarray) -> dict:
    """Distribution of off-network connector distances.

    Reported in full; never used to silently drop a point and never turned into
    a directional claim about bias. A straight-line connector may cross a fence,
    a building, a railway, a canal or private land, so its effect on any one
    point is unknown.
    """
    if connectors.size == 0:
        return {"label": label, "count": 0}
    percentiles = np.percentile(connectors, [50, 95, 99])
    return {
        "label": label,
        "count": int(connectors.size),
        "min_m": float(connectors.min()),
        "mean_m": float(connectors.mean()),
        "median_m": float(percentiles[0]),
        "p95_m": float(percentiles[1]),
        "p99_m": float(percentiles[2]),
        "max_m": float(connectors.max()),
    }


def snap_placement_stats(snap: EdgeSnap, network: WalkNetwork, *, endpoint_tol_m: float = 1.0) -> dict:
    """How many sources landed in an edge interior rather than at an endpoint."""
    if snap.count == 0:
        return {"count": 0}
    at_u = snap.cost_to_u <= endpoint_tol_m
    at_v = snap.cost_to_v <= endpoint_tol_m
    interior = ~(at_u | at_v)
    return {
        "count": snap.count,
        "endpoint_tolerance_m": endpoint_tol_m,
        "inserted_in_edge_interior": int(interior.sum()),
        "effectively_at_an_endpoint": int((at_u | at_v).sum()),
        "distinct_edges_containing_sources": int(np.unique(snap.edge_index).size),
        "max_sources_on_one_edge": int(np.bincount(snap.edge_index).max()),
    }


# ---------------------------------------------------------------------------
# Augmented routing graph with sources inside edge interiors
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AugmentedNetwork:
    """The canonical network with every transit source spliced into its edge.

    Each canonical edge is cut at the positions of the sources lying on it, in
    order along the edge. The result is an ordinary graph in which every source
    is a real vertex, so one multi-source Dijkstra gives exact distances to
    every original vertex AND to every source position.

    `break_fraction` / `break_node` hold, per canonical edge and in ascending
    order, the fractions at which that edge was cut and the augmented node index
    sitting there. Every edge always carries fraction 0.0 (its u) and fraction
    1.0 (its v), so any queried position on any edge is bracketed.
    `break_offset` is the CSR-style start index of each edge's block.
    """

    n_nodes: int
    break_offset: np.ndarray    # (m+1,) int64
    break_edge: np.ndarray      # (B,)   int64 canonical edge index per break
    break_fraction: np.ndarray  # (B,)   float64, ascending within each edge
    break_node: np.ndarray      # (B,)   int64 augmented node index
    edge_cost: np.ndarray       # (m,)   float64, from the canonical network
    source_node: np.ndarray     # (s,)   int64 augmented node per inserted source
    stats: dict


def build_augmented_network(network: WalkNetwork, snap: EdgeSnap) -> AugmentedNetwork:
    """Splice the snapped sources into the canonical edges they lie on.

    Sources on the same edge are ordered deterministically by position, and
    sources closer together than POSITION_EPS_M share one augmented node.
    A source at an endpoint reuses that endpoint's own node rather than adding
    a duplicate at distance zero, which keeps the endpoint case identical to
    ordinary graph routing.
    """
    n_edges = network.n_edges
    n_base = network.n_nodes

    # Order sources by (edge, position along edge, original index) so the split
    # is reproducible regardless of the order the sources arrived in.
    order = np.lexsort((np.arange(snap.count), snap.fraction, snap.edge_index))
    src_edge = snap.edge_index[order]
    src_frac = snap.fraction[order]

    # Position in metres along the routing cost, which is what determines
    # whether two sources are distinguishable and whether one sits on a vertex.
    src_pos_m = src_frac * network.edge_cost[src_edge]

    source_node = np.empty(snap.count, dtype=np.int64)
    breaks_edge: list[int] = []
    breaks_frac: list[float] = []
    breaks_node: list[int] = []

    next_node = n_base
    interior_added = 0
    reused_endpoint = 0
    merged_coincident = 0

    i = 0
    n_src = src_edge.size
    while i < n_src:
        edge = int(src_edge[i])
        j = i
        while j < n_src and int(src_edge[j]) == edge:
            j += 1
        block = slice(i, j)
        cost = float(network.edge_cost[edge])
        u = int(network.edge_u[edge])
        v = int(network.edge_v[edge])

        last_pos = -np.inf
        last_node = -1
        for k in range(block.start, block.stop):
            pos = float(src_pos_m[k])
            if pos - last_pos <= POSITION_EPS_M and last_node >= 0:
                source_node[order[k]] = last_node
                merged_coincident += 1
                continue
            if pos <= POSITION_EPS_M:
                node = u
                reused_endpoint += 1
            elif cost - pos <= POSITION_EPS_M:
                node = v
                reused_endpoint += 1
            else:
                node = next_node
                next_node += 1
                interior_added += 1
                breaks_edge.append(edge)
                breaks_frac.append(float(src_frac[k]))
                breaks_node.append(node)
            source_node[order[k]] = node
            last_pos = pos
            last_node = node
        i = j

    # Assemble the per-edge break table: endpoints plus any interior splits.
    edge_of_break = np.concatenate([
        np.arange(n_edges, dtype=np.int64),
        np.arange(n_edges, dtype=np.int64),
        np.asarray(breaks_edge, dtype=np.int64),
    ])
    frac_of_break = np.concatenate([
        np.zeros(n_edges, dtype=np.float64),
        np.ones(n_edges, dtype=np.float64),
        np.asarray(breaks_frac, dtype=np.float64),
    ])
    node_of_break = np.concatenate([
        network.edge_u,
        network.edge_v,
        np.asarray(breaks_node, dtype=np.int64),
    ])

    sort = np.lexsort((frac_of_break, edge_of_break))
    edge_of_break = edge_of_break[sort]
    frac_of_break = frac_of_break[sort]
    node_of_break = node_of_break[sort]

    counts = np.bincount(edge_of_break, minlength=n_edges)
    break_offset = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)

    stats = {
        "sources": int(snap.count),
        "augmented_nodes_added": int(next_node - n_base),
        "sources_inserted_in_edge_interior": int(interior_added),
        "sources_reusing_an_existing_endpoint": int(reused_endpoint),
        "sources_merged_onto_a_coincident_position": int(merged_coincident),
        "augmented_nodes_total": int(next_node),
        "augmented_routing_edges": int(len(frac_of_break) - n_edges),
        "canonical_routing_edges": int(n_edges),
        "position_epsilon_m": POSITION_EPS_M,
    }

    return AugmentedNetwork(
        n_nodes=int(next_node),
        break_offset=break_offset,
        break_edge=edge_of_break,
        break_fraction=frac_of_break,
        break_node=node_of_break,
        edge_cost=network.edge_cost,
        source_node=source_node,
        stats=stats,
    )


def _augmented_segments(aug: AugmentedNetwork) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Consecutive break pairs per edge: (edge, node_a, node_b, frac_a, frac_b)."""
    ends = aug.break_offset[1:]
    keep = np.ones(aug.break_fraction.size, dtype=bool)
    keep[ends - 1] = False                       # last break of each edge has no successor
    left = np.nonzero(keep)[0]
    right = left + 1
    return (aug.break_edge[left], aug.break_node[left], aug.break_node[right],
            aug.break_fraction[left], aug.break_fraction[right])


def multi_source_distances(
    network: WalkNetwork,
    aug: AugmentedNetwork,
    source_connector_m: np.ndarray,
    *,
    return_predecessors: bool = False,
):
    """Distance from the nearest transit source to every augmented node.

    A source does not sit on the network, so its off-network connector is paid
    once, on entry: a temporary super-source is joined to each source node with
    that connector as the edge weight. One Dijkstra from the super-source then
    yields, per augmented node,

        min over sources of (connector to the network + network distance)

    Nodes on a component holding no source come back as +inf, never 0.
    """
    if aug.source_node.size == 0:
        raise ValueError("no transit sources supplied")

    seg_edge, seg_a, seg_b, frac_a, frac_b = _augmented_segments(aug)
    seg_cost = (frac_b - frac_a) * aug.edge_cost[seg_edge]

    n = aug.n_nodes
    super_source = n

    # Cheapest connector per source node, deterministically.
    node_order = np.lexsort((source_connector_m, aug.source_node))
    nodes_sorted = aug.source_node[node_order]
    costs_sorted = np.asarray(source_connector_m, dtype=np.float64)[node_order]
    first = np.ones(nodes_sorted.size, dtype=bool)
    first[1:] = nodes_sorted[1:] != nodes_sorted[:-1]
    entry_nodes = nodes_sorted[first]
    entry_costs = costs_sorted[first]

    rows = np.concatenate([seg_a, seg_b, np.full(entry_nodes.size, super_source)])
    cols = np.concatenate([seg_b, seg_a, entry_nodes])
    data = np.concatenate([seg_cost, seg_cost, entry_costs])

    # coo_matrix SUMS duplicate (row, col) entries. Directional duplicates are
    # already removed by canonicalisation, but a self-loop or two parallel edges
    # can still produce the same node pair twice, so the minimum weight per pair
    # is taken explicitly. Summing here would silently double a walking cost -
    # the defect that produced the discarded 3.93 percent result.
    rows, cols, data = _min_by_pair(rows, cols, data, n + 1)

    matrix = coo_matrix((data, (rows, cols)), shape=(n + 1, n + 1)).tocsr()
    if return_predecessors:
        distances, predecessors = dijkstra(
            matrix, directed=True, indices=super_source, return_predecessors=True
        )
        return (np.asarray(distances[:n], dtype=np.float64),
                np.asarray(predecessors, dtype=np.int64), int(super_source))
    distances = dijkstra(matrix, directed=True, indices=super_source)
    return np.asarray(distances[:n], dtype=np.float64)


def _min_by_pair(
    rows: np.ndarray, cols: np.ndarray, data: np.ndarray, dim: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Collapse repeated (row, col) entries to the single smallest weight."""
    key = rows.astype(np.int64) * np.int64(dim) + cols.astype(np.int64)
    order = np.lexsort((data, key))          # by pair, then ascending weight
    key_sorted = key[order]
    first = np.ones(key_sorted.size, dtype=bool)
    first[1:] = key_sorted[1:] != key_sorted[:-1]
    keep = order[first]
    return rows[keep], cols[keep], data[keep]


def query_positions(
    aug: AugmentedNetwork,
    node_distance: np.ndarray,
    edge_index: np.ndarray,
    fraction: np.ndarray,
) -> np.ndarray:
    """Network distance from the sources to arbitrary positions along edges.

    A queried position lies inside exactly one segment of its (possibly split)
    edge, between consecutive breaks a and b. That segment's interior holds no
    vertex and no source, so any path reaching the position must enter the
    segment through a or through b. Hence

        d(position) = min( d(a) + cost(a -> position),
                           d(b) + cost(position -> b) )

    is exact, with d(a) and d(b) taken from the multi-source Dijkstra.

    This is what makes the same-edge case right. If a metro entrance sits 500 m
    along a 1000 m edge and a population cell sits at 550 m, the entrance is a
    break, the cell falls in the segment that starts at it, and the answer is
    50 m - not the walk out to an endpoint and back.

    A self-loop needs no special case: its two breaks at fractions 0 and 1 are
    the same vertex, so the formula returns min(d(u) + f*L, d(u) + (1-f)*L),
    which is walking round the loop the shorter way.
    """
    edge_index = np.asarray(edge_index, dtype=np.int64)
    fraction = np.asarray(fraction, dtype=np.float64)
    if edge_index.size == 0:
        return np.empty(0, dtype=np.float64)

    start = aug.break_offset[edge_index]
    stop = aug.break_offset[edge_index + 1]

    # One global searchsorted over a key that is strictly increasing across
    # edges and within an edge, then clamped into the queried edge's own block
    # so no result can ever leak into a neighbouring edge.
    global_key = aug.break_fraction + 2.0 * aug.break_edge.astype(np.float64)
    query_key = fraction + 2.0 * edge_index.astype(np.float64)
    right = np.searchsorted(global_key, query_key, side="right")
    right = np.clip(right, start + 1, stop - 1)
    left = right - 1

    cost = aug.edge_cost[edge_index]
    to_left = (fraction - aug.break_fraction[left]) * cost
    to_right = (aug.break_fraction[right] - fraction) * cost
    # Clip away sub-nanometre negatives from floating-point rounding.
    to_left = np.maximum(to_left, 0.0)
    to_right = np.maximum(to_right, 0.0)

    return np.minimum(
        node_distance[aug.break_node[left]] + to_left,
        node_distance[aug.break_node[right]] + to_right,
    )


def augmented_node_xy(network: WalkNetwork, aug: AugmentedNetwork) -> np.ndarray:
    """Projected coordinates of every augmented node, originals included.

    A node spliced into an edge interior sits where its break fraction falls
    along that edge's geometry, so an access path can be traced on the ground.
    """
    xy = np.zeros((aug.n_nodes, 2), dtype=np.float64)
    xy[:network.n_nodes] = network.node_xy
    inserted = aug.break_node >= network.n_nodes
    if inserted.any():
        edges = aug.break_edge[inserted]
        along = aug.break_fraction[inserted] * network.edge_geom_len[edges]
        points = shapely.line_interpolate_point(network.edge_geom[edges], along)
        xy[aug.break_node[inserted]] = shapely.get_coordinates(points)
    return xy


def trace_access_path(
    predecessors: np.ndarray, super_source: int, node: int
) -> list[int]:
    """Walk the Dijkstra predecessor chain back from a node to its source.

    Returns the node sequence from the entry node (the access point's own
    position on the network) forward to `node`. Empty when the node was never
    reached.
    """
    if node < 0 or predecessors[node] < 0:
        return []
    chain = [int(node)]
    guard = 0
    while True:
        previous = int(predecessors[chain[-1]])
        guard += 1
        if previous < 0 or previous == super_source or guard > 10_000_000:
            break
        chain.append(previous)
    return list(reversed(chain))


# ---------------------------------------------------------------------------
# Display service area
# ---------------------------------------------------------------------------
def build_service_area(
    network: WalkNetwork,
    aug: AugmentedNetwork,
    node_distance: np.ndarray,
    budget_m: float,
    *,
    buffer_m: float = cfg.ISOCHRONE_BUFFER_M,
    simplify_m: float = cfg.ISOCHRONE_SIMPLIFY_M,
) -> tuple[gpd.GeoDataFrame, dict]:
    """Buffer the reachable part of the network into a display polygon.

    FOR VISUALISATION ONLY. The population classification is computed from
    network distances directly and does not depend on this geometry.

    Built from the AUGMENTED segments, so a source sitting in the middle of a
    long edge generates reachable geometry around itself even when both of that
    edge's original endpoints are beyond the budget. Partially reachable
    segments are cut along the real edge geometry rather than along the straight
    chord between vertices.
    """
    seg_edge, seg_a, seg_b, frac_a, frac_b = _augmented_segments(aug)
    cost = network.edge_cost[seg_edge]
    seg_cost = (frac_b - frac_a) * cost
    d_a = node_distance[seg_a]
    d_b = node_distance[seg_b]

    inside_a = d_a <= budget_m
    inside_b = d_b <= budget_m
    both = inside_a & inside_b
    only_a = inside_a & ~inside_b
    only_b = inside_b & ~inside_a
    # Neither endpoint reachable means no interior point is either: a segment
    # interior can only be entered through one of its own two ends.

    geom_len = network.edge_geom_len[seg_edge]
    lines = network.edge_geom[seg_edge]

    pieces: list = []

    # Whole segments. An unsplit edge covers its geometry exactly, so it is
    # taken as-is; only genuinely split edges need a substring.
    whole = np.nonzero(both)[0]
    unsplit = whole[(frac_a[whole] == 0.0) & (frac_b[whole] == 1.0)]
    partial_whole = whole[~((frac_a[whole] == 0.0) & (frac_b[whole] == 1.0))]
    pieces.extend(lines[unsplit].tolist())
    for i in partial_whole:
        pieces.append(substring(
            lines[i], frac_a[i] * geom_len[i], frac_b[i] * geom_len[i]
        ))

    def cut(indices, from_frac, to_frac_limit, reach_from_start):
        out = []
        for i in indices:
            span = seg_cost[i]
            if span <= 0:
                continue
            reach = min(span, max(0.0, budget_m - reach_from_start[i]))
            if reach <= 0:
                continue
            step = reach / cost[i]
            if from_frac is frac_a:
                lo = frac_a[i]
                hi = min(frac_b[i], frac_a[i] + step)
            else:
                hi = frac_b[i]
                lo = max(frac_a[i], frac_b[i] - step)
            if hi <= lo:
                continue
            out.append(substring(lines[i], lo * geom_len[i], hi * geom_len[i]))
        return out

    pieces.extend(cut(np.nonzero(only_a)[0], frac_a, None, d_a))
    pieces.extend(cut(np.nonzero(only_b)[0], frac_b, None, d_b))

    pieces = [g for g in pieces if g is not None and not g.is_empty and g.length > 0]
    if not pieces:
        raise ValueError("service area is empty; no network is reachable within the budget")

    reachable_length_m = float(sum(g.length for g in pieces))

    # Buffering in chunks and dissolving the resulting polygons is far cheaper
    # than noding hundreds of thousands of line segments in one unary_union,
    # which for the bus network exhausted memory. The result is identical: the
    # union of per-segment buffers.
    chunk = 20_000
    buffered = [
        MultiLineString(pieces[i:i + chunk]).buffer(buffer_m, resolution=4)
        for i in range(0, len(pieces), chunk)
    ]
    merged = unary_union(buffered) if len(buffered) > 1 else buffered[0]
    merged = merged.buffer(0)  # normalise any self-touching ring
    if simplify_m > 0:
        merged = merged.simplify(simplify_m, preserve_topology=True)

    gdf = gpd.GeoDataFrame(
        {"budget_m": [budget_m], "buffer_m": [buffer_m], "simplify_m": [simplify_m]},
        geometry=[merged],
        crs=cfg.METRIC_CRS,
    )
    info = {
        "segments_considered": int(seg_edge.size),
        "segments_fully_reachable": int(both.sum()),
        "segments_partially_reachable": int(only_a.sum() + only_b.sum()),
        "segments_unreachable": int(seg_edge.size - both.sum() - only_a.sum() - only_b.sum()),
        "reachable_network_length_km": round(reachable_length_m / 1000.0, 4),
    }
    return gdf, info


def service_area_area_km2(gdf: gpd.GeoDataFrame) -> float:
    return float(gdf.to_crs(cfg.METRIC_CRS).area.sum() / 1e6)


# ---------------------------------------------------------------------------
# Population raster -> cells
# ---------------------------------------------------------------------------
def rasterize_districts(
    raster_path: Path,
    districts: gpd.GeoDataFrame,
    boundary_geom,
    *,
    boundary_crs: str = cfg.METRIC_CRS,
) -> tuple[pd.DataFrame, dict]:
    """Turn the WorldPop raster into one row per population cell.

    `boundary_geom` is interpreted in `boundary_crs` (metric by default), which
    must be stated rather than inferred from `districts` - the two are not
    necessarily the same CRS.

    Inclusion rule: a cell belongs to the district whose polygon contains the
    cell CENTRE. `rasterio.features.rasterize` with `all_touched=False` tests
    exactly that, so every cell is assigned to at most one district and no cell
    is counted twice. Cells whose centre falls in no district, or that carry
    nodata, are excluded.
    """
    import rasterio
    from rasterio.features import rasterize
    from rasterio.mask import mask as rio_mask

    with rasterio.open(raster_path) as src:
        window_geom = gpd.GeoSeries([boundary_geom], crs=boundary_crs).to_crs(src.crs)
        values, transform = rio_mask(src, [window_geom.iloc[0]], crop=True,
                                     filled=True, nodata=src.nodata)
        band = values[0].astype(np.float64)
        nodata = src.nodata
        raster_crs = str(src.crs)

        ordered = districts.sort_values("district_name").reset_index(drop=True)
        shapes = [
            (geom, idx + 1)
            for idx, geom in enumerate(ordered.to_crs(src.crs).geometry)
        ]
        labels = rasterize(
            shapes,
            out_shape=band.shape,
            transform=transform,
            fill=0,
            all_touched=False,
            dtype="int32",
        )

    valid = (band != nodata) & np.isfinite(band) & (labels > 0)
    rows, cols = np.nonzero(valid)
    if rows.size == 0:
        raise ValueError("no valid population cells inside the analysis boundary")

    # Cell centres in raster CRS, then projected.
    xs, ys = rasterio.transform.xy(transform, rows, cols, offset="center")
    lon = np.asarray(xs, dtype=np.float64)
    lat = np.asarray(ys, dtype=np.float64)
    centres = gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs=raster_crs).to_crs(cfg.METRIC_CRS)

    names = ordered.district_name.tolist()
    frame = pd.DataFrame(
        {
            "cell_id": [f"r{r}c{c}" for r, c in zip(rows, cols)],
            "row": rows.astype(np.int32),
            "col": cols.astype(np.int32),
            "lon": lon,
            "lat": lat,
            "x_m": centres.x.to_numpy(),
            "y_m": centres.y.to_numpy(),
            "district_name": [names[i - 1] for i in labels[rows, cols]],
            "worldpop_raw": band[rows, cols],
        }
    ).sort_values(["row", "col"]).reset_index(drop=True)

    meta = {
        "raster": raster_path.name,
        "raster_crs": raster_crs,
        "nodata": None if nodata is None else float(nodata),
        "window_shape": [int(band.shape[0]), int(band.shape[1])],
        "cells_in_window": int(band.size),
        "cells_included": int(len(frame)),
        "inclusion_rule": (
            "cell centre inside exactly one SIAT district polygon "
            "(rasterize all_touched=False), value not nodata and finite"
        ),
    }
    return frame, meta


def calibrate_to_official(
    cells: pd.DataFrame,
    official: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scale each district's cells so they sum to its official SIAT population.

    WorldPop is not allowed to decide how population splits BETWEEN districts;
    SIAT does. Each district therefore gets its own factor, never one city-wide
    factor.
    """
    raw = cells.groupby("district_name", sort=True)["worldpop_raw"].sum()
    official_map = official.set_index("district_name")["population"]

    missing = sorted(set(official_map.index) - set(raw.index))
    if missing:
        raise ValueError(f"districts with no population cells: {missing}")
    extra = sorted(set(raw.index) - set(official_map.index))
    if extra:
        raise ValueError(f"cells assigned to districts with no SIAT row: {extra}")

    zero = sorted(raw.index[raw <= 0])
    if zero:
        raise ValueError(f"districts with non-positive raw WorldPop sum: {zero}")

    factors = (official_map / raw).rename("calibration_factor")
    out = cells.copy()
    out["calibration_factor"] = out.district_name.map(factors).astype(float)
    out["population"] = out.worldpop_raw * out.calibration_factor

    table = pd.DataFrame(
        {
            "district_name": factors.index,
            "worldpop_raw_sum": raw.reindex(factors.index).to_numpy(),
            "official_population": official_map.reindex(factors.index).to_numpy(),
            "calibration_factor": factors.to_numpy(),
            "calibrated_population": out.groupby("district_name", sort=True)["population"]
            .sum()
            .reindex(factors.index)
            .to_numpy(),
        }
    ).reset_index(drop=True)
    return out, table
