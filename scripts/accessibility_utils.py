"""Network and raster primitives for the Week 4 accessibility analysis.

Everything metric happens in EPSG:32642. Nothing here computes a project
result; it provides the graph, snapping, shortest-path and service-area
building blocks that `analyze_accessibility.py` composes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiLineString
from shapely.ops import unary_union

import config as cfg
from pipeline_utils import log


# ---------------------------------------------------------------------------
# Projected pedestrian graph
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WalkGraph:
    """The pedestrian network as arrays, projected to the metric CRS.

    `node_ids` is the ordered OSM node id per matrix index, so every downstream
    result can be traced back to a real node. `xy` is projected metres.
    """

    node_ids: np.ndarray          # (n,) int64 OSM node ids, ascending
    xy: np.ndarray                # (n, 2) float64 projected metres
    edge_u: np.ndarray            # (m,) matrix index
    edge_v: np.ndarray            # (m,) matrix index
    edge_len: np.ndarray          # (m,) metres
    crs: str

    @property
    def n_nodes(self) -> int:
        return int(self.node_ids.size)

    @property
    def n_edges(self) -> int:
        return int(self.edge_len.size)

    def index_of(self) -> dict[int, int]:
        return {int(nid): i for i, nid in enumerate(self.node_ids)}


def load_walk_graph(path: Path) -> WalkGraph:
    """Load the GraphML walk network and project it to the metric CRS.

    `length` is already stored in metres by OSMnx (geodesic on the WGS84
    graph), so projection is needed for coordinates and snapping, not for edge
    weights. Edges are treated as undirected: a pedestrian may walk either way
    along any way in the walk network.
    """
    import osmnx as ox

    if not path.exists():
        raise FileNotFoundError(
            f"walk graph missing at {path}. Run: python scripts/acquire_data.py"
        )
    graph = ox.load_graphml(path)
    stored_crs = graph.graph.get("crs")
    log(f"    loaded graph: {graph.number_of_nodes():,} nodes, "
        f"{graph.number_of_edges():,} edges, crs={stored_crs}")

    projected = ox.project_graph(graph, to_crs=cfg.METRIC_CRS)
    proj_crs = str(projected.graph.get("crs"))
    log(f"    projected to {proj_crs}")

    # Deterministic node ordering by OSM id.
    node_ids = np.array(sorted(int(n) for n in projected.nodes), dtype=np.int64)
    position = {int(nid): i for i, nid in enumerate(node_ids)}
    xy = np.empty((node_ids.size, 2), dtype=np.float64)
    for nid, data in projected.nodes(data=True):
        i = position[int(nid)]
        xy[i, 0] = float(data["x"])
        xy[i, 1] = float(data["y"])

    if not np.isfinite(xy).all():
        raise ValueError("projected graph contains non-finite node coordinates")

    us, vs, lengths = [], [], []
    for u, v, data in projected.edges(data=True):
        length = data.get("length")
        if length is None or not np.isfinite(float(length)) or float(length) <= 0:
            continue
        us.append(position[int(u)])
        vs.append(position[int(v)])
        lengths.append(float(length))

    edge_u = np.asarray(us, dtype=np.int64)
    edge_v = np.asarray(vs, dtype=np.int64)
    edge_len = np.asarray(lengths, dtype=np.float64)
    if edge_len.size == 0:
        raise ValueError("projected graph has no usable edges")
    log(f"    usable edges with positive finite length: {edge_len.size:,}")

    return WalkGraph(node_ids, xy, edge_u, edge_v, edge_len, proj_crs)


# ---------------------------------------------------------------------------
# Snapping
# ---------------------------------------------------------------------------
def snap_points(graph: WalkGraph, points_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Nearest graph node index and straight-line offset (metres) per point."""
    if points_xy.size == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64)
    tree = cKDTree(graph.xy)
    offsets, indices = tree.query(points_xy, k=1)
    return indices.astype(np.int64), offsets.astype(np.float64)


def snap_diagnostics(label: str, offsets: np.ndarray) -> dict:
    """Distribution of snap offsets. Reported, never used to silently drop points."""
    if offsets.size == 0:
        return {"label": label, "count": 0}
    percentiles = np.percentile(offsets, [50, 95, 99])
    return {
        "label": label,
        "count": int(offsets.size),
        "min_m": float(offsets.min()),
        "median_m": float(percentiles[0]),
        "p95_m": float(percentiles[1]),
        "p99_m": float(percentiles[2]),
        "max_m": float(offsets.max()),
        "mean_m": float(offsets.mean()),
    }


# ---------------------------------------------------------------------------
# Multi-source shortest path with source-specific initial cost
# ---------------------------------------------------------------------------
def multi_source_distances(
    graph: WalkGraph,
    source_nodes: np.ndarray,
    source_offsets: np.ndarray,
) -> np.ndarray:
    """Walking distance from every graph node to the nearest transit access point.

    A transit point does not sit exactly on its snapped node, so its offset must
    be paid before entering the network. Sources are collapsed to one entry per
    graph node keeping the smallest offset, then a temporary super-source is
    attached to those nodes with edge weight equal to that offset. A single
    Dijkstra from the super-source therefore yields, per node:

        min over access points of (offset to network + network distance)

    Unreachable nodes come back as +inf, never 0 and never missing.
    """
    if source_nodes.size == 0:
        raise ValueError("no transit sources supplied")

    # Collapse to the cheapest source per node, deterministically.
    order = np.lexsort((source_offsets, source_nodes))
    nodes_sorted = source_nodes[order]
    offsets_sorted = source_offsets[order]
    keep = np.ones(nodes_sorted.size, dtype=bool)
    keep[1:] = nodes_sorted[1:] != nodes_sorted[:-1]
    entry_nodes = nodes_sorted[keep]
    entry_costs = offsets_sorted[keep]

    n = graph.n_nodes
    super_source = n

    # Undirected network edges, plus directed super-source -> entry node edges.
    rows = np.concatenate([graph.edge_u, graph.edge_v, np.full(entry_nodes.size, super_source)])
    cols = np.concatenate([graph.edge_v, graph.edge_u, entry_nodes])
    data = np.concatenate([graph.edge_len, graph.edge_len, entry_costs])

    # coo_matrix SUMS duplicate (row, col) entries. The OSMnx walk graph stores
    # both directions of a way, so symmetrising it produces duplicates and the
    # summing would silently double those edge weights. Keep the minimum weight
    # per node pair instead, which is the correct cost of walking between them.
    rows, cols, data = _min_by_pair(rows, cols, data, n + 1)

    matrix = coo_matrix((data, (rows, cols)), shape=(n + 1, n + 1)).tocsr()
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


# ---------------------------------------------------------------------------
# Display service area
# ---------------------------------------------------------------------------
def build_service_area(
    graph: WalkGraph,
    node_distance: np.ndarray,
    budget_m: float,
    *,
    buffer_m: float = cfg.ISOCHRONE_BUFFER_M,
    simplify_m: float = cfg.ISOCHRONE_SIMPLIFY_M,
) -> gpd.GeoDataFrame:
    """Buffer the reachable part of the network into a display polygon.

    FOR VISUALISATION ONLY. The population classification is computed from
    network distances directly and does not depend on this geometry.

    An edge with both endpoints inside the budget is included whole. An edge
    with one endpoint inside is included up to the point where the budget runs
    out, linearly interpolated along the straight segment between the two nodes
    (the graph is simplified, so this is an approximation of the true partial
    traversal). Edges with neither endpoint inside are dropped.
    """
    du = node_distance[graph.edge_u]
    dv = node_distance[graph.edge_v]
    pu = graph.xy[graph.edge_u]
    pv = graph.xy[graph.edge_v]

    both = (du <= budget_m) & (dv <= budget_m)
    only_u = (du <= budget_m) & ~(dv <= budget_m)
    only_v = (dv <= budget_m) & ~(du <= budget_m)

    segments: list[LineString] = []
    for a, b in zip(pu[both], pv[both]):
        if a[0] != b[0] or a[1] != b[1]:
            segments.append(LineString([tuple(a), tuple(b)]))

    def partial(inside_pts, outside_pts, inside_d, lengths):
        out = []
        for a, b, d, length in zip(inside_pts, outside_pts, inside_d, lengths):
            if length <= 0:
                continue
            frac = float(np.clip((budget_m - d) / length, 0.0, 1.0))
            if frac <= 0:
                continue
            end = (a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac)
            if end != tuple(a):
                out.append(LineString([tuple(a), end]))
        return out

    segments += partial(pu[only_u], pv[only_u], du[only_u], graph.edge_len[only_u])
    segments += partial(pv[only_v], pu[only_v], dv[only_v], graph.edge_len[only_v])

    if not segments:
        raise ValueError("service area is empty; no network is reachable within the budget")

    # Buffering in chunks and dissolving the resulting polygons is far cheaper
    # than noding hundreds of thousands of line segments in one unary_union,
    # which for the bus network exhausted memory. The result is identical: the
    # union of per-segment buffers.
    chunk = 20_000
    pieces = [
        MultiLineString(segments[i:i + chunk]).buffer(buffer_m, resolution=4)
        for i in range(0, len(segments), chunk)
    ]
    merged = unary_union(pieces) if len(pieces) > 1 else pieces[0]
    merged = merged.buffer(0)  # normalise any self-touching ring
    if simplify_m > 0:
        merged = merged.simplify(simplify_m, preserve_topology=True)

    gdf = gpd.GeoDataFrame(
        {"budget_m": [budget_m], "buffer_m": [buffer_m], "simplify_m": [simplify_m]},
        geometry=[merged],
        crs=cfg.METRIC_CRS,
    )
    return gdf


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
