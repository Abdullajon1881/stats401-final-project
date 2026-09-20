"""Deterministic helpers for Phase 2C current urban dimensions.

This module holds only small, testable transformations: OSM element geometry
assembly, representative-point selection, facility deduplication, canonical
walk-network edge geometry and district clipping. Network loading, edge-aware
snapping and shortest paths remain authoritative in ``accessibility_utils.py``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, polygonize, unary_union

import config as cfg
from pipeline_utils import name_key, normalise_name

HASH_BASIS_CANONICAL_TEXT = "canonical_utf8_lf"
HASH_BASIS_RAW_BYTES = "raw_file_bytes"

# A facility carrying several recognised tags resolves to exactly one category,
# highest precedence first, so the classification never depends on tag order.
HEALTHCARE_PRECEDENCE = ("hospital", "clinic")
EDUCATION_PRECEDENCE = ("university", "college", "school", "kindergarten")


# ---------------------------------------------------------------------------
# Canonical JSON and provenance
# ---------------------------------------------------------------------------
def write_json_lf(path: Path, payload: object) -> None:
    """Write JSON as canonical UTF-8 bytes with LF newlines on every platform."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    path.write_bytes(text.encode("utf-8"))


def canonical_utf8_lf_bytes(path: Path) -> bytes:
    """Return a checkout-independent byte image of a tracked UTF-8 text file."""
    raw = path.read_bytes()
    normalized = raw.decode("utf-8").replace("\r\n", "\n")
    if "\r" in normalized:
        raise ValueError(
            f"{path.name} contains a bare CR; refusing to normalize it silently "
            "because that byte is content, not a line ending"
        )
    return normalized.encode("utf-8")


def raw_file_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of the exact filesystem bytes, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def provenance_record(path: Path, hash_basis: str) -> dict[str, object]:
    """Describe one file under an explicitly named byte representation."""
    if hash_basis == HASH_BASIS_CANONICAL_TEXT:
        payload = canonical_utf8_lf_bytes(path)
        return {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "hash_basis": hash_basis,
        }
    if hash_basis == HASH_BASIS_RAW_BYTES:
        return {
            "sha256": raw_file_sha256(path),
            "size_bytes": path.stat().st_size,
            "hash_basis": hash_basis,
        }
    raise ValueError(f"unknown hash basis: {hash_basis!r}")


def write_csv_lf(frame: pd.DataFrame, path: Path) -> None:
    """Write a CSV with LF line endings on every platform."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def write_geojson_lf(
    gdf: gpd.GeoDataFrame, path: Path, extra: dict | None = None
) -> None:
    """Write GeoJSON as canonical UTF-8 LF bytes with stable key order.

    ``extra`` becomes a foreign member of the FeatureCollection. Acquisition
    provenance travels with the committed layer, so the manifest can record
    raw and deduplicated counts without depending on a gitignored cache.
    """
    payload = json.loads(gdf.to_json(drop_id=True))
    if extra:
        payload.update(extra)
    write_json_lf(path, payload)


def read_geojson_provenance(path: Path) -> dict:
    """Read the provenance foreign member written alongside a facility layer."""
    payload = json.loads(canonical_utf8_lf_bytes(path).decode("utf-8"))
    return payload.get("provenance", {})


# ---------------------------------------------------------------------------
# OSM element geometry
# ---------------------------------------------------------------------------
GEOMETRY_ASSEMBLY_METHODS = (
    "osm_node",
    "open_way_line",
    "closed_way_polygon",
    "multipolygon_polygonized",
    "line_fallback",
)


def element_geometry(element: dict) -> tuple[object, str]:
    """Build geometry from one Overpass ``out geom`` element, plus its method.

    Nodes become points. A closed way becomes a polygon and an open way stays a
    line. A relation is polygonized from its member linework so that rings
    split across several member ways still close, and only falls back to line
    geometry when the source genuinely cannot form an area.
    """
    kind = element.get("type")
    if kind == "node":
        lon, lat = element.get("lon"), element.get("lat")
        if lon is None or lat is None:
            return None, "osm_node"
        return Point(float(lon), float(lat)), "osm_node"

    if kind == "way":
        coords = [(float(p["lon"]), float(p["lat"])) for p in element.get("geometry") or []]
        geometry = _way_geometry(coords)
        if geometry is None:
            return None, "open_way_line"
        method = (
            "closed_way_polygon"
            if geometry.geom_type in ("Polygon", "MultiPolygon")
            else "open_way_line"
        )
        return geometry, method

    if kind == "relation":
        geometry = _relation_geometry(element)
        if geometry is None:
            return None, "line_fallback"
        method = (
            "multipolygon_polygonized"
            if geometry.geom_type in ("Polygon", "MultiPolygon")
            else "line_fallback"
        )
        return geometry, method
    return None, "line_fallback"


def _way_geometry(coords: list[tuple[float, float]]):
    if len(coords) < 2:
        return Point(coords[0]) if coords else None
    if len(coords) >= 4 and coords[0] == coords[-1]:
        polygon = Polygon(coords)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if not polygon.is_empty and polygon.area > 0:
            return polygon
    return LineString(coords)


def _polygonize_role(lines: list[LineString]):
    """Build area geometry from linework whose rings may be split across ways.

    An OSM multipolygon ring is routinely mapped as several member ways that
    only close when joined end to end, so each member must never be treated as
    a candidate ring on its own. Noding the linework with ``unary_union`` and
    then running ``polygonize`` closes those split rings; ``line_merge`` first
    keeps the noded input tidy for the common two-way case.
    """
    if not lines:
        return None
    noded = unary_union(lines)
    if noded.is_empty:
        return None
    # linemerge only accepts multi-part linework; a single noded LineString is
    # already as merged as it can be.
    merged = linemerge(noded) if noded.geom_type == "MultiLineString" else noded
    faces = list(polygonize(merged))
    if not faces:
        faces = list(polygonize(noded))
    if not faces:
        return None
    area = unary_union(faces)
    if area.is_empty or area.area <= 0:
        return None
    return area


def _relation_geometry(element: dict):
    """Assemble an OSM relation into area geometry, preserving inner holes."""
    outer_lines, inner_lines = [], []
    for member in element.get("members") or []:
        coords = [(float(p["lon"]), float(p["lat"])) for p in member.get("geometry") or []]
        if len(coords) < 2:
            continue
        line = LineString(coords)
        if member.get("role") == "inner":
            inner_lines.append(line)
        else:
            outer_lines.append(line)

    outer_area = _polygonize_role(outer_lines)
    if outer_area is not None:
        inner_area = _polygonize_role(inner_lines)
        if inner_area is not None:
            outer_area = outer_area.difference(inner_area)
        if not outer_area.is_valid:
            outer_area = outer_area.buffer(0)
        if not outer_area.is_empty and outer_area.area > 0:
            return outer_area

    lines = outer_lines + inner_lines
    if not lines:
        return None
    return unary_union(lines)


def representative_point(geometry) -> tuple[Point, str]:
    """Return a deterministic routing point plus the rule that produced it.

    A polygon uses shapely's representative point, which is guaranteed to lie
    inside the feature; a bounding-box centre is not. The returned point is a
    routing proxy, never a verified pedestrian entrance.
    """
    if geometry is None or geometry.is_empty:
        raise ValueError("cannot take a representative point of empty geometry")
    kind = geometry.geom_type
    if kind == "Point":
        return geometry, "osm_node"
    if kind in ("Polygon", "MultiPolygon"):
        return geometry.representative_point(), "polygon_representative_point"
    if kind in ("LineString", "MultiLineString"):
        return geometry.interpolate(0.5, normalized=True), "line_midpoint"
    if kind == "GeometryCollection":
        return geometry.representative_point(), "collection_representative_point"
    raise ValueError(f"unsupported geometry type: {kind}")


def classify_category(tags: dict, precedence: tuple[str, ...], keys: tuple[str, ...]) -> str | None:
    """Resolve one category from a tag dict using fixed precedence."""
    values = {str(tags.get(key)).strip().lower() for key in keys if tags.get(key)}
    for candidate in precedence:
        if candidate in values:
            return candidate
    return None


def normalized_name(value) -> str:
    """Case- and punctuation-insensitive key used only for duplicate detection."""
    return name_key(value)


def display_name(value) -> str | None:
    return normalise_name(value)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
def dedupe_facilities(
    gdf: gpd.GeoDataFrame,
    *,
    radius_m: float,
    geometry_rank_column: str = "geometry_rank",
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Collapse duplicate representations of one institution.

    Two records merge only when they share a category and a non-empty
    normalized name and lie within ``radius_m`` of each other. A polygon or
    relation outranks a bare node, so the richer representation survives.
    Unnamed facilities are never proximity-merged: two adjacent kindergartens
    with no name are not evidence of one kindergarten.
    """
    if gdf.empty:
        return gdf.copy(), pd.DataFrame(columns=["kept_facility_id", "dropped_facility_id"])

    work = gdf.to_crs(cfg.METRIC_CRS).copy()
    work = work.sort_values(
        [geometry_rank_column, "osm_type", "osm_id"], kind="stable"
    )

    kept_index: list = []
    kept_points: list[Point] = []
    kept_keys: list[tuple[str, str]] = []
    kept_ids: list[str] = []
    dropped: list[dict] = []

    for idx, row in work.iterrows():
        key = row["normalized_name"]
        category = row["facility_category"]
        point = row["representative_geometry"]
        duplicate_of = None
        if key:
            for position, other in enumerate(kept_points):
                if kept_keys[position] != (category, key):
                    continue
                if point.distance(other) <= radius_m:
                    duplicate_of = kept_ids[position]
                    break
        if duplicate_of is None:
            kept_index.append(idx)
            kept_points.append(point)
            kept_keys.append((category, key))
            kept_ids.append(row["facility_id"])
        else:
            dropped.append(
                {
                    "kept_facility_id": duplicate_of,
                    "dropped_facility_id": row["facility_id"],
                    "facility_category": category,
                    "normalized_name": key,
                }
            )

    kept = gdf.loc[kept_index].copy()
    return kept, pd.DataFrame(
        dropped, columns=["kept_facility_id", "dropped_facility_id",
                          "facility_category", "normalized_name"]
    )


DISTRICT_ASSIGNMENTS = ("within", "boundary_tie", "outside_analysis_districts")

# Only absorbs projection and floating-point noise at a true shared boundary.
# Far too small to capture a facility that genuinely sits outside the analysis
# districts, which is the whole point.
BOUNDARY_TIE_TOLERANCE_M = 0.001


def assign_analysis_district(
    point: Point, polygons: dict[str, object], *, tolerance_m: float = BOUNDARY_TIE_TOLERANCE_M
) -> tuple[str | None, str]:
    """Assign a routing point to one of the 12 analysis districts, or to none.

    A facility can legitimately sit inside the current city boundary yet
    outside every analysis district, because Yangi Toshkent Tumani is excluded
    from the population denominator. Such a facility stays a routing source but
    must not be credited to whichever district happens to be nearest: that
    fabricates supply. It is returned unassigned instead.
    """
    names = sorted(polygons)
    inside = [name for name in names if polygons[name].contains(point)]
    if len(inside) == 1:
        return inside[0], "within"
    if inside:
        return inside[0], "boundary_tie"

    touching = [
        name for name in names
        if polygons[name].distance(point) <= tolerance_m
    ]
    if touching:
        return touching[0], "boundary_tie"
    return None, "outside_analysis_districts"


def geometry_rank(geometry) -> int:
    """Prefer an areal representation over a line, and a line over a node."""
    kind = geometry.geom_type
    if kind in ("Polygon", "MultiPolygon"):
        return 0
    if kind in ("LineString", "MultiLineString"):
        return 1
    return 2


# ---------------------------------------------------------------------------
# Walk-network density
# ---------------------------------------------------------------------------
def canonical_edge_geometries(network) -> gpd.GeoSeries:
    """Return one projected geometry per canonical undirected routing edge.

    ``WalkNetwork`` already collapses the stored directional GraphML records
    into canonical undirected edges, so summing these geometries counts each
    physical way once. Summing the stored records instead would double the
    network. Parallel mapped ways stay distinct because they are genuinely
    separate walkable paths.
    """
    return gpd.GeoSeries(list(network.edge_geom), crs=cfg.METRIC_CRS)


def clipped_length_km(edges: gpd.GeoSeries, polygon) -> float:
    """Total projected length in km of the edge geometry inside one polygon."""
    if len(edges) == 0:
        return 0.0
    candidates = edges.iloc[list(edges.sindex.query(polygon, predicate="intersects"))]
    if len(candidates) == 0:
        return 0.0
    clipped = candidates.intersection(polygon)
    return float(clipped.length.sum()) / 1000.0


def partition_network_length_km(
    edges: gpd.GeoSeries, polygons: dict[str, object]
) -> tuple[dict[str, float], dict[str, float]]:
    """Assign every metre of the walk network to exactly one district.

    Tashkent's district boundaries follow major roads, so a substantial length
    of walkable way lies exactly on a shared border and a plain clip returns it
    in full to both neighbours. Counting it twice would inflate both densities
    and break reconciliation against the district union.

    Each edge is partitioned individually: its clip against the alphabetically
    first district is taken first, and every later district receives only what
    is left of that same edge. Subtracting geometry derived from the edge
    itself cancels exactly, which subtracting an independently computed border
    line does not. Parallel mapped ways stay distinct because edges are never
    unioned together.
    """
    names = sorted(polygons)
    lengths = {name: 0.0 for name in names}
    shared_border = 0.0

    touching: dict[int, list[str]] = {}
    for name in names:
        for index in edges.sindex.query(polygons[name], predicate="intersects"):
            touching.setdefault(int(index), []).append(name)

    for index, candidates in touching.items():
        geometry = edges.iloc[index]
        if len(candidates) == 1:
            name = candidates[0]
            lengths[name] += float(geometry.intersection(polygons[name]).length)
            continue

        taken = None
        for name in sorted(candidates):
            piece = geometry.intersection(polygons[name])
            if piece.is_empty:
                continue
            if taken is not None:
                overlap = piece.intersection(taken)
                if not overlap.is_empty:
                    shared_border += float(overlap.length)
                piece = piece.difference(taken)
                if piece.is_empty:
                    continue
            lengths[name] += float(piece.length)
            taken = piece if taken is None else unary_union([taken, piece])

    total = {name: lengths[name] / 1000.0 for name in names}
    detail = {
        "edges_touching_multiple_districts": sum(
            1 for v in touching.values() if len(v) > 1
        ),
        "shared_border_km": shared_border / 1000.0,
    }
    return total, detail


def union_clipped_length_km(edges: gpd.GeoSeries, polygons: dict[str, object]) -> float:
    """Network length inside the union of the analysis districts.

    The reconciliation target is the union computed from the district polygons
    themselves. ``analysis_boundary.geojson`` stores the same area with
    GeoJSON-rounded coordinates, which moves the long outer perimeter by up to
    a centimetre and clips a slightly different length.
    """
    return clipped_length_km(edges, unary_union(list(polygons.values())))


# ---------------------------------------------------------------------------
# Access metrics
# ---------------------------------------------------------------------------
def within_budget(distance_m: np.ndarray, budget_m: float) -> np.ndarray:
    """Classify by unrounded network distance at or inside the budget."""
    distance_m = np.asarray(distance_m, dtype=np.float64)
    return distance_m <= budget_m


def weighted_population(population: np.ndarray, mask: np.ndarray) -> float:
    """Sum the population of the selected cells."""
    population = np.asarray(population, dtype=np.float64)
    mask = np.asarray(mask, dtype=bool)
    if population.shape != mask.shape:
        raise ValueError("population and mask arrays must have the same shape")
    return float(population[mask].sum(dtype=np.float64))


def percentage(numerator: float, denominator: float) -> float:
    """Percentage share, or NaN when the denominator is not positive."""
    if denominator <= 0:
        return float("nan")
    return float(100.0 * numerator / denominator)


def per_capita_rate(count: float, population: float, per_people: float) -> float:
    """Facilities per ``per_people`` residents."""
    if population <= 0:
        return float("nan")
    return float(count * per_people / population)
