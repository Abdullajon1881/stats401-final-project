"""Week 4: pedestrian-network accessibility analysis for Tashkent.

    python scripts/analyze_accessibility.py

Turns the validated Week 3 datasets into district and city access metrics:

  * analysis boundary = the union of the 12 SIAT-matched districts
  * metro access points = mapped entrances, with a documented station fallback
  * one multi-source shortest-path pass per mode over the projected walk graph
  * WorldPop cells calibrated to official SIAT totals district by district
  * classification into metro / bus-only / underserved at 10 minutes
  * walking-speed and population-surface sensitivity
  * a display-only service-area polygon

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

ANALYSIS_VERSION = "week4.1"


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
    table.to_csv(cfg.METRO_ACCESS_POINTS_FILE, index=False, encoding="utf-8")

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
    log(f"  wrote {cfg.METRO_ACCESS_POINTS_FILE.name}")
    return points, table, stats


def load_bus_points() -> gpd.GeoDataFrame:
    stops = gpd.read_file(cfg.BUS_STOPS_FILE).sort_values("osm_id").reset_index(drop=True)
    return stops.to_crs(cfg.METRIC_CRS)


# ---------------------------------------------------------------------------
# Network distances
# ---------------------------------------------------------------------------
def mode_node_distances(
    graph: au.WalkGraph,
    points: gpd.GeoDataFrame,
    label: str,
) -> tuple[np.ndarray, dict]:
    """Snap a mode's access points and run one multi-source shortest-path pass."""
    xy = np.column_stack([points.geometry.x, points.geometry.y])
    nodes, offsets = au.snap_points(graph, xy)
    diagnostics = au.snap_diagnostics(label, offsets)
    log(f"  {label}: n={diagnostics['count']}  min={diagnostics['min_m']:.1f}  "
        f"median={diagnostics['median_m']:.1f}  p95={diagnostics['p95_m']:.1f}  "
        f"p99={diagnostics['p99_m']:.1f}  max={diagnostics['max_m']:.1f} m")

    worst = np.argsort(offsets)[-5:][::-1]
    log(f"    largest {label} snap offsets:")
    for i in worst:
        name = points.iloc[int(i)].get("name")
        log(f"      {offsets[i]:8.1f} m  {str(name)[:40]}")

    distances = au.multi_source_distances(graph, nodes, offsets)
    reachable = np.isfinite(distances)
    log(f"    nodes reachable from {label}: {int(reachable.sum()):,} / {distances.size:,} "
        f"({reachable.mean():.2%})")
    diagnostics["nodes_reachable"] = int(reachable.sum())
    diagnostics["nodes_total"] = int(distances.size)
    return distances, diagnostics


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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    cfg.ensure_directories()
    started = utc_now()

    districts, official = load_districts()
    boundary, boundary_area_km2 = write_analysis_boundary(districts)
    boundary_geom = districts.to_crs(cfg.METRIC_CRS).union_all()

    step("STEP 3  Pedestrian network")
    graph = au.load_walk_graph(cfg.WALK_GRAPH_FILE)
    log(f"  matrix nodes: {graph.n_nodes:,}   undirected edges: {graph.n_edges:,}")
    log(f"  graph CRS: {graph.crs}")

    metro_points, metro_table, metro_stats = build_metro_access_points()
    bus_points = load_bus_points()

    step("STEP 4  Transit snapping and multi-source shortest paths")
    metro_node_dist, metro_snap = mode_node_distances(graph, metro_points, "metro")
    bus_node_dist, bus_snap = mode_node_distances(graph, bus_points, "bus")

    snap_table = pd.DataFrame([metro_snap, bus_snap])
    snap_table.to_csv(cfg.TRANSIT_SNAP_DIAGNOSTICS_FILE, index=False, encoding="utf-8")
    log(f"  wrote {cfg.TRANSIT_SNAP_DIAGNOSTICS_FILE.name}")

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

    step("STEP 6  Population-cell snapping")
    cell_xy = np.column_stack([cells.x_m.to_numpy(), cells.y_m.to_numpy()])
    cell_nodes, cell_offsets = au.snap_points(graph, cell_xy)
    cell_snap = au.snap_diagnostics("population_cells", cell_offsets)
    log(f"  cells: n={cell_snap['count']:,}  min={cell_snap['min_m']:.1f}  "
        f"median={cell_snap['median_m']:.1f}  p95={cell_snap['p95_m']:.1f}  "
        f"p99={cell_snap['p99_m']:.1f}  max={cell_snap['max_m']:.1f} m")
    log("  the cell-centre-to-network link is a straight-line approximation")

    cells["node_index"] = cell_nodes
    cells["node_offset_m"] = cell_offsets
    cells["metro_distance_m"] = cell_offsets + metro_node_dist[cell_nodes]
    cells["bus_distance_m"] = cell_offsets + bus_node_dist[cell_nodes]

    unreachable_metro = float(cells.population[~np.isfinite(cells.metro_distance_m)].sum())
    unreachable_bus = float(cells.population[~np.isfinite(cells.bus_distance_m)].sum())
    log(f"  population on network components with no metro source: {unreachable_metro:,.0f}")
    log(f"  population on network components with no bus source  : {unreachable_bus:,.0f}")

    step("STEP 7  Access classification (main scenario)")
    main_speed = cfg.MAIN_WALK_SPEED_KMH
    log(f"  speed {main_speed} km/h = {cfg.kmh_to_ms(main_speed):.10f} m/s, "
        f"threshold {cfg.WALK_TIME_LIMIT_SECONDS} s "
        f"(budget {cfg.walk_budget_m(main_speed):.1f} m)")
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

    columns = [
        "district_name", "official_population", "calibrated_population",
        "metro_access_population", "metro_access_pct",
        "bus_only_population", "bus_only_pct",
        "underserved_population", "underserved_pct",
        "combined_walk_access_population", "combined_walk_access_pct",
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

    log(f"\n  {'district':26s} {'pop':>11s} {'metro%':>8s} {'bus-only%':>10s} {'unserved%':>10s}")
    log("  " + "-" * 70)
    for _, r in table.iterrows():
        log(f"  {r.district_name:26s} {r.calibrated_population:11,.0f} "
            f"{r.metro_access_pct:8.2f} {r.bus_only_pct:10.2f} {r.underserved_pct:10.2f}")

    step("STEP 9  Walking-speed sensitivity")
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
    surface_rows: list[dict] = []
    baseline_meta: dict = {}
    if not baseline_raster.exists():
        log(f"  ! {baseline_raster.name} not present; run scripts/audit_population_surface.py")
        raise FileNotFoundError(f"baseline raster missing: {baseline_raster}")

    baseline_cells, baseline_meta = au.rasterize_districts(
        baseline_raster, districts, boundary_geom
    )
    baseline_cells, baseline_calibration = au.calibrate_to_official(baseline_cells, official)
    log(f"  2020 cells included: {len(baseline_cells):,} "
        f"(2026: {len(cells):,}); both calibrated to the SAME SIAT 2026-Q2 totals")

    b_nodes, b_offsets = au.snap_points(
        graph, np.column_stack([baseline_cells.x_m.to_numpy(), baseline_cells.y_m.to_numpy()])
    )
    baseline_cells["node_offset_m"] = b_offsets
    baseline_cells["metro_distance_m"] = b_offsets + metro_node_dist[b_nodes]
    baseline_cells["bus_distance_m"] = b_offsets + bus_node_dist[b_nodes]
    baseline_flags = classify(baseline_cells, main_speed)

    base_city = with_percentages(aggregate(baseline_cells, baseline_flags, None)).iloc[0]
    curr_city = city.iloc[0]
    surface_rows.append({
        "scope": "city", "district_name": "",
        "metro_access_pct_using_2020_surface": base_city.metro_pct,
        "metro_access_pct_using_2026_surface": curr_city.metro_pct,
        "percentage_point_difference": curr_city.metro_pct - base_city.metro_pct,
    })
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

    step("STEP 11  Display service areas")
    budget = cfg.walk_budget_m(main_speed)
    metro_iso = au.build_service_area(graph, metro_node_dist, budget)
    metro_area = au.service_area_area_km2(metro_iso)
    metro_iso.to_crs(cfg.GEOGRAPHIC_CRS).to_file(cfg.METRO_ISOCHRONE_FILE, driver="GeoJSON")
    log(f"  metro service area: {metro_area:,.2f} km2 -> {cfg.METRO_ISOCHRONE_FILE.name} "
        f"({cfg.human_size(cfg.file_size_bytes(cfg.METRO_ISOCHRONE_FILE))})")

    bus_iso = au.build_service_area(graph, bus_node_dist, budget)
    bus_area = au.service_area_area_km2(bus_iso)
    bus_iso.to_crs(cfg.GEOGRAPHIC_CRS).to_file(cfg.BUS_ISOCHRONE_FILE, driver="GeoJSON")
    log(f"  bus service area  : {bus_area:,.2f} km2 -> {cfg.BUS_ISOCHRONE_FILE.name} "
        f"({cfg.human_size(cfg.file_size_bytes(cfg.BUS_ISOCHRONE_FILE))})")
    log("  THESE POLYGONS ARE FOR VISUALISATION. The population classification is")
    log("  computed from network distances and does not depend on them.")

    step("STEP 12  City summary and manifest")
    summary = {
        "status": "PRELIMINARY - pending independent audit",
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
        "worldpop_raw", "calibration_factor", "population", "node_index",
        "node_offset_m", "metro_distance_m", "bus_distance_m",
    ]]
    cells_out.to_parquet(cfg.POPULATION_CELLS_CACHE, index=False)
    log(f"  cached per-cell table -> {cfg.POPULATION_CELLS_CACHE.name} "
        f"({cfg.human_size(cfg.file_size_bytes(cfg.POPULATION_CELLS_CACHE))}, gitignored)")

    manifest = {
        "analysis": "Week 4 - geospatial accessibility engine",
        "status": "PRELIMINARY - pending independent audit",
        "analysis_version": ANALYSIS_VERSION,
        "started_at_utc": started,
        "generated_at_utc": utc_now(),
        "generated_by": "scripts/analyze_accessibility.py",
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
        },
        "graph": {
            "source": str(cfg.WALK_GRAPH_FILE.relative_to(cfg.REPO_ROOT)).replace("\\", "/"),
            "stored_crs": cfg.GEOGRAPHIC_CRS,
            "analysis_crs": graph.crs,
            "nodes": graph.n_nodes,
            "undirected_edges": graph.n_edges,
        },
        "walking_model": {
            "main_speed_kmh": main_speed,
            "main_speed_ms": cfg.kmh_to_ms(main_speed),
            "sensitivity_speeds_kmh": list(cfg.WALK_SPEED_SCENARIOS_KMH),
            "threshold_seconds": cfg.WALK_TIME_LIMIT_SECONDS,
            "threshold_minutes": cfg.WALK_TIME_LIMIT_MINUTES,
            "main_budget_m": budget,
        },
        "metro_sources": metro_stats,
        "bus_sources": {"stops_used": int(len(bus_points))},
        "transit_snap_diagnostics": [metro_snap, bus_snap],
        "population_cells": {
            "count": int(len(cells)),
            "snap_diagnostics": cell_snap,
            "population_without_metro_source": unreachable_metro,
            "population_without_bus_source": unreachable_bus,
        },
        "calibration_factors": calibration.round(10).to_dict(orient="records"),
        "calibrated_total": calibrated_total,
        "service_areas": {
            "method": (
                "reachable network edges within the budget, buffered by "
                f"{cfg.ISOCHRONE_BUFFER_M:.0f} m in {cfg.METRIC_CRS}, dissolved, "
                f"simplified at {cfg.ISOCHRONE_SIMPLIFY_M:.0f} m, written as WGS84. "
                "Partially reachable edges are cut at the budget by linear "
                "interpolation along the straight segment between their nodes."
            ),
            "purpose": "visualisation only; not used by the population classification",
            "metro_area_km2": round(metro_area, 4),
            "bus_area_km2": round(bus_area, 4),
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
            "The link from a raster-cell centre to the pedestrian network, and from a "
            "transit access point to the network, is a straight-line approximation.",
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


if __name__ == "__main__":
    raise SystemExit(main())
