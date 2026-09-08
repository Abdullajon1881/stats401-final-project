"""Validate the Week 3 processed datasets.

Run from the repository root:

    python scripts/validate_data.py

Exits 0 when every critical check passes, 1 otherwise. Warnings describe known
data-quality limitations that do not invalidate the foundation; they are printed
but do not fail the run.
"""

from __future__ import annotations

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


def validate_worldpop(layers) -> None:
    section("6. WorldPop raster")
    raster = cfg.WORLDPOP_RASTER
    if not raster.exists():
        check(
            False,
            f"WorldPop raster present at {raster.relative_to(cfg.REPO_ROOT)} "
            f"(run: python scripts/acquire_data.py)",
            critical=False,
        )
        print("    skipping raster checks; the file is gitignored and must be downloaded")
        return

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


def preliminary_worldpop_vs_siat(districts, population) -> None:
    """INTERNAL VALIDATION EXPERIMENT - not a project result.

    Confirms only that the raster and the district polygons can be intersected
    and that the magnitudes are comparable. No rescaling or calibration is
    applied; that belongs to the Week 4 analysis milestone.
    """
    section("7. PRELIMINARY integration check (WorldPop vs SIAT) - NOT A RESULT")
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
    print("=" * 74)
    print("Week 3 data foundation - validation")
    print("=" * 74)

    layers = validate_files_present()
    validate_layer_basics(layers)
    districts = validate_districts(layers)
    population = validate_population(districts)
    validate_points(layers, districts)
    validate_worldpop(layers)
    preliminary_worldpop_vs_siat(districts, population)

    section("Summary")
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
