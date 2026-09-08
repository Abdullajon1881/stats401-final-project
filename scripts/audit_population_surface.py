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
            "output": str(
                cfg.WORLDPOP_DIAGNOSTIC_FILE.relative_to(cfg.REPO_ROOT)
            ).replace("\\", "/"),
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
        log(f"  READING: every district scales by ~{scaling.mean():.2f} between "
            f"{BASELINE_YEAR} and {cfg.WORLDPOP_YEAR}, so the {cfg.WORLDPOP_YEAR} layer is")
        log("           essentially a uniform rescaling of the earlier surface and adds")
        log("           no new spatial detail for Tashkent.")
    else:
        log(f"  READING: the {BASELINE_YEAR}->{cfg.WORLDPOP_YEAR} scaling varies by district, so the")
        log(f"           {cfg.WORLDPOP_YEAR} layer does redistribute population.")
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

    record_diagnostic_sources(rasters)

    log("\n  Reminder: this is a diagnostic. No calibration is applied and no")
    log("  accessibility figure is produced here; that is Week 4 work.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
