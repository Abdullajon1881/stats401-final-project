# Phase 2 temporal methodology

## 1. Why Phase 2 exists

The completed project measures current public-transport accessibility in
Tashkent. Phase 2 adds a separately auditable temporal foundation for studying
population evolution and metro expansion without changing the deployed current
analysis.

## 2. Professor-requested temporal expansion

The eventual question is how public-transport accessibility changed over time
and where population growth outpaced access. Phase 2A supplies the annual
population series and station-opening history needed for the population-plus-
metro part of that question. It does not implement temporal accessibility or
frontend views.

## 3. Population sources

WorldPop Global 2 R2025A v1 constrained population counts are the primary
spatial series for 2015–2026. The release is pinned to DOI
`10.5258/SOTON/WP00839`; no other release is substituted. SIAT dataset 246 is
an official annual permanent-population control, in thousands of residents.
The WorldPop and SIAT series are not forced to agree.

## 4. Fixed-geography choice

Every WorldPop raster is aggregated to the same current 12-district analysis
geometry, identified as `current_12_district_analysis_geometry`. Each value
therefore means population modelled inside the current analysis footprint for
that model year. The polygons are not presented as historical 2015 boundaries.
Pixel centres determine district membership, providing one deterministic cell
identity and preventing double counting along shared district edges. The cell
cache retains the union of cells valid in any requested year, stores zero when a
cell is nodata in a particular year within that union, and excludes cells that
are nodata in all twelve years. This keeps one cell set while retaining cells
that enter the constrained model surface later.

## 5. 2021 administrative break

Yangikhayot appears as zero in SIAT through 2020 and becomes nonzero in 2021,
while Sergeli changes sharply. The reorganization also involved Bektemir and
territory transferred from Tashkent Region. The zero is structural, not a
population observation. SIAT rows for the city, Yangikhayot, Sergeli, and
Bektemir flag 2021 as a break. Ordinary 2020–2021 district growth must not be
calculated, and summing the three districts does not repair the historical
geography. The default safe official district comparison period is 2021–2026.

## 6. WorldPop modelling and alpha caveat

WorldPop values are modelled population surfaces, not annual census counts for
each neighbourhood. R2025A is an alpha release. Historical years remain model-
derived estimates, and 2026 is projected. Small-area changes must not be
described as observed migration or observed annual neighbourhood population.

## 7. SIAT official-control role

SIAT is a secondary official control. The diagnostic compares the annual
WorldPop total over the fixed current footprint with SIAT's official city total.
For 2015–2020 this has limited geography comparability because the official
historical city footprint differed. From 2021 comparability improves, but a
fixed analytical footprint and an official administrative series are still not
identical. The SIAT landing metadata reviewed here does not establish a precise
reference instant for every annual column, so the pipeline makes no mid-year or
January-1 assumption.

## 8. Metro opening-history sources

The 50-row station history uses current project station identities and current
station-centre coordinates. Opening batches come from government, presidential,
Tashkent Metro, and Uzbekistan Railways records. Month-only historical evidence
is stored as `YYYY-MM` with `date_precision=month`; the pipeline does not invent
days. Historical aliases are included only where the cited official source
states them. Current OSM IDs aid reconciliation but are not the stable project
primary key.

## 9. Standardized historical metro-access specification

The planned metric is `metro_access_pct_standardized`. It will use current
station-centre points for every year, include only stations open by the selected
year, snap those points to one fixed pedestrian network, and weight results with
that year's WorldPop surface within the fixed current geography. This is a
standardized temporal comparison, not a reconstruction of historical entrances
or street conditions.

## 10. What is held constant

- Current pedestrian graph and EPSG:32642 distance framework.
- Walking speed of 4.8 km/h.
- Ten-minute, 800-metre network-distance budget.
- Current station-centre source-placement rule for every station and year.
- Current 12-district fixed analysis geography.
- Routing and cell-to-network methodology.

## 11. What changes by year

- Metro stations included, based on `opening_year`.
- WorldPop modelled population weights for the selected year.

## 12. Why bus history is excluded from analytical history

Historical OSM bus features measure mapping state, not verified service state.
Tag evolution, duplicates, uneven mapper activity, and the lack of a consistent
official stop-coordinate archive make historical bus accessibility unsuitable
for the analytical series. Phase 2A contains no bus history and no historical
combined or underserved-access calculation.

## 13. Current headline versus temporal standardized metric

The current headline remains the audited, entrance-aware current method using
current calibrated population and the current network. Its approximately 13.6%
metro-access result is unchanged. The future temporal series will instead use a
uniform station-centre proxy, fixed current network, raw annual WorldPop model
weights, fixed current geography, and station opening-year filters. The two
methods answer different questions and must not be plotted or described as one
continuous identically measured series.

## 14. Known limitations

- WorldPop is modelled, R2025A is alpha, and 2026 is projected.
- Fixed current polygons do not recreate historical administrative boundaries.
- SIAT and WorldPop have different geography and measurement semantics.
- Historical entrance inventories and equal-quality pedestrian snapshots are
  unavailable.
- Station-centre access is a consistent proxy, not a literal entrance history.
- Some legacy station openings are known only to month precision.

## 15. Planned next phase

Phase 2B may compute the standardized station-centre metro-access series using
the frozen specification above. It must retain the existing entrance-aware
headline, validate each distinct opening-state network calculation, and keep bus
history outside the analytical temporal series.
