"""Acquire current OpenStreetMap healthcare and education facilities.

    python scripts/acquire_urban_dimensions.py

These are CURRENT OSM snapshots. OpenStreetMap carries no audited opening
history for these facilities, so Phase 2C makes no historical claim about
healthcare, education or bazaar availability.

The raw Overpass response is cached under the gitignored external directory so
a rerun reproduces byte-identical committed outputs without querying the API
again. Delete the cache to take a new snapshot.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
import urban_dimensions as ud  # noqa: E402
from pipeline_utils import enable_utf8_stdout, log, overpass_post, step  # noqa: E402

# Both the amenity and the healthcare tagging schemes are queried. An object
# carrying both is returned once by the Overpass union and classified once.
HEALTHCARE_SELECTORS = (
    ("amenity", "hospital"),
    ("amenity", "clinic"),
    ("healthcare", "hospital"),
    ("healthcare", "clinic"),
)
HEALTHCARE_TAG_KEYS = ("amenity", "healthcare")

EDUCATION_SELECTORS = (
    ("amenity", "school"),
    ("amenity", "college"),
    ("amenity", "university"),
    ("amenity", "kindergarten"),
)
EDUCATION_TAG_KEYS = ("amenity",)


def build_query(bbox: tuple[float, float, float, float], selectors) -> str:
    """Overpass QL union over node/way/relation, returning full geometry.

    ``out geom`` rather than ``out center``: a bounding-box centre can fall
    outside a concave building, while a polygon representative point cannot.

    Plain ``out geom`` rather than ``out geom tags``: ``tags`` is a print mode
    that emits ids and tags only, so relations come back without members and
    every multipolygon facility would be dropped for having no geometry.
    Body-level ``out geom`` carries tags, members and member geometry.
    """
    west, south, east, north = bbox
    area = f"({south},{west},{north},{east})"
    clauses = []
    for key, value in selectors:
        for element in ("node", "way", "relation"):
            clauses.append(f'  {element}["{key}"="{value}"]{area};')
    body = "\n".join(clauses)
    return f"[out:json][timeout:{cfg.OVERPASS_TIMEOUT}];\n(\n{body}\n);\nout geom;"


def fetch_cached(query: str, cache_path: Path, description: str) -> dict:
    """Return the cached Overpass snapshot, downloading it once if absent.

    A cache is only reused when it was produced by exactly the query being
    requested. Silently reusing a snapshot taken under different tag or output
    semantics would pin provenance to bytes that no longer describe the
    analysis.
    """
    if cache_path.exists():
        payload = json.loads(cache_path.read_bytes().decode("utf-8"))
        missing = [k for k in ("acquired_at_utc", "query", "elements") if k not in payload]
        if missing:
            raise SystemExit(
                f"{cache_path} is missing required keys {missing}; delete it to "
                "take a fresh snapshot"
            )
        if not isinstance(payload["elements"], list):
            raise SystemExit(f"{cache_path} does not store 'elements' as a list")
        if payload["query"] != query:
            raise SystemExit(
                f"{cache_path} was produced by a different Overpass query than the "
                "one now requested. Refusing to reuse a stale snapshot; review the "
                "change and delete the cache deliberately to re-acquire."
            )
        log(f"    reusing cached {description} snapshot "
            f"({len(payload['elements'])} elements, taken {payload['acquired_at_utc']})")
        return payload

    response = overpass_post(query, description)
    payload = {
        "acquired_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "query": query,
        "elements": response.get("elements", []),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    ud.write_json_lf(cache_path, payload)
    log(f"    downloaded {len(payload['elements'])} elements for {description}")
    return payload


def elements_to_frame(
    payload: dict,
    precedence: tuple[str, ...],
    tag_keys: tuple[str, ...],
    category_column: str,
    id_prefix: str,
) -> gpd.GeoDataFrame:
    """Turn raw Overpass elements into classified facilities with geometry."""
    records, geometries, points = [], [], []
    seen: set[tuple[str, int]] = set()

    for element in payload["elements"]:
        osm_type = element.get("type")
        osm_id = element.get("id")
        if osm_type is None or osm_id is None:
            continue
        key = (osm_type, int(osm_id))
        if key in seen:
            continue  # one object matching several selectors is still one object
        seen.add(key)

        tags = element.get("tags") or {}
        category = ud.classify_category(tags, precedence, tag_keys)
        if category is None:
            continue

        geometry, assembly = ud.element_geometry(element)
        if geometry is None or geometry.is_empty:
            continue
        point, method = ud.representative_point(geometry)

        name = ud.display_name(tags.get("name"))
        records.append(
            {
                "facility_id": f"{id_prefix}_{osm_type}_{osm_id}",
                "osm_type": osm_type,
                "osm_id": int(osm_id),
                "name": name,
                "normalized_name": ud.normalized_name(tags.get("name")),
                category_column: category,
                "amenity": tags.get("amenity"),
                "healthcare": tags.get("healthcare"),
                "operator": ud.display_name(tags.get("operator")),
                "osm_relation_type": tags.get("type") if osm_type == "relation" else None,
                "geometry_assembly": assembly,
                "representative_point_method": method,
                "longitude": round(float(point.x), 7),
                "latitude": round(float(point.y), 7),
            }
        )
        geometries.append(geometry)
        points.append(point)

    frame = gpd.GeoDataFrame(records, geometry=geometries, crs=cfg.GEOGRAPHIC_CRS)
    frame["representative_geometry"] = gpd.GeoSeries(points, crs=cfg.GEOGRAPHIC_CRS)
    frame["geometry_rank"] = [ud.geometry_rank(g) for g in geometries]
    return frame


def clip_to_city(frame: gpd.GeoDataFrame, city_geom_metric, label: str) -> gpd.GeoDataFrame:
    """Keep facilities whose routing point lies inside the city boundary."""
    if frame.empty:
        return frame
    points = gpd.GeoSeries(frame["representative_geometry"], crs=cfg.GEOGRAPHIC_CRS)
    inside = points.to_crs(cfg.METRIC_CRS).within(city_geom_metric)
    dropped = int((~inside).sum())
    if dropped:
        log(f"    dropped {dropped} {label} outside the Tashkent city boundary")
    return frame.loc[inside.to_numpy()].copy()


def attach_district(frame: gpd.GeoDataFrame, districts: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Label each facility with its analysis district, or with none.

    Routing scope is the full current city boundary; population and supply
    scope is the 12 SIAT-matched districts. A facility inside the city but
    outside every analysis district — Yangi Toshkent Tumani is excluded from
    the population denominator — stays a routing source and is left unassigned
    rather than credited to the nearest district.
    """
    if frame.empty:
        frame["district_name"] = pd.Series(dtype="object")
        frame["district_assignment"] = pd.Series(dtype="object")
        return frame

    projected = districts.to_crs(cfg.METRIC_CRS)
    polygons = {row.district_name: row.geometry for row in projected.itertuples()}
    points = gpd.GeoSeries(
        frame["representative_geometry"], crs=cfg.GEOGRAPHIC_CRS
    ).to_crs(cfg.METRIC_CRS)

    names, assignments = [], []
    for point in points:
        name, assignment = ud.assign_analysis_district(point, polygons)
        names.append(name)
        assignments.append(assignment)

    out = frame.copy()
    out["district_name"] = names
    out["district_assignment"] = assignments
    ties = assignments.count("boundary_tie")
    outside = assignments.count("outside_analysis_districts")
    if ties:
        log(f"    {ties} facility(ies) sit on a shared analysis-district boundary")
    if outside:
        log(f"    {outside} facility(ies) lie outside the 12 analysis districts; "
            f"kept as routing sources, credited to no district supply")
    return out


def summarize(frame: gpd.GeoDataFrame, category_column: str, categories) -> dict:
    """Counts used for the manifest and for the acquisition report."""
    counts = {c: int((frame[category_column] == c).sum()) for c in categories}
    named = int(frame["name"].notna().sum())
    return {
        "total": int(len(frame)),
        "by_category": counts,
        "named": named,
        "unnamed": int(len(frame) - named),
    }


def geometry_summary(frame: gpd.GeoDataFrame) -> dict:
    """Relation assembly counts, used to prove multipolygons were rebuilt."""
    relations = frame[frame.osm_type == "relation"]
    multipolygon = relations[relations.osm_relation_type == "multipolygon"]
    kinds = relations.geometry.geom_type.value_counts().to_dict()
    return {
        "relations": int(len(relations)),
        "multipolygon_relations": int(len(multipolygon)),
        "relation_geometry_types": {k: int(v) for k, v in sorted(kinds.items())},
        "relation_polygonal": int(
            relations.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).sum()
        ),
        "relation_line_fallback": int(
            (relations.geometry_assembly == "line_fallback").sum()
        ),
        "multipolygon_line_fallback": int(
            (multipolygon.geometry_assembly == "line_fallback").sum()
        ),
        "assembly_methods": {
            k: int(v) for k, v in sorted(
                frame.geometry_assembly.value_counts().to_dict().items()
            )
        },
    }


def district_summary(frame: gpd.GeoDataFrame) -> dict:
    """Split the routing scope from the 12-district supply scope."""
    counts = frame.district_assignment.value_counts().to_dict()
    within = int(counts.get("within", 0))
    tie = int(counts.get("boundary_tie", 0))
    outside = int(counts.get("outside_analysis_districts", 0))
    return {
        "routing_sources": int(len(frame)),
        "in_analysis_districts": within + tie,
        "within": within,
        "boundary_tie": tie,
        "outside_analysis_districts": outside,
    }


def build_class(
    payload: dict,
    *,
    precedence: tuple[str, ...],
    tag_keys: tuple[str, ...],
    categories: tuple[str, ...],
    category_column: str,
    id_prefix: str,
    label: str,
    city_geom_metric,
    districts: gpd.GeoDataFrame,
    output_path: Path,
    cache_path: Path,
) -> dict:
    """Classify, clip, deduplicate and write one facility class."""
    raw = elements_to_frame(payload, precedence, tag_keys, category_column, id_prefix)
    log(f"    classified {len(raw)} {label} candidates from "
        f"{len(payload['elements'])} returned elements")
    clipped = clip_to_city(raw, city_geom_metric, label)
    raw_summary = summarize(clipped, category_column, categories)

    work = clipped.rename(columns={category_column: "facility_category"})
    kept, dropped = ud.dedupe_facilities(
        work, radius_m=cfg.PHASE2C_NAME_DEDUPE_RADIUS_M
    )
    kept = kept.rename(columns={"facility_category": category_column})
    distances = ud.dedupe_distance_summary(dropped)
    log(f"    deduplicated {label}: {len(clipped)} raw -> {len(kept)} clean "
        f"({len(dropped)} duplicate representations removed)")
    if len(dropped):
        log(f"      collapsed-pair distance: min {distances['dedupe_distance_min_m']:.1f} m, "
            f"median {distances['dedupe_distance_median_m']:.1f} m, "
            f"max {distances['dedupe_distance_max_m']:.1f} m "
            f"(limit {cfg.PHASE2C_NAME_DEDUPE_RADIUS_M:.0f} m)")

    kept = attach_district(kept, districts)
    kept = kept.sort_values(["osm_type", "osm_id"], kind="stable").reset_index(drop=True)
    clean_summary = summarize(kept, category_column, categories)

    columns = [
        "facility_id", "osm_type", "osm_id", "name", "normalized_name",
        category_column, "amenity", "healthcare", "operator",
        "osm_relation_type", "geometry_assembly",
        "representative_point_method", "longitude", "latitude",
        "district_name", "district_assignment", "geometry",
    ]
    if category_column != "facility_category":
        columns = [c for c in columns if c != "facility_category"]
    out = gpd.GeoDataFrame(kept[columns], geometry="geometry", crs=cfg.GEOGRAPHIC_CRS)
    provenance = {
        "facility_class": label,
        "osm_licence": "ODbL 1.0",
        "acquired_at_utc": payload["acquired_at_utc"],
        "overpass_query": payload["query"],
        "elements_returned": int(len(payload["elements"])),
        "raw_in_city": raw_summary,
        "clean": clean_summary,
        "geometry": geometry_summary(out),
        "scope": district_summary(out),
        "duplicates_removed": int(len(dropped)),
        "dedupe_radius_m": cfg.PHASE2C_NAME_DEDUPE_RADIUS_M,
        **distances,
        "raw_cache_path": str(cache_path.relative_to(cfg.REPO_ROOT)).replace("\\", "/"),
        "raw_cache_sha256": ud.raw_file_sha256(cache_path),
        "raw_cache_size_bytes": cache_path.stat().st_size,
        "dedupe_rule": (
            "one object per OSM type/id; records sharing a category and a "
            f"non-empty normalized name within {cfg.PHASE2C_NAME_DEDUPE_RADIUS_M:.0f} m "
            "collapse to the areal representation; unnamed facilities are never "
            "proximity-merged and categories are never merged"
        ),
        "representative_point_rule": (
            "OSM node as-is; a closed way and a polygonized multipolygon relation "
            "use a representative point guaranteed inside the reconstructed area; "
            "only a genuine line feature uses its midpoint. These are routing "
            "proxies, not verified pedestrian entrances."
        ),
        "relation_assembly_rule": (
            "relation member linework is noded and polygonized by role, so an "
            "outer ring split across several member ways still closes; inner "
            "rings are subtracted so courtyards remain holes"
        ),
        "city_clipping_rule": (
            "retained when the routing representative point lies within "
            "data/processed/tashkent_boundary.geojson"
        ),
        "district_scope_rule": (
            "routing scope is the full current city boundary; supply scope is "
            "the 12 SIAT-matched analysis districts. A facility outside all 12 "
            "stays a routing source and is credited to no district supply"
        ),
    }
    ud.write_geojson_lf(out, output_path, extra={"provenance": provenance})
    log(f"  wrote {output_path.name}: {len(out)} facilities")

    return provenance


def main() -> int:
    enable_utf8_stdout()
    step("PHASE 2C  Acquire current healthcare and education facilities")

    city = gpd.read_file(cfg.BOUNDARY_FILE)
    districts = gpd.read_file(cfg.DISTRICTS_FILE)
    districts = districts.loc[districts.in_siat].copy()
    city_geom_metric = city.to_crs(cfg.METRIC_CRS).geometry.iloc[0]
    bbox = tuple(float(v) for v in city.total_bounds)
    log(f"  city bbox {bbox}")
    log(f"  {len(districts)} SIAT-matched analysis districts")

    step("HEALTHCARE  amenity/healthcare hospital and clinic")
    healthcare_payload = fetch_cached(
        build_query(bbox, HEALTHCARE_SELECTORS),
        cfg.PHASE2C_HEALTHCARE_RAW_CACHE,
        "phase2c healthcare",
    )
    healthcare = build_class(
        healthcare_payload,
        precedence=ud.HEALTHCARE_PRECEDENCE,
        tag_keys=HEALTHCARE_TAG_KEYS,
        categories=cfg.PHASE2C_HEALTHCARE_CATEGORIES,
        category_column="facility_category",
        id_prefix="hc",
        label="healthcare",
        city_geom_metric=city_geom_metric,
        districts=districts,
        output_path=cfg.HEALTHCARE_FACILITIES_FILE,
        cache_path=cfg.PHASE2C_HEALTHCARE_RAW_CACHE,
    )

    step("EDUCATION  amenity school, college, university and kindergarten")
    education_payload = fetch_cached(
        build_query(bbox, EDUCATION_SELECTORS),
        cfg.PHASE2C_EDUCATION_RAW_CACHE,
        "phase2c education",
    )
    education = build_class(
        education_payload,
        precedence=ud.EDUCATION_PRECEDENCE,
        tag_keys=EDUCATION_TAG_KEYS,
        categories=cfg.PHASE2C_EDUCATION_CATEGORIES,
        category_column="education_category",
        id_prefix="ed",
        label="education",
        city_geom_metric=city_geom_metric,
        districts=districts,
        output_path=cfg.EDUCATION_FACILITIES_FILE,
        cache_path=cfg.PHASE2C_EDUCATION_RAW_CACHE,
    )

    step("Phase 2C source acquisition complete")
    for label, summary in (("healthcare", healthcare), ("education", education)):
        log(f"  {label}: raw {summary['raw_in_city']['total']}, clean "
            f"{summary['clean']['total']}, removed {summary['duplicates_removed']}")
        log(f"    by category: {summary['clean']['by_category']}")
        log(f"    named {summary['clean']['named']}, unnamed {summary['clean']['unnamed']}")
        geometry = summary["geometry"]
        log(f"    relations {geometry['relations']} "
            f"({geometry['multipolygon_relations']} type=multipolygon); "
            f"polygonal {geometry['relation_polygonal']}, "
            f"line fallback {geometry['relation_line_fallback']} "
            f"(multipolygon fallbacks {geometry['multipolygon_line_fallback']})")
        scope = summary["scope"]
        log(f"    routing sources {scope['routing_sources']}; in analysis districts "
            f"{scope['in_analysis_districts']} (within {scope['within']}, "
            f"boundary tie {scope['boundary_tie']}); outside "
            f"{scope['outside_analysis_districts']}")
    log("  Next: python scripts/analyze_urban_dimensions.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
