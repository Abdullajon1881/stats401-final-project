"""Acquire and process the Phase 2A annual population foundation.

Run from the repository root:

    python scripts/acquire_temporal_population.py

The twelve raw WorldPop GeoTIFFs and the optional cell cache are written below
``data/external`` and remain gitignored. Committed CSV outputs are deterministic
for unchanged inputs.
"""

from __future__ import annotations

import gzip
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import xy
from rasterio.windows import Window, from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg
from phase2_manifest import update_manifest
from pipeline_utils import enable_utf8_stdout, http_get, log, step


def _serialise_transform(transform: rasterio.Affine) -> list[float]:
    return [float(value) for value in transform[:6]]


def _raster_metadata(path: Path) -> dict[str, Any]:
    with rasterio.open(path) as src:
        if src.count != 1:
            raise RuntimeError(f"{path.name}: expected one raster band, got {src.count}")
        if src.crs is None:
            raise RuntimeError(f"{path.name}: missing CRS")
        if src.nodata is None:
            raise RuntimeError(f"{path.name}: missing nodata value")
        return {
            "crs": src.crs.to_string(),
            "width": int(src.width),
            "height": int(src.height),
            "transform": _serialise_transform(src.transform),
            "bounds": [float(value) for value in src.bounds],
            "nodata": float(src.nodata),
            "dtype": src.dtypes[0],
        }


def _is_valid_local_raster(path: Path, year: int) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    expected_name = cfg.worldpop_temporal_filename(year)
    if path.name != expected_name:
        return False
    try:
        metadata = _raster_metadata(path)
    except (OSError, rasterio.errors.RasterioError, RuntimeError):
        return False
    return (
        metadata["crs"] == cfg.GEOGRAPHIC_CRS
        and metadata["width"] > 0
        and metadata["height"] > 0
        and metadata["nodata"] is not None
    )


def _stream_to_file(url: str, destination: Path) -> dict[str, str | None]:
    """Stream one response to an atomic temporary file."""
    response = http_get(url, stream=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                if chunk:
                    handle.write(chunk)
        if temporary.stat().st_size == 0:
            raise RuntimeError(f"empty download from {url}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
        response.close()
    return {
        "http_last_modified": response.headers.get("Last-Modified"),
        "http_etag": response.headers.get("ETag"),
    }


def acquire_worldpop() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    step("WORLDPOP  Acquire pinned annual rasters")
    records: list[dict[str, Any]] = []
    reference_grid: dict[str, Any] | None = None

    for year in cfg.TEMPORAL_YEARS:
        path = cfg.worldpop_temporal_path(year)
        url = cfg.worldpop_temporal_url(year)
        headers: dict[str, str | None] = {
            "http_last_modified": None,
            "http_etag": None,
        }

        if _is_valid_local_raster(path, year):
            log(f"  {year}: reusing valid local raster ({cfg.human_size(path.stat().st_size)})")
        else:
            if path.exists():
                log(f"  {year}: local raster is invalid; replacing it")
                path.unlink()
            log(f"  {year}: downloading {url}")
            headers = _stream_to_file(url, path)
            if not _is_valid_local_raster(path, year):
                raise RuntimeError(f"{year}: downloaded file failed raster validation")

        grid = _raster_metadata(path)
        grid_comparison = {
            key: grid[key]
            for key in ("crs", "width", "height", "transform", "bounds", "nodata")
        }
        if reference_grid is None:
            reference_grid = grid_comparison
        elif grid_comparison != reference_grid:
            raise RuntimeError(
                f"{year}: WorldPop grid differs from {cfg.TEMPORAL_START_YEAR}; "
                f"expected {reference_grid}, got {grid_comparison}"
            )

        records.append(
            {
                "year": year,
                "url": url,
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": cfg.sha256_file(path),
                "crs": grid["crs"],
                "width": grid["width"],
                "height": grid["height"],
                "transform": grid["transform"],
                "nodata": grid["nodata"],
                "release": cfg.WORLDPOP_TEMPORAL_RELEASE,
                "product_version": cfg.WORLDPOP_TEMPORAL_PRODUCT_VERSION,
                "projection_flag": year == cfg.TEMPORAL_END_YEAR,
                **headers,
            }
        )

    assert reference_grid is not None
    log(f"  verified one identical grid across {len(records)} years")
    return records, reference_grid


def _analysis_districts() -> gpd.GeoDataFrame:
    districts = gpd.read_file(cfg.DISTRICTS_FILE)
    required = {"siat_code", "district_name", "in_siat", "geometry"}
    missing = required - set(districts.columns)
    if missing:
        raise RuntimeError(f"district geometry missing columns: {sorted(missing)}")
    in_siat = districts["in_siat"].map(
        lambda value: value is True or str(value).strip().lower() in {"true", "1"}
    )
    districts = districts[in_siat].copy()
    if len(districts) != cfg.EXPECTED_ANALYSIS_DISTRICTS:
        raise RuntimeError(
            f"expected {cfg.EXPECTED_ANALYSIS_DISTRICTS} analysis districts, "
            f"got {len(districts)}"
        )
    districts["district_id"] = districts["siat_code"].astype(str)
    districts["area_km2_fixed"] = districts.to_crs(cfg.METRIC_CRS).area / 1_000_000
    return districts.sort_values("district_id").reset_index(drop=True)


def _analysis_window(src: rasterio.DatasetReader, districts: gpd.GeoDataFrame) -> Window:
    raster_districts = districts.to_crs(src.crs)
    raw = from_bounds(*raster_districts.total_bounds, transform=src.transform)
    col_start = max(0, int(np.floor(raw.col_off)))
    row_start = max(0, int(np.floor(raw.row_off)))
    col_stop = min(src.width, int(np.ceil(raw.col_off + raw.width)))
    row_stop = min(src.height, int(np.ceil(raw.row_off + raw.height)))
    return Window(
        col_start,
        row_start,
        col_stop - col_start,
        row_stop - row_start,
    )


def build_worldpop_outputs() -> tuple[pd.DataFrame, dict[str, Any]]:
    step("WORLDPOP  Build fixed-geography annual outputs")
    districts = _analysis_districts()
    first_path = cfg.worldpop_temporal_path(cfg.TEMPORAL_START_YEAR)

    with rasterio.open(first_path) as src:
        window = _analysis_window(src, districts)
        window_transform = src.window_transform(window)
        raster_districts = districts.to_crs(src.crs)
        shapes = [
            (row.geometry, index)
            for index, row in raster_districts.reset_index(drop=True).iterrows()
        ]
        district_index = rasterize(
            shapes,
            out_shape=(int(window.height), int(window.width)),
            transform=window_transform,
            fill=-1,
            dtype="int16",
            all_touched=False,
        )
        assigned_rows, assigned_cols = np.where(district_index >= 0)
        if assigned_rows.size == 0:
            raise RuntimeError("fixed analysis districts selected no WorldPop cells")
        source_transform = src.transform

    selected_by_year: dict[int, np.ndarray] = {}
    valid_by_year: dict[int, np.ndarray] = {}
    for year in cfg.TEMPORAL_YEARS:
        path = cfg.worldpop_temporal_path(year)
        with rasterio.open(path) as src:
            values = src.read(1, window=window)
            selected = values[assigned_rows, assigned_cols].astype("float64")
            invalid = ~np.isfinite(selected) | (selected == src.nodata)
            if (selected[~invalid] < 0).any():
                raise RuntimeError(f"{year}: negative population inside analysis districts")
            selected_by_year[year] = selected
            valid_by_year[year] = ~invalid

    union_valid = np.logical_or.reduce(list(valid_by_year.values()))
    if not union_valid.any():
        raise RuntimeError("no cells are valid in any requested WorldPop year")
    invalid_counts = {year: int((~valid).sum()) for year, valid in valid_by_year.items()}
    masks_identical = all(
        np.array_equal(valid, valid_by_year[cfg.TEMPORAL_START_YEAR])
        for valid in valid_by_year.values()
    )
    log(
        f"  fixed polygon-centre cells: {len(union_valid):,}; "
        f"valid in any requested year: {int(union_valid.sum()):,}; "
        f"nodata in every year: {int((~union_valid).sum()):,}"
    )
    if not masks_identical:
        log(f"  annual nodata counts differed; fixed union cell set used: {invalid_counts}")

    assigned_rows = assigned_rows[union_valid]
    assigned_cols = assigned_cols[union_valid]
    assigned_indices = district_index[assigned_rows, assigned_cols]
    global_rows = assigned_rows + int(window.row_off)
    global_cols = assigned_cols + int(window.col_off)
    lon, lat = xy(source_transform, global_rows, global_cols, offset="center")
    assigned_districts = np.asarray(
        [districts.iloc[index].district_id for index in assigned_indices]
    )

    wide_cells: dict[str, Any] = {
        "cell_id": [
            f"r{row:05d}c{col:05d}"
            for row, col in zip(global_rows, global_cols, strict=True)
        ],
        "district_id": assigned_districts,
        "lon": np.asarray(lon),
        "lat": np.asarray(lat),
    }
    annual_totals: dict[int, dict[str, float]] = {}

    for year in cfg.TEMPORAL_YEARS:
        selected = np.where(
            valid_by_year[year][union_valid],
            selected_by_year[year][union_valid],
            0.0,
        )
        wide_cells[f"pop_{year}"] = selected

        year_totals: dict[str, float] = {}
        for district_id in districts.district_id:
            year_totals[district_id] = float(selected[assigned_districts == district_id].sum())
        annual_totals[year] = year_totals
        log(f"  {year}: current-footprint total {sum(year_totals.values()):,.1f}")

    cell_frame = pd.DataFrame(wide_cells).sort_values("cell_id").reset_index(drop=True)
    cache_csv = cell_frame.to_csv(index=False, float_format="%.6f", lineterminator="\n")
    cfg.WORLDPOP_TEMPORAL_CELL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with (
        cfg.WORLDPOP_TEMPORAL_CELL_CACHE.open("wb") as raw_handle,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as zipped,
    ):
        zipped.write(cache_csv.encode("utf-8"))

    rows: list[dict[str, Any]] = []
    base = annual_totals[cfg.TEMPORAL_START_YEAR]
    for district in districts.itertuples(index=False):
        district_id = str(district.district_id)
        for year in cfg.TEMPORAL_YEARS:
            population = annual_totals[year][district_id]
            base_population = base[district_id]
            growth = (population / base_population - 1.0) * 100.0
            if year == cfg.TEMPORAL_START_YEAR:
                growth = 0.0
            rows.append(
                {
                    "district_id": district_id,
                    "district_name": district.district_name,
                    "year": year,
                    "geography_version": cfg.TEMPORAL_GEOGRAPHY_VERSION,
                    "population_modelled": round(population, 6),
                    "population_density_modelled_km2": round(
                        population / float(district.area_km2_fixed), 6
                    ),
                    "population_growth_pct_from_2015": round(growth, 6),
                    "population_projection_flag": year == cfg.TEMPORAL_END_YEAR,
                    "worldpop_release": cfg.WORLDPOP_TEMPORAL_RELEASE,
                    "worldpop_product": cfg.WORLDPOP_TEMPORAL_PRODUCT,
                    "source_url": cfg.worldpop_temporal_url(year),
                }
            )

    result = pd.DataFrame(rows).sort_values(["district_id", "year"])
    result.to_csv(cfg.WORLDPOP_DISTRICT_YEAR_FILE, index=False, lineterminator="\n")
    cache_record = {
        "filename": cfg.WORLDPOP_TEMPORAL_CELL_CACHE.name,
        "rows": len(cell_frame),
        "size_bytes": cfg.WORLDPOP_TEMPORAL_CELL_CACHE.stat().st_size,
        "sha256": cfg.sha256_file(cfg.WORLDPOP_TEMPORAL_CELL_CACHE),
        "cell_identity": "global raster row and column encoded as r#####c#####",
        "fixed_polygon_centre_cells_before_nodata_filter": len(union_valid),
        "union_valid_cells": int(union_valid.sum()),
        "excluded_all_years_nodata_cells": int((~union_valid).sum()),
        "annual_nodata_masks_identical": masks_identical,
        "annual_nodata_counts": invalid_counts,
        "nodata_treatment": (
            "Retain cells valid in any requested year; store zero for a year's nodata "
            "inside that fixed union cell set; exclude cells nodata in every year."
        ),
        "tracked": False,
    }
    log(f"  wrote {len(result)} district-year rows")
    log(f"  wrote gitignored cell cache with {len(cell_frame):,} fixed-grid cells")
    return result, cache_record


def acquire_siat_annual() -> tuple[pd.DataFrame, dict[str, Any]]:
    step("SIAT  Acquire and normalize official annual population control")
    pointer_response = http_get(cfg.SIAT_ANNUAL_DOWNLOAD_API)
    pointer = pointer_response.json()
    file_url = pointer.get("file")
    if not isinstance(file_url, str) or not file_url.startswith("https://api.siat.stat.uz/"):
        raise RuntimeError(f"SIAT 246 returned an unexpected file URL: {file_url!r}")

    file_response = http_get(file_url, stream=True)
    payload = bytearray()
    for chunk in file_response.iter_content(chunk_size=1 << 20):
        if chunk:
            payload.extend(chunk)
    file_response.close()
    if not payload:
        raise RuntimeError("SIAT 246 returned an empty CSV")
    cfg.SIAT_ANNUAL_RAW_FILE.parent.mkdir(parents=True, exist_ok=True)
    cfg.SIAT_ANNUAL_RAW_FILE.write_bytes(payload)

    source = pd.read_csv(BytesIO(payload), dtype={"Code": str})
    years = [str(year) for year in cfg.TEMPORAL_YEARS]
    required = {"Code", "Klassifikator_en", *years}
    missing = required - set(source.columns)
    if missing:
        raise RuntimeError(f"SIAT 246 missing columns: {sorted(missing)}")

    selected = source[
        (source["Code"] == cfg.TASHKENT_SOATO)
        | source["Code"].isin(cfg.SIAT_TO_OSM_DISTRICT)
    ].copy()
    expected_codes = {cfg.TASHKENT_SOATO, *cfg.SIAT_TO_OSM_DISTRICT}
    found_codes = set(selected["Code"])
    if found_codes != expected_codes:
        raise RuntimeError(
            f"SIAT 246 Tashkent identities differ: missing {sorted(expected_codes - found_codes)}, "
            f"unexpected {sorted(found_codes - expected_codes)}"
        )

    long = selected.melt(
        id_vars=["Code", "Klassifikator_en"],
        value_vars=years,
        var_name="year",
        value_name="population_thousand",
    ).rename(columns={"Code": "siat_code", "Klassifikator_en": "district_name"})
    long["year"] = pd.to_numeric(long["year"], errors="raise").astype(int)
    long["population_thousand"] = pd.to_numeric(
        long["population_thousand"], errors="raise"
    )
    long["population_people"] = (long["population_thousand"] * 1000).round().astype(int)

    affected = {cfg.TASHKENT_SOATO, "1726264", "1726283", "1726292"}
    long["geography_break_flag"] = (
        long["siat_code"].isin(affected) & (long["year"] == 2021)
    )
    note = (
        "The 2021 Yangikhayot reorganization changed district and city footprints; "
        "territory also came from Tashkent Region. Do not interpret Yangikhayot's "
        "pre-2021 zeros as zero population or calculate ordinary 2020-2021 district growth."
    )
    long["geography_note"] = np.where(long["siat_code"].isin(affected), note, "")
    long["source_dataset"] = cfg.SIAT_ANNUAL_DATASET_ID
    long["source_url"] = cfg.SIAT_ANNUAL_LANDING_URL
    long = long.sort_values(["siat_code", "year"]).reset_index(drop=True)
    long.to_csv(cfg.SIAT_ANNUAL_POPULATION_FILE, index=False, lineterminator="\n")

    record = {
        "dataset_id": cfg.SIAT_ANNUAL_DATASET_ID,
        "role": "secondary official control",
        "landing_url": cfg.SIAT_ANNUAL_LANDING_URL,
        "download_api": cfg.SIAT_ANNUAL_DOWNLOAD_API,
        "resolved_csv_url": file_url,
        "source_updated_at": pointer.get("updated_at"),
        "source_file_size_label": pointer.get("size"),
        "downloaded_size_bytes": len(payload),
        "sha256": cfg.sha256_file(cfg.SIAT_ANNUAL_RAW_FILE),
        "units": "thousand permanent residents",
        "years_extracted": list(cfg.TEMPORAL_YEARS),
        "temporal_semantics_note": (
            "Dataset 246 is an annual permanent-population series. The landing-page "
            "metadata reviewed for this project does not establish a precise reference "
            "instant for every annual column, so no mid-year or January-1 assumption is made."
        ),
    }
    log(f"  wrote {len(long)} SIAT rows (city plus 12 districts × 12 years)")
    return long, record


def build_population_diagnostic(
    worldpop: pd.DataFrame,
    siat: pd.DataFrame,
) -> pd.DataFrame:
    step("DIAGNOSTIC  Compare fixed-current WorldPop footprint with SIAT city series")
    wp_city = (
        worldpop.groupby("year", as_index=False)["population_modelled"]
        .sum()
        .rename(
            columns={"population_modelled": "worldpop_current_footprint_population"}
        )
    )
    siat_city = siat[siat["siat_code"] == cfg.TASHKENT_SOATO][
        ["year", "population_people"]
    ].rename(columns={"population_people": "siat_official_city_population"})
    diagnostic = wp_city.merge(siat_city, on="year", validate="one_to_one")
    diagnostic["difference_people"] = (
        diagnostic["worldpop_current_footprint_population"]
        - diagnostic["siat_official_city_population"]
    ).round(6)
    diagnostic["difference_pct"] = (
        diagnostic["difference_people"]
        / diagnostic["siat_official_city_population"]
        * 100
    ).round(6)
    diagnostic["geography_comparability"] = np.where(
        diagnostic["year"] <= 2020,
        "limited_changing_historical_footprint",
        "improved_fixed_current_vs_official_administrative",
    )
    diagnostic["projection_flag"] = diagnostic["year"] == cfg.TEMPORAL_END_YEAR
    diagnostic["worldpop_source_label"] = (
        "WorldPop Global 2 R2025A v1 fixed current analysis footprint"
    )
    diagnostic["siat_source_label"] = "SIAT dataset 246 official city population"
    diagnostic["notes"] = np.where(
        diagnostic["year"] <= 2020,
        "Limited comparability: current fixed footprint is compared with the historical official city footprint before the 2021 reorganization.",
        "Improved but not identical geography: fixed current analysis footprint is compared with the official administrative city series.",
    )
    diagnostic = diagnostic.sort_values("year").reset_index(drop=True)
    diagnostic.to_csv(
        cfg.TEMPORAL_POPULATION_DIAGNOSTIC_FILE,
        index=False,
        lineterminator="\n",
    )
    log(f"  wrote {len(diagnostic)} annual diagnostic rows")
    return diagnostic


def main() -> int:
    cfg.ensure_directories()
    raster_records, grid = acquire_worldpop()
    worldpop, cache_record = build_worldpop_outputs()
    siat, siat_record = acquire_siat_annual()
    build_population_diagnostic(worldpop, siat)

    update_manifest(
        "worldpop",
        {
            "role": "primary fixed-geography temporal spatial series",
            "product": cfg.WORLDPOP_TEMPORAL_PRODUCT,
            "release": cfg.WORLDPOP_TEMPORAL_RELEASE,
            "product_version": cfg.WORLDPOP_TEMPORAL_PRODUCT_VERSION,
            "release_status": "alpha",
            "doi": cfg.WORLDPOP_DOI,
            "release_statement_url": cfg.WORLDPOP_RELEASE_STATEMENT_URL,
            "years": list(cfg.TEMPORAL_YEARS),
            "projected_years": [cfg.TEMPORAL_END_YEAR],
            "geography_version": cfg.TEMPORAL_GEOGRAPHY_VERSION,
            "grid": grid,
            "files": raster_records,
            "cell_cache": cache_record,
            "semantics": (
                "Modelled population counts per grid cell; historical years remain "
                "model-derived estimates and 2026 is projected. Values are not calibrated to SIAT."
            ),
        },
    )
    update_manifest("siat", siat_record)
    update_manifest(
        "population_diagnostic",
        {
            "output": cfg.TEMPORAL_POPULATION_DIAGNOSTIC_FILE.name,
            "comparison": (
                "WorldPop fixed current 12-district footprint versus SIAT official city series"
            ),
            "pre_2021_comparability": "limited",
            "post_2020_comparability": "improved but not identical",
        },
    )
    log("\nTemporal population foundation complete.")
    return 0


if __name__ == "__main__":
    enable_utf8_stdout()
    raise SystemExit(main())
