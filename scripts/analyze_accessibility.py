"""Week 4: pedestrian-network accessibility analysis for Tashkent.

    python scripts/analyze_accessibility.py

Turns the validated Week 3 datasets into district and city access metrics:

  * analysis boundary = the union of the 12 SIAT-matched districts
  * metro access points = mapped entrances, with a documented station fallback
  * EDGE-AWARE network distances: transit sources are spliced into the walk
    edges they stand beside, and population cells are queried at their own
    positions along the edges they stand beside
  * WorldPop cells calibrated to official SIAT totals district by district
  * classification into metro / bus-only / underserved at 10 minutes
  * walking-speed and population-surface sensitivity
  * a display-only service-area polygon, also edge-aware

Why edge-aware. An earlier Week 4 implementation snapped both transit points
and population cells to the nearest graph VERTEX. The OSM walk graph is
simplified, so its vertices sit at intersections rather than continuously along
every path: a cell beside the middle of a long edge was charged the walk to the
end of that edge. On this graph the median cell was 39.6 m from a vertex but the
99th percentile was 367.5 m and the worst was 905.9 m, against a headline budget
of 800 m. That artefact could decide the 10-minute answer on its own, so the
model was rebuilt before any result was merged.

Results are PRELIMINARY until independently audited. This script measures
physical walking access only - not frequency, span, transfers, in-vehicle time,
reliability, crowding or fare.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))

import accessibility_utils as au  # noqa: E402
import config as cfg  # noqa: E402
from pipeline_utils import log, step  # noqa: E402

ANALYSIS_VERSION = "week4.2-edge-aware"
SNAPPING_METHOD = "edge-aware"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def load_districts() -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    districts = gpd.read_file(cfg.DISTRICTS_FILE)
    analysis = districts[districts.in_siat.astype(bool)].copy()
    analysis = analysis.sort_values("district_name").reset_index(drop=True)
    if len(analysis) != cfg.EXPECTED_ANALYSIS_DISTRICTS:
        raise ValueError(
            f"expected {cfg.EXPECTED_ANALYSIS_DISTRICTS} SIAT districts, got {len(analysis)}"
        )
    population = pd.read_csv(cfg.SIAT_POPULATION_FILE, dtype={"siat_code": str})
    population = population.sort_values("district_name").reset_index(drop=True)
    return analysis, population


def write_analysis_boundary(districts: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, float]:
    """The union of the 12 SIAT districts: the population denominator boundary.

    Yangi Toshkent is deliberately outside it - it has no SIAT population row,
    so there is nothing to calibrate its WorldPop cells against.
    """
    step("STEP 1  Analysis boundary")
    metric = districts.to_crs(cfg.METRIC_CRS)
    union = metric.union_all()
    area_km2 = float(union.area / 1e6)
    boundary = gpd.GeoDataFrame(
        {
            "name": ["Tashkent analysis boundary (12 SIAT districts)"],
            "district_count": [len(districts)],
            "area_km2": [round(area_km2, 4)],
            "excludes": ["Yangi Toshkent Tumani (no SIAT population row)"],
        },
        geometry=[union],
        crs=cfg.METRIC_CRS,
    ).to_crs(cfg.GEOGRAPHIC_CRS)
    if cfg.ANALYSIS_BOUNDARY_FILE.exists():
        cfg.ANALYSIS_BOUNDARY_FILE.unlink()
    boundary.to_file(cfg.ANALYSIS_BOUNDARY_FILE, driver="GeoJSON")
    log(f"  districts: {len(districts)}   area: {area_km2:,.2f} km2")
    log(f"  wrote {cfg.ANALYSIS_BOUNDARY_FILE.name}")
    return boundary, area_km2


# ---------------------------------------------------------------------------
# Metro access points
# ---------------------------------------------------------------------------
def build_metro_access_points() -> tuple[gpd.GeoDataFrame, pd.DataFrame, dict]:
    """Entrances are the access points; a station falls back to its own point.

    Entering the metro means walking to an entrance. Using every station centre
    as well would make deep stations artificially easy to reach, so a station
    contributes its own point only when no mapped entrance is associated with it.
    The association radius is an assumption carried over unchanged from the
    first implementation; the counts below are derived from the data, never
    hard-coded.
    """
    step("STEP 2  Metro access points")
    stations = gpd.read_file(cfg.METRO_STATIONS_FILE).sort_values("osm_id").reset_index(drop=True)
    entrances = gpd.read_file(cfg.METRO_ENTRANCES_FILE).sort_values("osm_id").reset_index(drop=True)
    log(f"  stations: {len(stations)}   mapped entrances: {len(entrances)}")

    stations_m = stations.to_crs(cfg.METRIC_CRS)
    entrances_m = entrances.to_crs(cfg.METRIC_CRS)
    station_xy = np.column_stack([stations_m.geometry.x, stations_m.geometry.y])
    entrance_xy = np.column_stack([entrances_m.geometry.x, entrances_m.geometry.y])

    tree = cKDTree(entrance_xy)
    nearest_dist, nearest_idx = tree.query(station_xy, k=1)
    radius = cfg.ENTRANCE_ASSOCIATION_RADIUS_M
    has_entrance = nearest_dist <= radius

    log(f"  association radius: {radius:.0f} m")
    log(f"  stations with an associated mapped entrance: {int(has_entrance.sum())}")
    log(f"  stations needing a fallback point         : {int((~has_entrance).sum())}")

    records = []
    for i, row in entrances.iterrows():
        geom = entrances_m.geometry.iloc[i]
        records.append({
            "access_id": f"entrance:{int(row.osm_id)}",
            "access_type": "entrance",
            "source_osm_id": int(row.osm_id),
            "source_osm_element": row.get("osm_element"),
            "name": row.get("name"),
            "district_name": row.get("district_name"),
            "nearest_entrance_distance_m": 0.0,
            "fallback_reason": None,
            "x_m": float(geom.x),
            "y_m": float(geom.y),
        })
    for i, row in stations.iterrows():
        if has_entrance[i]:
            continue
        geom = stations_m.geometry.iloc[i]
        records.append({
            "access_id": f"station:{int(row.osm_id)}",
            "access_type": "station_fallback",
            "source_osm_id": int(row.osm_id),
            "source_osm_element": row.get("osm_element"),
            "name": row.get("name"),
            "district_name": row.get("district_name"),
            "nearest_entrance_distance_m": float(nearest_dist[i]),
            "fallback_reason": (
                f"no mapped railway=subway_entrance within {radius:.0f} m "
                f"(nearest is {nearest_dist[i]:.0f} m away)"
            ),
            "x_m": float(geom.x),
            "y_m": float(geom.y),
        })

    table = pd.DataFrame(records).sort_values(["access_type", "access_id"]).reset_index(drop=True)

    fallbacks = table[table.access_type == "station_fallback"]
    if len(fallbacks):
        log("  fallback stations:")
        for _, row in fallbacks.iterrows():
            log(f"    {str(row['name'])[:26]:26s} nearest entrance "
                f"{row.nearest_entrance_distance_m:8.0f} m")

    points = gpd.GeoDataFrame(
        table,
        geometry=gpd.points_from_xy(table.x_m, table.y_m),
        crs=cfg.METRIC_CRS,
    )
    stats = {
        "stations_total": int(len(stations)),
        "entrances_total": int(len(entrances)),
        "association_radius_m": radius,
        "stations_with_entrance": int(has_entrance.sum()),
        "stations_fallback": int((~has_entrance).sum()),
        "fallback_station_names": sorted(
            str(n) for n in fallbacks["name"].fillna("(unnamed)").tolist()
        ),
        "access_points_total": int(len(table)),
    }
    log(f"  metro access points: {len(table)} "
        f"({stats['entrances_total']} entrances + {stats['stations_fallback']} fallback)")
    return points, table, stats


def load_bus_points() -> gpd.GeoDataFrame:
    stops = gpd.read_file(cfg.BUS_STOPS_FILE).sort_values("osm_id").reset_index(drop=True)
    return stops.to_crs(cfg.METRIC_CRS)


# ---------------------------------------------------------------------------
# Edge-aware mode setup
# ---------------------------------------------------------------------------
def prepare_mode(
    network: au.WalkNetwork,
    tree,
    points: gpd.GeoDataFrame,
    label: str,
    *,
    want_predecessors: bool = False,
):
    """Snap a mode's access points to edges, splice them in, run one Dijkstra."""
    xy = np.column_stack([points.geometry.x, points.geometry.y])
    snap = au.snap_points_to_edges(network, xy, tree=tree)
    diagnostics = au.connector_diagnostics(label, snap.connector_m)
    placement = au.snap_placement_stats(
        snap, network, endpoint_tol_m=cfg.EDGE_ENDPOINT_TOLERANCE_M
    )

    log(f"  {label}: n={diagnostics['count']}  min={diagnostics['min_m']:.1f}  "
        f"mean={diagnostics['mean_m']:.1f}  median={diagnostics['median_m']:.1f}  "
        f"p95={diagnostics['p95_m']:.1f}  p99={diagnostics['p99_m']:.1f}  "
        f"max={diagnostics['max_m']:.1f} m  (to the nearest walkable EDGE)")

    worst = np.argsort(snap.connector_m)[-5:][::-1]
    log(f"    largest {label} off-network connectors:")
    for i in worst:
        row = points.iloc[int(i)]
        log(f"      {snap.connector_m[i]:8.1f} m  {str(row.get('name'))[:38]:38s} "
            f"{str(row.get('district_name'))[:22]}")

    aug = au.build_augmented_network(network, snap)
    log(f"    spliced into the network: {placement['inserted_in_edge_interior']} in edge "
        f"interiors, {placement['effectively_at_an_endpoint']} at existing endpoints, "
        f"over {placement['distinct_edges_containing_sources']} distinct canonical edges")
    log(f"    augmented nodes {aug.stats['augmented_nodes_total']:,} "
        f"(+{aug.stats['augmented_nodes_added']:,})   "
        f"routing segments {aug.stats['augmented_routing_edges']:,} "
        f"(canonical edges {aug.stats['canonical_routing_edges']:,})")

    result = au.multi_source_distances(
        network, aug, snap.connector_m, return_predecessors=want_predecessors
    )
    if want_predecessors:
        node_distance, predecessors, super_source = result
    else:
        node_distance, predecessors, super_source = result, None, None

    reachable = np.isfinite(node_distance)
    log(f"    augmented nodes reachable from {label}: {int(reachable.sum()):,} / "
        f"{node_distance.size:,} ({reachable.mean():.2%})")
    diagnostics["augmented_nodes_reachable"] = int(reachable.sum())
    diagnostics["augmented_nodes_total"] = int(node_distance.size)

    return snap, aug, node_distance, diagnostics, placement, predecessors, super_source


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------
def classify(cells: pd.DataFrame, speed_kmh: float) -> pd.DataFrame:
    """Assign every cell to exactly one access category at a given speed.

    Times are compared unrounded. Categories are mutually exclusive by
    construction: bus-only requires the metro test to have failed, and
    underserved requires both to have failed.
    """
    speed_ms = cfg.kmh_to_ms(speed_kmh)
    limit = cfg.WALK_TIME_LIMIT_SECONDS
    metro_time = cells.metro_distance_m / speed_ms
    bus_time = cells.bus_distance_m / speed_ms

    metro_ok = metro_time <= limit
    bus_ok = bus_time <= limit
    out = pd.DataFrame(
        {
            "metro_access": metro_ok,
            "bus_only": (~metro_ok) & bus_ok,
            "underserved": (~metro_ok) & (~bus_ok),
        },
        index=cells.index,
    )
    overlap = (out.metro_access.astype(int) + out.bus_only.astype(int)
               + out.underserved.astype(int))
    if not (overlap == 1).all():
        raise ValueError("access categories are not a partition")
    return out


def aggregate(cells: pd.DataFrame, flags: pd.DataFrame, by: str | None) -> pd.DataFrame:
    frame = pd.DataFrame({
        "population": cells.population,
        "metro": cells.population.where(flags.metro_access, 0.0),
        "bus_only": cells.population.where(flags.bus_only, 0.0),
        "underserved": cells.population.where(flags.underserved, 0.0),
    })
    if by is None:
        totals = frame.sum().to_frame().T
        totals.insert(0, "scope", "city")
        return totals
    frame[by] = cells[by]
    grouped = frame.groupby(by, sort=True).sum().reset_index()
    return grouped


def with_percentages(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    total = out.population.replace(0, np.nan)
    out["metro_pct"] = (out.metro / total * 100).fillna(0.0)
    out["bus_only_pct"] = (out.bus_only / total * 100).fillna(0.0)
    out["underserved_pct"] = (out.underserved / total * 100).fillna(0.0)
    out["combined_pct"] = out.metro_pct + out.bus_only_pct
    return out


def attach_distances(
    cells: pd.DataFrame,
    network: au.WalkNetwork,
    tree,
    metro: tuple,
    bus: tuple,
) -> tuple[pd.DataFrame, dict]:
    """Snap population cells to edges and read off both modes' distances.

    The cell's own off-network connector is added once, on top of a network
    distance that already contains the source's connector.
    """
    cell_xy = np.column_stack([cells.x_m.to_numpy(), cells.y_m.to_numpy()])
    snap = au.snap_points_to_edges(network, cell_xy, tree=tree)
    diagnostics = au.connector_diagnostics("population_cells", snap.connector_m)

    metro_aug, metro_dist = metro
    bus_aug, bus_dist = bus

    out = cells.copy()
    out["edge_index"] = snap.edge_index
    out["edge_fraction"] = snap.fraction
    out["edge_connector_m"] = snap.connector_m
    out["metro_distance_m"] = snap.connector_m + au.query_positions(
        metro_aug, metro_dist, snap.edge_index, snap.fraction
    )
    out["bus_distance_m"] = snap.connector_m + au.query_positions(
        bus_aug, bus_dist, snap.edge_index, snap.fraction
    )
    return out, diagnostics


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:  # noqa: PLR0915 - a linear pipeline reads better in one place
    cfg.ensure_directories()
    started = utc_now()

    districts, official = load_districts()
    boundary, boundary_area_km2 = write_analysis_boundary(districts)
    boundary_geom = districts.to_crs(cfg.METRIC_CRS).union_all()

    step("STEP 3  Canonical pedestrian network")
    source_manifest = json.loads(cfg.MANIFEST_PATH.read_text(encoding="utf-8"))
    recorded = source_manifest.get("walk_network", {})
    network = au.load_walk_network(
        cfg.WALK_GRAPH_FILE,
        expected_nodes=recorded.get("nodes"),
        expected_edge_records=recorded.get("edges"),
    )
    log(f"  matches the Week 3 snapshot: {recorded.get('nodes'):,} nodes, "
        f"{recorded.get('edges'):,} stored edge records")
    log(f"  network CRS: {network.crs}")
    edge_tree = au.build_edge_index(network)

    metro_points, metro_table, metro_stats = build_metro_access_points()
    bus_points = load_bus_points()

    step("STEP 4  Edge-aware transit snapping and multi-source shortest paths")
    (metro_snap, metro_aug, metro_node_dist, metro_diag, metro_place,
     metro_pred, metro_super) = prepare_mode(
        network, edge_tree, metro_points, "metro", want_predecessors=True)
    (bus_snap, bus_aug, bus_node_dist, bus_diag, bus_place,
     _, _) = prepare_mode(network, edge_tree, bus_points, "bus")

    # metro_access_points.csv gains the snapping columns, so the audit can see
    # exactly where every access point entered the network.
    metro_table = metro_table.copy()
    metro_table["snap_edge_index"] = metro_snap.edge_index
    metro_table["snap_edge_fraction"] = metro_snap.fraction.round(9)
    metro_table["off_network_connector_m"] = metro_snap.connector_m.round(4)
    metro_table["snap_cost_to_edge_u_m"] = metro_snap.cost_to_u.round(4)
    metro_table["snap_cost_to_edge_v_m"] = metro_snap.cost_to_v.round(4)
    metro_table["snapped_x_m"] = metro_snap.snapped_xy[:, 0].round(3)
    metro_table["snapped_y_m"] = metro_snap.snapped_xy[:, 1].round(3)
    metro_table["snapped_into_edge_interior"] = (
        (metro_snap.cost_to_u > cfg.EDGE_ENDPOINT_TOLERANCE_M)
        & (metro_snap.cost_to_v > cfg.EDGE_ENDPOINT_TOLERANCE_M)
    )
    metro_table.to_csv(cfg.METRO_ACCESS_POINTS_FILE, index=False, encoding="utf-8")
    log(f"  wrote {cfg.METRO_ACCESS_POINTS_FILE.name}")

    step("STEP 5  Population cells and district calibration")
    raster_2026 = cfg.worldpop_raster_path(cfg.WORLDPOP_YEAR)
    cells, raster_meta = au.rasterize_districts(raster_2026, districts, boundary_geom)
    log(f"  cells in window: {raster_meta['cells_in_window']:,}   "
        f"included: {raster_meta['cells_included']:,}")

    cells, calibration = au.calibrate_to_official(cells, official)
    log(f"\n  {'district':26s} {'raw WorldPop':>14s} {'official':>12s} {'factor':>9s}")
    log("  " + "-" * 66)
    for _, row in calibration.iterrows():
        log(f"  {row.district_name:26s} {row.worldpop_raw_sum:14,.0f} "
            f"{row.official_population:12,.0f} {row.calibration_factor:9.4f}")
    calibrated_total = float(calibration.calibrated_population.sum())
    official_total = float(calibration.official_population.sum())
    log("  " + "-" * 66)
    log(f"  calibrated total {calibrated_total:,.4f}   official {official_total:,.0f}   "
        f"difference {abs(calibrated_total - official_total):.6f}")
    if abs(calibrated_total - official_total) > 1.0:
        raise ValueError("calibrated population does not reproduce the official total")

    step("STEP 6  Edge-aware population-cell queries")
    cells, cell_diag = attach_distances(
        cells, network, edge_tree,
        (metro_aug, metro_node_dist), (bus_aug, bus_node_dist),
    )
    log(f"  cells: n={cell_diag['count']:,}  min={cell_diag['min_m']:.1f}  "
        f"mean={cell_diag['mean_m']:.1f}  median={cell_diag['median_m']:.1f}  "
        f"p95={cell_diag['p95_m']:.1f}  p99={cell_diag['p99_m']:.1f}  "
        f"max={cell_diag['max_m']:.1f} m  (to the nearest walkable EDGE)")
    log("  An off-network connector is a straight-line approximation to the nearest")
    log("  mapped walkable edge. It may not describe a physically walkable link in")
    log("  every case, so its effect on any individual cell is uncertain.")

    snap_rows = [
        {**metro_diag, "role": "transit_source", **{
            k: v for k, v in metro_place.items() if k != "count"}},
        {**bus_diag, "role": "transit_source", **{
            k: v for k, v in bus_place.items() if k != "count"}},
        {**cell_diag, "role": "population_query"},
    ]
    snap_table = pd.DataFrame(snap_rows)
    snap_table.insert(1, "measures", "straight-line distance to the nearest walkable edge")
    snap_table.to_csv(cfg.TRANSIT_SNAP_DIAGNOSTICS_FILE, index=False, encoding="utf-8")
    log(f"  wrote {cfg.TRANSIT_SNAP_DIAGNOSTICS_FILE.name}")

    unreachable_metro = float(cells.population[~np.isfinite(cells.metro_distance_m)].sum())
    unreachable_bus = float(cells.population[~np.isfinite(cells.bus_distance_m)].sum())
    log(f"  population on network components with no metro source: {unreachable_metro:,.0f}")
    log(f"  population on network components with no bus source  : {unreachable_bus:,.0f}")

    step("STEP 7  Access classification (main scenario)")
    main_speed = cfg.MAIN_WALK_SPEED_KMH
    budget = cfg.walk_budget_m(main_speed)
    log(f"  speed {main_speed} km/h = {cfg.kmh_to_ms(main_speed):.10f} m/s, "
        f"threshold {cfg.WALK_TIME_LIMIT_SECONDS} s (budget {budget:.1f} m)")
    flags = classify(cells, main_speed)

    city = with_percentages(aggregate(cells, flags, None))
    per_district = with_percentages(aggregate(cells, flags, "district_name"))

    log("\n  PRELIMINARY city result (pending independent audit):")
    row = city.iloc[0]
    log(f"    analysis population : {row.population:,.0f}")
    log(f"    metro accessible    : {row.metro:,.0f}  ({row.metro_pct:.2f}%)")
    log(f"    bus only            : {row.bus_only:,.0f}  ({row.bus_only_pct:.2f}%)")
    log(f"    underserved         : {row.underserved:,.0f}  ({row.underserved_pct:.2f}%)")

    step("STEP 8  District metrics")
    metric_districts = districts.to_crs(cfg.METRIC_CRS)
    areas = dict(zip(districts.district_name, metric_districts.area / 1e6))

    def count_within(path: Path) -> dict:
        gdf = gpd.read_file(path).to_crs(cfg.METRIC_CRS)
        joined = gpd.sjoin(gdf[["geometry"]], metric_districts[["district_name", "geometry"]],
                           how="inner", predicate="within")
        return joined.district_name.value_counts().to_dict()

    station_counts = count_within(cfg.METRO_STATIONS_FILE)
    access_counts = metro_points[metro_points.geometry.within(boundary_geom)]
    access_counts = gpd.sjoin(
        access_counts[["geometry"]], metric_districts[["district_name", "geometry"]],
        how="inner", predicate="within",
    ).district_name.value_counts().to_dict()
    bus_counts = count_within(cfg.BUS_STOPS_FILE)
    bazaar_counts = count_within(cfg.BAZAARS_FILE)

    table = per_district.rename(columns={
        "population": "calibrated_population",
        "metro": "metro_access_population",
        "bus_only": "bus_only_population",
        "underserved": "underserved_population",
        "metro_pct": "metro_access_pct",
    })
    table = table.merge(official[["district_name", "population"]]
                        .rename(columns={"population": "official_population"}),
                        on="district_name", how="left")
    table["combined_walk_access_population"] = (
        table.metro_access_population + table.bus_only_population
    )
    table["combined_walk_access_pct"] = table.combined_pct
    table["area_km2"] = table.district_name.map(areas)
    table["population_density_per_km2"] = table.calibrated_population / table.area_km2
    table["metro_stations_in_district"] = table.district_name.map(station_counts).fillna(0).astype(int)
    table["metro_access_points_in_district"] = table.district_name.map(access_counts).fillna(0).astype(int)
    table["bus_stops_in_district"] = table.district_name.map(bus_counts).fillna(0).astype(int)
    table["bazaars_in_district"] = table.district_name.map(bazaar_counts).fillna(0).astype(int)

    # Nearest-metro distance per district: the continuous evidence behind a
    # 0.00 percent, reported whether or not the share is zero.
    nearest = cells.groupby("district_name", sort=True).metro_distance_m.min()
    table["min_cell_metro_distance_m"] = table.district_name.map(nearest)
    table["min_cell_metro_margin_m"] = table.min_cell_metro_distance_m - budget

    columns = [
        "district_name", "official_population", "calibrated_population",
        "metro_access_population", "metro_access_pct",
        "bus_only_population", "bus_only_pct",
        "underserved_population", "underserved_pct",
        "combined_walk_access_population", "combined_walk_access_pct",
        "min_cell_metro_distance_m", "min_cell_metro_margin_m",
        "area_km2", "population_density_per_km2",
        "metro_stations_in_district", "metro_access_points_in_district",
        "bus_stops_in_district", "bazaars_in_district",
    ]
    table = table[columns].sort_values("district_name").reset_index(drop=True)
    for column in table.columns:
        if table[column].dtype.kind == "f":
            table[column] = table[column].round(6)
    table.to_csv(cfg.DISTRICT_ACCESS_METRICS_FILE, index=False, encoding="utf-8")
    log(f"  wrote {cfg.DISTRICT_ACCESS_METRICS_FILE.name} ({len(table)} rows)")

    log(f"\n  {'district':26s} {'pop':>11s} {'metro%':>8s} {'bus-only%':>10s} "
        f"{'unserved%':>10s} {'min metro m':>12s}")
    log("  " + "-" * 82)
    for _, r in table.iterrows():
        log(f"  {r.district_name:26s} {r.calibrated_population:11,.0f} "
            f"{r.metro_access_pct:8.2f} {r.bus_only_pct:10.2f} {r.underserved_pct:10.2f} "
            f"{r.min_cell_metro_distance_m:12.1f}")

    step("STEP 9  Walking-speed sensitivity")
    log("  Distances are speed-independent, so the same network result is reused;")
    log("  only the distance budget changes. No shortest path is recomputed.")
    sensitivity_rows = []
    for speed in cfg.WALK_SPEED_SCENARIOS_KMH:
        scenario_flags = classify(cells, speed)
        scoped = with_percentages(aggregate(cells, scenario_flags, None)).iloc[0]
        sensitivity_rows.append({
            "scope": "city", "district_name": "", "speed_kmh": speed,
            "budget_m": cfg.walk_budget_m(speed),
            "metro_access_population": scoped.metro, "metro_access_pct": scoped.metro_pct,
            "bus_only_population": scoped.bus_only, "bus_only_pct": scoped.bus_only_pct,
            "underserved_population": scoped.underserved,
            "underserved_pct": scoped.underserved_pct,
            "combined_pct": scoped.combined_pct,
        })
        for _, r in with_percentages(aggregate(cells, scenario_flags, "district_name")).iterrows():
            sensitivity_rows.append({
                "scope": "district", "district_name": r.district_name, "speed_kmh": speed,
                "budget_m": cfg.walk_budget_m(speed),
                "metro_access_population": r.metro, "metro_access_pct": r.metro_pct,
                "bus_only_population": r.bus_only, "bus_only_pct": r.bus_only_pct,
                "underserved_population": r.underserved,
                "underserved_pct": r.underserved_pct,
                "combined_pct": r.combined_pct,
            })
    sensitivity = pd.DataFrame(sensitivity_rows)
    for column in sensitivity.columns:
        if sensitivity[column].dtype.kind == "f":
            sensitivity[column] = sensitivity[column].round(6)
    sensitivity = sensitivity.sort_values(["scope", "district_name", "speed_kmh"]).reset_index(drop=True)
    sensitivity.to_csv(cfg.WALK_SPEED_SENSITIVITY_FILE, index=False, encoding="utf-8")
    city_rows = sensitivity[sensitivity.scope == "city"]
    log(f"  {'speed':>6s} {'budget m':>9s} {'metro%':>8s} {'bus-only%':>10s} {'unserved%':>10s}")
    for _, r in city_rows.iterrows():
        log(f"  {r.speed_kmh:6.1f} {r.budget_m:9.1f} {r.metro_access_pct:8.2f} "
            f"{r.bus_only_pct:10.2f} {r.underserved_pct:10.2f}")
    log(f"  wrote {cfg.WALK_SPEED_SENSITIVITY_FILE.name} ({len(sensitivity)} rows)")

    step("STEP 10  Population-surface sensitivity (2020 vs 2026)")
    baseline_raster = cfg.worldpop_raster_path(cfg.WORLDPOP_BASELINE_YEAR)
    if not baseline_raster.exists():
        raise FileNotFoundError(f"baseline raster missing: {baseline_raster}")

    baseline_cells, baseline_meta = au.rasterize_districts(
        baseline_raster, districts, boundary_geom
    )
    baseline_cells, _ = au.calibrate_to_official(baseline_cells, official)
    log(f"  2020 cells included: {len(baseline_cells):,} "
        f"(2026: {len(cells):,}); both calibrated to the SAME SIAT 2026-Q2 totals")

    baseline_cells, baseline_cell_diag = attach_distances(
        baseline_cells, network, edge_tree,
        (metro_aug, metro_node_dist), (bus_aug, bus_node_dist),
    )
    baseline_flags = classify(baseline_cells, main_speed)

    base_city = with_percentages(aggregate(baseline_cells, baseline_flags, None)).iloc[0]
    curr_city = city.iloc[0]
    surface_rows = [{
        "scope": "city", "district_name": "",
        "metro_access_pct_using_2020_surface": base_city.metro_pct,
        "metro_access_pct_using_2026_surface": curr_city.metro_pct,
        "percentage_point_difference": curr_city.metro_pct - base_city.metro_pct,
    }]
    base_district = with_percentages(
        aggregate(baseline_cells, baseline_flags, "district_name")
    ).set_index("district_name")
    curr_district = per_district.set_index("district_name")
    for name in sorted(curr_district.index):
        b_pct = float(base_district.loc[name, "metro_pct"])
        c_pct = float(curr_district.loc[name, "metro_pct"])
        surface_rows.append({
            "scope": "district", "district_name": name,
            "metro_access_pct_using_2020_surface": b_pct,
            "metro_access_pct_using_2026_surface": c_pct,
            "percentage_point_difference": c_pct - b_pct,
        })
    surface = pd.DataFrame(surface_rows)
    for column in surface.columns:
        if surface[column].dtype.kind == "f":
            surface[column] = surface[column].round(6)
    surface.to_csv(cfg.POPULATION_SURFACE_SENSITIVITY_FILE, index=False, encoding="utf-8")
    log(f"  city metro access: 2020 surface {base_city.metro_pct:.2f}%  "
        f"2026 surface {curr_city.metro_pct:.2f}%  "
        f"difference {curr_city.metro_pct - base_city.metro_pct:+.2f} pp")
    log(f"  wrote {cfg.POPULATION_SURFACE_SENSITIVITY_FILE.name} ({len(surface)} rows)")
    del baseline_cells

    step("STEP 11  Edge-aware district focus: nearest metro cell per district")
    focus = district_focus(
        cells, table, network, metro_aug, metro_node_dist, metro_pred, metro_super,
        metro_table, metric_districts, budget, sensitivity,
    )

    step("STEP 12  Display service areas (edge-aware)")
    metro_iso, metro_iso_info = au.build_service_area(
        network, metro_aug, metro_node_dist, budget)
    metro_area = au.service_area_area_km2(metro_iso)
    metro_iso.to_crs(cfg.GEOGRAPHIC_CRS).to_file(cfg.METRO_ISOCHRONE_FILE, driver="GeoJSON")
    log(f"  metro service area: {metro_area:,.2f} km2 -> {cfg.METRO_ISOCHRONE_FILE.name} "
        f"({cfg.human_size(cfg.file_size_bytes(cfg.METRO_ISOCHRONE_FILE))})")
    log(f"    {metro_iso_info}")

    bus_iso, bus_iso_info = au.build_service_area(
        network, bus_aug, bus_node_dist, budget)
    bus_area = au.service_area_area_km2(bus_iso)
    bus_iso.to_crs(cfg.GEOGRAPHIC_CRS).to_file(cfg.BUS_ISOCHRONE_FILE, driver="GeoJSON")
    log(f"  bus service area  : {bus_area:,.2f} km2 -> {cfg.BUS_ISOCHRONE_FILE.name} "
        f"({cfg.human_size(cfg.file_size_bytes(cfg.BUS_ISOCHRONE_FILE))})")
    log(f"    {bus_iso_info}")
    log("  THESE POLYGONS ARE FOR VISUALISATION. The population classification is")
    log("  computed from network distances and does not depend on them.")

    step("STEP 13  City summary and manifest")
    summary = {
        "status": "PRELIMINARY - pending independent audit",
        "snapping_method": SNAPPING_METHOD,
        "analysis_population": float(curr_city.population),
        "official_population": official_total,
        "metro_access_population": float(curr_city.metro),
        "metro_access_pct": float(curr_city.metro_pct),
        "bus_only_population": float(curr_city.bus_only),
        "bus_only_pct": float(curr_city.bus_only_pct),
        "underserved_population": float(curr_city.underserved),
        "underserved_pct": float(curr_city.underserved_pct),
        "combined_walk_access_population": float(curr_city.metro + curr_city.bus_only),
        "combined_walk_access_pct": float(curr_city.combined_pct),
        "walking_speed_kmh": main_speed,
        "walking_speed_ms": cfg.kmh_to_ms(main_speed),
        "walking_time_minutes": cfg.WALK_TIME_LIMIT_MINUTES,
        "walking_time_seconds": cfg.WALK_TIME_LIMIT_SECONDS,
        "distance_budget_m": budget,
        "analysis_district_count": int(len(districts)),
        "analysis_boundary_area_km2": round(boundary_area_km2, 4),
        "measures": "physical walking access only",
        "does_not_measure": [
            "route frequency", "service span", "transfers", "in-vehicle travel time",
            "reliability", "crowding", "fare", "destination usefulness",
        ],
        "analysis_version": ANALYSIS_VERSION,
        "generated_at_utc": utc_now(),
    }
    cfg.CITY_ACCESS_SUMMARY_FILE.write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    log(f"  wrote {cfg.CITY_ACCESS_SUMMARY_FILE.name}")

    cells_out = cells[[
        "cell_id", "row", "col", "lon", "lat", "x_m", "y_m", "district_name",
        "worldpop_raw", "calibration_factor", "population", "edge_index",
        "edge_fraction", "edge_connector_m", "metro_distance_m", "bus_distance_m",
    ]]
    cells_out.to_parquet(cfg.POPULATION_CELLS_CACHE, index=False)
    log(f"  cached per-cell table -> {cfg.POPULATION_CELLS_CACHE.name} "
        f"({cfg.human_size(cfg.file_size_bytes(cfg.POPULATION_CELLS_CACHE))}, gitignored)")

    manifest = {
        "analysis": "Week 4 - geospatial accessibility engine",
        "status": "PRELIMINARY - pending independent audit",
        "analysis_version": ANALYSIS_VERSION,
        "snapping_method": SNAPPING_METHOD,
        "started_at_utc": started,
        "generated_at_utc": utc_now(),
        "generated_by": "scripts/analyze_accessibility.py",
        "correction": {
            "supersedes": "week4.1 nearest-graph-node snapping",
            "reason": (
                "Independent review found that nearest-node snapping on the simplified "
                "OSM pedestrian graph could add hundreds of metres to some population "
                "cells simply because no graph vertex existed near the middle of a long "
                "edge. Population-cell vertex offsets ran to a median of 39.6 m, a 99th "
                "percentile of 367.5 m and a maximum of 905.9 m against an 800 m budget. "
                "Before any Week 4 result was merged, the analysis was recomputed using "
                "edge-aware network snapping."
            ),
            "regression_tests": "scripts/test_accessibility_utils.py",
        },
        "source_manifest": {
            "path": "data/source_manifest.json",
            "sha256": cfg.sha256_file(cfg.MANIFEST_PATH),
        },
        "analysis_boundary": {
            "definition": "union of the 12 SIAT-matched district polygons",
            "district_count": int(len(districts)),
            "area_km2": round(boundary_area_km2, 4),
            "excluded": {
                "district": "Yangi Toshkent Tumani",
                "reason": "no SIAT population row, so no official total to calibrate against",
            },
            "file": str(cfg.ANALYSIS_BOUNDARY_FILE.relative_to(cfg.REPO_ROOT)).replace("\\", "/"),
        },
        "siat": {
            "reference_period": cfg.SIAT_REFERENCE_PERIOD,
            "official_population_total": official_total,
        },
        "worldpop": {
            "product": cfg.WORLDPOP_PRODUCT,
            "release": cfg.WORLDPOP_RELEASE,
            "release_status": cfg.WORLDPOP_RELEASE_STATUS,
            "main_year": cfg.WORLDPOP_YEAR,
            "sensitivity_year": cfg.WORLDPOP_BASELINE_YEAR,
            "raster_2026": raster_meta,
            "raster_2020": baseline_meta,
            "sensitivity_note": (
                "both surfaces are calibrated to the SAME SIAT 2026-Q2 district totals, "
                "so the comparison isolates sensitivity to WITHIN-district weights and "
                "says nothing about which surface is closer to the truth"
            ),
        },
        "network": {
            "source": str(cfg.WALK_GRAPH_FILE.relative_to(cfg.REPO_ROOT)).replace("\\", "/"),
            "stored_crs": cfg.GEOGRAPHIC_CRS,
            "analysis_crs": network.crs,
            "nodes": network.n_nodes,
            **network.stats,
        },
        "routing_model": {
            "snapping_method": SNAPPING_METHOD,
            "edge_snap_method": (
                "shapely STRtree nearest canonical edge geometry, then "
                "line_locate_point for the position along that edge"
            ),
            "position_units": (
                "fraction along the projected edge geometry, converted to routing "
                "metres with the SAME edge's cost: cost_to_u = fraction * edge_cost, "
                "cost_to_v = (1 - fraction) * edge_cost"
            ),
            "source_insertion_method": (
                "canonical edges are split at the snapped source positions, in order "
                "along the edge, producing an augmented graph in which every transit "
                "source is a real vertex"
            ),
            "population_edge_query_method": (
                "a cell's position is bracketed by the two consecutive breaks of its "
                "own edge; the segment interior holds no vertex and no source, so "
                "d(cell) = min(d(a) + cost(a->cell), d(b) + cost(cell->b)) is exact"
            ),
            "same_edge_handling": (
                "a source in the interior of a cell's own edge is one of that cell's "
                "bracketing breaks, so the walk is measured directly along the edge and "
                "never forced out to an endpoint and back"
            ),
            "self_loop_handling": (
                "a self-loop's two breaks are the same vertex, so the same formula "
                "returns min(d(u) + f*L, d(u) + (1-f)*L): round the loop the short way"
            ),
            "directional_duplicate_handling": (
                "removed during canonicalisation; the sparse matrix additionally "
                "collapses any repeated node pair to its minimum weight, because "
                "coo_matrix sums duplicates and would otherwise double a walking cost"
            ),
            "unreachable": "+inf for components holding no source of that mode",
            "shortest_path_passes": 2,
            "shortest_path_note": (
                "one multi-source Dijkstra per mode over the augmented graph; walking-"
                "speed sensitivity reuses those distances and recomputes no path"
            ),
        },
        "walking_model": {
            "main_speed_kmh": main_speed,
            "main_speed_ms": cfg.kmh_to_ms(main_speed),
            "sensitivity_speeds_kmh": list(cfg.WALK_SPEED_SCENARIOS_KMH),
            "threshold_seconds": cfg.WALK_TIME_LIMIT_SECONDS,
            "threshold_minutes": cfg.WALK_TIME_LIMIT_MINUTES,
            "main_budget_m": budget,
        },
        "metro_sources": {**metro_stats, "placement": metro_place,
                          "augmentation": metro_aug.stats},
        "bus_sources": {"stops_used": int(len(bus_points)), "placement": bus_place,
                        "augmentation": bus_aug.stats},
        "connector_diagnostics": {
            "definition": (
                "straight-line distance from the point to the nearest walkable EDGE "
                "(not to the nearest graph vertex)"
            ),
            "interpretation": (
                "Off-network connectors are straight-line approximations to the nearest "
                "mapped walkable edge. They may not represent a physically walkable "
                "connection in every case, so their effect on individual cells is "
                "uncertain. A connector may cross a fence, a parcel boundary, a "
                "building, a railway, a canal, private land or another unmapped barrier; "
                "the model does not know."
            ),
            "metro": metro_diag,
            "bus": bus_diag,
            "population_cells": cell_diag,
            "population_cells_2020_surface": baseline_cell_diag,
        },
        "population_cells": {
            "count": int(len(cells)),
            "connector_diagnostics": cell_diag,
            "population_without_metro_source": unreachable_metro,
            "population_without_bus_source": unreachable_bus,
        },
        "calibration_factors": calibration.round(10).to_dict(orient="records"),
        "calibrated_total": calibrated_total,
        "district_focus": focus,
        "service_areas": {
            "method": (
                "reachable AUGMENTED segments within the budget, cut along the real "
                "edge geometry where the budget runs out, buffered by "
                f"{cfg.ISOCHRONE_BUFFER_M:.0f} m in {cfg.METRIC_CRS}, dissolved, "
                f"simplified at {cfg.ISOCHRONE_SIMPLIFY_M:.0f} m, written as WGS84. "
                "Because sources are spliced into edge interiors, a stop in the middle "
                "of a long edge produces reachable geometry around itself even when "
                "both of that edge's original endpoints lie beyond the budget."
            ),
            "purpose": "visualisation only; not used by the population classification",
            "metro_area_km2": round(metro_area, 4),
            "bus_area_km2": round(bus_area, 4),
            "metro": metro_iso_info,
            "bus": bus_iso_info,
        },
        "outputs": [
            str(p.relative_to(cfg.REPO_ROOT)).replace("\\", "/") for p in (
                cfg.ANALYSIS_BOUNDARY_FILE, cfg.METRO_ACCESS_POINTS_FILE,
                cfg.TRANSIT_SNAP_DIAGNOSTICS_FILE, cfg.DISTRICT_ACCESS_METRICS_FILE,
                cfg.CITY_ACCESS_SUMMARY_FILE, cfg.WALK_SPEED_SENSITIVITY_FILE,
                cfg.POPULATION_SURFACE_SENSITIVITY_FILE, cfg.METRO_ISOCHRONE_FILE,
                cfg.BUS_ISOCHRONE_FILE,
            )
        ],
        "output_counts": {
            "district_rows": int(len(table)),
            "walking_speed_sensitivity_rows": int(len(sensitivity)),
            "population_surface_sensitivity_rows": int(len(surface)),
            "metro_access_point_rows": int(len(metro_table)),
            "transit_snap_rows": int(len(snap_table)),
        },
        "limitations": [
            "Physical walking access only: no frequency, span, transfers, in-vehicle "
            "time, reliability, crowding, fare or destination usefulness.",
            "The link from a raster-cell centre to the network, and from a transit "
            "access point to the network, is a straight-line off-network connector to "
            "the nearest mapped walkable edge. It may not represent a physically "
            "walkable connection in every case, so its effect on individual cells is "
            "uncertain in an unknown direction.",
            "Routing runs on the SIMPLIFIED OSM walk graph. Positions along an edge are "
            "exact, but the edge's own shape is OSM's generalisation of the real path.",
            "Parallel ways between the same node pair are kept as separate canonical "
            "edges, so a cell is costed against the way it actually stands beside; "
            "1,380 node pairs carry such parallel edges here.",
            "WorldPop R2025A is an alpha product; it supplies within-district weights "
            "only, and its within-district accuracy is unverified.",
            "Bus stops come from OSM alone; no official open-data bus layer was "
            "reachable in Week 3.",
            "Metro entrances are used where mapped; stations without a mapped entrance "
            "fall back to the station point, which flatters deep stations slightly.",
            "Yangi Toshkent district is outside the population denominator.",
            "The service-area polygons are for display and play no part in the "
            "population classification.",
        ],
    }
    cfg.ANALYSIS_MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    log(f"  wrote {cfg.ANALYSIS_MANIFEST_PATH.relative_to(cfg.REPO_ROOT)}")

    step("Analysis complete - PRELIMINARY, pending independent audit")
    log("  Next: python scripts/validate_analysis.py")
    return 0


def district_focus(
    cells: pd.DataFrame,
    table: pd.DataFrame,
    network: au.WalkNetwork,
    metro_aug: au.AugmentedNetwork,
    metro_node_dist: np.ndarray,
    predecessors: np.ndarray,
    super_source: int,
    metro_table: pd.DataFrame,
    metric_districts: gpd.GeoDataFrame,
    budget: float,
    sensitivity: pd.DataFrame,
) -> dict:
    """Trace, for each district, the closest population cell to the metro.

    Reported for every district, not only the ones with a zero share, so a
    0.00 percent can be read against its actual distance margin instead of
    being asserted.
    """
    aug_xy = au.augmented_node_xy(network, metro_aug)
    district_geom = dict(zip(metric_districts.district_name, metric_districts.geometry))
    access_xy = np.column_stack([metro_table.snapped_x_m, metro_table.snapped_y_m])

    focus: dict[str, dict] = {}
    for name in sorted(cells.district_name.unique()):
        subset = cells[cells.district_name == name]
        if subset.empty or not np.isfinite(subset.metro_distance_m).any():
            continue
        row = subset.loc[subset.metro_distance_m.idxmin()]
        edge = int(row.edge_index)
        fraction = float(row.edge_fraction)

        start = int(metro_aug.break_offset[edge])
        stop = int(metro_aug.break_offset[edge + 1])
        block = metro_aug.break_fraction[start:stop]
        right = int(np.clip(np.searchsorted(block, fraction, side="right"), 1, len(block) - 1))
        left = right - 1
        cost = float(network.edge_cost[edge])
        options = [
            (metro_node_dist[metro_aug.break_node[start + left]] + (fraction - block[left]) * cost,
             int(metro_aug.break_node[start + left])),
            (metro_node_dist[metro_aug.break_node[start + right]] + (block[right] - fraction) * cost,
             int(metro_aug.break_node[start + right])),
        ]
        _, entry_node = min(options, key=lambda pair: pair[0])

        path = au.trace_access_path(predecessors, super_source, entry_node)
        crosses = None
        nearest_access = None
        if path:
            geom = district_geom.get(name)
            path_xy = aug_xy[np.asarray(path, dtype=np.int64)]
            if geom is not None:
                inside = gpd.GeoSeries(gpd.points_from_xy(path_xy[:, 0], path_xy[:, 1]),
                                       crs=cfg.METRIC_CRS).within(geom)
                crosses = bool((~inside).any())
            # the path starts at the access point's own position on the network
            first = path_xy[0]
            distances = np.hypot(access_xy[:, 0] - first[0], access_xy[:, 1] - first[1])
            best = int(np.argmin(distances))
            nearest_access = {
                "access_id": str(metro_table.access_id.iloc[best]),
                "access_type": str(metro_table.access_type.iloc[best]),
                "name": None if pd.isna(metro_table.name.iloc[best]) else str(metro_table.name.iloc[best]),
                "district_name": None if pd.isna(metro_table.district_name.iloc[best])
                else str(metro_table.district_name.iloc[best]),
                "off_network_connector_m": float(metro_table.off_network_connector_m.iloc[best]),
                "distance_from_traced_entry_point_m": float(distances[best]),
            }

        district_row = table[table.district_name == name].iloc[0]
        speeds = sensitivity[(sensitivity.scope == "district")
                             & (sensitivity.district_name == name)]
        focus[name] = {
            "calibrated_population": float(district_row.calibrated_population),
            "metro_access_population": float(district_row.metro_access_population),
            "metro_access_pct": float(district_row.metro_access_pct),
            "nearest_cell": {
                "cell_id": str(row.cell_id),
                "lon": float(row.lon),
                "lat": float(row.lat),
                "total_walking_distance_to_metro_m": float(row.metro_distance_m),
                "margin_against_budget_m": float(row.metro_distance_m - budget),
                "off_network_connector_m": float(row.edge_connector_m),
                "canonical_edge_index": edge,
                "fraction_along_edge": fraction,
                "cell_population": float(row.population),
            },
            "nearest_metro_access_point": nearest_access,
            "access_path_leaves_the_district": crosses,
            "access_path_nodes": len(path),
            "metro_access_pct_by_speed": {
                f"{r.speed_kmh:.1f}": float(r.metro_access_pct) for _, r in speeds.iterrows()
            },
        }
        marker = "" if district_row.metro_access_pct > 0 else "   <- zero metro share"
        log(f"  {name:26s} nearest cell {row.metro_distance_m:8.1f} m "
            f"({row.metro_distance_m - budget:+8.1f} m vs budget), "
            f"connector {row.edge_connector_m:6.1f} m{marker}")
    return focus


if __name__ == "__main__":
    raise SystemExit(main())
