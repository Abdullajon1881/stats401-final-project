"""Acquire and normalise every source dataset for the Tashkent transit project.

Run from the repository root:

    python scripts/acquire_data.py                 # everything
    python scripts/acquire_data.py --skip network  # skip the slow walk graph

The script is deliberately noisy: each step prints the counts it produced so a
reviewer can see what changed between runs. Critical failures raise instead of
being swallowed, so a broken source cannot quietly become an empty output file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import geopandas as gpd
import osmnx as ox
import pandas as pd
from pyproj import CRS

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
import osm_features as osmf  # noqa: E402
from pipeline_utils import (  # noqa: E402
    NOTES,
    http_get,
    local_file_record,
    log,
    normalise_name,
    overpass_failover,
    overpass_post,
    step,
    utc_now,
    write_geojson,
)

MANIFEST: dict[str, dict] = {}


def record_source(key: str, **fields) -> None:
    MANIFEST[key] = {"acquired_at_utc": utc_now(), **fields}


# ---------------------------------------------------------------------------
# Step 0 - environment and CRS
# ---------------------------------------------------------------------------
def configure_osmnx() -> None:
    cfg.ensure_directories()
    ox.settings.cache_folder = str(cfg.OSM_CACHE_DIR)
    ox.settings.use_cache = True
    ox.settings.log_console = False
    ox.settings.requests_timeout = cfg.OVERPASS_TIMEOUT
    ox.settings.overpass_rate_limit = True  # respect Overpass slot limits
    ox.settings.http_user_agent = cfg.USER_AGENT


def verify_metric_crs() -> dict:
    """Check that the chosen projected CRS actually suits Tashkent.

    Adopting EPSG:32642 without checking would be exactly the kind of unverified
    assumption this milestone is meant to eliminate.
    """
    step("STEP 0  Coordinate reference system check")
    crs = CRS.from_user_input(cfg.METRIC_CRS)
    area = crs.area_of_use
    lon, lat = 69.24, 41.31  # approximate Tashkent city centre
    within = area.west <= lon <= area.east and area.south <= lat <= area.north
    central_meridian = crs.to_dict().get("lon_0", 69.0)
    unit = crs.axis_info[0].unit_name

    log(f"  CRS             : {crs.name} ({cfg.METRIC_CRS})")
    log(f"  axis units      : {unit}")
    log(f"  area of use     : {area.west}..{area.east} E, {area.south}..{area.north} N")
    log(f"  Tashkent inside : {within}")
    log(f"  central meridian: {central_meridian} deg "
        f"(Tashkent is {abs(lon - central_meridian):.2f} deg away)")

    if not within:
        raise RuntimeError(f"{cfg.METRIC_CRS} does not cover Tashkent")
    if unit != "metre":
        raise RuntimeError(f"{cfg.METRIC_CRS} axis unit is {unit!r}, not metres")

    return {
        "code": cfg.METRIC_CRS,
        "name": crs.name,
        "units": unit,
        "central_meridian_deg": central_meridian,
        "offset_from_central_meridian_deg": round(abs(lon - central_meridian), 3),
        "covers_tashkent": bool(within),
    }


# ---------------------------------------------------------------------------
# Step 1 - city boundary and districts
# ---------------------------------------------------------------------------
def overpass_member_relations(relation_id: int) -> list[dict]:
    """Return the admin_level=6 boundary relations that are members of `relation_id`.

    Membership is used instead of a spatial query because a bounding-box query
    also returns Tashkent *region* districts that merely touch the city.
    """
    query = f"[out:json][timeout:{cfg.OVERPASS_TIMEOUT}];rel({relation_id});rel(r);out tags;"
    payload = overpass_post(query, f"member relations of {relation_id}")
    members = [
        {"id": e["id"], "tags": e.get("tags", {})}
        for e in payload["elements"]
        if e.get("tags", {}).get("boundary") == "administrative"
        and e.get("tags", {}).get("admin_level") == "6"
    ]
    if not members:
        raise RuntimeError(f"no admin_level=6 member relations for relation {relation_id}")
    return members


def acquire_boundary_and_districts() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    step("STEP 1  Tashkent city boundary and district boundaries (OSM)")

    city = ox.geocode_to_gdf(f"R{cfg.TASHKENT_CITY_OSM_RELATION}", by_osmid=True)
    city = city.set_crs(cfg.GEOGRAPHIC_CRS, allow_override=True)
    city["osm_type"] = "relation"
    city["osm_id"] = cfg.TASHKENT_CITY_OSM_RELATION
    city["name"] = normalise_name(city.iloc[0].get("name")) or "Toshkent"
    city_metric = city.to_crs(cfg.METRIC_CRS)
    city["area_km2"] = (city_metric.area / 1e6).round(3)
    log(f"  city relation {cfg.TASHKENT_CITY_OSM_RELATION}: "
        f"{city['area_km2'].iloc[0]:.2f} km2, bounds {city.total_bounds.round(4).tolist()}")

    members = overpass_member_relations(cfg.TASHKENT_CITY_OSM_RELATION)
    log(f"  city relation has {len(members)} admin_level=6 member relations")

    frames = []
    for member in members:
        gdf = ox.geocode_to_gdf(f"R{member['id']}", by_osmid=True)
        gdf = gdf.set_crs(cfg.GEOGRAPHIC_CRS, allow_override=True)
        tags = member["tags"]
        gdf["osm_id"] = member["id"]
        gdf["osm_type"] = "relation"
        gdf["osm_name"] = normalise_name(tags.get("name"))
        gdf["osm_name_en"] = normalise_name(tags.get("name:en"))
        gdf["osm_name_ru"] = normalise_name(tags.get("name:ru"))
        gdf["admin_level"] = tags.get("admin_level")
        gdf["osm_start_date"] = tags.get("start_date")
        frames.append(gdf)

    districts = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=cfg.GEOGRAPHIC_CRS)

    # Explicit crosswalk keyed on OSM relation id - no fuzzy string matching.
    osm_to_siat = {
        v["osm_relation"]: {"siat_code": k, "siat_name_en": v["siat_name_en"]}
        for k, v in cfg.SIAT_TO_OSM_DISTRICT.items()
    }
    districts["siat_code"] = districts.osm_id.map(
        lambda i: osm_to_siat.get(i, {}).get("siat_code")
    )
    districts["siat_name_en"] = districts.osm_id.map(
        lambda i: osm_to_siat.get(i, {}).get("siat_name_en")
    )
    districts["in_siat"] = districts.siat_code.notna()
    districts["district_name"] = districts.siat_name_en.fillna(districts.osm_name)

    metric = districts.to_crs(cfg.METRIC_CRS)
    city_geom = city_metric.geometry.iloc[0]
    districts["area_km2"] = (metric.area / 1e6).round(3)
    districts["frac_inside_city"] = (
        metric.geometry.intersection(city_geom).area / metric.area
    ).round(4)
    districts["geometry_valid"] = districts.geometry.is_valid

    districts = districts.sort_values(
        ["in_siat", "district_name"], ascending=[False, True]
    ).reset_index(drop=True)

    log("")
    log(f"  {'district':34s} | in SIAT | area km2 | in city | valid")
    log("  " + "-" * 70)
    for _, row in districts.iterrows():
        log(f"  {str(row.district_name)[:34]:34s} | {str(row.in_siat):7s} | "
            f"{row.area_km2:8.2f} | {row.frac_inside_city:7.4f} | {row.geometry_valid}")

    matched = int(districts.in_siat.sum())
    log("")
    log(f"  districts matched to SIAT : {matched} (expected {cfg.EXPECTED_ANALYSIS_DISTRICTS})")
    log(f"  districts in OSM relation : {len(districts)} (expected {cfg.EXPECTED_OSM_DISTRICTS})")
    log(f"  sum of SIAT-matched areas : {districts[districts.in_siat].area_km2.sum():.2f} km2")
    log(f"  sum of all district areas : {districts.area_km2.sum():.2f} km2")
    log(f"  city boundary area        : {city['area_km2'].iloc[0]:.2f} km2")

    if matched != cfg.EXPECTED_ANALYSIS_DISTRICTS:
        raise RuntimeError(
            f"expected {cfg.EXPECTED_ANALYSIS_DISTRICTS} SIAT-matched districts, got {matched}"
        )
    for _, row in districts[~districts.in_siat].iterrows():
        NOTES.append(
            f"OSM district '{row.osm_name}' (relation {row.osm_id}, "
            f"start_date={row.osm_start_date}, {row.area_km2:.0f} km2) is a member of the "
            f"Tashkent city relation but has no SIAT population row. Kept with in_siat=False."
        )

    write_geojson(city, cfg.BOUNDARY_FILE, ["osm_type", "osm_id", "name", "area_km2"])
    write_geojson(
        districts,
        cfg.DISTRICTS_FILE,
        [
            "osm_type", "osm_id", "osm_name", "osm_name_en", "osm_name_ru",
            "admin_level", "osm_start_date", "siat_code", "siat_name_en",
            "district_name", "in_siat", "area_km2", "frac_inside_city",
        ],
    )
    crosswalk = districts[
        ["osm_id", "osm_name", "osm_name_en", "siat_code", "siat_name_en",
         "district_name", "in_siat"]
    ]
    crosswalk.to_csv(cfg.DISTRICT_NAME_MAP_FILE, index=False, encoding="utf-8")
    log(f"\n  wrote {cfg.BOUNDARY_FILE.name}, {cfg.DISTRICTS_FILE.name}, "
        f"{cfg.DISTRICT_NAME_MAP_FILE.name}")

    record_source(
        "osm_boundaries",
        source="OpenStreetMap (Overpass API / OSMnx)",
        url=f"https://www.openstreetmap.org/relation/{cfg.TASHKENT_CITY_OSM_RELATION}",
        licence="Open Database License (ODbL) v1.0",
        licence_url="https://www.openstreetmap.org/copyright",
        licence_status="verified",
        method="OSMnx geocode_to_gdf(by_osmid=True) + Overpass member-relation query",
        query_rule=(
            "City = relation 2216724. Districts = admin_level=6 boundary relations "
            "that are members of that relation (not a spatial bounding-box query)."
        ),
        crs=cfg.GEOGRAPHIC_CRS,
        outputs=[
            local_file_record(cfg.BOUNDARY_FILE),
            local_file_record(cfg.DISTRICTS_FILE),
            local_file_record(cfg.DISTRICT_NAME_MAP_FILE),
        ],
        feature_counts={
            "city_boundary": 1,
            "districts_total": int(len(districts)),
            "districts_matched_to_siat": matched,
        },
    )
    return city, districts


# ---------------------------------------------------------------------------
# Step 2 - pedestrian network
# ---------------------------------------------------------------------------
def acquire_walk_network(city: gpd.GeoDataFrame) -> dict:
    step("STEP 2  Pedestrian (walk) street network (OSM)")

    buffered = (
        city.to_crs(cfg.METRIC_CRS)
        .geometry.iloc[0]
        .buffer(cfg.NETWORK_BUFFER_M)
    )
    polygon = gpd.GeoSeries([buffered], crs=cfg.METRIC_CRS).to_crs(cfg.GEOGRAPHIC_CRS).iloc[0]
    west, south, east, north = polygon.bounds
    log(f"  downloading walk network for the city bbox + {cfg.NETWORK_BUFFER_M} m buffer")
    log(f"  bbox: {(round(west, 4), round(south, 4), round(east, 4), round(north, 4))}")
    log("  (slowest step; the graph is then truncated to the buffered boundary)")

    # A single Overpass request for the whole ~990 km2 bbox times out on every
    # public mirror. Capping the query area makes OSMnx split it into several
    # smaller requests, each of which completes; the graph timeout is also
    # raised well above the one used for the small point queries.
    ox.settings.max_query_area_size = cfg.MAX_OVERPASS_QUERY_AREA_M2
    ox.settings.requests_timeout = cfg.GRAPH_TIMEOUT

    def download(endpoint: str):
        ox.settings.overpass_url = endpoint
        # OSMnx polls /status when rate limiting is on; the mirrors advertise no
        # slot limit and that polling recurses against them, so only enable it
        # for the main instance.
        ox.settings.overpass_rate_limit = endpoint.startswith("https://overpass-api.de")
        return ox.graph_from_bbox(
            (west, south, east, north), network_type="walk", simplify=True
        )

    graph = overpass_failover(download, "walk network")
    log(f"  downloaded graph: {graph.number_of_nodes():,} nodes, "
        f"{graph.number_of_edges():,} edges (bbox extent)")
    graph = ox.truncate.truncate_graph_polygon(graph, polygon, truncate_by_edge=True)
    n_nodes, n_edges = graph.number_of_nodes(), graph.number_of_edges()
    log(f"  nodes: {n_nodes:,}   edges: {n_edges:,}")

    cfg.WALK_GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(graph, cfg.WALK_GRAPH_FILE)
    size = cfg.file_size_bytes(cfg.WALK_GRAPH_FILE)
    log(f"  saved -> {cfg.WALK_GRAPH_FILE.relative_to(cfg.REPO_ROOT)} ({cfg.human_size(size)})")
    log("  NOT committed to git: rebuildable and far too large; see .gitignore")

    ox.settings.requests_timeout = cfg.OVERPASS_TIMEOUT
    stats = {"nodes": n_nodes, "edges": n_edges, "size_bytes": size}
    record_source(
        "osm_walk_network",
        source="OpenStreetMap (Overpass API / OSMnx)",
        url="https://www.openstreetmap.org/",
        licence="Open Database License (ODbL) v1.0",
        licence_url="https://www.openstreetmap.org/copyright",
        licence_status="verified",
        method=(
            f"osmnx.graph_from_bbox(network_type='walk', simplify=True) over the city "
            f"bbox, then truncated to the city boundary buffered by "
            f"{cfg.NETWORK_BUFFER_M} m"
        ),
        query_rule=(
            "OSMnx 'walk' filter: all highways except motorways and private/no-access "
            "ways; sidewalk and footway detail retained. Buffer avoids truncating "
            "routes at the city edge."
        ),
        crs=cfg.GEOGRAPHIC_CRS,
        storage="data/external (gitignored, rebuilt by this script)",
        outputs=[local_file_record(cfg.WALK_GRAPH_FILE)],
        feature_counts={"nodes": n_nodes, "edges": n_edges},
    )
    return stats


# ---------------------------------------------------------------------------
# Step 6 - SIAT official district population
# ---------------------------------------------------------------------------
def acquire_siat_population() -> pd.DataFrame:
    step("STEP 3  Official district population (SIAT / Statistics Agency)")

    def download(dataset_id: int, api_url: str) -> pd.DataFrame:
        # The download endpoint returns JSON metadata pointing at the real CSV.
        pointer = http_get(api_url).json()
        file_url = pointer.get("file")
        if not file_url:
            raise RuntimeError(f"SIAT dataset {dataset_id} returned no file URL: {pointer}")
        raw_path = cfg.RAW_DIR / f"siat_{dataset_id}.csv"
        raw_path.write_bytes(http_get(file_url).content)
        log(f"  dataset {dataset_id}: {file_url}")
        log(f"    updated_at={pointer.get('updated_at')} size={pointer.get('size')} "
            f"-> {raw_path.relative_to(cfg.REPO_ROOT)}")
        return pd.read_csv(raw_path, encoding="utf-8-sig", dtype={"Code": str})

    urban = download(cfg.SIAT_DATASET_ID, cfg.SIAT_DOWNLOAD_API)
    rural = download(cfg.SIAT_RURAL_DATASET_ID, cfg.SIAT_RURAL_DOWNLOAD_API)

    period = cfg.SIAT_REFERENCE_PERIOD
    if period not in urban.columns:
        raise RuntimeError(f"reference period {period} missing from SIAT dataset "
                           f"{cfg.SIAT_DATASET_ID}; available: {list(urban.columns)}")

    def tashkent_rows(df: pd.DataFrame) -> pd.DataFrame:
        mask = df.Code.str.startswith(cfg.TASHKENT_SOATO) & (df.Code.str.len() > 4)
        return df.loc[mask]

    urban_t = tashkent_rows(urban)
    rural_t = tashkent_rows(rural)

    # Dataset 3890 is the *urban* series. Tashkent city has no rural population,
    # so for this city the urban series is also the total. Prove it rather than
    # assume it.
    rural_total = float(rural_t[period].sum())
    log(f"\n  Tashkent district rural population ({period}): {rural_total} thousand")
    if rural_total != 0:
        raise RuntimeError(
            "Tashkent districts have non-zero rural population; dataset 3890 (urban) "
            "can no longer be treated as the district total."
        )
    log("  -> urban series equals total population for Tashkent city districts")

    records = []
    for code, meta in cfg.SIAT_TO_OSM_DISTRICT.items():
        row = urban_t[urban_t.Code == code]
        if len(row) != 1:
            raise RuntimeError(f"expected exactly 1 SIAT row for {code}, found {len(row)}")
        row = row.iloc[0]
        thousands = float(row[period])
        records.append(
            {
                "siat_code": code,
                "district_name": meta["siat_name_en"],
                "name_uz": normalise_name(row["Klassifikator"]),
                "name_ru": normalise_name(row["Klassifikator_ru"]),
                "name_en_source": normalise_name(row["Klassifikator_en"]),
                "osm_relation": meta["osm_relation"],
                "population": int(round(thousands * 1000)),
                "population_thousands": thousands,
                "reference_period": period,
                "source_dataset": cfg.SIAT_DATASET_ID,
            }
        )

    table = pd.DataFrame(records).sort_values("siat_code").reset_index(drop=True)
    city_row = urban[urban.Code == cfg.TASHKENT_SOATO]
    city_total = float(city_row[period].iloc[0])
    district_sum = table.population_thousands.sum()

    log("")
    log(f"  {'district':26s} {'SOATO':10s} {'population':>12s}")
    log("  " + "-" * 52)
    for _, r in table.iterrows():
        log(f"  {r.district_name:26s} {r.siat_code:10s} {r.population:12,d}")
    log("  " + "-" * 52)
    log(f"  {'sum of districts':26s} {'':10s} {int(round(district_sum * 1000)):12,d}")
    log(f"  {'SIAT city row':26s} {cfg.TASHKENT_SOATO:10s} "
        f"{int(round(city_total * 1000)):12,d}")

    if abs(district_sum - city_total) > 0.05:
        raise RuntimeError(
            f"district populations sum to {district_sum} but the city row is {city_total}"
        )
    log("  -> districts sum exactly to the official city total")

    if table.siat_code.duplicated().any() or table.district_name.duplicated().any():
        raise RuntimeError("duplicate district rows in SIAT extraction")
    if not (table.population > 0).all():
        raise RuntimeError("non-positive population value in SIAT extraction")

    table.to_csv(cfg.SIAT_POPULATION_FILE, index=False, encoding="utf-8")
    log(f"\n  wrote {cfg.SIAT_POPULATION_FILE.name} ({len(table)} rows)")

    record_source(
        "siat_population",
        source="Statistics Agency under the President of the Republic of Uzbekistan (SIAT)",
        url=cfg.SIAT_LANDING_URL,
        api_url=cfg.SIAT_DOWNLOAD_API,
        dataset_id=cfg.SIAT_DATASET_ID,
        dataset_code="2.01.02.0056",
        dataset_title="Permanent population (city)",
        licence="unclear",
        licence_note=(
            "No explicit licence statement found on the SIAT dataset page or portal "
            "footer. Treated as official public statistics used with attribution; "
            "FLAGGED FOR REVIEW before publication."
        ),
        licence_status="unclear",
        method="HTTP GET of the portal CSV download endpoint, then the CSV it points to",
        reference_period=period,
        source_units=cfg.SIAT_UNITS,
        stored_units="persons (source value x 1000)",
        crs=None,
        outputs=[local_file_record(cfg.SIAT_POPULATION_FILE)],
        feature_counts={
            "district_rows": int(len(table)),
            "city_total_persons": int(round(city_total * 1000)),
        },
        verification={
            "districts_sum_equals_city_total": True,
            "tashkent_rural_population": rural_total,
            "urban_series_equals_total": True,
        },
    )
    return table


# ---------------------------------------------------------------------------
# Step 7 - WorldPop raster
# ---------------------------------------------------------------------------
def acquire_worldpop() -> dict:
    step("STEP 4  WorldPop gridded population raster")

    target = cfg.WORLDPOP_RASTER
    if target.exists():
        log(f"  already present: {target.name} ({cfg.human_size(cfg.file_size_bytes(target))})")
    else:
        log(f"  downloading {cfg.WORLDPOP_URL}")
        response = http_get(cfg.WORLDPOP_URL, stream=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                handle.write(chunk)
                written += len(chunk)
                if written % (10 << 20) < (1 << 20):
                    log(f"    {cfg.human_size(written)} ...")
        log(f"  downloaded {cfg.human_size(written)}")

    checksum = cfg.sha256_file(target)
    size = cfg.file_size_bytes(target)
    log(f"  sha256: {checksum}")
    log(f"  size  : {cfg.human_size(size)}")
    log("  NOT committed to git (36 MB, immutable, reproducible); see .gitignore")

    import rasterio  # imported here so the earlier steps do not require it

    with rasterio.open(target) as src:
        info = {
            "crs": str(src.crs),
            "width": src.width,
            "height": src.height,
            "dtype": src.dtypes[0],
            "nodata": None if src.nodata is None else float(src.nodata),
            "bounds": [round(v, 6) for v in src.bounds],
            "pixel_size_deg": [abs(src.transform.a), abs(src.transform.e)],
        }
    approx_m = info["pixel_size_deg"][0] * 111_320
    info["approx_pixel_size_m"] = round(approx_m, 1)
    for key, value in info.items():
        log(f"  {key:20s}: {value}")

    record_source(
        "worldpop",
        source="WorldPop, University of Southampton",
        url=cfg.WORLDPOP_URL,
        landing_page=cfg.WORLDPOP_LANDING,
        doi=cfg.WORLDPOP_DOI,
        product=cfg.WORLDPOP_PRODUCT,
        release=cfg.WORLDPOP_RELEASE,
        product_year=cfg.WORLDPOP_YEAR,
        licence="Creative Commons Attribution 4.0 International (CC BY 4.0)",
        licence_url=cfg.WORLDPOP_LICENCE_URL,
        licence_status="verified",
        method="HTTP GET of the WorldPop data server GeoTIFF (URL from the WorldPop REST API)",
        value_meaning="estimated number of people per grid cell (persons per pixel)",
        crs=info["crs"],
        resolution=f"3 arc-seconds (~{info['approx_pixel_size_m']} m at this latitude)",
        storage="data/external (gitignored, re-downloadable)",
        outputs=[local_file_record(target, checksum=True)],
        raster_profile=info,
    )
    return info


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
def write_manifest(crs_info: dict, extra: dict) -> None:
    """Write the manifest, preserving entries for steps this run skipped.

    A partial run (`--skip`) must not silently delete the provenance of sources
    it did not touch. Each source carries its own `acquired_at_utc`, so a merged
    manifest stays honest about when each piece was actually fetched.
    """
    step("Writing source manifest")

    previous: dict = {}
    if cfg.MANIFEST_PATH.exists():
        try:
            previous = json.loads(cfg.MANIFEST_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log("  ! existing manifest is not valid JSON; rewriting from scratch")

    sources = dict(previous.get("sources", {}))
    carried = [k for k in sources if k not in MANIFEST]
    sources.update(MANIFEST)
    if carried:
        log(f"  carried forward {len(carried)} source record(s) from a previous run: "
            f"{', '.join(sorted(carried))}")

    notes = list(previous.get("notes", []))
    for note in NOTES:
        if note not in notes:
            notes.append(note)

    merged_extra = {
        k: v for k, v in previous.items()
        if k not in {"sources", "notes", "generated_at_utc", "environment",
                     "coordinate_reference_systems", "project", "milestone",
                     "generated_by"}
    }
    merged_extra.update(extra)

    manifest = {
        "project": "STATS 401 - Tashkent Transit & Walkability",
        "milestone": "Week 3 - data foundation",
        "generated_at_utc": utc_now(),
        "generated_by": "scripts/acquire_data.py",
        "coordinate_reference_systems": {
            "storage_geographic": cfg.GEOGRAPHIC_CRS,
            "analysis_metric": crs_info,
        },
        "environment": {
            "python": sys.version.split()[0],
            "geopandas": gpd.__version__,
            "osmnx": ox.__version__,
            "pandas": pd.__version__,
        },
        "sources": sources,
        "notes": notes,
        **merged_extra,
    }
    cfg.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg.MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    log(f"  wrote {cfg.MANIFEST_PATH.relative_to(cfg.REPO_ROOT)}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip",
        nargs="*",
        default=[],
        choices=["network", "worldpop", "osm-poi", "siat"],
        help="skip named steps (useful when iterating)",
    )
    args = parser.parse_args()

    configure_osmnx()
    crs_info = verify_metric_crs()

    city, districts = acquire_boundary_and_districts()

    extra: dict = {}
    if "osm-poi" not in args.skip:
        poi_summary = osmf.acquire_transit_and_poi(city, districts, record_source)
        extra["osm_poi_summary"] = poi_summary
    if "siat" not in args.skip:
        acquire_siat_population()
    if "worldpop" not in args.skip:
        extra["worldpop_profile"] = acquire_worldpop()
    # Last on purpose: it is the slowest step and the most exposed to Overpass
    # outages, so everything else is already on disk if it fails.
    if "network" not in args.skip:
        extra["walk_network"] = acquire_walk_network(city)

    write_manifest(crs_info, extra)

    step("Acquisition complete")
    for note in NOTES:
        log(f"  NOTE: {note}")
    log(f"\n  processed outputs in {cfg.PROCESSED_DIR.relative_to(cfg.REPO_ROOT)}:")
    for path in sorted(cfg.PROCESSED_DIR.glob("*")):
        log(f"    {path.name:38s} {cfg.human_size(cfg.file_size_bytes(path)):>10s}")
    log("\n  Next: python scripts/validate_data.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
