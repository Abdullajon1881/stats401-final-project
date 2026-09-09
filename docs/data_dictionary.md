# Data dictionary — `data/processed/`

Fields carried forward from Week 3 into the Week 4 analysis. Every GeoJSON here
is **EPSG:4326**; all metric work happens in **EPSG:32642** (see
[data_sources.md](data_sources.md)).

Provenance for each file, including counts and acquisition timestamps, is in
[`data/source_manifest.json`](../data/source_manifest.json).

---

## `tashkent_boundary.geojson`

One polygon: the Tashkent city administrative boundary.

| Field | Type | Notes |
|---|---|---|
| `osm_type` | string | Always `relation`. |
| `osm_id` | integer | `2216724`. |
| `name` | string | Name as tagged in OSM. |
| `area_km2` | float | Computed in EPSG:32642. |

Note: this boundary **includes Yangi Toshkent district**, so it is larger than
the union of the 12 SIAT districts. Which one is the right denominator is a Week 4
decision.

---

## `tashkent_districts.geojson`

13 polygons: every `admin_level=6` relation that is a member of the city
relation. Twelve are the official SIAT districts; one is not.

| Field | Type | Notes |
|---|---|---|
| `osm_type` | string | Always `relation`. |
| `osm_id` | integer | OSM relation id. Unique; the join key to the crosswalk. |
| `osm_name` | string | Uzbek name as tagged (`Yunusobod Tumani`). |
| `osm_name_en` | string | OSM `name:en`, where present. |
| `osm_name_ru` | string | OSM `name:ru`, where present. |
| `admin_level` | string | Always `6`. |
| `osm_start_date` | string | OSM `start_date`; only set for Yangi Toshkent (`2024`). |
| `siat_code` | string | SOATO code, e.g. `1726266`. Null when unmatched. |
| `siat_name_en` | string | Official SIAT English name. Null when unmatched. |
| `district_name` | string | **Canonical label used everywhere downstream.** SIAT name when matched, otherwise the OSM name. |
| `in_siat` | boolean | `true` for the 12 analysis districts, `false` for Yangi Toshkent. |
| `area_km2` | float | Computed in EPSG:32642. |
| `frac_inside_city` | float | Share of the district inside the city boundary; 1.0 for all 13. |

**Filter on `in_siat == true` for any population-weighted analysis.**

---

## `district_name_crosswalk.csv`

The explicit OSM ↔ SIAT mapping, so no downstream step has to guess that
`Yunusobod Tumani` and `Yunusabad district` are the same place.

| Field | Type | Notes |
|---|---|---|
| `osm_id` | integer | OSM relation id. |
| `osm_name`, `osm_name_en` | string | Names as OSM has them. |
| `siat_code` | string | SOATO code, or empty. |
| `siat_name_en` | string | SIAT name, or empty. |
| `district_name` | string | Canonical label. |
| `in_siat` | boolean | Whether a SIAT row exists. |

---

## `siat_district_population.csv`

12 rows, one per official district.

| Field | Type | Notes |
|---|---|---|
| `siat_code` | string | SOATO code. Unique. |
| `district_name` | string | Canonical label; joins to the districts layer. |
| `name_uz`, `name_ru`, `name_en_source` | string | Names exactly as SIAT publishes them. |
| `osm_relation` | integer | OSM relation id, from the crosswalk. |
| `population` | integer | **Persons.** Source value ×1000. |
| `population_thousands` | float | Raw source value, kept for traceability. |
| `reference_period` | string | `2026-Q2` for every row. |
| `source_dataset` | integer | SIAT dataset id `3890`. |

The 12 values sum exactly to the SIAT city total of 3,212,200. Use `population`;
`population_thousands` exists only so the published figure can be traced.

---

## `metro_stations.geojson`

50 points, one per physical metro station.

| Field | Type | Notes |
|---|---|---|
| `osm_element` | string | `node` or `way`. |
| `osm_id` | integer | OSM id of the surviving object. Unique. |
| `name` | string | Station name as tagged. Not translated. |
| `name_en`, `name_ru` | string | OSM `name:en` / `name:ru` where present. |
| `line` | string | **Empty** — Tashkent station nodes carry no `line` tag. |
| `network` | string | Usually `Ташкентский метрополитен`. |
| `operator` | string | Operator as tagged; sometimes missing. |
| `station_tag` | string | The `station` tag (`subway`). |
| `subway_tag` | string | The `subway` tag (`yes`). |
| `district_name` | string | District containing the point. |
| `district_assignment` | string | `within`, or `boundary_nearest` when the point lies exactly on a district border and was resolved to the nearest district. |

Where a station was mapped twice (Latin + Cyrillic), one object survives and the
other is dropped; `osm_id` is the survivor's.

---

## `metro_entrances.geojson`

`railway=subway_entrance` points. Several per station, and **not every station
has one** — surface and elevated Circle Line stations are not mapped this way.

| Field | Type | Notes |
|---|---|---|
| `osm_element` | string | Nearly always `node`. |
| `osm_id` | integer | Unique. |
| `name`, `name_en`, `name_ru` | string | Often null; entrances are usually unnamed. |
| `railway` | string | Always `subway_entrance`. |
| `district_name` | string | District containing the point. |
| `district_assignment` | string | `within`, or `boundary_nearest` when the point lies exactly on a district border and was resolved to the nearest district. |

Entrances are not linked to a parent station id — OSM does not reliably provide
that link. Week 4 should associate them by proximity, and fall back to the
station point where no entrance exists.

---

## `bus_stops.geojson`

Deduplicated bus stop access points.

| Field | Type | Notes |
|---|---|---|
| `osm_element` | string | `node`, `way` or `relation`. |
| `osm_id` | integer | Unique. |
| `name`, `name_ru` | string | Often null; unnamed stops are kept. |
| `highway` | string | `bus_stop` where tagged. |
| `public_transport` | string | `platform` or `stop_position`. |
| `bus` | string | `yes` where tagged. |
| `stop_role` | string | `platform` (kerbside, preferred) or `stop_position` (on the carriageway, kept only when unpaired). |
| `operator` | string | Rarely populated. |
| `district_name` | string | District containing the point. |
| `district_assignment` | string | `within`, or `boundary_nearest` when the point lies exactly on a district border and was resolved to the nearest district. |

Opposite-direction stops on the same road are intentionally **two separate
records**.

---

## `bazaars.geojson`

`amenity=marketplace` points. A lower bound on Tashkent's markets.

| Field | Type | Notes |
|---|---|---|
| `osm_element` | string | `node`, `way` or `relation`. Polygons are reduced to a point. |
| `osm_id` | integer | Unique. |
| `name`, `name_ru` | string | Some are generic (`базарчик`); a few are null. |
| `amenity` | string | Always `marketplace`. |
| `operator` | string | Rarely populated. |
| `district_name` | string | District containing the point. |
| `district_assignment` | string | `within`, or `boundary_nearest` when the point lies exactly on a district border and was resolved to the nearest district. |

---

## `worldpop_siat_diagnostic.csv`

**A diagnostic, not a project result.** Produced by
`python scripts/audit_population_surface.py`. 12 rows, one per SIAT district.
It exists so the WorldPop claims in [data_sources.md](data_sources.md) can be
reproduced instead of taken on trust. No calibration is applied and no
accessibility figure is derived from it.

| Field | Type | Notes |
|---|---|---|
| `district_name` | string | Canonical label. |
| `area_km2` | float | District area, EPSG:32642. |
| `worldpop_2020` | float | WorldPop R2025A constrained 2020, summed over the district. |
| `worldpop_2026` | float | Same for 2026 — the layer the project uses. |
| `siat_code` | string | SOATO code. |
| `siat_population` | integer | Official SIAT persons, 2026-Q2. |
| `ratio_2020_to_siat` | float | `worldpop_2020 / siat_population`. |
| `ratio_2026_to_siat` | float | `worldpop_2026 / siat_population`. |
| `scaling_2020_to_2026` | float | `worldpop_2026 / worldpop_2020` for the district total. A near-constant value across districts shows the two layers keep the same *between-district* split. It says nothing about whether population moved between cells *inside* a district — that is what `worldpop_temporal_diagnostic.json` tests. |

---

## `worldpop_temporal_diagnostic.json`

**A diagnostic, not a project result.** Written by
`python scripts/audit_population_surface.py`. Tests whether the WorldPop 2026
raster is simply the 2020 raster rescaled, at the **raster-cell** level over the
union of the 12 SIAT districts. District totals cannot answer this, because a
district total survives any reshuffle of cells inside it.

Every field describes a relationship between two **modelled** surfaces. None of
it measures construction, migration or settlement growth, and agreement between
the two layers does not validate the accuracy of either.

| Field | Notes |
|---|---|
| `years` | `[2020, 2026]` — the two WorldPop layers compared. |
| `grid_aligned` | `true` only if both rasters share one pixel grid. The script aborts otherwise. |
| `grid_compatibility` | Per-property CRS, dimensions, transform, nodata and bounds comparison, each with a `match` flag. |
| `positive_cell_threshold_persons` | Baseline cells at or below this (0.05 persons) are excluded from ratio statistics, so near-empty cells cannot manufacture huge ratios. Percentiles are stable for thresholds from 0 to 1.0. |
| `cells.in_masked_window` | Cells in the cropped window around the districts. |
| `cells.valid_in_both` | Cells with data in both years — the comparison set. |
| `cells.valid_only_in_baseline` / `valid_only_in_current` | Cells whose nodata status differs between the two modelled layers. A modelling difference, not an observation of settlement change. |
| `cells.zero_in_both`, `zero_to_positive`, `positive_to_zero` | Occupancy transitions. |
| `cells.above_ratio_threshold` | Cells used for the ratio statistics. |
| `totals` | Summed population per year over the comparison set, plus the population and share held by newly-valid cells. |
| `pearson_correlation_cell_values` | Correlation of 2020 vs 2026 cell values. |
| `scaling_factor.least_squares` / `.total_ratio` / `.median_of_cell_ratios` | Three estimates of a single multiplier relating the years. |
| `ratio_percentiles` | min, p1, p5, median, p95, p99, max of `2026 / 2020` per cell. |
| `residuals_after_least_squares_scaling` | Mean, median and max absolute residual in persons/cell after applying the fitted scalar `k`, plus `normalized_rmse` and `relative_l1_error`. |
| `fraction_of_cells_matching_scalar` | Share of cells within 0.1 / 0.5 / 1 / 5 / 10 % of a pure scalar multiple. |
| `residuals_after_least_squares_scaling.relative_l1_error` | `Σ&#124;B − kA&#124; ÷ ΣB`, where `A` is 2020, `B` is 2026 and `k` is the least-squares scalar. The total absolute cell-wise residual as a fraction of the modelled 2026 total. It is **not** variance explained, accuracy, or "population reproduced". |
| `modelled_differences` | Counts of cells whose modelled value ratio is above 1.5, above 2, or below 1, and the share of the modelled 2026 total held by cells above 1.5. Differences in model output, not observed change. |
| `is_pure_scalar_multiple` | Computed verdict. **Currently `false`.** |
| `one_minus_relative_l1_error` | Exactly `1 − relative_l1_error`. Kept only as a convenience; it carries no additional meaning and must not be described as accuracy or explained population. |

---

## Not committed (rebuilt by `scripts/acquire_data.py`)

| Path | What | Why not in git |
|---|---|---|
| `data/external/tashkent_walk_network.graphml` | Pedestrian graph for the city + 1 km buffer | Large and fully reproducible. |
| `data/external/uzb_pop_2026_CN_100m_R2025A_v1.tif` | WorldPop 2026 raster, 36 MB | Large, immutable, re-downloadable; SHA-256 recorded in the manifest. |
| `data/external/osm_cache/` | OSMnx HTTP cache | Cache. |
| `data/raw/siat_*.csv` | Untouched SIAT downloads | Reproducible; the processed CSV is committed instead. |
| `data/external/uzb_pop_2020_CN_100m_R2025A_v1.tif` | WorldPop 2020 raster, used only by the diagnostic script | Large; re-downloadable. Checksum recorded under `diagnostic_sources` in the manifest. |

## Conventions

* Geometry is stored in EPSG:4326; anything in metres is computed in EPSG:32642.
* `district_name` is the join key between layers.
* Names are whitespace-normalised only. Nothing is transliterated or translated.
* Population is in persons.
* No file contains a pandas index column; `validate_data.py` checks this.

## Validating

```bash
python scripts/validate_data.py              # FULL: committed + external artifacts
python scripts/validate_data.py --repo-only  # committed artifacts only
```

FULL is the default and is what the Week 3 test report uses. It requires the
WorldPop raster and the walk graph to be present and to match the size, checksum
and node/edge counts recorded in the manifest, so a missing or corrupt external
artifact is a hard failure.

`--repo-only` exists for a fresh clone, before `scripts/acquire_data.py` has run.
It checks only what git carries and **cannot certify the foundation on its own**;
it says so in its own output.
