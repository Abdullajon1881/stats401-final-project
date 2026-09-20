"""Validate the actual Phase 2A temporal artifacts and external inputs."""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg
import phase2_manifest as pm
from pipeline_utils import enable_utf8_stdout

PASSED: list[str] = []
FAILED: list[str] = []


def check(condition: bool, message: str) -> bool:
    marker = "PASS" if condition else "FAIL"
    print(f"  [{marker}] {message}")
    (PASSED if condition else FAILED).append(message)
    return condition


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def _bools(series: pd.Series) -> pd.Series:
    return series.map(
        lambda value: value is True or str(value).strip().lower() in {"true", "1"}
    )


def validate_worldpop() -> None:
    section("WorldPop external rasters and district-year output")
    paths = [cfg.worldpop_temporal_path(year) for year in cfg.TEMPORAL_YEARS]
    check(len(paths) == 12, "configuration requests exactly 12 years")
    check(all(path.exists() for path in paths), "all 12 requested rasters exist locally")
    if not all(path.exists() for path in paths):
        return

    grids = []
    for year, path in zip(cfg.TEMPORAL_YEARS, paths, strict=True):
        check(
            path.name == cfg.worldpop_temporal_filename(year),
            f"{year} filename pins {cfg.WORLDPOP_TEMPORAL_RELEASE} v1",
        )
        with rasterio.open(path) as src:
            grids.append(
                (
                    src.crs.to_string() if src.crs else None,
                    tuple(src.transform),
                    src.width,
                    src.height,
                    src.nodata,
                )
            )
            check(src.nodata is not None and math.isfinite(src.nodata),
                  f"{year} has a valid finite nodata value")
    check(len(set(grids)) == 1, "all annual rasters share identical grid geometry")
    check(grids[0][0] == cfg.GEOGRAPHIC_CRS, f"raster CRS is {cfg.GEOGRAPHIC_CRS}")

    path = cfg.WORLDPOP_DISTRICT_YEAR_FILE
    if not check(path.exists(), f"{path.name} exists"):
        return
    frame = pd.read_csv(path, dtype={"district_id": str})
    required = {
        "district_id", "district_name", "year", "geography_version",
        "population_modelled", "population_density_modelled_km2",
        "population_growth_pct_from_2015", "population_model_status",
        "population_projection_flag",
        "worldpop_release", "worldpop_product", "source_url",
    }
    check(required <= set(frame.columns), "district-year table has every required column")
    check(len(frame) == 144, "district-year table has 12 × 12 = 144 rows")
    check(not frame.duplicated(["district_id", "year"]).any(),
          "district-year key is unique")
    check(set(frame.year) == set(cfg.TEMPORAL_YEARS), "all requested years are present")
    check(frame.groupby("year").district_id.nunique().eq(12).all(),
          "every year contains 12 districts")
    check(frame.groupby("district_id").year.nunique().eq(12).all(),
          "every district contains 12 years")
    check(pd.to_numeric(frame.population_modelled, errors="coerce").notna().all(),
          "all modelled population values are numeric")
    check((frame.population_modelled > 0).all(), "all district populations are positive")
    check((frame.population_density_modelled_km2 > 0).all(),
          "all district population densities are positive")
    check(frame.population_model_status.eq(cfg.WORLDPOP_TEMPORAL_MODEL_STATUS).all(),
          "every district-year row explicitly identifies a modelled estimate")
    baseline = frame[frame.year == cfg.TEMPORAL_START_YEAR]
    check((baseline.population_growth_pct_from_2015 == 0).all(),
          "2015 baseline growth is exactly zero")
    flags = _bools(frame.population_projection_flag)
    check(set(frame.loc[flags, "year"]) == {2026} and flags.sum() == 12,
          "only the twelve 2026 district rows are projected")
    check(set(frame.worldpop_release) == {cfg.WORLDPOP_TEMPORAL_RELEASE},
          "district-year output pins the expected WorldPop release")
    check(set(frame.geography_version) == {cfg.TEMPORAL_GEOGRAPHY_VERSION},
          "district-year output uses the fixed geography identifier")
    check(frame.source_url.map(lambda value: cfg.WORLDPOP_TEMPORAL_RELEASE in value).all(),
          "every source URL pins the expected release")


def validate_siat() -> None:
    section("SIAT annual official control")
    path = cfg.SIAT_ANNUAL_POPULATION_FILE
    if not check(path.exists(), f"{path.name} exists"):
        return
    frame = pd.read_csv(path, dtype={"siat_code": str})
    required = {
        "siat_code", "district_name", "year", "population_thousand",
        "population_people", "geography_break_flag", "geography_note",
        "source_dataset", "source_url",
    }
    check(required <= set(frame.columns), "SIAT output has every required column")
    check(set(frame.source_dataset) == {cfg.SIAT_ANNUAL_DATASET_ID},
          "SIAT dataset ID is 246")
    check(set(frame.year) == set(cfg.TEMPORAL_YEARS), "SIAT years cover 2015–2026")
    check(len(frame) == 13 * 12, "SIAT has city plus 12 districts for 12 years")
    expected_codes = {cfg.TASHKENT_SOATO, *cfg.SIAT_TO_OSM_DISTRICT}
    check(set(frame.siat_code) == expected_codes, "SIAT identities are the expected city/district codes")
    city = frame[frame.siat_code == cfg.TASHKENT_SOATO]
    check(len(city) == 12, "SIAT citywide row is present for every year")
    check(pd.to_numeric(frame.population_thousand, errors="coerce").notna().all(),
          "SIAT values are numeric")
    check((frame.population_thousand >= 0).all(), "SIAT values are non-negative")
    check((frame.population_people == (frame.population_thousand * 1000).round()).all(),
          "SIAT people values equal thousands × 1,000")

    yang = frame[frame.siat_code == "1726292"]
    check((yang.loc[yang.year <= 2020, "population_thousand"] == 0).all()
          and (yang.loc[yang.year >= 2021, "population_thousand"] > 0).all(),
          "Yangikhayot structural zero/nonzero transition is detected")
    for code, name in (("1726292", "Yangikhayot"), ("1726283", "Sergeli"),
                       ("1726264", "Bektemir")):
        selected = frame[(frame.siat_code == code) & (frame.year == 2021)]
        check(len(selected) == 1 and bool(_bools(selected.geography_break_flag).iloc[0]),
              f"{name} has a 2021 boundary-break flag")
        check(selected.geography_note.fillna("").str.contains("Tashkent Region").all(),
              f"{name} note records external regional territory")
    check(not any("growth" in column.lower() for column in frame.columns),
          "SIAT output contains no ordinary growth field across the structural break")


def validate_metro() -> None:
    section("Metro station opening history")
    path = cfg.METRO_STATION_HISTORY_FILE
    timeline_path = cfg.METRO_OPENING_TIMELINE_FILE
    if not check(path.exists(), f"{path.name} exists"):
        return
    history = pd.read_csv(path, dtype={"station_id": str, "current_osm_id": str})
    check(len(history) == 50, "station history contains exactly 50 rows")
    check(history.station_id.notna().all() and history.station_id.is_unique,
          "stable station IDs are complete and unique")
    current = gpd.read_file(cfg.METRO_STATIONS_FILE)
    current_ids = set(current.osm_id.astype(str))
    check(set(history.current_osm_id) == current_ids,
          "every current station is covered exactly once")
    check(history.opening_year.notna().all()
          and history.opening_year.between(1977, 2024).all(),
          "every opening year is populated and plausible")
    check(history.line.fillna("").str.len().gt(0).all(), "every station has a line")
    check(history.source_url.fillna("").str.startswith("https://").all(),
          "every station has a source URL")
    check(history.source_provider.fillna("").str.len().gt(0).all(),
          "every station has a source provider")
    check(set(history.date_precision) <= {"day", "month", "year"},
          "date precision uses allowed explicit values")
    date_valid = history.apply(
        lambda row: bool(
            re.fullmatch(
                {"day": r"\d{4}-\d{2}-\d{2}", "month": r"\d{4}-\d{2}",
                 "year": r"\d{4}"}[row.date_precision],
                str(row.opening_date),
            )
        ),
        axis=1,
    )
    check(date_valid.all(), "opening-date strings match their precision")
    batch_consistent = history.groupby("opening_batch_id").agg(
        dates=("opening_date", "nunique"), years=("opening_year", "nunique"),
        lines=("line", "nunique"), sources=("source_url", "nunique")
    ).eq(1).all(axis=1).all()
    check(bool(batch_consistent), "opening batches have compatible date, line, and source history")
    check((history.source_quality == "primary").all(),
          "all station rows have primary-source support")

    if not check(timeline_path.exists(), f"{timeline_path.name} exists"):
        return
    timeline = pd.read_csv(timeline_path)
    check(timeline.year.is_monotonic_increasing, "opening timeline is sorted by year")
    check((timeline.stations_opened.cumsum() == timeline.cumulative_station_count).all(),
          "timeline cumulative counts equal the opening counts")
    check(int(timeline.cumulative_station_count.iloc[-1]) == 50,
          "opening timeline ends at 50 stations")


def validate_diagnostic() -> None:
    section("Temporal population diagnostic")
    path = cfg.TEMPORAL_POPULATION_DIAGNOSTIC_FILE
    if not check(path.exists(), f"{path.name} exists"):
        return
    frame = pd.read_csv(path)
    check(len(frame) == 12 and set(frame.year) == set(cfg.TEMPORAL_YEARS),
          "diagnostic years align with 2015–2026")
    check(frame.worldpop_source_label.eq(
        "WorldPop Global 2 R2025A v1 fixed current analysis footprint"
    ).all(), "WorldPop diagnostic source label is correct")
    check(frame.siat_source_label.eq(
        "SIAT dataset 246 official city population"
    ).all(), "SIAT diagnostic source label is correct")
    flags = _bools(frame.projection_flag)
    check(set(frame.loc[flags, "year"]) == {2026} and flags.sum() == 1,
          "diagnostic marks only 2026 as projected")
    pre = frame[frame.year <= 2020]
    check(pre.geography_comparability.eq("limited_changing_historical_footprint").all(),
          "pre-2021 rows make no false geography-comparability claim")
    check(pd.to_numeric(frame.difference_people, errors="coerce").notna().all()
          and pd.to_numeric(frame.difference_pct, errors="coerce").notna().all(),
          "diagnostic differences are numeric")


def validate_mask_diagnostic() -> None:
    section("WorldPop temporal mask diagnostic")
    path = cfg.WORLDPOP_TEMPORAL_MASK_DIAGNOSTIC_FILE
    if not check(path.exists(), f"{path.name} exists"):
        return
    diagnostic = json.loads(path.read_text(encoding="utf-8"))
    counts = diagnostic.get("cell_counts", {})
    required_counts = {
        "fixed_polygon_centre_cells", "valid_in_all_years_cells",
        "nodata_in_all_years_cells", "nodata_to_valid_cells",
        "valid_to_nodata_cells", "multi_switch_cells",
    }
    check(required_counts <= set(counts), "mask diagnostic has every required cell count")
    check(all(isinstance(counts.get(key), int) and counts[key] >= 0
              for key in required_counts), "mask cell counts are non-negative integers")
    classified = (
        counts.get("valid_in_all_years_cells", 0)
        + counts.get("nodata_in_all_years_cells", 0)
        + counts.get("nodata_to_valid_cells", 0)
    )
    check(
        counts.get("valid_to_nodata_cells") == 0
        and counts.get("multi_switch_cells") == 0
        and classified == counts.get("fixed_polygon_centre_cells"),
        "observed masks are monotonic nodata-to-valid with every polygon cell classified",
    )

    transitions = diagnostic.get("transition_counts_by_year", [])
    check(len(transitions) == len(cfg.TEMPORAL_YEARS) - 1
          and {row.get("to_year") for row in transitions}
          == set(cfg.TEMPORAL_YEARS[1:]),
          "mask diagnostic contains one transition record per year after 2015")
    check(sum(row.get("nodata_to_valid_cells", -1) for row in transitions)
          == counts.get("nodata_to_valid_cells")
          and sum(row.get("valid_to_nodata_cells", -1) for row in transitions)
          == counts.get("valid_to_nodata_cells"),
          "annual transition counts reconcile with the overall cell counts")
    check(all(math.isfinite(float(row.get("newly_valid_population_people")))
              and math.isfinite(float(row.get("newly_nodata_previous_population_people")))
              for row in transitions),
          "transition population contributions are finite")

    affected = diagnostic.get("affected_districts", [])
    check(bool(affected)
          and len({row.get("district_id") for row in affected}) == len(affected),
          "affected districts are listed once with stable identities")
    check(sum(row.get("nodata_to_valid_cells", -1) for row in affected)
          == counts.get("nodata_to_valid_cells")
          and sum(row.get("valid_to_nodata_cells", -1) for row in affected)
          == counts.get("valid_to_nodata_cells"),
          "affected-district transition counts reconcile")

    contributions = diagnostic.get("transition_cells_annual_population_contribution", [])
    check(len(contributions) == len(cfg.TEMPORAL_YEARS)
          and {row.get("year") for row in contributions} == set(cfg.TEMPORAL_YEARS),
          "transition-cell contributions cover every requested year")
    check(all(math.isfinite(float(row.get(key)))
              for row in contributions
              for key in ("population_people", "city_population_people",
                          "share_of_city_population_pct")),
          "annual transition-cell contribution metrics are finite")

    treatment = diagnostic.get("production_treatment", {})
    check(treatment.get("method") == "union_valid_with_annual_missing"
          and treatment.get("annual_nodata")
          == "stored as null/missing, never imputed as numeric zero",
          "production mask treatment retains union cells with annual missing values")
    encoding = diagnostic.get("raster_encoding", {})
    valid_zero_counts = encoding.get("valid_zero_cells_by_year", {})
    check(encoding.get("nodata_value") != 0
          and set(valid_zero_counts) == {str(year) for year in cfg.TEMPORAL_YEARS}
          and all(isinstance(count, int) and count > 0
                  for count in valid_zero_counts.values()),
          "raster diagnostic distinguishes valid numeric zero from the nodata sentinel")
    evidence = diagnostic.get("source_evidence", {})
    check(str(evidence.get("release_statement_url", ""))
          == cfg.WORLDPOP_RELEASE_STATEMENT_URL
          and "does not explicitly define" in str(evidence.get("not_established", "")),
          "diagnostic records the source limit on interpreting nodata as zero")

    sensitivity = diagnostic.get("sensitivity", {})
    city = sensitivity.get("city", {})
    city_fields = {
        "method_a_population_2015", "method_b_population_2015",
        "method_a_population_2026", "method_b_population_2026",
        "method_a_growth_pct", "method_b_growth_pct", "growth_difference_pp",
    }
    check(city_fields <= set(city)
          and all(math.isfinite(float(city[key])) for key in city_fields),
          "city mask-sensitivity metrics are finite and complete")
    districts = sensitivity.get("districts", [])
    district_fields = {
        "method_a_population_2015", "method_b_population_2015",
        "method_a_population_2026", "method_b_population_2026",
        "method_a_growth_pct", "method_b_growth_pct", "growth_difference_pp",
    }
    check(len(districts) == cfg.EXPECTED_ANALYSIS_DISTRICTS
          and len({row.get("district_id") for row in districts}) == len(districts)
          and all(district_fields <= set(row)
                  and all(math.isfinite(float(row[key])) for key in district_fields)
                  for row in districts),
          "district mask-sensitivity metrics are finite and complete")
    if districts:
        maximum = max(districts, key=lambda row: abs(row["growth_difference_pp"]))
        check(math.isclose(
            float(sensitivity.get("maximum_absolute_growth_difference_pp", math.nan)),
            abs(float(maximum["growth_difference_pp"])),
            abs_tol=1e-9,
        ) and sensitivity.get("maximum_difference_district_id")
            == maximum.get("district_id"),
            "reported maximum district sensitivity is data-derived")


def validate_provenance() -> None:
    section("Phase 2 provenance")
    path = cfg.PHASE2_SOURCE_MANIFEST_PATH
    if not check(path.exists(), f"{path.name} exists"):
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    worldpop = manifest.get("worldpop", {})
    siat = manifest.get("siat", {})
    metro = manifest.get("metro", {})
    access_spec = manifest.get("standardized_temporal_metro_access_specification", {})
    check(worldpop.get("release") == cfg.WORLDPOP_TEMPORAL_RELEASE,
          "manifest pins WorldPop R2025A")
    check(worldpop.get("product_version") == cfg.WORLDPOP_TEMPORAL_PRODUCT_VERSION,
          "manifest pins WorldPop product v1")
    check(worldpop.get("doi") == cfg.WORLDPOP_DOI, "manifest records the WorldPop DOI")
    files = worldpop.get("files", [])
    check(len(files) == 12 and {item.get("year") for item in files} == set(cfg.TEMPORAL_YEARS),
          "manifest records all twelve WorldPop files")
    check(all(str(item.get("url", "")).startswith("https://") for item in files),
          "manifest WorldPop source URLs are present")
    check(all(item.get("model_status") == cfg.WORLDPOP_TEMPORAL_MODEL_STATUS
              for item in files),
          "manifest explicitly identifies every WorldPop year as modelled")
    check(all(item.get("temporal_reference") == cfg.WORLDPOP_TEMPORAL_REFERENCE_DATE
              for item in files)
          and worldpop.get("temporal_reference") == cfg.WORLDPOP_TEMPORAL_REFERENCE_DATE,
          "manifest records the January 1 WorldPop reference date")
    check(worldpop.get("all_years_modelled") is True,
          "manifest states that all WorldPop years are modelled estimates")
    projection_definition = str(worldpop.get("projection_flag_definition", ""))
    check("release-year basis" in projection_definition
          and "False does not mean observed" in projection_definition,
          "manifest defines the projection flag without implying observation")
    check(all("http_etag" not in item and "http_last_modified" not in item
              for item in files),
          "deterministic manifest excludes transient HTTP response headers")
    cell_cache = worldpop.get("cell_cache", {})
    check(cell_cache.get("union_valid_cells", 0) > 0,
          "manifest records a non-empty fixed union cell cache")
    check(cell_cache.get("annual_nodata_cache_encoding") == "empty/null"
          and "null/missing" in str(cell_cache.get("nodata_treatment", "")),
          "manifest records annual nodata as missing rather than zero")
    if check(cfg.WORLDPOP_TEMPORAL_CELL_CACHE.exists(),
             "gitignored temporal cell cache exists for full validation"):
        cached_cells = pd.read_csv(cfg.WORLDPOP_TEMPORAL_CELL_CACHE)
        population_columns = [f"pop_{year}" for year in cfg.TEMPORAL_YEARS]
        expected_missing = {
            column: int(cell_cache.get("annual_nodata_counts", {}).get(str(year), 0))
            - int(cell_cache.get("excluded_all_years_nodata_cells", 0))
            for year, column in zip(cfg.TEMPORAL_YEARS, population_columns, strict=True)
        }
        observed_missing = {
            column: int(cached_cells[column].isna().sum())
            for column in population_columns
        }
        check(len(cached_cells) == cell_cache.get("union_valid_cells")
              and set(population_columns) <= set(cached_cells),
              "cell cache uses the documented union cell set and annual columns")
        check(observed_missing == expected_missing,
              "cell cache annual missing values match raster nodata masks")
        check(all((cached_cells[column].dropna() >= 0).all()
                  for column in population_columns),
              "cell cache contains only non-negative finite population estimates or missing")
    # The mask diagnostic is tracked text, so its on-disk newlines depend on the
    # checkout. It is pinned by canonical UTF-8 LF bytes, and an unknown or
    # missing basis fails rather than falling back to raw filesystem bytes.
    mask_record = worldpop.get("mask_diagnostic", {})
    mask_basis = mask_record.get("hash_basis")
    check(mask_basis == pm.HASH_BASIS_CANONICAL_TEXT,
          "mask diagnostic declares the canonical UTF-8 LF hash basis")
    try:
        mask_provenance = pm.canonical_provenance(
            cfg.WORLDPOP_TEMPORAL_MASK_DIAGNOSTIC_FILE
        )
    except (ValueError, UnicodeDecodeError):
        mask_provenance = None
    check(mask_provenance is not None,
          "mask diagnostic is canonical UTF-8 text with no bare CR")
    check(mask_record.get("filename") == cfg.WORLDPOP_TEMPORAL_MASK_DIAGNOSTIC_FILE.name
          and mask_record.get("production_method")
          == "union_valid_with_annual_missing"
          and mask_provenance is not None
          and mask_record.get("sha256") == mask_provenance["sha256"],
          "manifest pins the mask diagnostic and documented production method")
    check(mask_provenance is not None
          and mask_record.get("size_bytes") == mask_provenance["size_bytes"],
          "mask diagnostic size describes the same canonical bytes as its hash")
    check(siat.get("dataset_id") == cfg.SIAT_ANNUAL_DATASET_ID,
          "manifest pins SIAT dataset 246")
    check(str(siat.get("landing_url", "")).startswith("https://")
          and str(siat.get("download_api", "")).startswith("https://"),
          "manifest SIAT source URLs are present")
    check(len(metro.get("source_urls", [])) > 0,
          "manifest records metro source URLs")
    check(access_spec.get("status") == "specified_not_computed_in_phase2a",
          "manifest records that standardized access is specified but not computed")
    check(access_spec.get("historical_reconstruction_claim") is False,
          "manifest rejects a literal historical-reconstruction claim")
    check(access_spec.get("bus_history_used") is False,
          "manifest records that bus history is not used")
    check(access_spec.get("walking_budget_m") == 800.0,
          "manifest pins the standardized 800 m walking budget")
    serialized = json.dumps(manifest, ensure_ascii=False)
    check("D:\\" not in serialized and "C:\\" not in serialized,
          "manifest contains no temporary machine paths")

    methodology = (cfg.DOCS_DIR / "phase2_temporal_methodology.md").read_text(
        encoding="utf-8"
    )
    check("January 1" in methodology,
          "methodology records the WorldPop January 1 reference date")
    check("every year are modelled" in methodology
          and "`false` does not mean observed" in methodology,
          "methodology states all years are modelled and defines a false projection flag")
    check("stores a blank" in methodology and "Nodata is not imputed" in methodology,
          "methodology documents the chosen annual nodata treatment")


def main() -> int:
    print("=" * 74)
    print("Phase 2A temporal data foundation - validation")
    print("=" * 74)
    validate_worldpop()
    validate_siat()
    validate_metro()
    validate_diagnostic()
    validate_mask_diagnostic()
    validate_provenance()
    section("Summary")
    print(f"  passed: {len(PASSED)}")
    print(f"  failed: {len(FAILED)}")
    if FAILED:
        for message in FAILED:
            print(f"    FAIL {message}")
        print("\nVALIDATION FAILED")
        return 1
    print("\nVALIDATION PASSED")
    return 0


if __name__ == "__main__":
    enable_utf8_stdout()
    raise SystemExit(main())
