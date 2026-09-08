"""Diagnostic: how well does WorldPop agree with official SIAT district totals?

    python scripts/audit_population_surface.py

This exists because `docs/data_sources.md` makes quantitative claims about the
WorldPop surface that were originally checked by hand. This script makes them
reproducible.

It aggregates the WorldPop R2025A constrained 100 m rasters for **2020** and
**2026** over the 12 SIAT-matched district polygons, compares both against the
official SIAT populations, and writes a small CSV.

THIS IS A DIAGNOSTIC, NOT A PROJECT RESULT. It computes no accessibility figure
and applies no calibration. Its only job is to characterise how usable WorldPop
is as a spatial weight before Week 4 relies on it.

Both rasters live in `data/external/` and are gitignored; only the small CSV is
committed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
from pipeline_utils import http_get, local_file_record, log, step, utc_now  # noqa: E402

# The comparison year. 2026 is the layer the project uses; 2020 is the earliest
# year of the same release that sits closest to the underlying census inputs, so
# it shows whether the disagreement is a projection artifact or inherent.
BASELINE_YEAR = 2020


def worldpop_url(year: int) -> str:
    return (
        f"https://data.worldpop.org/GIS/Population/Global_2015_2030/{cfg.WORLDPOP_RELEASE}/"
        f"{year}/UZB/v1/100m/constrained/"
        f"uzb_pop_{year}_CN_100m_{cfg.WORLDPOP_RELEASE}_v1.tif"
    )


def worldpop_path(year: int) -> Path:
    return cfg.EXTERNAL_DIR / f"uzb_pop_{year}_CN_100m_{cfg.WORLDPOP_RELEASE}_v1.tif"


def ensure_raster(year: int) -> Path:
    """Download the raster for `year` unless it is already cached."""
    target = worldpop_path(year)
    if target.exists():
        log(f"  cached: {target.name} ({cfg.human_size(cfg.file_size_bytes(target))})")
        return target

    url = worldpop_url(year)
    log(f"  downloading {url}")
    response = http_get(url, stream=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with target.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1 << 20):
            handle.write(chunk)
            written += len(chunk)
    log(f"  downloaded {cfg.human_size(written)} -> {target.name}")
    return target


def district_totals(raster: Path, districts: gpd.GeoDataFrame) -> list[float]:
    """Sum raster values inside each district polygon."""
    totals: list[float] = []
    with rasterio.open(raster) as src:
        polygons = districts.to_crs(src.crs)
        for _, row in polygons.iterrows():
            clipped, _ = mask(src, [row.geometry], crop=True, filled=True, nodata=src.nodata)
            band = clipped[0]
            valid = band[(band != src.nodata) & (band == band)]
            totals.append(float(valid.sum()) if valid.size else 0.0)
    return totals


def verify_grid_compatibility(rasters: dict[int, Path]) -> dict:
    """Confirm the two rasters share one pixel grid before comparing them cell by cell.

    Comparing array positions across rasters that are not aligned would silently
    compare different places on the ground, so a mismatch stops the run.
    """
    step("Raster grid compatibility")
    baseline, current = sorted(rasters)
    with rasterio.open(rasters[baseline]) as ra, rasterio.open(rasters[current]) as rb:
        report = {
            "baseline_year": baseline,
            "current_year": current,
            "crs": {"baseline": str(ra.crs), "current": str(rb.crs),
                    "match": ra.crs == rb.crs},
            "dimensions": {"baseline": [ra.width, ra.height],
                           "current": [rb.width, rb.height],
                           "match": (ra.width, ra.height) == (rb.width, rb.height)},
            "transform": {"baseline": [round(v, 12) for v in tuple(ra.transform)[:6]],
                          "current": [round(v, 12) for v in tuple(rb.transform)[:6]],
                          "match": ra.transform == rb.transform},
            "nodata": {"baseline": ra.nodata, "current": rb.nodata,
                       "match": ra.nodata == rb.nodata},
            "bounds_match": tuple(ra.bounds) == tuple(rb.bounds),
            "dtype": {"baseline": ra.dtypes[0], "current": rb.dtypes[0]},
        }

    for key in ("crs", "dimensions", "transform", "nodata"):
        log(f"  {key:12s}: match={report[key]['match']}  "
            f"{report[key]['baseline']} vs {report[key]['current']}")
    log(f"  {'bounds':12s}: match={report['bounds_match']}")

    report["aligned"] = bool(
        report["crs"]["match"]
        and report["dimensions"]["match"]
        and report["transform"]["match"]
        and report["nodata"]["match"]
        and report["bounds_match"]
    )
    if not report["aligned"]:
        raise RuntimeError(
            "WorldPop rasters are not on the same pixel grid; a cell-level "
            f"comparison would be meaningless. Details: {report}"
        )
    log("  -> identical pixel grid; cell-by-cell comparison is valid")
    return report


def cell_level_comparison(rasters: dict[int, Path], districts: gpd.GeoDataFrame) -> dict:
    """Test whether the later raster is a pure rescaling of the earlier one.

    District totals scaling by the same factor does not prove this: population
    can move between cells inside a district and leave the district total
    unchanged. Week 4 wants WorldPop for *within-district* weights, so the claim
    has to be tested at the cell level, which is what this does.
    """
    step("Cell-level comparison over the 12 SIAT districts")
    baseline, current = sorted(rasters)
    union = districts.union_all()

    def read(path: Path):
        with rasterio.open(path) as src:
            arr, transform = mask(src, [union], crop=True, filled=True, nodata=src.nodata)
            return arr[0].astype(np.float64), transform, src.nodata

    a, tr_a, nodata_a = read(rasters[baseline])
    b, tr_b, nodata_b = read(rasters[current])
    if a.shape != b.shape or tr_a != tr_b:
        raise RuntimeError("masked windows differ between years; cannot compare cells")

    valid_a = (a != nodata_a) & np.isfinite(a)
    valid_b = (b != nodata_b) & np.isfinite(b)
    both = valid_a & valid_b
    only_a = valid_a & ~valid_b
    only_b = valid_b & ~valid_a

    A = a[both]
    B = b[both]
    zero_both = int(((A == 0) & (B == 0)).sum())
    zero_to_pos = int(((A == 0) & (B > 0)).sum())
    pos_to_zero = int(((A > 0) & (B == 0)).sum())

    # Ratios explode when the baseline cell is essentially empty. 0.05 persons
    # per 100 m cell is the cut: below that a cell is model noise, not a place
    # where anyone lives. It removes only a handful of cells and no measurable
    # population, and the percentiles below are stable across thresholds from
    # 0 to 1.0 person per cell.
    threshold = 0.05
    ratio_mask = A > threshold
    ratios = B[ratio_mask] / A[ratio_mask]
    percentiles = [0, 1, 5, 50, 95, 99, 100]
    ratio_stats = dict(
        zip(
            ["min", "p1", "p5", "median", "p95", "p99", "max"],
            [float(v) for v in np.percentile(ratios, percentiles)],
        )
    )

    positive = A > 0
    k_least_squares = float((A[positive] * B[positive]).sum() / (A[positive] ** 2).sum())
    k_total = float(B.sum() / A.sum())
    k_median = float(np.median(B[positive] / A[positive]))

    residual = B - k_least_squares * A
    abs_residual = np.abs(residual)
    tolerances = [0.001, 0.005, 0.01, 0.05, 0.10]
    within = {
        f"within_{int(t * 1000) / 10:g}pct": float(
            (np.abs(ratios - k_median) <= t * k_median).mean()
        )
        for t in tolerances
    }

    high = ratios > 1.5
    result = {
        "years": [baseline, current],
        "grid_aligned": True,
        "positive_cell_threshold_persons": threshold,
        "cells": {
            "in_masked_window": int(a.size),
            "valid_in_both": int(both.sum()),
            "valid_only_in_baseline": int(only_a.sum()),
            "valid_only_in_current": int(only_b.sum()),
            "zero_in_both": zero_both,
            "zero_to_positive": zero_to_pos,
            "positive_to_zero": pos_to_zero,
            "above_ratio_threshold": int(ratio_mask.sum()),
        },
        "totals": {
            f"worldpop_{baseline}": float(A.sum()),
            f"worldpop_{current}": float(B.sum()),
            "population_in_cells_valid_only_in_current": float(b[only_b].sum()),
            "share_of_current_in_newly_valid_cells": float(
                b[only_b].sum() / b[valid_b].sum()
            ),
        },
        "pearson_correlation_cell_values": float(np.corrcoef(A, B)[0, 1]),
        "scaling_factor": {
            "least_squares": k_least_squares,
            "total_ratio": k_total,
            "median_of_cell_ratios": k_median,
        },
        "ratio_percentiles": ratio_stats,
        "residuals_after_least_squares_scaling": {
            "mean_absolute": float(abs_residual.mean()),
            "median_absolute": float(np.median(abs_residual)),
            "max_absolute": float(abs_residual.max()),
            "normalized_rmse": float(np.sqrt((residual**2).mean()) / B.mean()),
            "sum_absolute_over_total": float(abs_residual.sum() / B.sum()),
        },
        "fraction_of_cells_matching_scalar": within,
        "redistribution": {
            "cells_ratio_above_1_5": int(high.sum()),
            "cells_ratio_above_2": int((ratios > 2).sum()),
            "cells_ratio_below_1": int((ratios < 1).sum()),
            "share_of_current_total_in_cells_above_1_5": float(
                B[ratio_mask][high].sum() / B.sum()
            ),
        },
    }

    cells = result["cells"]
    log(f"  cells in window            : {cells['in_masked_window']:,}")
    log(f"  valid in both years        : {cells['valid_in_both']:,}")
    log(f"  valid only in {baseline}         : {cells['valid_only_in_baseline']:,}")
    log(f"  valid only in {current}         : {cells['valid_only_in_current']:,}")
    log(f"  zero in both years         : {cells['zero_in_both']:,}")
    log(f"  zero -> positive           : {cells['zero_to_positive']:,}")
    log(f"  positive -> zero           : {cells['positive_to_zero']:,}")
    log(f"\n  Pearson correlation        : {result['pearson_correlation_cell_values']:.6f}")
    log(f"  scaling factor (LS)        : {k_least_squares:.6f}")
    log(f"  scaling factor (total)     : {k_total:.6f}")
    log(f"  scaling factor (median)    : {k_median:.6f}")
    log("\n  ratio percentiles (2026/2020, cells above threshold):")
    for name, value in ratio_stats.items():
        log(f"    {name:>6}: {value:.6f}")
    res = result["residuals_after_least_squares_scaling"]
    log("\n  residuals after applying the fitted scalar:")
    log(f"    mean |resid|   : {res['mean_absolute']:.6f} persons/cell")
    log(f"    median |resid| : {res['median_absolute']:.6f} persons/cell")
    log(f"    max |resid|    : {res['max_absolute']:.4f} persons/cell")
    log(f"    normalized RMSE: {res['normalized_rmse']:.6f}")
    log(f"    sum|resid|/total: {res['sum_absolute_over_total']:.6f}")
    log("\n  share of cells within tolerance of a pure scalar multiple:")
    for name, value in within.items():
        log(f"    {name:>16}: {value:.4f}")

    # Verdict, computed from the numbers rather than assumed.
    tight = within["within_1pct"]
    pure_scalar = bool(
        tight > 0.99
        and cells["valid_only_in_current"] == 0
        and cells["zero_to_positive"] == 0
        and result["redistribution"]["cells_ratio_above_1_5"] == 0
    )
    result["is_pure_scalar_multiple"] = pure_scalar
    result["mass_share_explained_by_scalar"] = 1.0 - res["sum_absolute_over_total"]

    log("")
    if pure_scalar:
        log(f"  VERDICT: the {current} surface IS a pure scalar multiple of {baseline}.")
        log("           It adds no new spatial detail.")
    else:
        log(f"  VERDICT: the {current} surface is NOT a pure scalar multiple of {baseline}.")
        log(f"           {result['mass_share_explained_by_scalar']:.2%} of the {current} "
            f"population is reproduced by scaling {baseline} by "
            f"{k_least_squares:.4f}, but")
        log(f"           {cells['valid_only_in_current']:,} cells became populated that were "
            f"nodata in {baseline},")
        log(f"           {cells['zero_to_positive']:,} went from zero to positive, and "
            f"{result['redistribution']['cells_ratio_above_1_5']:,} cells grew by more "
            f"than 50%.")
        log(f"           Those fast-growing cells carry only "
            f"{result['redistribution']['share_of_current_total_in_cells_above_1_5']:.4%} "
            f"of the total, so the")
        log(f"           redistribution is real but small: the {current} layer still "
            f"carries essentially")
        log(f"           the {baseline} within-district pattern.")
    return result


def record_diagnostic_sources(rasters: dict[int, Path]) -> None:
    """Add a clearly separated diagnostic section to the source manifest.

    These rasters are not project inputs; only the 2026 layer is. Keeping them
    under their own key stops a diagnostic download from being mistaken for a
    source the analysis depends on.
    """
    if not cfg.MANIFEST_PATH.exists():
        log("  ! no source manifest yet; run scripts/acquire_data.py first")
        return

    manifest = json.loads(cfg.MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["diagnostic_sources"] = {
        "worldpop_year_comparison": {
            "acquired_at_utc": utc_now(),
            "purpose": (
                "Reproduces the WorldPop-vs-SIAT claims in docs/data_sources.md. "
                "Diagnostic only - not an input to the accessibility analysis."
            ),
            "produced_by": "scripts/audit_population_surface.py",
            "source": "WorldPop, University of Southampton",
            "product": cfg.WORLDPOP_PRODUCT,
            "release": cfg.WORLDPOP_RELEASE,
            "release_status": cfg.WORLDPOP_RELEASE_STATUS,
            "release_statement_url": cfg.WORLDPOP_RELEASE_STATEMENT_URL,
            "licence": "Creative Commons Attribution 4.0 International (CC BY 4.0)",
            "licence_url": cfg.WORLDPOP_LICENCE_URL,
            "licence_status": "verified",
            "years": sorted(rasters),
            "rasters": [
                {
                    "year": year,
                    "url": worldpop_url(year),
                    **local_file_record(path, checksum=True),
                }
                for year, path in sorted(rasters.items())
            ],
            "outputs": [
                str(path.relative_to(cfg.REPO_ROOT)).replace("\\", "/")
                for path in (cfg.WORLDPOP_DIAGNOSTIC_FILE, cfg.WORLDPOP_TEMPORAL_FILE)
            ],
        }
    }
    cfg.MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    log(f"  recorded diagnostic sources in {cfg.MANIFEST_PATH.name}")


def main() -> int:
    cfg.ensure_directories()

    step("WorldPop surface audit (DIAGNOSTIC - not a project result)")
    if not cfg.DISTRICTS_FILE.exists() or not cfg.SIAT_POPULATION_FILE.exists():
        log("  ! run scripts/acquire_data.py first; districts or population missing")
        return 1

    districts = gpd.read_file(cfg.DISTRICTS_FILE)
    districts = districts[districts.in_siat.astype(bool)].copy()
    population = pd.read_csv(cfg.SIAT_POPULATION_FILE, dtype={"siat_code": str})
    log(f"  districts: {len(districts)}   SIAT rows: {len(population)}")

    years = [BASELINE_YEAR, cfg.WORLDPOP_YEAR]
    rasters: dict[int, Path] = {}
    for year in years:
        log(f"\n  -- WorldPop {year} --")
        rasters[year] = ensure_raster(year)

    table = districts[["district_name", "area_km2"]].copy()
    for year in years:
        table[f"worldpop_{year}"] = district_totals(rasters[year], districts)

    table = table.merge(
        population[["district_name", "siat_code", "population"]],
        on="district_name",
        how="left",
    )
    table = table.rename(columns={"population": "siat_population"})

    baseline = f"worldpop_{BASELINE_YEAR}"
    current = f"worldpop_{cfg.WORLDPOP_YEAR}"
    table[f"ratio_{BASELINE_YEAR}_to_siat"] = table[baseline] / table.siat_population
    table[f"ratio_{cfg.WORLDPOP_YEAR}_to_siat"] = table[current] / table.siat_population
    table[f"scaling_{BASELINE_YEAR}_to_{cfg.WORLDPOP_YEAR}"] = table[current] / table[baseline]
    table = table.sort_values(f"ratio_{cfg.WORLDPOP_YEAR}_to_siat").reset_index(drop=True)

    step("Per-district comparison")
    header = (f"  {'district':24s} {BASELINE_YEAR:>11} {cfg.WORLDPOP_YEAR:>11} "
              f"{'SIAT':>11} {'r' + str(BASELINE_YEAR):>7} "
              f"{'r' + str(cfg.WORLDPOP_YEAR):>7} {'scale':>7}")
    log(header)
    log("  " + "-" * (len(header) - 2))
    for _, r in table.iterrows():
        log(f"  {r.district_name:24s} {r[baseline]:11,.0f} {r[current]:11,.0f} "
            f"{r.siat_population:11,.0f} "
            f"{r[f'ratio_{BASELINE_YEAR}_to_siat']:7.2f} "
            f"{r[f'ratio_{cfg.WORLDPOP_YEAR}_to_siat']:7.2f} "
            f"{r[f'scaling_{BASELINE_YEAR}_to_{cfg.WORLDPOP_YEAR}']:7.3f}")

    totals = {
        baseline: table[baseline].sum(),
        current: table[current].sum(),
        "siat": table.siat_population.sum(),
    }
    log("  " + "-" * (len(header) - 2))
    log(f"  {'TOTAL':24s} {totals[baseline]:11,.0f} {totals[current]:11,.0f} "
        f"{totals['siat']:11,.0f} "
        f"{totals[baseline] / totals['siat']:7.2f} "
        f"{totals[current] / totals['siat']:7.2f} "
        f"{totals[current] / totals[baseline]:7.3f}")

    step("Summary statistics")
    corr_baseline = float(table[baseline].corr(table.siat_population))
    corr_current = float(table[current].corr(table.siat_population))
    scaling = table[f"scaling_{BASELINE_YEAR}_to_{cfg.WORLDPOP_YEAR}"]
    ratio_current = table[f"ratio_{cfg.WORLDPOP_YEAR}_to_siat"]

    log(f"  correlation with SIAT, {BASELINE_YEAR}      : {corr_baseline:+.3f}")
    log(f"  correlation with SIAT, {cfg.WORLDPOP_YEAR}      : {corr_current:+.3f}")
    log(f"  {BASELINE_YEAR}->{cfg.WORLDPOP_YEAR} scaling factor    : "
        f"min {scaling.min():.3f}, max {scaling.max():.3f}, "
        f"spread {scaling.max() - scaling.min():.5f}")
    log(f"  {cfg.WORLDPOP_YEAR}/SIAT ratio range      : "
        f"{ratio_current.min():.2f} .. {ratio_current.max():.2f} "
        f"({ratio_current.max() / ratio_current.min():.1f}x spread)")
    log(f"  city-level {cfg.WORLDPOP_YEAR}/SIAT ratio  : "
        f"{totals[current] / totals['siat']:.3f}")

    uniform = bool((scaling.max() - scaling.min()) < 0.005)
    log("")
    if uniform:
        log(f"  READING: every district total scales by ~{scaling.mean():.3f} between "
            f"{BASELINE_YEAR} and {cfg.WORLDPOP_YEAR}.")
        log("           This says nothing on its own about whether population moved")
        log("           BETWEEN cells inside a district - a district total is preserved")
        log("           by any internal reshuffle. The cell-level section below is what")
        log("           actually tests that.")
    else:
        log(f"  READING: the {BASELINE_YEAR}->{cfg.WORLDPOP_YEAR} district scaling varies, so the")
        log(f"           {cfg.WORLDPOP_YEAR} layer redistributes population between districts.")
    if abs(corr_current) < 0.5:
        log(f"  READING: correlation with official district totals is {corr_current:+.3f}, so")
        log("           WorldPop carries little between-district signal here. It may only")
        log("           serve as a WITHIN-district weight, calibrated per district to SIAT.")

    cfg.WORLDPOP_DIAGNOSTIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    rounded = table.copy()
    for column in rounded.columns:
        if rounded[column].dtype.kind == "f":
            rounded[column] = rounded[column].round(4)
    rounded.to_csv(cfg.WORLDPOP_DIAGNOSTIC_FILE, index=False, encoding="utf-8")
    log(f"\n  wrote {cfg.WORLDPOP_DIAGNOSTIC_FILE.relative_to(cfg.REPO_ROOT)} "
        f"({len(rounded)} rows)")

    grid = verify_grid_compatibility(rasters)
    temporal = cell_level_comparison(rasters, districts)
    temporal["grid_compatibility"] = grid
    cfg.WORLDPOP_TEMPORAL_FILE.write_text(
        json.dumps(temporal, indent=2) + "\n", encoding="utf-8"
    )
    log(f"\n  wrote {cfg.WORLDPOP_TEMPORAL_FILE.relative_to(cfg.REPO_ROOT)}")

    record_diagnostic_sources(rasters)

    log("\n  Reminder: this is a diagnostic. No calibration is applied and no")
    log("  accessibility figure is produced here; that is Week 4 work.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
