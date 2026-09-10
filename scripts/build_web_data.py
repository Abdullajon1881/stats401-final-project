"""Week 5: build the compact web artifacts the D3 prototype consumes.

    python scripts/build_web_data.py

This script CONSUMES the audited Week 4 analysis. It does not recompute network
accessibility, and it never writes to `data/processed/` or `data/`. Every
analytical number in `site/data/` is copied from an audited artifact at full
precision; only display geometry is derived here.

Analytical vs display, which the prototype must not blur:

  ANALYTICAL (copied, never recomputed)
    data/processed/city_access_summary.json
    data/processed/district_access_metrics.csv

  DISPLAY ONLY (derived here, drives no percentage)
    the metro service-area polygon, copied and rounded
    the population-density bins, aggregated from the audited per-cell table
    every point layer

The build is deterministic: no timestamps are written, ordering is stable, and
coordinates are rounded to a fixed precision. Running it twice produces
byte-identical output.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import box, mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
from pipeline_utils import enable_utf8_stdout, log, step  # noqa: E402

SITE_DIR = cfg.REPO_ROOT / "site"
WEB_DATA_DIR = SITE_DIR / "data"

# Display-only source, acquired deliberately by scripts/acquire_metro_lines.py.
# It lives outside data/processed so the analytical boundary is structural.
DISPLAY_DIR = cfg.DATA_DIR / "display"
METRO_LINES_SNAPSHOT = DISPLAY_DIR / "metro_lines_osm.geojson"
METRO_LINES_PROVENANCE = DISPLAY_DIR / "metro_lines_provenance.json"

# ~1.1 m at this latitude: far finer than any mark the map draws, and it keeps
# shared district borders identical on both sides because both round the same.
COORD_PRECISION = 5

# Display-only aggregation for the population layer. 500 m squares over a
# 437.7 km2 study area give roughly two thousand cells: enough to read the
# built-up pattern, few enough to stay light in the browser.
DENSITY_BIN_M = 500.0

WEB_FILES = {
    "city_summary": "city_summary.json",
    "districts": "districts.geojson",
    "metro_isochrone": "metro_isochrone_10min.geojson",
    "metro_access_points": "metro_access_points.geojson",
    "metro_stations": "metro_stations.geojson",
    "bus_stops": "bus_stops.geojson",
    "bazaars": "bazaars.geojson",
    "population_density": "population_density.geojson",
    "metro_lines": "metro_lines.geojson",
    "analysis_mask": "analysis_mask.geojson",
    "sensitivity": "sensitivity.json",
    "manifest": "manifest.json",
}


# ---------------------------------------------------------------------------
# deterministic GeoJSON writing
# ---------------------------------------------------------------------------
def _round_coords(value, precision: int):
    if isinstance(value, (list, tuple)):
        if value and isinstance(value[0], (int, float)):
            return [round(float(v), precision) for v in value]
        return [_round_coords(v, precision) for v in value]
    return value


def _clean(value):
    """JSON-safe scalar. NaN and pandas NA become null, numpy types unwrap.

    Numbers must survive as JSON numbers. bool is checked before int because
    it subclasses it, and plain Python int before float for the same reason -
    a number that fell through to str() here would reach the browser quoted.
    """
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if np.isfinite(number) else None
    if value is pd.NA:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value)
    return None if text in ("nan", "None", "<NA>", "") else text


def reduce_precision(geometry, precision: int = COORD_PRECISION):
    """Snap a geometry to the output coordinate grid, keeping it valid.

    Rounding coordinates naively can collapse a tiny ring below three distinct
    points and produce an invalid polygon - which is exactly what happened to
    the metro service area, whose source geometry is valid. GEOS precision
    reduction snaps to the same grid but repairs the topology as it goes, and
    identical input coordinates still snap identically, so shared district
    borders stay shared.
    """
    if geometry.geom_type not in ("Polygon", "MultiPolygon"):
        return geometry
    reduced = shapely.set_precision(geometry, 10.0 ** -precision)
    if reduced.is_empty:
        return geometry
    if not reduced.is_valid:
        reduced = shapely.make_valid(reduced)
    return reduced


def feature(geometry, properties: dict, precision: int = COORD_PRECISION) -> dict:
    geom = mapping(reduce_precision(geometry, precision))
    return {
        "type": "Feature",
        "properties": {k: _clean(v) for k, v in properties.items()},
        "geometry": {
            "type": geom["type"],
            "coordinates": _round_coords(geom["coordinates"], precision),
        },
    }


DISPLAY_ROLE = "display_only"


def display_feature(geometry, properties: dict,
                    precision: int = COORD_PRECISION) -> dict:
    """Build a feature belonging to a display-only layer, labelled as such.

    The manifest already records which files are display-only, but a GeoJSON
    file travels on its own - the map fetches each one directly - so the
    analytical/display boundary has to survive that journey on the features
    themselves. Every display layer is built through here, which is why a new
    display layer cannot quietly ship without the label: there is no other
    constructor for one.

    Analytical layers (city_summary, districts) deliberately do NOT come
    through here, and must never carry this role.
    """
    return feature(geometry, {**properties, "role": DISPLAY_ROLE}, precision)


def write_json(path: Path, payload: dict) -> int:
    """Write compact, deterministic JSON. No timestamps anywhere.

    Newlines are forced to LF. Without that, Python translates them on Windows
    and every file lands one byte larger in the working tree than in the commit,
    so the byte counts recorded in the manifest would not survive a checkout on
    a platform that does not translate.
    """
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    size = path.stat().st_size
    log(f"    wrote {path.relative_to(cfg.REPO_ROOT)}  ({cfg.human_size(size)})")
    return size


def write_geojson(path: Path, features: list[dict]) -> int:
    return write_json(path, {"type": "FeatureCollection", "features": features})


# Text sources are hashed with newlines normalised to LF. Git stores these files
# with LF but checks them out with CRLF on Windows, so a raw byte hash would
# differ between a Windows and a Linux clone of the same commit and the
# "sources unchanged" check would fail on content that never changed. Binary
# sources are hashed as-is.
TEXT_SUFFIXES = {".json", ".csv", ".geojson", ".txt", ".md"}


def content_hash(path: Path) -> str:
    """SHA-256 of a source, independent of how the checkout wrote its newlines."""
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return cfg.sha256_file(path)
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def short_label(district_name: str) -> str:
    """'Mirzo Ulugbek district' -> 'Mirzo Ulugbek', for chart axes."""
    return district_name.removesuffix(" district")


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------
def require(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(
            f"required audited input missing: {path.relative_to(cfg.REPO_ROOT)}"
        )
    return path


def load_inputs() -> dict:
    step("STEP 1  Audited inputs")
    paths = {
        "city_access_summary": require(cfg.CITY_ACCESS_SUMMARY_FILE),
        "district_access_metrics": require(cfg.DISTRICT_ACCESS_METRICS_FILE),
        "analysis_manifest": require(cfg.ANALYSIS_MANIFEST_PATH),
        "districts": require(cfg.DISTRICTS_FILE),
        "metro_isochrone": require(cfg.METRO_ISOCHRONE_FILE),
        "metro_access_points": require(cfg.METRO_ACCESS_POINTS_FILE),
        "metro_stations": require(cfg.METRO_STATIONS_FILE),
        "bus_stops": require(cfg.BUS_STOPS_FILE),
        "bazaars": require(cfg.BAZAARS_FILE),
        "population_cells": cfg.POPULATION_CELLS_CACHE,
        "metro_lines_snapshot": require(METRO_LINES_SNAPSHOT),
        "metro_lines_provenance": require(METRO_LINES_PROVENANCE),
        "walk_speed_sensitivity": require(cfg.WALK_SPEED_SENSITIVITY_FILE),
        "population_surface_sensitivity": require(cfg.POPULATION_SURFACE_SENSITIVITY_FILE),
    }
    if not paths["population_cells"].exists():
        raise FileNotFoundError(
            f"{paths['population_cells']} is missing. It is the audited Week 4 per-cell "
            f"table and the only legitimate source for the display population-density "
            f"layer. Regenerate it with `python scripts/analyze_accessibility.py` rather "
            f"than substituting another surface."
        )
    for name, path in paths.items():
        log(f"    {name:26s} {path.relative_to(cfg.REPO_ROOT)}")
    return paths


# ---------------------------------------------------------------------------
# city summary
# ---------------------------------------------------------------------------
def build_city_summary(paths: dict) -> tuple[dict, int]:
    step("STEP 2  City summary (analytical, copied at full precision)")
    audited = json.loads(paths["city_access_summary"].read_text(encoding="utf-8"))
    manifest = json.loads(paths["analysis_manifest"].read_text(encoding="utf-8"))

    payload = {
        "analysis_population": audited["analysis_population"],
        "official_population": audited["official_population"],
        "metro_access_population": audited["metro_access_population"],
        "metro_access_pct": audited["metro_access_pct"],
        "bus_only_population": audited["bus_only_population"],
        "bus_only_pct": audited["bus_only_pct"],
        "underserved_population": audited["underserved_population"],
        "underserved_pct": audited["underserved_pct"],
        "combined_walk_access_population": audited["combined_walk_access_population"],
        "combined_walk_access_pct": audited["combined_walk_access_pct"],
        "walking_speed_kmh": audited["walking_speed_kmh"],
        "walking_time_minutes": audited["walking_time_minutes"],
        "walking_time_seconds": audited["walking_time_seconds"],
        "distance_budget_m": audited["distance_budget_m"],
        "analysis_district_count": audited["analysis_district_count"],
        "analysis_boundary_area_km2": audited["analysis_boundary_area_km2"],
        "snapping_method": audited["snapping_method"],
        "analysis_version": audited["analysis_version"],
        "reference_period": manifest["siat"]["reference_period"],
        "measures": audited["measures"],
        "does_not_measure": audited["does_not_measure"],
        "definitions": {
            "metro_access": (
                "Modelled walking distance along the pedestrian network from a "
                "population-cell centre to a metro access point is within the "
                "10-minute budget."
            ),
            "bus_only": (
                "Outside 10-minute metro access, but within 10-minute walking access "
                "of a mapped bus stop."
            ),
            "underserved": (
                "Outside the 10-minute walking threshold of both mapped metro access "
                "and mapped bus stops."
            ),
        },
        "estimate_note": (
            "These are model estimates from a pedestrian-network routing model, not "
            "observed walking behaviour. They assume a 4.8 km/h walking speed and a "
            "10-minute budget, and measure physical walking access only."
        ),
        "display_layer_note": (
            "Access shading is a display layer. Population estimates use "
            "pedestrian-network distance, not polygon intersection."
        ),
    }
    log(f"    metro {payload['metro_access_pct']:.4f}%   "
        f"bus-only {payload['bus_only_pct']:.4f}%   "
        f"underserved {payload['underserved_pct']:.4f}%")
    size = write_json(WEB_DATA_DIR / WEB_FILES["city_summary"], payload)
    return payload, size


# ---------------------------------------------------------------------------
# districts
# ---------------------------------------------------------------------------
DISTRICT_FIELDS = [
    "official_population",
    "calibrated_population",
    "metro_access_population",
    "metro_access_pct",
    "bus_only_population",
    "bus_only_pct",
    "underserved_population",
    "underserved_pct",
    "combined_walk_access_population",
    "combined_walk_access_pct",
    "min_cell_metro_distance_m",
    "min_cell_metro_margin_m",
    "area_km2",
    "population_density_per_km2",
    "metro_stations_in_district",
    "metro_access_points_in_district",
    "bus_stops_in_district",
    "bazaars_in_district",
]


def build_districts(paths: dict) -> tuple[gpd.GeoDataFrame, int, int]:
    """The 12 SIAT analysis districts with their audited metrics joined in.

    Yangi Toshkent is deliberately absent: it has no SIAT population row, so it
    has no analysed population result and must not be drawn as though it did.
    """
    step("STEP 3  District features (analytical metrics joined, 12 SIAT districts)")
    districts = gpd.read_file(paths["districts"])
    analysis = districts[districts.in_siat.astype(str).str.lower() == "true"].copy()
    analysis = analysis.sort_values("district_name").reset_index(drop=True)
    if len(analysis) != cfg.EXPECTED_ANALYSIS_DISTRICTS:
        raise ValueError(
            f"expected {cfg.EXPECTED_ANALYSIS_DISTRICTS} SIAT districts, got {len(analysis)}"
        )
    excluded = sorted(set(districts.district_name) - set(analysis.district_name))
    log(f"    excluded from the analytical layer: {excluded}")

    metrics = pd.read_csv(paths["district_access_metrics"])
    missing = sorted(set(analysis.district_name) - set(metrics.district_name))
    if missing:
        raise ValueError(f"districts with no audited metrics: {missing}")

    # Keep only identity and geometry from the boundary file. Every metric,
    # `area_km2` included, comes from the audited table so the two sources
    # cannot silently disagree.
    identity = analysis[["district_name", "siat_code", "osm_id", "geometry"]]
    joined = identity.merge(metrics, on="district_name", how="left", validate="one_to_one")
    if joined[DISTRICT_FIELDS].isna().any().any():
        bad = joined.loc[joined[DISTRICT_FIELDS].isna().any(axis=1), "district_name"].tolist()
        raise ValueError(f"districts with missing metric values: {bad}")

    features = []
    for _, row in joined.iterrows():
        properties = {
            "district_name": row.district_name,
            "label": short_label(row.district_name),
            "siat_code": row.siat_code,
            "osm_id": row.osm_id,
        }
        for field in DISTRICT_FIELDS:
            properties[field] = row[field]
        features.append(feature(row.geometry, properties))

    size = write_geojson(WEB_DATA_DIR / WEB_FILES["districts"], features)
    ranked = joined.sort_values("metro_access_pct", ascending=False)
    log(f"    {len(features)} districts, metro access "
        f"{ranked.metro_access_pct.iloc[0]:.2f}% ({ranked.district_name.iloc[0]}) down to "
        f"{ranked.metro_access_pct.iloc[-1]:.2f}% ({ranked.district_name.iloc[-1]})")
    return joined, len(features), size


# ---------------------------------------------------------------------------
# display layers
# ---------------------------------------------------------------------------
def build_isochrone(paths: dict) -> tuple[int, int, float]:
    step("STEP 4  Metro service area (DISPLAY ONLY)")
    iso = gpd.read_file(paths["metro_isochrone"])
    area_km2 = float(iso.to_crs(cfg.METRIC_CRS).area.sum() / 1e6)
    features = [
        display_feature(row.geometry, {
            "budget_m": row.budget_m,
            "buffer_m": row.buffer_m,
            "area_km2": round(area_km2, 4),
            "note": (
                "Access shading is a display layer. Population estimates use "
                "pedestrian-network distance, not polygon intersection."
            ),
        })
        for _, row in iso.iterrows()
    ]
    size = write_geojson(WEB_DATA_DIR / WEB_FILES["metro_isochrone"], features)
    log(f"    {len(features)} feature(s), {area_km2:,.2f} km2 — drives no percentage")
    return len(features), size, area_km2


def build_analysis_mask(districts: gpd.GeoDataFrame) -> tuple[int, int]:
    """Everything outside the 12 analysis districts, as one polygon (DISPLAY ONLY).

    The map dims the world beyond the study area so the eye goes to the ground the
    analysis actually covers. It is a cartographic device and nothing more: it
    carries no value, and the districts it masks around are the same twelve the
    audited result is computed over.
    """
    step("STEP 3b  Analysis-area mask (DISPLAY ONLY)")
    union = districts.to_crs(cfg.GEOGRAPHIC_CRS).union_all()
    world = box(-180.0, -85.0, 180.0, 85.0)
    mask = world.difference(union)
    features = [display_feature(mask, {"purpose": "dim outside the study area"})]
    size = write_geojson(WEB_DATA_DIR / WEB_FILES["analysis_mask"], features)
    log("    world minus the union of the 12 SIAT districts")
    return 1, size


def build_metro_lines(paths: dict) -> tuple[int, int, dict]:
    """Copy the metro route lines through to the web, unchanged (DISPLAY ONLY).

    These lines make the network legible on the map. They are never measured:
    the audited access result comes from entrances and station points, and this
    layer cannot move it. Each line's colour is the value OSM carries on its
    route relations - the interface tunes that named colour for a dark ground
    but never invents one for a line that has none.
    """
    step("STEP 4b  Metro route lines (DISPLAY ONLY)")
    snapshot = json.loads(paths["metro_lines_snapshot"].read_text(encoding="utf-8"))
    provenance = json.loads(paths["metro_lines_provenance"].read_text(encoding="utf-8"))

    features = []
    for source in snapshot["features"]:
        p = source["properties"]
        features.append({
            "type": "Feature",
            "properties": {
                "ref": p["ref"],
                "line_name": p.get("line_name"),
                "colour": p.get("colour"),
                "role": DISPLAY_ROLE,
            },
            "geometry": source["geometry"],
        })
    features.sort(key=lambda f: (len(f["properties"]["ref"]), f["properties"]["ref"]))

    size = write_geojson(WEB_DATA_DIR / WEB_FILES["metro_lines"], features)
    info = {
        "lines": len(features),
        "source": "OpenStreetMap route=subway relations",
        "snapshot": str(paths["metro_lines_snapshot"].relative_to(cfg.REPO_ROOT)).replace("\\", "/"),
        # The acquisition timestamp lives in the provenance file, not here: a
        # timestamp in the web manifest would break the build's byte-determinism.
        "provenance": str(
            paths["metro_lines_provenance"].relative_to(cfg.REPO_ROOT)
        ).replace("\\", "/"),
        "licence": provenance.get("licence"),
        "colours_from_osm": [f["properties"]["colour"] for f in features],
        "note": (
            "display only; the audited access result is computed from metro entrances "
            "and station points and is unaffected by this layer"
        ),
    }
    for f in features:
        p = f["properties"]
        log(f"    ref {p['ref']}  {str(p['line_name'])[:26]:26s} colour={p['colour']}")
    return len(features), size, info


def build_metro_access_points(paths: dict) -> tuple[int, int, dict]:
    step("STEP 5  Metro access points")
    table = pd.read_csv(paths["metro_access_points"])
    points = gpd.GeoSeries(
        gpd.points_from_xy(table.x_m, table.y_m), crs=cfg.METRIC_CRS
    ).to_crs(cfg.GEOGRAPHIC_CRS)

    table = table.assign(_geom=points.to_numpy())
    table = table.sort_values(["access_type", "access_id"]).reset_index(drop=True)

    features = []
    for _, row in table.iterrows():
        is_fallback = row.access_type == "station_fallback"
        features.append(display_feature(row._geom, {
            "access_id": row.access_id,
            "access_type": row.access_type,
            "name": row["name"],
            "district_name": row.district_name,
            "kind_label": "Station fallback" if is_fallback else "Metro entrance",
            "detail": (
                f"No mapped entrance within "
                f"{cfg.ENTRANCE_ASSOCIATION_RADIUS_M:.0f} m "
                f"(nearest {row.nearest_entrance_distance_m:.0f} m)"
                if is_fallback else "Mapped subway entrance"
            ),
        }))

    counts = table.access_type.value_counts().to_dict()
    size = write_geojson(WEB_DATA_DIR / WEB_FILES["metro_access_points"], features)
    log(f"    {len(features)} access points: {counts}")
    return len(features), size, {k: int(v) for k, v in counts.items()}


def build_point_layer(path: Path, out_name: str, label: str, fields: dict) -> tuple[int, int]:
    """Metro stations, bus stops and bazaars: shown on the map, never measured."""
    gdf = gpd.read_file(path).to_crs(cfg.GEOGRAPHIC_CRS)
    sort_key = "osm_id" if "osm_id" in gdf.columns else gdf.columns[0]
    gdf = gdf.sort_values(sort_key).reset_index(drop=True)
    features = [
        display_feature(row.geometry,
                        {out_key: row.get(src) for out_key, src in fields.items()})
        for _, row in gdf.iterrows()
    ]
    size = write_geojson(WEB_DATA_DIR / out_name, features)
    log(f"    {label}: {len(features)} features")
    return len(features), size


# ---------------------------------------------------------------------------
# sensitivity (analytical, copied not recomputed)
# ---------------------------------------------------------------------------
def build_sensitivity(paths: dict) -> tuple[int, dict]:
    """Copy the audited sensitivity results through to the web, unchanged.

    The site should not make a reader open the repository to find out how much
    the headline depends on its assumptions. Both of these were computed and
    audited in Week 4; nothing is recomputed here. The city rows are selected,
    the columns the interface needs are carried across, and the values are
    written at full precision so the presentation layer decides the rounding.
    """
    step("STEP 6b  Sensitivity (ANALYTICAL, copied from audited outputs)")

    speed = pd.read_csv(paths["walk_speed_sensitivity"])
    city_speed = speed[speed.scope == "city"].sort_values("speed_kmh")
    if len(city_speed) == 0:
        raise ValueError("walking_speed_sensitivity.csv carries no city-scope rows")

    rows = [
        {
            "speed_kmh": _clean(row.speed_kmh),
            "budget_m": _clean(row.budget_m),
            "metro_access_pct": _clean(row.metro_access_pct),
            "combined_pct": _clean(row.combined_pct),
            "underserved_pct": _clean(row.underserved_pct),
            "metro_access_population": _clean(row.metro_access_population),
        }
        for row in city_speed.itertuples()
    ]

    surface = pd.read_csv(paths["population_surface_sensitivity"])
    city_surface = surface[surface.scope == "city"]
    if len(city_surface) != 1:
        raise ValueError(
            f"population_surface_sensitivity.csv should carry exactly one city row, "
            f"found {len(city_surface)}"
        )
    srow = city_surface.iloc[0]

    payload = {
        "role": "analytical",
        "note": (
            "Copied from the audited Week 4 sensitivity outputs. Nothing here is "
            "recomputed by the build or by the site."
        ),
        "walking_speed": {
            "headline_speed_kmh": _clean(cfg.MAIN_WALK_SPEED_KMH),
            "source": str(paths["walk_speed_sensitivity"].relative_to(cfg.REPO_ROOT))
                .replace("\\", "/"),
            "rows": rows,
        },
        "population_surface": {
            "source": str(paths["population_surface_sensitivity"].relative_to(cfg.REPO_ROOT))
                .replace("\\", "/"),
            "metro_access_pct_using_2020_surface":
                _clean(srow.metro_access_pct_using_2020_surface),
            "metro_access_pct_using_2026_surface":
                _clean(srow.metro_access_pct_using_2026_surface),
            "percentage_point_difference": _clean(srow.percentage_point_difference),
            "interpretation": (
                "The result is insensitive to this particular temporal-surface "
                "substitution once both surfaces are calibrated to the same official "
                "district totals. It does not validate the population surface."
            ),
        },
    }

    size = write_json(WEB_DATA_DIR / WEB_FILES["sensitivity"], payload)
    for row in rows:
        log(f"    {row['speed_kmh']:.1f} km/h  metro {row['metro_access_pct']:.6f}%  "
            f"combined {row['combined_pct']:.6f}%  "
            f"underserved {row['underserved_pct']:.6f}%")
    log(f"    population surface: {payload['population_surface']['percentage_point_difference']:+.6f} pp")
    return size, payload


# ---------------------------------------------------------------------------
# population density (display only)
# ---------------------------------------------------------------------------
def build_population_density(paths: dict, districts: gpd.GeoDataFrame) -> tuple[int, int, dict]:
    """Aggregate the audited per-cell population into 500 m display bins.

    DISPLAY ONLY. This layer exists so the map can show where people are. It
    drives no access percentage: every reported share comes from the Week 4
    network-distance classification, cell by cell, not from these bins.

    Each ~100 m population cell is assigned to the 500 m square containing its
    projected centre, populations are summed, the squares are clipped to the
    12-district analysis boundary, and density uses the CLIPPED area so an edge
    bin is not diluted by the part of it that lies outside the study area.
    """
    step("STEP 6  Population density bins (DISPLAY ONLY)")
    cells = pd.read_parquet(paths["population_cells"])
    total = float(cells.population.sum())
    log(f"    audited per-cell table: {len(cells):,} cells, {total:,.1f} people")

    x = cells.x_m.to_numpy()
    y = cells.y_m.to_numpy()
    col = np.floor(x / DENSITY_BIN_M).astype(np.int64)
    row = np.floor(y / DENSITY_BIN_M).astype(np.int64)

    binned = (
        pd.DataFrame({"bin_col": col, "bin_row": row, "population": cells.population.to_numpy()})
        .groupby(["bin_row", "bin_col"], sort=True, as_index=False)["population"]
        .sum()
    )
    binned = binned[binned.population > 0].reset_index(drop=True)
    log(f"    {DENSITY_BIN_M:.0f} m bins with population: {len(binned):,}")

    squares = [
        box(c * DENSITY_BIN_M, r * DENSITY_BIN_M,
            (c + 1) * DENSITY_BIN_M, (r + 1) * DENSITY_BIN_M)
        for r, c in zip(binned.bin_row, binned.bin_col)
    ]
    grid = gpd.GeoDataFrame(binned, geometry=squares, crs=cfg.METRIC_CRS)

    boundary = districts.to_crs(cfg.METRIC_CRS).union_all()
    grid["geometry"] = grid.geometry.intersection(boundary)
    grid = grid[~grid.geometry.is_empty & grid.geometry.notna()].copy()
    grid["clipped_area_km2"] = grid.geometry.area / 1e6
    grid = grid[grid.clipped_area_km2 > 0].copy()
    grid["density_per_km2"] = grid.population / grid.clipped_area_km2

    grid = grid.sort_values(["bin_row", "bin_col"]).reset_index(drop=True)
    retained = float(grid.population.sum())

    web = grid.to_crs(cfg.GEOGRAPHIC_CRS)
    features = [
        display_feature(row.geometry, {
            "population": round(float(row.population), 3),
            "density_per_km2": round(float(row.density_per_km2), 2),
            "area_km2": round(float(row.clipped_area_km2), 6),
        })
        for _, row in web.iterrows()
    ]
    size = write_geojson(WEB_DATA_DIR / WEB_FILES["population_density"], features)

    stats = {
        "bin_size_m": DENSITY_BIN_M,
        "features": len(features),
        "source_cells": int(len(cells)),
        "population_in_bins": round(retained, 6),
        "population_in_source_cells": round(total, 6),
        "population_retained_pct": round(retained / total * 100.0, 6),
        "density_min_per_km2": round(float(grid.density_per_km2.min()), 4),
        "density_median_per_km2": round(float(grid.density_per_km2.median()), 4),
        "density_max_per_km2": round(float(grid.density_per_km2.max()), 4),
        "role": DISPLAY_ROLE,
    }
    log(f"    kept {len(features):,} bins, {retained:,.1f} people "
        f"({stats['population_retained_pct']:.4f}% of the audited total)")
    log(f"    density per km2: min {stats['density_min_per_km2']:,.0f}  "
        f"median {stats['density_median_per_km2']:,.0f}  "
        f"max {stats['density_max_per_km2']:,.0f}")
    log("    DISPLAY ONLY: this layer drives no access percentage")
    return len(features), size, stats


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)

    paths = load_inputs()
    sizes: dict[str, int] = {}
    counts: dict[str, int] = {}

    city, sizes["city_summary"] = build_city_summary(paths)
    districts, counts["districts"], sizes["districts"] = build_districts(paths)
    counts["metro_isochrone"], sizes["metro_isochrone"], iso_area = build_isochrone(paths)
    counts["metro_access_points"], sizes["metro_access_points"], access_counts = \
        build_metro_access_points(paths)
    counts["metro_lines"], sizes["metro_lines"], metro_line_info = build_metro_lines(paths)
    counts["analysis_mask"], sizes["analysis_mask"] = build_analysis_mask(districts)

    step("STEP 7  Remaining point layers")
    counts["metro_stations"], sizes["metro_stations"] = build_point_layer(
        paths["metro_stations"], WEB_FILES["metro_stations"], "metro stations",
        {"osm_id": "osm_id", "name": "name", "name_en": "name_en",
         "district_name": "district_name"},
    )
    # Bus stops carry only their district. The layer exists to show spatial
    # coverage, not to be hovered stop by stop, so per-stop names would add
    # weight the interface never reads.
    counts["bus_stops"], sizes["bus_stops"] = build_point_layer(
        paths["bus_stops"], WEB_FILES["bus_stops"], "bus stops",
        {"district_name": "district_name"},
    )
    counts["bazaars"], sizes["bazaars"] = build_point_layer(
        paths["bazaars"], WEB_FILES["bazaars"], "bazaars",
        {"name": "name", "name_ru": "name_ru", "district_name": "district_name"},
    )

    counts["population_density"], sizes["population_density"], density_stats = \
        build_population_density(paths, districts)
    sizes["sensitivity"], sensitivity = build_sensitivity(paths)

    step("STEP 8  Web data manifest")
    manifest = {
        "milestone": "Week 5 - interim interactive prototype",
        "generated_by": "scripts/build_web_data.py",
        "deterministic": (
            "No timestamp is recorded. Ordering, rounding and precision are fixed, so "
            "repeated runs are byte-identical."
        ),
        "analysis_source": {
            "analysis_version": city["analysis_version"],
            "snapping_method": city["snapping_method"],
            "note": (
                "Identified by content hash rather than a commit SHA so the build stays "
                "byte-deterministic and cannot go stale against its own inputs."
            ),
            "files": {
                name: {
                    "path": str(path.relative_to(cfg.REPO_ROOT)).replace("\\", "/"),
                    "sha256_lf_normalised": content_hash(path),
                }
                for name, path in sorted(paths.items())
            },
        },
        "analysis_parameters": {
            "analysis_population": city["analysis_population"],
            "walking_speed_kmh": city["walking_speed_kmh"],
            "walking_time_minutes": city["walking_time_minutes"],
            "walking_time_seconds": city["walking_time_seconds"],
            "distance_budget_m": city["distance_budget_m"],
            "district_count": city["analysis_district_count"],
            "snapping_method": city["snapping_method"],
        },
        "coordinate_reference_system": cfg.GEOGRAPHIC_CRS,
        "coordinate_precision_decimals": COORD_PRECISION,
        "layers": {
            "city_summary": {
                "file": WEB_FILES["city_summary"], "role": "analytical",
                "features": None, "bytes": sizes["city_summary"],
                "source": "data/processed/city_access_summary.json",
                "note": "copied at full precision; not recomputed",
            },
            "districts": {
                "file": WEB_FILES["districts"], "role": "analytical",
                "features": counts["districts"], "bytes": sizes["districts"],
                "source": ("data/processed/tashkent_districts.geojson + "
                           "data/processed/district_access_metrics.csv"),
                "note": ("the 12 SIAT analysis districts only; Yangi Toshkent has no SIAT "
                         "population row and is therefore absent from the analytical layer"),
            },
            "metro_isochrone": {
                "file": WEB_FILES["metro_isochrone"], "role": DISPLAY_ROLE,
                "features": counts["metro_isochrone"], "bytes": sizes["metro_isochrone"],
                "source": "data/processed/metro_isochrone_10min.geojson",
                "area_km2": round(iso_area, 4),
                "note": ("Access shading is a display layer. Population estimates use "
                         "pedestrian-network distance, not polygon intersection."),
            },
            "metro_access_points": {
                "file": WEB_FILES["metro_access_points"], "role": DISPLAY_ROLE,
                "features": counts["metro_access_points"],
                "bytes": sizes["metro_access_points"],
                "source": "data/processed/metro_access_points.csv",
                "by_access_type": access_counts,
            },
            "metro_stations": {
                "file": WEB_FILES["metro_stations"], "role": DISPLAY_ROLE,
                "features": counts["metro_stations"], "bytes": sizes["metro_stations"],
                "source": "data/processed/metro_stations.geojson",
            },
            "bus_stops": {
                "file": WEB_FILES["bus_stops"], "role": DISPLAY_ROLE,
                "features": counts["bus_stops"], "bytes": sizes["bus_stops"],
                "source": "data/processed/bus_stops.geojson",
            },
            "bazaars": {
                "file": WEB_FILES["bazaars"], "role": DISPLAY_ROLE,
                "features": counts["bazaars"], "bytes": sizes["bazaars"],
                "source": "data/processed/bazaars.geojson",
            },
            "metro_lines": {
                "file": WEB_FILES["metro_lines"], "role": DISPLAY_ROLE,
                "features": counts["metro_lines"], "bytes": sizes["metro_lines"],
                "source": "data/display/metro_lines_osm.geojson",
                **metro_line_info,
            },
            "analysis_mask": {
                "file": WEB_FILES["analysis_mask"], "role": DISPLAY_ROLE,
                "features": counts["analysis_mask"], "bytes": sizes["analysis_mask"],
                "source": "derived from the 12 SIAT district polygons",
                "note": "dims the map outside the study area; carries no value",
            },
            "population_density": {
                "file": WEB_FILES["population_density"], "role": DISPLAY_ROLE,
                "features": counts["population_density"],
                "bytes": sizes["population_density"],
                "source": "data/external/population_cells.parquet (audited Week 4 run)",
                **density_stats,
                "note": ("visual context only; every reported access share comes from the "
                         "Week 4 per-cell network-distance classification, never from "
                         "these bins"),
            },
            "sensitivity": {
                "file": WEB_FILES["sensitivity"], "role": "analytical",
                "features": None, "bytes": sizes["sensitivity"],
                "source": "data/processed/walking_speed_sensitivity.csv + "
                          "data/processed/population_surface_sensitivity.csv",
                "note": "audited sensitivity results copied through; not recomputed",
            },
        },
        "not_recomputed": [
            "network accessibility", "population calibration",
            "district access metrics", "city access summary",
        ],
    }
    write_json(WEB_DATA_DIR / WEB_FILES["manifest"], manifest)

    step("Web data build complete")
    total_bytes = sum(p.stat().st_size for p in WEB_DATA_DIR.glob("*"))
    for name in sorted(WEB_FILES.values()):
        path = WEB_DATA_DIR / name
        log(f"    {name:34s} {cfg.human_size(path.stat().st_size):>10s}")
    log(f"    {'TOTAL':34s} {cfg.human_size(total_bytes):>10s}")
    log("  Next: python scripts/validate_prototype.py")
    return 0


if __name__ == "__main__":
    enable_utf8_stdout()
    raise SystemExit(main())
