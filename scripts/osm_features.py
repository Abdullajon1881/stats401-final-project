"""Extract metro, bus and bazaar features from OpenStreetMap.

Each extractor follows the same shape:

  1. download a generous candidate set using OSM tags,
  2. classify candidates with an explicit, written-down rule,
  3. clip to the Tashkent city boundary,
  4. deduplicate with a rule that is stated rather than implied,
  5. report raw / filtered / deduplicated / final counts.

Nothing is invented: names are whitespace-normalised but never translated, and
no location is added that OSM does not contain.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

import config as cfg
import overpass_client
from pipeline_utils import (
    NOTES,
    is_latin_name,
    log,
    name_key,
    normalise_name,
    step,
    tag_series,
    to_points,
    write_geojson,
)

# --- Deduplication radii (metres, measured in EPSG:32642) --------------------
# A metro interchange is mapped as one station object per line. Two objects with
# the same name this close together are the same walking access point.
METRO_DUP_RADIUS_M = 200
# Entrances legitimately cluster around one station, so only near-identical
# coordinates are treated as double-mapping.
ENTRANCE_DUP_RADIUS_M = 5
# A stop_position sits on the carriageway and its platform on the kerb, normally
# 10-30 m apart. 50 m covers that pairing without reaching across a road to the
# opposite-direction stop, which is a *different* physical stop and is kept.
BUS_ROLE_PAIR_RADIUS_M = 50
BUS_ROLE_PAIR_RADIUS_UNNAMED_M = 25
# Two objects of the same role this close together are genuine double-mapping.
BUS_COINCIDENT_RADIUS_M = 5
BAZAAR_DUP_RADIUS_M = 100


def _greedy_dedupe(
    gdf: gpd.GeoDataFrame,
    radius_m: float,
    *,
    same_key: bool = True,
    priority: pd.Series | None = None,
) -> tuple[gpd.GeoDataFrame, int]:
    """Keep one feature per cluster of near-coincident features.

    Deterministic: candidates are visited in priority order (then by osm id), and
    a candidate is dropped when an already-kept feature lies within `radius_m`
    (and, when `same_key`, shares its name key).
    """
    if gdf.empty:
        return gdf, 0

    work = gdf.to_crs(cfg.METRIC_CRS).copy()
    work["_priority"] = 0 if priority is None else priority.reindex(work.index).fillna(9)
    work = work.sort_values(["_priority", "osm_id"], kind="stable")

    kept_index: list = []
    kept_geoms: list = []
    kept_keys: list[frozenset] = []
    for idx, row in work.iterrows():
        duplicate = False
        for pos, geom in enumerate(kept_geoms):
            # Two features are the same place when they share ANY name variant
            # (name / name:en / name:ru). OSM maps several Tashkent stations
            # twice, once in Latin and once in Cyrillic; only the transliterated
            # variants reveal that they are one station.
            if same_key and not (kept_keys[pos] & row["name_keys"]):
                continue
            if row.geometry.distance(geom) <= radius_m:
                duplicate = True
                break
        if not duplicate:
            kept_index.append(idx)
            kept_geoms.append(row.geometry)
            kept_keys.append(row["name_keys"])

    removed = len(work) - len(kept_index)
    return gdf.loc[kept_index].copy(), removed


def _download(bbox, selectors, description: str) -> gpd.GeoDataFrame:
    """Fetch OSM elements matching any of `selectors` within the city bbox.

    A bbox query is used rather than a polygon query because the Tashkent city
    boundary has thousands of vertices; embedding it in Overpass QL produces a
    query large enough to stall the public mirrors. Anything outside the true
    boundary is clipped in `_prepare`.
    """
    return overpass_client.fetch(bbox, selectors, description)


def _prepare(gdf: gpd.GeoDataFrame, city_geom_metric, label: str) -> gpd.GeoDataFrame:
    """Reduce to points, normalise the name, and clip to the city boundary."""
    gdf = to_points(gdf).set_crs(cfg.GEOGRAPHIC_CRS, allow_override=True)
    gdf["name"] = tag_series(gdf, "name").map(normalise_name)
    gdf["name_key"] = gdf["name"].map(name_key)
    # All name variants OSM provides, used only for duplicate detection.
    variants = [tag_series(gdf, c) for c in ("name", "name:en", "name:ru")]
    gdf["name_keys"] = [
        frozenset(k for k in (name_key(v) for v in values) if k)
        for values in zip(*variants)
    ]

    metric = gdf.to_crs(cfg.METRIC_CRS)
    inside = metric.geometry.within(city_geom_metric)
    outside = int((~inside).sum())
    if outside:
        log(f"    dropped {outside} {label} outside the Tashkent city boundary")
    return gdf.loc[inside.values].copy()


def _attach_district(gdf: gpd.GeoDataFrame, districts: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Label each point with its district.

    Tashkent's district boundaries follow major roads, and bus stops sit on those
    roads, so a meaningful number of points land exactly *on* a shared border.
    Such a point is inside neither polygon under a `within` test and would be
    left unassigned. Those are resolved to the nearest district instead, chosen
    alphabetically when two are equidistant so the result is deterministic, and
    flagged in `district_assignment` so the choice stays visible.
    """
    if gdf.empty:
        gdf["district_name"] = pd.Series(dtype="object")
        gdf["district_assignment"] = pd.Series(dtype="object")
        return gdf

    left = gdf.to_crs(cfg.METRIC_CRS)
    right = districts.to_crs(cfg.METRIC_CRS)[["district_name", "geometry"]]

    joined = gpd.sjoin(left, right, how="left", predicate="within")
    joined = joined[~joined.index.duplicated(keep="first")]
    assigned = joined["district_name"].reindex(gdf.index)
    assignment = pd.Series("within", index=gdf.index, dtype="object")

    missing = assigned.isna()
    if missing.any():
        nearest = gpd.sjoin_nearest(
            left.loc[missing, ["geometry"]], right, how="left", distance_col="_dist"
        )
        # Two districts are equidistant for a point on their shared border; sort
        # so the same one always wins.
        nearest = nearest.sort_values(["_dist", "district_name"], kind="stable")
        nearest = nearest[~nearest.index.duplicated(keep="first")]
        assigned.loc[missing] = nearest["district_name"].reindex(assigned.loc[missing].index)
        assignment.loc[missing] = "boundary_nearest"
        log(f"    {int(missing.sum())} feature(s) lay exactly on a district border; "
            f"assigned to the nearest district")

    out = gdf.copy()
    out["district_name"] = assigned
    out["district_assignment"] = assignment
    return out


# ---------------------------------------------------------------------------
# Metro
# ---------------------------------------------------------------------------
def extract_metro(bbox, city_geom_metric, districts) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, dict]:
    log("\n-- Metro stations and entrances --")
    selectors = [
        ("railway", "station"),
        ("railway", "halt"),
        ("railway", "subway_entrance"),
        ("station", "subway"),
        ("subway", "yes"),
        ("public_transport", "station"),
    ]
    raw = _download(bbox, selectors, "metro candidates")
    log(f"    raw metro-related OSM objects returned: {len(raw)}")
    if raw.empty:
        raise RuntimeError("Overpass returned no metro candidates for Tashkent")

    railway = tag_series(raw, "railway")
    station_tag = tag_series(raw, "station")
    subway_tag = tag_series(raw, "subway")
    public_transport = tag_series(raw, "public_transport")

    log("    tag breakdown of candidates:")
    for column, series in (
        ("railway", railway), ("station", station_tag),
        ("subway", subway_tag), ("public_transport", public_transport),
    ):
        counts = series.value_counts(dropna=True).head(6).to_dict()
        log(f"      {column:18s}: {counts}")

    # Rule: a station is any object tagged station=subway or subway=yes that is
    # not an entrance. railway=station alone is NOT enough - Tashkent's main
    # railway terminal carries that tag and is not a metro station.
    is_entrance = railway.eq("subway_entrance")
    is_metro = (station_tag.eq("subway") | subway_tag.eq("yes")) & ~is_entrance

    stations_raw = raw.loc[is_metro.fillna(False).values].copy()
    entrances_raw = raw.loc[is_entrance.fillna(False).values].copy()
    log(f"    classified as metro stations : {len(stations_raw)}")
    log(f"    classified as metro entrances: {len(entrances_raw)}")

    excluded = int((~is_metro.fillna(False) & ~is_entrance.fillna(False)).sum())
    log(f"    excluded (non-metro rail / other): {excluded}")

    stations = _prepare(stations_raw, city_geom_metric, "metro stations")
    entrances = _prepare(entrances_raw, city_geom_metric, "metro entrances")
    log(f"    inside city -> stations {len(stations)}, entrances {len(entrances)}")

    # Which of two duplicate objects survives: a node beats a way/area, and a
    # Latin name beats a Cyrillic one so the output is internally consistent.
    # Both alternatives are real OSM names; neither is transliterated here.
    priority = pd.Series(
        [
            (0 if element == "node" else 2) + (0 if is_latin_name(nm) else 1)
            for element, nm in zip(stations["osm_element"], stations["name"])
        ],
        index=stations.index,
    )
    stations, station_dupes = _greedy_dedupe(
        stations, METRO_DUP_RADIUS_M, same_key=True, priority=priority
    )
    entrances, entrance_dupes = _greedy_dedupe(
        entrances, ENTRANCE_DUP_RADIUS_M, same_key=False
    )
    log(f"    duplicates removed -> stations {station_dupes}, entrances {entrance_dupes}")

    for gdf, extra in ((stations, True), (entrances, False)):
        gdf["line"] = tag_series(gdf, "line").map(normalise_name)
        gdf["network"] = tag_series(gdf, "network").map(normalise_name)
        gdf["operator"] = tag_series(gdf, "operator").map(normalise_name)
        gdf["name_ru"] = tag_series(gdf, "name:ru").map(normalise_name)
        gdf["name_en"] = tag_series(gdf, "name:en").map(normalise_name)
        if extra:
            gdf["station_tag"] = tag_series(gdf, "station")
            gdf["subway_tag"] = tag_series(gdf, "subway")
        else:
            gdf["railway"] = tag_series(gdf, "railway")

    stations = _attach_district(stations, districts)
    entrances = _attach_district(entrances, districts)

    # Which stations have no mapped entrance within 400 m?
    if not entrances.empty:
        s_m = stations.to_crs(cfg.METRIC_CRS)
        e_m = entrances.to_crs(cfg.METRIC_CRS)
        joined = gpd.sjoin_nearest(
            s_m, e_m[["geometry"]], how="left", max_distance=400, distance_col="_d"
        )
        with_entrance = joined[joined["_d"].notna()].index.unique()
        without = [n for i, n in stations["name"].items() if i not in set(with_entrance)]
    else:
        without = list(stations["name"])
    log(f"    stations with no mapped entrance within 400 m: {len(without)}")
    if without:
        preview = ", ".join(str(n) for n in without[:12])
        log(f"      {preview}{' ...' if len(without) > 12 else ''}")

    unnamed = int(stations["name"].isna().sum())
    if unnamed:
        NOTES.append(f"{unnamed} metro station(s) have no name tag in OSM.")

    station_cols = [
        "osm_element", "osm_id", "name", "name_en", "name_ru", "line", "network",
        "operator", "station_tag", "subway_tag", "district_name", "district_assignment",
    ]
    entrance_cols = [
        "osm_element", "osm_id", "name", "name_en", "name_ru", "railway", "district_name",
        "district_assignment",
    ]
    write_geojson(stations, cfg.METRO_STATIONS_FILE, station_cols)
    write_geojson(entrances, cfg.METRO_ENTRANCES_FILE, entrance_cols)
    log(f"    wrote {cfg.METRO_STATIONS_FILE.name} ({len(stations)}) and "
        f"{cfg.METRO_ENTRANCES_FILE.name} ({len(entrances)})")

    stats = {
        "raw_candidates": int(len(raw)),
        "classified_stations": int(len(stations_raw)),
        "classified_entrances": int(len(entrances_raw)),
        "excluded_non_metro": excluded,
        "station_duplicates_removed": station_dupes,
        "entrance_duplicates_removed": entrance_dupes,
        "final_stations": int(len(stations)),
        "final_entrances": int(len(entrances)),
        "stations_without_entrance_within_400m": len(without),
        "unique_station_names": int(stations["name"].nunique(dropna=True)),
    }
    return stations, entrances, stats


# ---------------------------------------------------------------------------
# Bus stops
# ---------------------------------------------------------------------------
def extract_bus_stops(bbox, city_geom_metric, districts) -> tuple[gpd.GeoDataFrame, dict]:
    log("\n-- Bus stops --")
    selectors = [
        ("highway", "bus_stop"),
        ("public_transport", "platform"),
        ("public_transport", "stop_position"),
        ("bus", "yes"),
    ]
    raw = _download(bbox, selectors, "bus-stop candidates")
    log(f"    raw candidate objects returned: {len(raw)}")
    if raw.empty:
        raise RuntimeError("Overpass returned no bus-stop candidates for Tashkent")

    highway = tag_series(raw, "highway")
    public_transport = tag_series(raw, "public_transport")
    bus = tag_series(raw, "bus")
    railway = tag_series(raw, "railway")
    train = tag_series(raw, "train")
    subway = tag_series(raw, "subway")
    tram = tag_series(raw, "tram")

    log("    tag breakdown of candidates:")
    for column, series in (
        ("highway", highway), ("public_transport", public_transport),
        ("bus", bus), ("railway", railway),
    ):
        log(f"      {column:18s}: {series.value_counts(dropna=True).head(6).to_dict()}")

    # Rule: keep highway=bus_stop, or a public_transport platform/stop_position
    # that is explicitly bus=yes. Drop anything that is really a rail, metro or
    # tram platform - those share the public_transport tags.
    is_bus = highway.eq("bus_stop") | (
        public_transport.isin(["platform", "stop_position"]) & bus.eq("yes")
    )
    is_rail = (
        railway.notna() | train.eq("yes") | subway.eq("yes") | tram.eq("yes")
    ) & ~highway.eq("bus_stop")
    keep = is_bus.fillna(False) & ~is_rail.fillna(False)

    candidates = raw.loc[keep.values].copy()
    log(f"    classified as bus stops: {len(candidates)} "
        f"(dropped {int((~keep).sum())} non-bus / rail objects)")

    stops = _prepare(candidates, city_geom_metric, "bus stops")
    log(f"    inside city: {len(stops)}")
    before_dedupe = len(stops)

    highway_s = tag_series(stops, "highway")
    pt_s = tag_series(stops, "public_transport")
    # role: 0 = kerbside platform / bus_stop (preferred), 1 = on-carriageway node
    role = pd.Series(
        [
            0 if (h == "bus_stop" or p == "platform") else 1
            for h, p in zip(highway_s, pt_s)
        ],
        index=stops.index,
    )
    stops["stop_role"] = role.map({0: "platform", 1: "stop_position"})

    # Rule A: a stop_position paired with a nearby platform of the same name is
    # the same physical stop -> drop the stop_position.
    platforms = stops[role.eq(0)]
    positions = stops[role.eq(1)]
    paired_removed = 0
    if not platforms.empty and not positions.empty:
        plat_m = platforms.to_crs(cfg.METRIC_CRS)
        pos_m = positions.to_crs(cfg.METRIC_CRS)
        drop: list = []
        for idx, row in pos_m.iterrows():
            named = bool(row["name_keys"])
            radius = BUS_ROLE_PAIR_RADIUS_M if named else BUS_ROLE_PAIR_RADIUS_UNNAMED_M
            near = plat_m[plat_m.geometry.distance(row.geometry) <= radius]
            if named:
                near = near[near["name_keys"].map(lambda k: bool(k & row["name_keys"]))]
            if not near.empty:
                drop.append(idx)
        paired_removed = len(drop)
        stops = stops.drop(index=drop)
    log(f"    rule A - stop_position paired with a platform: {paired_removed} removed")

    # Rule B: two objects of the same role, same name, within 5 m are genuine
    # double-mapping. Opposite-side stops are both platforms and stay separate.
    coincident_removed = 0
    kept_frames = []
    for role_name, group in stops.groupby("stop_role", dropna=False):
        deduped, removed = _greedy_dedupe(group, BUS_COINCIDENT_RADIUS_M, same_key=True)
        coincident_removed += removed
        kept_frames.append(deduped)
    stops = gpd.GeoDataFrame(pd.concat(kept_frames), crs=cfg.GEOGRAPHIC_CRS)
    log(f"    rule B - coincident same-role duplicates: {coincident_removed} removed")

    stops["highway"] = highway_s.reindex(stops.index)
    stops["public_transport"] = pt_s.reindex(stops.index)
    stops["bus"] = tag_series(stops, "bus")
    stops["operator"] = tag_series(stops, "operator").map(normalise_name)
    stops["name_ru"] = tag_series(stops, "name:ru").map(normalise_name)
    stops = _attach_district(stops, districts)

    unnamed = int(stops["name"].isna().sum())
    log(f"    final bus stops: {len(stops)}  ({unnamed} without a name tag)")
    if unnamed:
        NOTES.append(
            f"{unnamed} of {len(stops)} bus stops have no name tag in OSM; they are kept "
            f"because an unnamed stop is still a physical access point."
        )

    write_geojson(
        stops,
        cfg.BUS_STOPS_FILE,
        ["osm_element", "osm_id", "name", "name_ru", "highway", "public_transport",
         "bus", "stop_role", "operator", "district_name", "district_assignment"],
    )
    log(f"    wrote {cfg.BUS_STOPS_FILE.name}")

    stats = {
        "raw_candidates": int(len(raw)),
        "classified_as_bus": int(len(candidates)),
        "inside_city": before_dedupe,
        "removed_stop_position_paired_with_platform": paired_removed,
        "removed_coincident_same_role": coincident_removed,
        "final_bus_stops": int(len(stops)),
        "without_name": unnamed,
    }
    return stops, stats


# ---------------------------------------------------------------------------
# Bazaars
# ---------------------------------------------------------------------------
def extract_bazaars(bbox, city_geom_metric, districts) -> tuple[gpd.GeoDataFrame, dict]:
    log("\n-- Bazaars / marketplaces --")
    raw = _download(bbox, [("amenity", "marketplace")], "marketplace candidates")
    log(f"    raw amenity=marketplace objects returned: {len(raw)}")
    if raw.empty:
        NOTES.append("OSM returned no amenity=marketplace features for Tashkent.")
        return raw, {"raw_candidates": 0, "final_bazaars": 0}

    element_counts = raw.get("osm_element", pd.Series(dtype=object)).value_counts().to_dict()
    log(f"    element types: {element_counts}")

    bazaars = _prepare(raw, city_geom_metric, "marketplaces")
    log(f"    inside city: {len(bazaars)}")

    # A bazaar is commonly mapped as a polygon plus a node inside it. Same name
    # within 100 m is treated as one marketplace; the polygon wins.
    priority = pd.Series(
        [1 if e == "node" else 0 for e in bazaars.get("osm_element", pd.Series(dtype=object))],
        index=bazaars.index,
    )
    bazaars, removed = _greedy_dedupe(
        bazaars, BAZAAR_DUP_RADIUS_M, same_key=True, priority=priority
    )
    log(f"    duplicates removed: {removed}")

    bazaars["amenity"] = tag_series(bazaars, "amenity")
    bazaars["name_ru"] = tag_series(bazaars, "name:ru").map(normalise_name)
    bazaars["operator"] = tag_series(bazaars, "operator").map(normalise_name)
    bazaars = _attach_district(bazaars, districts)

    unnamed = int(bazaars["name"].isna().sum())
    log(f"    final bazaars: {len(bazaars)}  ({unnamed} without a name tag)")
    named = [n for n in bazaars["name"].dropna().tolist()]
    log(f"    names: {', '.join(named[:20])}{' ...' if len(named) > 20 else ''}")

    NOTES.append(
        "Bazaar coverage rests on amenity=marketplace only. Smaller informal markets "
        "are very likely missing from OSM; the count is a lower bound, not a census."
    )

    write_geojson(
        bazaars,
        cfg.BAZAARS_FILE,
        ["osm_element", "osm_id", "name", "name_ru", "amenity", "operator", "district_name",
         "district_assignment"],
    )
    log(f"    wrote {cfg.BAZAARS_FILE.name}")

    return bazaars, {
        "raw_candidates": int(len(raw)),
        "duplicates_removed": removed,
        "final_bazaars": int(len(bazaars)),
        "without_name": unnamed,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def acquire_transit_and_poi(city, districts, record_source) -> dict:
    from pipeline_utils import local_file_record

    step("STEP 2  Metro, bus and bazaar features (OSM)")
    west, south, east, north = city.to_crs(cfg.GEOGRAPHIC_CRS).total_bounds
    bbox = (float(west), float(south), float(east), float(north))
    city_geom_metric = city.to_crs(cfg.METRIC_CRS).geometry.iloc[0]
    log(f"  querying Overpass over bbox {tuple(round(v, 4) for v in bbox)}; "
        f"features are then clipped to the exact city boundary")

    stations, entrances, metro_stats = extract_metro(bbox, city_geom_metric, districts)
    stops, bus_stats = extract_bus_stops(bbox, city_geom_metric, districts)
    bazaars, bazaar_stats = extract_bazaars(bbox, city_geom_metric, districts)

    osm_licence = {
        "licence": "Open Database License (ODbL) v1.0",
        "licence_url": "https://www.openstreetmap.org/copyright",
        "licence_status": "verified",
        "source": "OpenStreetMap (Overpass API / OSMnx)",
        "url": "https://www.openstreetmap.org/",
        "crs": cfg.GEOGRAPHIC_CRS,
    }
    record_source(
        "osm_metro",
        **osm_licence,
        method="Overpass QL union query over the city bbox (out center), clipped to the city boundary",
        query_rule=(
            "Candidates: railway in (station, halt, subway_entrance), station=subway, "
            "subway=yes, public_transport=station. Station = (station=subway OR "
            "subway=yes) AND NOT railway=subway_entrance. Entrance = "
            "railway=subway_entrance. railway=station alone is rejected so the "
            "national railway terminal is not counted as a metro station."
        ),
        dedupe_rule=(
            f"Two station objects within {METRO_DUP_RADIUS_M} m that share any name "
            f"variant (name / name:en / name:ru) are one station. This merges the "
            f"Latin+Cyrillic double-mappings that OSM carries for several Tashkent "
            f"stations while keeping genuine interchanges (Oybek/Mingo'rik, "
            f"Paxtakor/Alisher Navoiy, Amir Temur xiyoboni/Yunus Rajabiy, "
            f"Do'stlik/Texnopark) separate. A node beats a way; a Latin name beats a "
            f"Cyrillic one. Entrances within {ENTRANCE_DUP_RADIUS_M} m collapse "
            f"regardless of name."
        ),
        outputs=[
            local_file_record(cfg.METRO_STATIONS_FILE),
            local_file_record(cfg.METRO_ENTRANCES_FILE),
        ],
        feature_counts=metro_stats,
    )
    record_source(
        "osm_bus_stops",
        **osm_licence,
        method="Overpass QL union query over the city bbox (out center), clipped to the city boundary",
        query_rule=(
            "Candidates: highway=bus_stop, public_transport in (platform, "
            "stop_position), bus=yes. Kept when highway=bus_stop OR "
            "(public_transport in (platform, stop_position) AND bus=yes); rail, "
            "metro and tram platforms are excluded."
        ),
        dedupe_rule=(
            f"Rule A: a stop_position within {BUS_ROLE_PAIR_RADIUS_M} m of a "
            f"platform sharing any name variant ({BUS_ROLE_PAIR_RADIUS_UNNAMED_M} m when unnamed) "
            f"is dropped as the same physical stop. Rule B: same-role, same-name "
            f"objects within {BUS_COINCIDENT_RADIUS_M} m collapse. Stops on opposite "
            f"sides of a road are both platforms and are deliberately kept separate."
        ),
        outputs=[local_file_record(cfg.BUS_STOPS_FILE)],
        feature_counts=bus_stats,
    )
    record_source(
        "osm_bazaars",
        **osm_licence,
        method="Overpass QL union query over the city bbox (out center), clipped to the city boundary",
        query_rule="amenity=marketplace only; no other tag is treated as a bazaar.",
        dedupe_rule=(
            f"Same normalised name within {BAZAAR_DUP_RADIUS_M} m collapses to one "
            f"marketplace; the polygon is preferred over a node inside it."
        ),
        outputs=[local_file_record(cfg.BAZAARS_FILE)],
        feature_counts=bazaar_stats,
    )

    return {"metro": metro_stats, "bus": bus_stats, "bazaars": bazaar_stats}
