"""Fast synthetic regression tests for Phase 2C urban dimensions.

    python scripts/test_urban_dimensions.py
    pytest scripts/test_urban_dimensions.py

No repository data and no network download is used.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point, Polygon

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
import urban_dimensions as ud  # noqa: E402

TOL = 1e-9


def facility_frame(rows: list[dict]) -> gpd.GeoDataFrame:
    """Build the minimal frame ``dedupe_facilities`` consumes."""
    geometries = [row.pop("geometry") for row in rows]
    frame = gpd.GeoDataFrame(rows, geometry=geometries, crs=cfg.METRIC_CRS)
    points, ranks = [], []
    for geometry in frame.geometry:
        point, _ = ud.representative_point(geometry)
        points.append(point)
        ranks.append(ud.geometry_rank(geometry))
    frame["representative_geometry"] = gpd.GeoSeries(points, crs=cfg.METRIC_CRS)
    frame["geometry_rank"] = ranks
    return frame


def test_normalized_names_are_deterministic():
    variants = [
        "  Respublika   Shifoxonasi ",
        "Respublika Shifoxonasi",
        "RESPUBLIKA SHIFOXONASI",
        "Respublika  shifoxonasi",
    ]
    keys = {ud.normalized_name(v) for v in variants}
    assert len(keys) == 1, keys
    # The apostrophe variants OSM uses for Uzbek names fold together.
    assert ud.normalized_name("O'zbekiston") == ud.normalized_name("Oʻzbekiston")
    assert ud.normalized_name(None) == ""
    return f"four spellings share the key {keys.pop()!r}"


def test_point_inside_polygon_duplicate_collapses():
    square = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    frame = facility_frame([
        {"facility_id": "hc_node_1", "osm_type": "node", "osm_id": 1,
         "normalized_name": "city clinic", "facility_category": "clinic",
         "geometry": Point(50, 50)},
        {"facility_id": "hc_way_2", "osm_type": "way", "osm_id": 2,
         "normalized_name": "city clinic", "facility_category": "clinic",
         "geometry": square},
    ])
    kept, dropped = facility_dedupe(frame)
    assert len(kept) == 1, kept.facility_id.tolist()
    assert kept.facility_id.iloc[0] == "hc_way_2", "the areal record must survive"
    assert dropped.dropped_facility_id.tolist() == ["hc_node_1"]
    return "a node inside its own building collapses into the polygon"


def test_unnamed_neighbours_are_not_merged():
    frame = facility_frame([
        {"facility_id": "ed_node_1", "osm_type": "node", "osm_id": 1,
         "normalized_name": "", "facility_category": "kindergarten",
         "geometry": Point(0, 0)},
        {"facility_id": "ed_node_2", "osm_type": "node", "osm_id": 2,
         "normalized_name": "", "facility_category": "kindergarten",
         "geometry": Point(5, 0)},
    ])
    kept, dropped = facility_dedupe(frame)
    assert len(kept) == 2, "unnamed neighbours are not evidence of one facility"
    assert dropped.empty
    return "two unnamed kindergartens 5 m apart stay distinct"


def test_different_categories_never_merge():
    frame = facility_frame([
        {"facility_id": "hc_node_1", "osm_type": "node", "osm_id": 1,
         "normalized_name": "markaz", "facility_category": "hospital",
         "geometry": Point(0, 0)},
        {"facility_id": "hc_node_2", "osm_type": "node", "osm_id": 2,
         "normalized_name": "markaz", "facility_category": "clinic",
         "geometry": Point(1, 0)},
    ])
    kept, _ = facility_dedupe(frame)
    assert len(kept) == 2, "a hospital and a clinic are not one facility"
    return "same name, different category, 1 m apart stays two facilities"


def test_polygon_representative_point_is_inside():
    # An L shape whose bounding-box centre falls outside the polygon.
    shape = Polygon([(0, 0), (100, 0), (100, 20), (20, 20), (20, 100), (0, 100)])
    centre = shape.envelope.centroid
    point, method = ud.representative_point(shape)
    assert not shape.contains(centre), "fixture must have an outside bbox centre"
    assert shape.contains(point), "representative point must lie inside"
    assert method == "polygon_representative_point"
    return "an L-shaped building yields an interior routing point"


def test_category_precedence_is_deterministic():
    tags = {"amenity": "school", "healthcare": "clinic"}
    assert ud.classify_category(tags, ud.EDUCATION_PRECEDENCE, ("amenity",)) == "school"
    both = {"amenity": "clinic", "healthcare": "hospital"}
    assert ud.classify_category(
        both, ud.HEALTHCARE_PRECEDENCE, ("amenity", "healthcare")
    ) == "hospital", "hospital outranks clinic regardless of which key carried it"
    assert ud.classify_category({"amenity": "pharmacy"}, ud.HEALTHCARE_PRECEDENCE,
                                ("amenity", "healthcare")) is None
    return "hospital outranks clinic; out-of-scope tags classify as None"


def test_canonical_edges_are_not_doubled():
    # Two directional records of one way collapse to a single canonical edge
    # upstream; the helper must read that canonical set, never the records.
    line = LineString([(0, 0), (100, 0)])

    class FakeNetwork:
        edge_geom = np.array([line, LineString([(100, 0), (200, 0)])], dtype=object)

    edges = ud.canonical_edge_geometries(FakeNetwork())
    assert len(edges) == 2
    square = Polygon([(-10, -10), (210, -10), (210, 10), (-10, 10)])
    assert abs(ud.clipped_length_km(edges, square) - 0.200) < TOL
    return "two canonical edges of 100 m clip to 0.200 km, not 0.400"


def test_clipping_across_two_districts_conserves_length():
    west = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
    east = Polygon([(100, 0), (200, 0), (200, 100), (100, 100)])
    # One edge spanning both, and one lying exactly on the shared border.
    edges = gpd.GeoSeries(
        [LineString([(10, 50), (190, 50)]), LineString([(100, 10), (100, 90)])],
        crs=cfg.METRIC_CRS,
    )
    polygons = {"east district": east, "west district": west}
    lengths, detail = ud.partition_network_length_km(edges, polygons)
    total = sum(lengths.values())
    union_total = ud.union_clipped_length_km(edges, polygons)

    assert abs(total - union_total) < TOL, (total, union_total)
    assert abs(total - 0.260) < TOL, total  # 180 m crossing + 80 m on the border
    assert abs(detail["shared_border_km"] - 0.080) < TOL
    # The border line is assigned once, to the alphabetically first district.
    assert abs(lengths["east district"] - 0.170) < TOL, lengths
    assert abs(lengths["west district"] - 0.090) < TOL, lengths
    return "a crossing edge splits 90/90 and the border edge is counted once"


def test_threshold_uses_unrounded_800_m():
    distance = np.array([799.9, 800.0, 800.0000001, 801.0, np.inf])
    mask = ud.within_budget(distance, 800.0)
    assert mask.tolist() == [True, True, False, False, False]
    return "800.0 m is inside and 800.0000001 m is outside"


def test_and_mask_and_per_capita_rate():
    population = np.array([100.0, 200.0, 300.0, 400.0])
    healthcare = np.array([True, True, False, False])
    education = np.array([True, False, True, False])
    both = healthcare & education
    assert ud.weighted_population(population, both) == 100.0
    assert ud.weighted_population(population, healthcare) == 300.0
    assert ud.weighted_population(population, education) == 400.0
    assert abs(ud.percentage(100.0, 1000.0) - 10.0) < TOL
    assert np.isnan(ud.percentage(0.0, 0.0))
    # 25 facilities for 125,000 residents is 2 per 10,000.
    assert abs(ud.per_capita_rate(25, 125_000, 10_000) - 2.0) < TOL
    assert np.isnan(ud.per_capita_rate(5, 0, 10_000))
    return "AND mask keeps only cells served by both classes; 25/125k = 2.0 per 10k"


def facility_dedupe(frame: gpd.GeoDataFrame):
    return ud.dedupe_facilities(frame, radius_m=cfg.PHASE2C_NAME_DEDUPE_RADIUS_M)


TESTS = [
    ("normalized names are deterministic", test_normalized_names_are_deterministic),
    ("a point inside its own polygon collapses", test_point_inside_polygon_duplicate_collapses),
    ("unnamed neighbours are never merged", test_unnamed_neighbours_are_not_merged),
    ("different categories never merge", test_different_categories_never_merge),
    ("a polygon representative point lies inside", test_polygon_representative_point_is_inside),
    ("facility category precedence is deterministic", test_category_precedence_is_deterministic),
    ("canonical edge length is not doubled", test_canonical_edges_are_not_doubled),
    ("clipping across districts conserves length", test_clipping_across_two_districts_conserves_length),
    ("the threshold is unrounded 800.0 m", test_threshold_uses_unrounded_800_m),
    ("AND mask and per-10k rate are correct", test_and_mask_and_per_capita_rate),
]


def main() -> int:
    print("=" * 74)
    print("Phase 2C urban dimensions - synthetic regression tests")
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
