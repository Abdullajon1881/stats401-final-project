"""Compute current urban-dimension accessibility and supply for Tashkent.

    python scripts/analyze_urban_dimensions.py

Phase 2C extends the current-period analysis beyond transit and population
density with healthcare, education, bazaars, facility supply and walk-network
density. It reuses the audited edge-aware routing engine, the current
SIAT-calibrated population surface and the frozen current walking definition,
so a 10-minute walk means the same thing for every destination class.

No composite score or district ranking is produced, and no historical claim is
made about healthcare, education or bazaar availability.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import accessibility_utils as au  # noqa: E402
import config as cfg  # noqa: E402
import urban_dimensions as ud  # noqa: E402
from pipeline_utils import enable_utf8_stdout, log, step  # noqa: E402

BUDGET_M = cfg.PHASE2C_ACCESS_DISTANCE_BUDGET_M
LENGTH_TOLERANCE_KM = 1e-6
POPULATION_TOLERANCE = 1e-6


def relative(path: Path) -> str:
    return str(path.relative_to(cfg.REPO_ROOT)).replace("\\", "/")


def load_population_cells() -> pd.DataFrame:
    """Load and re-validate the current calibrated population cell table."""
    if not cfg.POPULATION_CELLS_CACHE.exists():
        raise SystemExit(
            f"missing {relative(cfg.POPULATION_CELLS_CACHE)}; rebuild it with "
            "scripts/analyze_accessibility.py before running Phase 2C"
        )
    cells = pd.read_parquet(cfg.POPULATION_CELLS_CACHE)
    required = {
        "cell_id", "x_m", "y_m", "district_name", "population",
        "edge_index", "edge_fraction", "edge_connector_m",
    }
    missing = sorted(required - set(cells.columns))
    if missing:
        raise SystemExit(f"population cell cache is missing columns: {missing}")
    if cells.cell_id.duplicated().any():
        raise SystemExit("population cell cache contains duplicate cell_id values")
    if not np.isfinite(cells.population.to_numpy()).all():
        raise SystemExit("population cell cache contains non-finite population")
    if (cells.population.to_numpy() < 0).any():
        raise SystemExit("population cell cache contains negative population")
    fraction = cells.edge_fraction.to_numpy()
    if not ((fraction >= 0.0) & (fraction <= 1.0)).all():
        raise SystemExit("edge_fraction outside [0, 1] in the population cell cache")
    if (cells.edge_connector_m.to_numpy() < 0).any():
        raise SystemExit("negative off-network connector in the population cell cache")
    return cells


def facility_points(path: Path, label: str) -> gpd.GeoDataFrame:
    """Read a facility layer and return its projected routing points."""
    gdf = gpd.read_file(path)
    points = gpd.GeoSeries(
        gpd.points_from_xy(gdf.longitude, gdf.latitude), crs=cfg.GEOGRAPHIC_CRS
    ).to_crs(cfg.METRIC_CRS)
    out = gdf.copy()
    out["routing_geometry"] = points
    log(f"  {label}: {len(out)} routing points")
    return out


def bazaar_points() -> gpd.GeoDataFrame:
    """Reuse the existing audited bazaar layer without modifying it."""
    gdf = gpd.read_file(cfg.BAZAARS_FILE)
    projected = gdf.to_crs(cfg.METRIC_CRS)
    representative = []
    for geometry in projected.geometry:
        point, _ = ud.representative_point(geometry)
        representative.append(point)
    out = gdf.copy()
    out["routing_geometry"] = gpd.GeoSeries(representative, crs=cfg.METRIC_CRS)
    log(f"  bazaars: {len(out)} routing points (existing amenity=marketplace layer)")
    return out


def route_class(
    network: au.WalkNetwork,
    tree,
    sources: gpd.GeoDataFrame,
    cells: pd.DataFrame,
    label: str,
) -> tuple[np.ndarray, dict, dict]:
    """One multi-source Dijkstra for a whole destination class.

    The source's own off-network connector is paid inside the augmented
    network, and the population cell's connector is added once on top, exactly
    as the current headline analysis does.
    """
    xy = np.column_stack([
        sources.routing_geometry.x.to_numpy(),
        sources.routing_geometry.y.to_numpy(),
    ])
    snap = au.snap_points_to_edges(network, xy, tree=tree)
    diagnostics = au.connector_diagnostics(label, snap.connector_m)
    placement = au.snap_placement_stats(
        snap, network, endpoint_tol_m=cfg.EDGE_ENDPOINT_TOLERANCE_M
    )
    log(f"  {label}: n={diagnostics['count']}  min={diagnostics['min_m']:.1f}  "
        f"median={diagnostics['median_m']:.1f}  p95={diagnostics['p95_m']:.1f}  "
        f"p99={diagnostics['p99_m']:.1f}  max={diagnostics['max_m']:.1f} m")

    augmented = au.build_augmented_network(network, snap)
    node_distance = au.multi_source_distances(network, augmented, snap.connector_m)
    distance = cells.edge_connector_m.to_numpy(dtype=np.float64) + au.query_positions(
        augmented, node_distance, cells.edge_index.to_numpy(), cells.edge_fraction.to_numpy()
    )
    if np.isnan(distance).any():
        raise SystemExit(f"{label} produced NaN cell distances")
    reachable = int(np.isfinite(distance).sum())
    accessible = int(ud.within_budget(distance, BUDGET_M).sum())
    log(f"    finite-distance cells {reachable:,}/{len(cells):,}; "
        f"within {BUDGET_M:.0f} m: {accessible:,}")
    return distance, diagnostics, placement


def district_supply(
    facilities: gpd.GeoDataFrame, column: str, categories, districts: list[str]
) -> pd.DataFrame:
    """Per-district counts for one facility class."""
    table = pd.DataFrame(index=pd.Index(districts, name="district_name"))
    for category in categories:
        subset = facilities.loc[facilities[column] == category, "district_name"]
        table[f"{category}s" if not category.endswith("s") else category] = (
            subset.value_counts().reindex(districts).fillna(0).astype(int)
        )
    return table.reset_index()


def main() -> int:  # noqa: PLR0915 - linear analysis pipeline is intentional
    enable_utf8_stdout()
    step("PHASE 2C  Current urban dimensions")

    districts = gpd.read_file(cfg.DISTRICTS_FILE)
    districts = districts.loc[districts.in_siat].copy()
    district_names = sorted(districts.district_name.tolist())
    log(f"  {len(district_names)} SIAT-matched analysis districts")

    current = pd.read_csv(cfg.DISTRICT_ACCESS_METRICS_FILE)
    log(f"  reusing current metro/bus district metrics: {len(current)} rows")

    step("STEP 1  Current calibrated population surface")
    cells = load_population_cells()
    population = cells.population.to_numpy(dtype=np.float64)
    city_population = float(population.sum(dtype=np.float64))
    log(f"  {len(cells):,} cells; calibrated population {city_population:,.6f}")
    official_total = float(current.official_population.sum())
    if abs(city_population - official_total) > 1.0:
        raise SystemExit(
            f"population cells ({city_population:.6f}) do not reproduce the official "
            f"district total ({official_total:.6f})"
        )
    log(f"  official SIAT district total {official_total:,.0f}")

    step("STEP 2  Load the fixed current pedestrian network")
    network = au.load_walk_network(cfg.WALK_GRAPH_FILE)
    log(f"  nodes {network.n_nodes:,}  stored records "
        f"{network.stats['stored_edge_records']:,}  canonical edges {network.n_edges:,}")
    tree = au.build_edge_index(network)

    step("STEP 3  Destination sources")
    healthcare = facility_points(cfg.HEALTHCARE_FACILITIES_FILE, "healthcare")
    education = facility_points(cfg.EDUCATION_FACILITIES_FILE, "education")
    bazaars = bazaar_points()

    step("STEP 4  One multi-source Dijkstra per destination class")
    classes = {
        "healthcare": healthcare,
        "education": education,
        "bazaar": bazaars,
    }
    distances: dict[str, np.ndarray] = {}
    connector_diagnostics: dict[str, dict] = {}
    placements: dict[str, dict] = {}
    for label, sources in classes.items():
        distance, diagnostics, placement = route_class(
            network, tree, sources, cells, label
        )
        distances[label] = distance
        connector_diagnostics[label] = diagnostics
        placements[label] = placement
    log(f"  Dijkstra runs: {len(classes)}")

    step("STEP 5  City and district access metrics")
    masks = {label: ud.within_budget(d, BUDGET_M) for label, d in distances.items()}
    masks["healthcare_and_education"] = masks["healthcare"] & masks["education"]

    city_row: dict[str, object] = {
        "analysis": cfg.PHASE2C_ANALYSIS_VERSION,
        "population_total": round(city_population, 6),
        "population_cells": int(len(cells)),
        "walking_speed_kmh": cfg.MAIN_WALK_SPEED_KMH,
        "walking_time_minutes": cfg.WALK_TIME_LIMIT_MINUTES,
        "distance_budget_m": BUDGET_M,
    }
    for label in ("healthcare", "education", "bazaar", "healthcare_and_education"):
        accessible = ud.weighted_population(population, masks[label])
        city_row[f"{label}_10min_population"] = round(accessible, 6)
        city_row[f"{label}_10min_pct"] = round(
            ud.percentage(accessible, city_population), 9
        )
        city_row[f"{label}_accessible_cells"] = int(masks[label].sum())
        log(f"  {label}: {accessible:,.6f} people "
            f"({city_row[f'{label}_10min_pct']:.9f}%)")

    district_ids = cells.district_name.to_numpy(dtype=str)
    rows = []
    for name in district_names:
        selector = district_ids == name
        district_population = float(population[selector].sum(dtype=np.float64))
        row: dict[str, object] = {
            "district_name": name,
            "population": round(district_population, 6),
        }
        for label in ("healthcare", "education", "bazaar", "healthcare_and_education"):
            accessible = ud.weighted_population(
                population[selector], masks[label][selector]
            )
            row[f"{label}_10min_population"] = round(accessible, 6)
            row[f"{label}_10min_pct"] = round(
                ud.percentage(accessible, district_population), 9
            )
        rows.append(row)
    district = pd.DataFrame(rows)

    step("STEP 6  District facility supply")
    healthcare_counts = district_supply(
        healthcare, "facility_category", cfg.PHASE2C_HEALTHCARE_CATEGORIES, district_names
    )
    education_counts = district_supply(
        education, "education_category", cfg.PHASE2C_EDUCATION_CATEGORIES, district_names
    )
    district = district.merge(healthcare_counts, on="district_name", validate="1:1")
    district = district.merge(education_counts, on="district_name", validate="1:1")
    district["healthcare_total"] = district.hospitals + district.clinics
    district["education_total"] = (
        district.schools + district.colleges
        + district.universitys + district.kindergartens
    )
    district = district.rename(columns={"universitys": "universities"})
    log(f"  healthcare {int(district.healthcare_total.sum())}, "
        f"education {int(district.education_total.sum())}")

    step("STEP 7  Walk-network density")
    edges = ud.canonical_edge_geometries(network)
    projected = districts.to_crs(cfg.METRIC_CRS).set_index("district_name")
    polygons = {name: projected.loc[name, "geometry"] for name in district_names}
    lengths, length_detail = ud.partition_network_length_km(edges, polygons)
    union_km = ud.union_clipped_length_km(edges, polygons)
    stored_boundary = gpd.read_file(cfg.ANALYSIS_BOUNDARY_FILE).to_crs(cfg.METRIC_CRS)
    stored_km = ud.clipped_length_km(edges, stored_boundary.geometry.iloc[0])
    district_sum = float(sum(lengths.values()))
    border_km = float(length_detail["shared_border_km"])
    log(f"  {length_detail['edges_touching_multiple_districts']:,} edges span more than "
        f"one district; {border_km:,.6f} km lies on shared borders and is assigned once")
    log(f"  district partition total {district_sum:,.6f} km; district-union clip "
        f"{union_km:,.6f} km; difference {abs(district_sum - union_km):.9f} km")
    log(f"  stored analysis_boundary.geojson clips {stored_km:,.6f} km "
        f"({abs(stored_km - union_km):.6f} km from the union, GeoJSON coordinate rounding)")
    if abs(district_sum - union_km) > LENGTH_TOLERANCE_KM:
        raise SystemExit(
            f"district walk-network lengths ({district_sum:.9f} km) do not reconcile "
            f"with the district-union clip ({union_km:.9f} km)"
        )
    district["walk_network_km"] = district.district_name.map(lengths).round(6)

    step("STEP 8  Reuse current transit and bazaar supply, normalize rates")
    keep = [
        "district_name", "official_population", "area_km2",
        "population_density_per_km2", "metro_access_pct", "bus_only_pct",
        "underserved_pct", "metro_stations_in_district",
        "metro_access_points_in_district", "bus_stops_in_district",
        "bazaars_in_district",
    ]
    district = district.merge(current[keep], on="district_name", validate="1:1")
    district = district.rename(
        columns={
            "metro_stations_in_district": "metro_stations",
            "metro_access_points_in_district": "metro_access_points",
            "bus_stops_in_district": "bus_stops",
            "bazaars_in_district": "bazaars",
        }
    )
    district["walk_network_density_km_per_km2"] = (
        district.walk_network_km / district.area_km2
    ).round(9)
    for column, count in (
        ("healthcare_facilities_per_10k", "healthcare_total"),
        ("education_facilities_per_10k", "education_total"),
        ("bazaars_per_10k", "bazaars"),
        ("bus_stops_per_10k", "bus_stops"),
    ):
        district[column] = [
            round(ud.per_capita_rate(c, p, 10_000), 9)
            for c, p in zip(district[count], district.official_population)
        ]
    # Metro stations stay a raw count. At 50 stations across 12 districts a
    # per-capita rate would be dominated by whether a district happens to hold
    # one extra station, which reads as precision the sparse network cannot
    # support.
    district = district.sort_values("district_name", kind="stable").reset_index(drop=True)

    ordered = [
        "district_name", "official_population", "area_km2",
        "population_density_per_km2",
        "metro_access_pct", "bus_only_pct", "underserved_pct",
        "metro_stations", "metro_access_points", "bus_stops", "bus_stops_per_10k",
        "hospitals", "clinics", "healthcare_total", "healthcare_facilities_per_10k",
        "healthcare_10min_population", "healthcare_10min_pct",
        "schools", "colleges", "universities", "kindergartens", "education_total",
        "education_facilities_per_10k",
        "education_10min_population", "education_10min_pct",
        "bazaars", "bazaars_per_10k",
        "bazaar_10min_population", "bazaar_10min_pct",
        "healthcare_and_education_10min_population",
        "healthcare_and_education_10min_pct",
        "population", "walk_network_km", "walk_network_density_km_per_km2",
    ]
    district = district[ordered]
    ud.write_csv_lf(district, cfg.URBAN_DIMENSIONS_DISTRICT_FILE)
    log(f"  wrote {cfg.URBAN_DIMENSIONS_DISTRICT_FILE.name}: {len(district)} rows")

    city_row["walk_network_km"] = round(union_km, 6)
    city_row["walk_network_density_km_per_km2"] = round(
        union_km / float(district.area_km2.sum()), 9
    )
    city_row["healthcare_facilities"] = int(district.healthcare_total.sum())
    city_row["education_facilities"] = int(district.education_total.sum())
    city_row["bazaars"] = int(district.bazaars.sum())
    city = pd.DataFrame([city_row])
    ud.write_csv_lf(city, cfg.URBAN_DIMENSIONS_CITY_FILE)
    log(f"  wrote {cfg.URBAN_DIMENSIONS_CITY_FILE.name}: {len(city)} row")

    step("STEP 9  Deterministic Phase 2C manifest")
    healthcare_meta = _class_metadata(
        healthcare, "facility_category", cfg.PHASE2C_HEALTHCARE_CATEGORIES,
        cfg.HEALTHCARE_FACILITIES_FILE,
    )
    education_meta = _class_metadata(
        education, "education_category", cfg.PHASE2C_EDUCATION_CATEGORIES,
        cfg.EDUCATION_FACILITIES_FILE,
    )
    manifest = {
        "analysis": "Phase 2C current urban dimensions",
        "analysis_version": cfg.PHASE2C_ANALYSIS_VERSION,
        "period": "current",
        "historical_facility_claims": False,
        "composite_score_or_ranking": False,
        "osm_licence": "ODbL 1.0",
        "city_clipping_rule": (
            "a facility is retained when its routing representative point lies "
            "within data/processed/tashkent_boundary.geojson"
        ),
        "analysis_geography": {
            "districts": len(district_names),
            "excluded": "Yangi Toshkent Tumani has no matching official SIAT population row",
            "official_population": official_total,
        },
        "population": {
            "method": (
                "WorldPop 2026 cells calibrated independently within each district "
                "to SIAT 2026-Q2 district totals; identical to the current headline"
            ),
            "cells": int(len(cells)),
            "total": round(city_population, 6),
            "cache": relative(cfg.POPULATION_CELLS_CACHE),
        },
        "pedestrian_network": {
            "path": relative(cfg.WALK_GRAPH_FILE),
            "nodes": network.n_nodes,
            "stored_edge_records": network.stats["stored_edge_records"],
            "canonical_routing_edges": network.n_edges,
            "routing_crs": cfg.METRIC_CRS,
            "fixed_current_snapshot": True,
        },
        "routing": {
            "engine": "scripts/accessibility_utils.py edge-aware primitives",
            "walking_speed_kmh": cfg.MAIN_WALK_SPEED_KMH,
            "walking_time_minutes": cfg.WALK_TIME_LIMIT_MINUTES,
            "distance_budget_m": BUDGET_M,
            "classification": "unrounded network distance <= 800.0 m",
            "dijkstra_runs": len(classes),
            "destination_classes": sorted(classes),
            "source_representative_point_rule": (
                "OSM node as-is; polygon or multipolygon uses a representative "
                "point guaranteed inside the feature; line uses its midpoint. "
                "These are routing proxies, not verified pedestrian entrances."
            ),
            "connector_diagnostics": connector_diagnostics,
            "source_snap_placement": placements,
        },
        "sources": {
            "healthcare": healthcare_meta,
            "education": education_meta,
            "bazaars": {
                "reused_existing_layer": relative(cfg.BAZAARS_FILE),
                "definition": "amenity=marketplace only",
                "count": int(len(bazaars)),
                "coverage": "mapped lower bound, not a census",
            },
        },
        "walk_network_density": {
            "method": (
                "canonical undirected routing edges, projected EPSG:32642 "
                "geometry clipped to each district polygon, summed and divided "
                "by district area"
            ),
            "double_counting_guard": (
                "canonical undirected edges are used, never the stored "
                "directional GraphML records"
            ),
            "shared_border_rule": (
                "Tashkent district boundaries follow major roads, so each edge "
                "is partitioned individually and border-coincident length is "
                "assigned to the alphabetically first district covering it. "
                "District lengths are therefore a partition of the network."
            ),
            "shared_border_km": round(border_km, 6),
            "edges_touching_multiple_districts": length_detail[
                "edges_touching_multiple_districts"
            ],
            "district_union_clipped_km": round(union_km, 6),
            "stored_analysis_boundary_clipped_km": round(stored_km, 6),
            "stored_boundary_note": (
                "analysis_boundary.geojson stores the same area with "
                "GeoJSON-rounded coordinates, so it clips a marginally "
                "different length; the district union is the reconciliation target"
            ),
            "district_clipped_total_km": round(district_sum, 6),
            "reconciliation_difference_km": round(abs(district_sum - union_km), 9),
            "label": "walk-network density, not a walkability score",
        },
        "city_access": {
            f"{label}_10min_pct": city_row[f"{label}_10min_pct"]
            for label in ("healthcare", "education", "bazaar", "healthcare_and_education")
        },
        "input_files": {
            relative(path): ud.provenance_record(path, basis)
            for path, basis in (
                (cfg.DISTRICTS_FILE, ud.HASH_BASIS_CANONICAL_TEXT),
                (cfg.BOUNDARY_FILE, ud.HASH_BASIS_CANONICAL_TEXT),
                (cfg.ANALYSIS_BOUNDARY_FILE, ud.HASH_BASIS_CANONICAL_TEXT),
                (cfg.BAZAARS_FILE, ud.HASH_BASIS_CANONICAL_TEXT),
                (cfg.DISTRICT_ACCESS_METRICS_FILE, ud.HASH_BASIS_CANONICAL_TEXT),
                (cfg.WALK_GRAPH_FILE, ud.HASH_BASIS_RAW_BYTES),
                (cfg.POPULATION_CELLS_CACHE, ud.HASH_BASIS_RAW_BYTES),
            )
        },
        "output_files": {
            relative(path): ud.provenance_record(path, basis)
            for path, basis in (
                (cfg.HEALTHCARE_FACILITIES_FILE, ud.HASH_BASIS_CANONICAL_TEXT),
                (cfg.EDUCATION_FACILITIES_FILE, ud.HASH_BASIS_CANONICAL_TEXT),
                (cfg.URBAN_DIMENSIONS_CITY_FILE, ud.HASH_BASIS_CANONICAL_TEXT),
                (cfg.URBAN_DIMENSIONS_DISTRICT_FILE, ud.HASH_BASIS_CANONICAL_TEXT),
            )
        },
        "limitations": [
            "Healthcare, education and bazaar layers are current OpenStreetMap snapshots.",
            "OpenStreetMap facility coverage is incomplete and is not a census.",
            "Facility counts are mapped OSM objects after documented deduplication.",
            "Representative points are routing proxies, not verified pedestrian entrances.",
            "Ten-minute access is physical pedestrian-network proximity only.",
            "No measure of quality, capacity, staffing, opening hours, affordability, eligibility, catchment rules or specialization is implied.",
            "Bazaar coverage remains an amenity=marketplace mapped lower bound.",
            "Walk-network density is a network-density proxy, not a general walkability score.",
            "Transit supply counts do not measure service frequency or quality.",
            "No historical healthcare, education or bazaar availability is computed.",
        ],
    }
    ud.write_json_lf(cfg.PHASE2C_MANIFEST_PATH, manifest)
    log(f"  wrote {relative(cfg.PHASE2C_MANIFEST_PATH)}")

    step("Phase 2C analysis complete")
    log("  Next: python scripts/validate_phase2_urban_dimensions.py")
    return 0


def _class_metadata(
    frame: gpd.GeoDataFrame, column: str, categories, path: Path
) -> dict:
    """Combine the committed layer's own acquisition provenance with a recount.

    The counts are recomputed here from the committed features rather than
    trusted, so a mismatch between the layer and its recorded provenance shows
    up in the manifest instead of being carried silently.
    """
    provenance = dict(ud.read_geojson_provenance(path))
    named = int(frame["name"].notna().sum())
    provenance["recounted_clean"] = {
        "total": int(len(frame)),
        "by_category": {c: int((frame[column] == c).sum()) for c in categories},
        "named": named,
        "unnamed": int(len(frame) - named),
    }
    provenance["source_file"] = relative(path)
    return provenance


if __name__ == "__main__":
    raise SystemExit(main())
