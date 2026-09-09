"""Validate the Week 3 processed datasets.

Run from the repository root:

    python scripts/validate_data.py

Exits 0 when every critical check passes, 1 otherwise. Warnings describe known
data-quality limitations that do not invalidate the foundation; they are printed
but do not fail the run.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402

CRITICAL: list[str] = []
WARNINGS: list[str] = []
PASSED: list[str] = []


def check(condition: bool, description: str, *, critical: bool = True) -> bool:
    """Record the outcome of one check and return it."""
    if condition:
        PASSED.append(description)
        print(f"  PASS  {description}")
    elif critical:
        CRITICAL.append(description)
        print(f"  FAIL  {description}")
    else:
        WARNINGS.append(description)
        print(f"  WARN  {description}")
    return condition


def section(title: str) -> None:
    print("\n" + "-" * 74)
    print(title)
    print("-" * 74)


# --- Expected schemas --------------------------------------------------------
# Columns every consumer downstream is allowed to rely on.
REQUIRED_COLUMNS = {
    cfg.BOUNDARY_FILE: ["osm_type", "osm_id", "name", "area_km2"],
    cfg.DISTRICTS_FILE: [
        "osm_id", "osm_name", "admin_level", "siat_code", "siat_name_en",
        "district_name", "in_siat", "area_km2",
    ],
    cfg.METRO_STATIONS_FILE: ["osm_element", "osm_id", "name", "district_name"],
    cfg.METRO_ENTRANCES_FILE: ["osm_element", "osm_id", "railway", "district_name"],
    cfg.BUS_STOPS_FILE: [
        "osm_element", "osm_id", "stop_role", "district_name", "district_assignment",
    ],
    cfg.BAZAARS_FILE: ["osm_element", "osm_id", "name", "amenity", "district_name"],
}
# Column names that indicate a pandas index was written out by accident.
INDEX_COLUMN_NAMES = {"", "index", "level_0", "unnamed: 0", "fid_1", "field_1"}


def load(path: Path) -> gpd.GeoDataFrame | None:
    if not path.exists():
        return None
    return gpd.read_file(path)


def _manifest_sources() -> dict:
    if not cfg.MANIFEST_PATH.exists():
        return {}
    return json.loads(cfg.MANIFEST_PATH.read_text(encoding="utf-8")).get("sources", {})


def _manifest_output(path: Path) -> dict | None:
    """Find the manifest `outputs` entry describing `path`, if any."""
    wanted = str(path.relative_to(cfg.REPO_ROOT)).replace("\\", "/")
    for source in _manifest_sources().values():
        for output in source.get("outputs", []):
            if output.get("path") == wanted:
                return output
    return None


def validate_files_present() -> dict[Path, gpd.GeoDataFrame | None]:
    section("1. Required files")
    layers: dict[Path, gpd.GeoDataFrame | None] = {}
    for path in REQUIRED_COLUMNS:
        exists = path.exists()
        check(exists, f"{path.name} exists")
        layers[path] = load(path) if exists else None
    check(cfg.SIAT_POPULATION_FILE.exists(), f"{cfg.SIAT_POPULATION_FILE.name} exists")
    check(cfg.DISTRICT_NAME_MAP_FILE.exists(), f"{cfg.DISTRICT_NAME_MAP_FILE.name} exists")
    check(cfg.MANIFEST_PATH.exists(), f"{cfg.MANIFEST_PATH.name} exists")
    return layers


def validate_layer_basics(layers: dict[Path, gpd.GeoDataFrame | None]) -> None:
    section("2. Schema, CRS and geometry")
    for path, gdf in layers.items():
        if gdf is None:
            continue
        name = path.name
        expected = REQUIRED_COLUMNS[path]
        missing = [c for c in expected if c not in gdf.columns]
        check(not missing, f"{name}: has required columns (missing: {missing or 'none'})")

        stray = [c for c in gdf.columns if str(c).strip().lower() in INDEX_COLUMN_NAMES]
        check(not stray, f"{name}: no accidental index column (found: {stray or 'none'})")

        check(gdf.crs is not None, f"{name}: CRS is explicitly set")
        if gdf.crs is not None:
            check(
                gdf.crs.to_epsg() == 4326,
                f"{name}: stored in EPSG:4326 (got EPSG:{gdf.crs.to_epsg()})",
            )

        check(len(gdf) > 0, f"{name}: is not empty")
        check(not gdf.geometry.isna().any(), f"{name}: no null geometry")
        check(not gdf.geometry.is_empty.any(), f"{name}: no empty geometry")
        check(bool(gdf.geometry.is_valid.all()), f"{name}: all geometries valid")

        if "osm_id" in gdf.columns:
            duplicated = int(gdf.osm_id.duplicated().sum())
            check(duplicated == 0, f"{name}: osm_id unique ({duplicated} duplicates)")


def validate_districts(layers) -> gpd.GeoDataFrame | None:
    section("3. District boundaries")
    districts = layers.get(cfg.DISTRICTS_FILE)
    boundary = layers.get(cfg.BOUNDARY_FILE)
    if districts is None or boundary is None:
        check(False, "district and boundary layers loadable")
        return None

    analysis = districts[districts.in_siat.astype(bool)]
    check(
        len(analysis) == cfg.EXPECTED_ANALYSIS_DISTRICTS,
        f"exactly {cfg.EXPECTED_ANALYSIS_DISTRICTS} SIAT-matched districts "
        f"(got {len(analysis)})",
    )
    check(
        len(districts) == cfg.EXPECTED_OSM_DISTRICTS,
        f"exactly {cfg.EXPECTED_OSM_DISTRICTS} districts in the OSM city relation "
        f"(got {len(districts)})",
    )
    check(
        analysis.district_name.is_unique,
        "SIAT-matched district names are unique",
    )
    check(analysis.siat_code.is_unique, "SIAT district codes are unique")
    check(
        bool((districts.admin_level.astype(str) == "6").all()),
        "every district is admin_level=6",
    )

    metric = districts.to_crs(cfg.METRIC_CRS)
    areas = metric.area / 1e6
    check(bool((areas > 5).all()), f"every district larger than 5 km2 (min {areas.min():.1f})")
    check(
        bool((areas < 400).all()),
        f"no district larger than 400 km2 (max {areas.max():.1f})",
    )

    city_geom = boundary.to_crs(cfg.METRIC_CRS).geometry.iloc[0]
    inside_fraction = metric.geometry.intersection(city_geom).area / metric.area
    check(
        bool((inside_fraction > 0.99).all()),
        f"every district lies inside the city boundary "
        f"(min overlap {inside_fraction.min():.4f})",
    )

    union_area = metric.union_all().area / 1e6
    city_area = city_geom.area / 1e6
    coverage = union_area / city_area
    check(
        0.99 <= coverage <= 1.01,
        f"districts tile the city boundary (union/city = {coverage:.4f})",
    )

    # Districts must not overlap each other beyond sliver-level topology noise.
    overlap = 0.0
    geoms = list(metric.geometry)
    for i in range(len(geoms)):
        for j in range(i + 1, len(geoms)):
            overlap += geoms[i].intersection(geoms[j]).area
    check(
        overlap / 1e6 < 1.0,
        f"district polygons do not overlap materially ({overlap / 1e6:.4f} km2 total)",
    )

    print("\n  districts as stored:")
    for _, row in districts.sort_values(["in_siat", "district_name"],
                                        ascending=[False, True]).iterrows():
        flag = "SIAT" if row.in_siat else "no SIAT row"
        print(f"    {str(row.district_name):26s} {row.area_km2:8.2f} km2   [{flag}]")

    unmatched = districts[~districts.in_siat.astype(bool)]
    if len(unmatched):
        for _, row in unmatched.iterrows():
            check(
                False,
                f"district '{row.district_name}' (OSM relation {row.osm_id}) has no SIAT "
                f"population row - see docs/data_sources.md",
                critical=False,
            )
    return districts


def validate_population(districts: gpd.GeoDataFrame | None) -> pd.DataFrame | None:
    section("4. Official district population (SIAT)")
    if not cfg.SIAT_POPULATION_FILE.exists():
        check(False, "SIAT population file loadable")
        return None

    table = pd.read_csv(cfg.SIAT_POPULATION_FILE, dtype={"siat_code": str})
    expected = ["siat_code", "district_name", "population", "reference_period"]
    missing = [c for c in expected if c not in table.columns]
    check(not missing, f"population CSV columns present (missing: {missing or 'none'})")

    stray = [c for c in table.columns if str(c).strip().lower() in INDEX_COLUMN_NAMES]
    check(not stray, f"population CSV has no index column (found: {stray or 'none'})")

    check(
        len(table) == cfg.EXPECTED_ANALYSIS_DISTRICTS,
        f"{cfg.EXPECTED_ANALYSIS_DISTRICTS} population rows (got {len(table)})",
    )
    check(table.siat_code.is_unique, "SIAT codes unique in population CSV")
    check(table.district_name.is_unique, "district names unique in population CSV")
    check(
        bool(pd.to_numeric(table.population, errors="coerce").notna().all()),
        "all population values numeric",
    )
    check(bool((table.population > 0).all()), "all population values positive")
    check(
        bool(table.population.between(20_000, 1_000_000).all()),
        "population values plausible for a city district (20k-1M)",
    )
    check(
        table.reference_period.nunique() == 1,
        f"single reference period ({table.reference_period.unique().tolist()})",
    )

    total = int(table.population.sum())
    print(f"\n  total population across 12 districts: {total:,} "
          f"({table.reference_period.iloc[0]})")

    if districts is not None:
        analysis = districts[districts.in_siat.astype(bool)]
        codes_geo = set(analysis.siat_code.astype(str))
        codes_pop = set(table.siat_code.astype(str))
        check(codes_geo == codes_pop, "district geometry and population share the same SIAT codes")
        names_geo = set(analysis.district_name)
        names_pop = set(table.district_name)
        check(names_geo == names_pop, "district geometry and population share the same names")
    return table


def validate_points(layers, districts) -> None:
    section("5. Transit and POI point layers")
    if districts is None:
        return
    city = layers.get(cfg.BOUNDARY_FILE)
    city_geom = city.to_crs(cfg.METRIC_CRS).geometry.iloc[0]

    for path, label, minimum in (
        (cfg.METRO_STATIONS_FILE, "metro stations", 30),
        (cfg.METRO_ENTRANCES_FILE, "metro entrances", 1),
        (cfg.BUS_STOPS_FILE, "bus stops", 200),
        (cfg.BAZAARS_FILE, "bazaars", 5),
    ):
        gdf = layers.get(path)
        if gdf is None:
            continue
        metric = gdf.to_crs(cfg.METRIC_CRS)
        check(
            bool((metric.geometry.geom_type == "Point").all()),
            f"{label}: every feature is a Point",
        )
        inside = metric.geometry.within(city_geom)
        check(bool(inside.all()), f"{label}: all {len(gdf)} inside the city boundary "
                                  f"({int((~inside).sum())} outside)")
        check(len(gdf) >= minimum, f"{label}: plausible count ({len(gdf)} >= {minimum})")

        if "district_name" in gdf.columns:
            unassigned = int(gdf.district_name.isna().sum())
            check(
                unassigned == 0,
                f"{label}: every feature has a district ({unassigned} unassigned)",
            )
            if "district_assignment" in gdf.columns:
                on_border = int((gdf.district_assignment == "boundary_nearest").sum())
                check(
                    on_border <= len(gdf) * 0.1,
                    f"{label}: {on_border} of {len(gdf)} sit exactly on a district "
                    f"border and were assigned to the nearest district",
                    critical=False,
                )
            print(f"    {label} by district:")
            counts = gdf.district_name.value_counts(dropna=False)
            for name, count in counts.items():
                print(f"      {str(name):26s} {count:5d}")


def validate_manifest_counts(layers, population) -> None:
    """Cross-check the manifest's recorded counts against the actual files.

    The manifest is the provenance record. If it claims a count the committed
    data does not have, the provenance is wrong and that is a hard failure, not
    a warning.
    """
    section("6. Source manifest vs processed files")
    if not cfg.MANIFEST_PATH.exists():
        check(False, "source_manifest.json loadable")
        return

    manifest = json.loads(cfg.MANIFEST_PATH.read_text(encoding="utf-8"))
    sources = manifest.get("sources", {})

    def counted(path: Path) -> int | None:
        gdf = layers.get(path)
        return None if gdf is None else len(gdf)

    expectations = [
        ("osm_metro", "final_stations", counted(cfg.METRO_STATIONS_FILE), "metro stations"),
        ("osm_metro", "final_entrances", counted(cfg.METRO_ENTRANCES_FILE), "metro entrances"),
        ("osm_bus_stops", "final_bus_stops", counted(cfg.BUS_STOPS_FILE), "bus stops"),
        (
            "osm_bus_stops",
            "without_name",
            None
            if layers.get(cfg.BUS_STOPS_FILE) is None
            else int(layers[cfg.BUS_STOPS_FILE]["name"].isna().sum()),
            "unnamed bus stops",
        ),
        ("osm_bazaars", "final_bazaars", counted(cfg.BAZAARS_FILE), "bazaars"),
        ("osm_boundaries", "districts_total", counted(cfg.DISTRICTS_FILE), "districts"),
        (
            "siat_population",
            "district_rows",
            None if population is None else len(population),
            "SIAT population rows",
        ),
    ]
    for source_key, field, actual, label in expectations:
        recorded = sources.get(source_key, {}).get("feature_counts", {}).get(field)
        if recorded is None:
            check(False, f"manifest records {source_key}.{field} for {label}")
            continue
        if actual is None:
            check(False, f"{label}: file present to compare against the manifest")
            continue
        check(
            recorded == actual,
            f"{label}: manifest says {recorded}, file has {actual}",
        )

    # The manifest's notes must not contradict themselves. Two notes with the
    # same (source, id) would mean a stale note survived a rerun.
    notes = manifest.get("notes", [])
    keys = [(n.get("source"), n.get("id")) for n in notes]
    duplicates = {k for k in keys if keys.count(k) > 1}
    check(not duplicates, f"manifest notes have unique (source, id) keys "
                          f"(duplicates: {sorted(duplicates) or 'none'})")
    # Notes quote live counts in their text. That text is what a reader believes,
    # so it has to agree with the file too - this is the exact bug class that let
    # "233 of 2164" and "231 of 2163" sit in the manifest at the same time.
    bus = layers.get(cfg.BUS_STOPS_FILE)
    note_text = next(
        (n.get("text", "") for n in notes if n.get("id") == "stops_without_name"), None
    )
    if bus is not None and note_text is not None:
        expected = f"{int(bus['name'].isna().sum())} of {len(bus)} bus stops"
        check(
            expected in note_text,
            f"bus-stop note quotes the current counts ('{expected}')",
        )

    print(f"    manifest notes: {len(notes)}")
    for note in notes:
        print(f"      [{note.get('source')}/{note.get('id')}] {note.get('text', '')[:90]}")


def validate_worldpop(layers, *, required: bool) -> None:
    section("7. WorldPop raster (external artifact)")
    raster = cfg.WORLDPOP_RASTER
    if not raster.exists():
        check(
            False,
            f"WorldPop raster present at {raster.relative_to(cfg.REPO_ROOT)} "
            f"(run: python scripts/acquire_data.py)",
            critical=required,
        )
        print("    skipping raster checks; the file is gitignored and must be downloaded")
        return

    # Size and checksum must match what the manifest recorded, otherwise the
    # provenance record does not describe the file actually on disk.
    recorded = _manifest_output(cfg.WORLDPOP_RASTER)
    if recorded is None:
        check(False, "manifest records an output entry for the WorldPop raster")
    else:
        actual_size = cfg.file_size_bytes(raster)
        check(
            recorded.get("size_bytes") == actual_size,
            f"WorldPop size matches the manifest "
            f"({recorded.get('size_bytes')} vs {actual_size})",
        )
        recorded_hash = recorded.get("sha256")
        if recorded_hash is None:
            check(False, "manifest records a sha256 for the WorldPop raster")
        else:
            actual_hash = cfg.sha256_file(raster)
            check(
                recorded_hash == actual_hash,
                f"WorldPop sha256 matches the manifest ({actual_hash[:16]}...)",
            )

    import rasterio
    from rasterio.mask import mask

    boundary = layers.get(cfg.BOUNDARY_FILE)
    with rasterio.open(raster) as src:
        check(src.crs is not None, f"raster CRS is set ({src.crs})")
        check(src.count == 1, f"raster has a single band (got {src.count})")
        check(src.nodata is not None, f"raster declares a nodata value ({src.nodata})")

        city_wgs = boundary.to_crs(src.crs)
        left, bottom, right, top = city_wgs.total_bounds
        rb = src.bounds
        overlaps = (
            left < rb.right and right > rb.left and bottom < rb.top and top > rb.bottom
        )
        check(overlaps, "raster bounding box overlaps the Tashkent city boundary")

        geoms = [city_wgs.geometry.iloc[0]]
        clipped, _ = mask(src, geoms, crop=True, filled=True, nodata=src.nodata)
        band = clipped[0]
        valid = band[(band != src.nodata) & (band == band)]
        check(valid.size > 0, f"raster has valid cells over Tashkent ({valid.size:,} cells)")
        if valid.size:
            check(bool((valid >= 0).all()), "no negative population values over Tashkent")
            total = float(valid.sum())
            print(f"    valid cells over city : {valid.size:,}")
            print(f"    cell value range      : {valid.min():.4f} .. {valid.max():.2f}")
            print(f"    raw sum over city     : {total:,.0f} persons")
            check(
                500_000 < total < 8_000_000,
                f"raw WorldPop city total is in a plausible range ({total:,.0f})",
            )


def validate_walk_graph(layers, *, required: bool) -> None:
    """Validate the pedestrian graph that lives outside git.

    The graph is the input to every Week 4 isochrone, so a corrupt or truncated
    download must fail loudly rather than be discovered mid-analysis.
    """
    section("8. Pedestrian walk network (external artifact)")
    path = cfg.WALK_GRAPH_FILE
    if not path.exists():
        check(
            False,
            f"walk graph present at {path.relative_to(cfg.REPO_ROOT)} "
            f"(run: python scripts/acquire_data.py)",
            critical=required,
        )
        print("    skipping graph checks; the file is gitignored and must be rebuilt")
        return

    import networkx as nx
    import osmnx as ox

    try:
        graph = ox.load_graphml(path)
    except Exception as error:  # noqa: BLE001 - a load failure is the finding
        check(False, f"walk graph loads with OSMnx ({type(error).__name__}: {error})")
        return
    check(True, "walk graph loads with OSMnx")

    n_nodes = graph.number_of_nodes()
    n_edges = graph.number_of_edges()
    check(n_nodes > 0 and n_edges > 0,
          f"walk graph is non-empty ({n_nodes:,} nodes, {n_edges:,} edges)")

    graph_crs = graph.graph.get("crs")
    check(graph_crs is not None, f"walk graph declares a CRS ({graph_crs})")
    if graph_crs is not None:
        check(
            str(graph_crs).lower().replace("epsg:", "") == "4326",
            f"walk graph is stored in EPSG:4326 (got {graph_crs})",
        )

    recorded = _manifest_sources().get("osm_walk_network", {}).get("feature_counts", {})
    if not recorded:
        check(False, "manifest records node/edge counts for the walk network")
    else:
        check(recorded.get("nodes") == n_nodes,
              f"walk graph node count matches the manifest "
              f"({recorded.get('nodes')} vs {n_nodes})")
        check(recorded.get("edges") == n_edges,
              f"walk graph edge count matches the manifest "
              f"({recorded.get('edges')} vs {n_edges})")

    # Node coordinates
    xs = [d.get("x") for _, d in graph.nodes(data=True)]
    ys = [d.get("y") for _, d in graph.nodes(data=True)]
    finite_xy = all(
        isinstance(v, (int, float)) and math.isfinite(v) for v in xs
    ) and all(isinstance(v, (int, float)) and math.isfinite(v) for v in ys)
    check(finite_xy, "every node has finite x/y coordinates")

    # Edge lengths drive the isochrones, so they must all be usable numbers.
    lengths = [d.get("length") for _, _, d in graph.edges(data=True)]
    missing = sum(1 for v in lengths if v is None)
    check(missing == 0, f"every edge has a length attribute ({missing} missing)")
    numeric = [v for v in lengths if isinstance(v, (int, float)) and math.isfinite(v)]
    check(len(numeric) == len(lengths),
          f"every edge length is numeric and finite "
          f"({len(lengths) - len(numeric)} bad values)")
    if numeric:
        non_positive = sum(1 for v in numeric if v <= 0)
        check(non_positive == 0,
              f"every edge has positive length ({non_positive} non-positive)")
        print(f"    edge length: min {min(numeric):.2f} m, "
              f"median {sorted(numeric)[len(numeric) // 2]:.2f} m, "
              f"max {max(numeric):.2f} m, total {sum(numeric) / 1000:,.0f} km")

    # Spatial extent must cover the study area.
    boundary = layers.get(cfg.BOUNDARY_FILE)
    if boundary is not None and xs and ys:
        west, south, east, north = boundary.total_bounds
        gw, gs, ge, gn = min(xs), min(ys), max(xs), max(ys)
        print(f"    graph bounds : {gw:.4f}, {gs:.4f}, {ge:.4f}, {gn:.4f}")
        print(f"    city  bounds : {west:.4f}, {south:.4f}, {east:.4f}, {north:.4f}")
        check(
            gw <= west and gs <= south and ge >= east and gn >= north,
            "walk graph extent contains the Tashkent city boundary",
        )

    # Connectivity is reported, not enforced: a real pedestrian network always
    # contains small isolated fragments (courtyards, service areas, mapping
    # gaps), so demanding a single component would be a brittle false alarm.
    components = list(nx.weakly_connected_components(graph))
    largest = max(len(c) for c in components)
    share = largest / n_nodes
    print(f"    weakly connected components: {len(components):,}")
    print(f"    largest component          : {largest:,} nodes ({share:.2%})")
    check(share > 0.90,
          f"largest connected component holds most of the network ({share:.2%})",
          critical=False)


def validate_temporal_diagnostic() -> None:
    """Check the committed WorldPop 2020-vs-2026 cell-level diagnostic.

    The docs draw a methodological conclusion from this file, so it has to be
    present, internally consistent, and built on aligned rasters.
    """
    section("9. WorldPop temporal diagnostic")
    path = cfg.WORLDPOP_TEMPORAL_FILE
    if not check(path.exists(), f"{path.name} exists "
                                f"(run: python scripts/audit_population_surface.py)"):
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        check(False, f"{path.name} is valid JSON ({error})")
        return
    check(True, f"{path.name} is valid JSON")

    check(data.get("years") == [2020, 2026],
          f"diagnostic compares 2020 and 2026 (got {data.get('years')})")
    check(bool(data.get("grid_aligned")),
          "rasters were confirmed to share one pixel grid")

    grid = data.get("grid_compatibility", {})
    for key in ("crs", "dimensions", "transform", "nodata"):
        check(bool(grid.get(key, {}).get("match")),
              f"raster {key} matched between years")
    check(bool(grid.get("bounds_match")), "raster bounds matched between years")

    # Every reported metric must be a finite number; a NaN would silently
    # invalidate the conclusion drawn in docs/data_sources.md.
    def finite_leaves(node, trail=""):
        bad = []
        if isinstance(node, dict):
            for key, value in node.items():
                bad += finite_leaves(value, f"{trail}.{key}" if trail else key)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            if not math.isfinite(node):
                bad.append(trail)
        return bad

    for group in ("cells", "totals", "scaling_factor", "ratio_percentiles",
                  "residuals_after_least_squares_scaling",
                  "fraction_of_cells_matching_scalar", "modelled_differences"):
        bad = finite_leaves(data.get(group, {}), group)
        check(not bad, f"{group}: all metrics finite (bad: {bad or 'none'})")

    residuals = data.get("residuals_after_least_squares_scaling", {})
    l1 = residuals.get("relative_l1_error")
    check(
        isinstance(l1, float) and math.isfinite(l1) and 0.0 <= l1 <= 1.0,
        f"relative L1 error recorded as a finite fraction ({l1})",
    )

    correlation = data.get("pearson_correlation_cell_values")
    check(isinstance(correlation, float) and math.isfinite(correlation)
          and -1.0 <= correlation <= 1.0,
          f"cell-level correlation is a finite value in [-1, 1] ({correlation})")

    cells = data.get("cells", {})
    check(cells.get("valid_in_both", 0) > 0,
          f"cells were actually compared ({cells.get('valid_in_both'):,})")

    verdict = data.get("is_pure_scalar_multiple")
    check(isinstance(verdict, bool), f"verdict is recorded ({verdict})")
    print(f"    correlation                : {correlation}")
    print(f"    fitted scalar (LS)         : "
          f"{data.get('scaling_factor', {}).get('least_squares')}")
    print(f"    pure scalar multiple       : {verdict}")
    print(f"    relative L1 error          : {l1}")
    print(f"    within 1% / 5% of scalar   : "
          f"{data.get('fraction_of_cells_matching_scalar', {}).get('within_1pct')} / "
          f"{data.get('fraction_of_cells_matching_scalar', {}).get('within_5pct')}")
    if verdict is False:
        check(
            True,
            "2026 is NOT a pure rescaling of 2020; docs must not claim "
            "'no new spatial detail' (see docs/data_sources.md)",
        )


def preliminary_worldpop_vs_siat(districts, population) -> None:
    """INTERNAL VALIDATION EXPERIMENT - not a project result.

    Confirms only that the raster and the district polygons can be intersected
    and that the magnitudes are comparable. No rescaling or calibration is
    applied; that belongs to the Week 4 analysis milestone.
    """
    section("10. PRELIMINARY integration check (WorldPop vs SIAT) - NOT A RESULT")
    if districts is None or population is None or not cfg.WORLDPOP_RASTER.exists():
        print("    skipped (missing raster, districts or population)")
        return

    import rasterio
    from rasterio.mask import mask

    analysis = districts[districts.in_siat.astype(bool)]
    rows = []
    with rasterio.open(cfg.WORLDPOP_RASTER) as src:
        polygons = analysis.to_crs(src.crs)
        for _, row in polygons.iterrows():
            try:
                clipped, _ = mask(src, [row.geometry], crop=True, filled=True,
                                  nodata=src.nodata)
            except ValueError:
                rows.append({"district_name": row.district_name, "worldpop": float("nan")})
                continue
            band = clipped[0]
            valid = band[(band != src.nodata) & (band == band)]
            rows.append({
                "district_name": row.district_name,
                "worldpop": float(valid.sum()) if valid.size else 0.0,
            })

    comparison = pd.DataFrame(rows).merge(
        population[["district_name", "population"]], on="district_name", how="left"
    )
    comparison["ratio"] = comparison.worldpop / comparison.population
    comparison["diff_pct"] = (comparison.ratio - 1) * 100

    print(f"\n  {'district':26s} {'WorldPop':>12s} {'SIAT':>12s} {'ratio':>7s} {'diff %':>8s}")
    print("  " + "-" * 70)
    for _, r in comparison.sort_values("district_name").iterrows():
        print(f"  {r.district_name:26s} {r.worldpop:12,.0f} {r.population:12,.0f} "
              f"{r.ratio:7.3f} {r.diff_pct:+8.1f}")
    wp_total, siat_total = comparison.worldpop.sum(), comparison.population.sum()
    print("  " + "-" * 70)
    print(f"  {'TOTAL':26s} {wp_total:12,.0f} {siat_total:12,.0f} "
          f"{wp_total / siat_total:7.3f} {(wp_total / siat_total - 1) * 100:+8.1f}")

    check(
        bool(comparison.worldpop.notna().all()) and bool((comparison.worldpop > 0).all()),
        "every district intersects the raster and returns a positive total",
    )
    check(
        0.5 < wp_total / siat_total < 2.0,
        f"WorldPop and SIAT city totals are the same order of magnitude "
        f"(ratio {wp_total / siat_total:.3f})",
        critical=False,
    )

    # How much district-level signal does WorldPop actually carry? A correlation
    # near zero means WorldPop cannot be trusted to distribute population
    # *between* districts, and Week 4 must calibrate per district rather than
    # applying a single city-wide factor.
    correlation = float(comparison.worldpop.corr(comparison.population))
    spread = comparison.ratio.max() / comparison.ratio.min()
    print(f"\n  correlation(WorldPop, SIAT) across districts : {correlation:+.3f}")
    print(f"  ratio spread (max/min)                      : {spread:.1f}x")
    check(
        correlation > 0.5,
        f"WorldPop district totals track SIAT district totals (correlation "
        f"{correlation:+.3f}); below 0.5 means WorldPop carries little "
        f"between-district signal and per-district calibration is required",
        critical=False,
    )

    print("\n  NOTE: this is a compatibility check only. Calibration of WorldPop to")
    print("        official SIAT totals is Week 4 work and is NOT applied here.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-only",
        action="store_true",
        help=(
            "check only the artifacts committed to git. Use this on a fresh clone, "
            "before running scripts/acquire_data.py. The default is FULL validation, "
            "which also requires the gitignored WorldPop raster and walk graph."
        ),
    )
    args = parser.parse_args()
    full = not args.repo_only
    mode = "FULL (committed + external artifacts)" if full else "REPOSITORY-ONLY (committed artifacts)"

    print("=" * 74)
    print("Week 3 data foundation - validation")
    print(f"mode: {mode}")
    print("=" * 74)
    if not full:
        print("\n  NOTE: --repo-only skips the WorldPop raster and the walk graph.")
        print("        It cannot certify the foundation on its own; run the full mode")
        print("        after `python scripts/acquire_data.py`.")

    layers = validate_files_present()
    validate_layer_basics(layers)
    districts = validate_districts(layers)
    population = validate_population(districts)
    validate_points(layers, districts)
    validate_manifest_counts(layers, population)
    validate_worldpop(layers, required=full)
    validate_walk_graph(layers, required=full)
    validate_temporal_diagnostic()
    preliminary_worldpop_vs_siat(districts, population)

    section("Summary")
    print(f"  mode    : {mode}")
    print(f"  passed  : {len(PASSED)}")
    print(f"  warnings: {len(WARNINGS)}")
    print(f"  critical: {len(CRITICAL)}")
    for item in WARNINGS:
        print(f"    WARN  {item}")
    for item in CRITICAL:
        print(f"    FAIL  {item}")

    if CRITICAL:
        print("\nVALIDATION FAILED")
        return 1
    print("\nVALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
