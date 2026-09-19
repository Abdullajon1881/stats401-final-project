# Phase 2B standardized temporal metro accessibility

## 1. Question

How did modelled 10-minute walking access to Tashkent's metro change from 2015
through 2026 when the comparison holds geography, the pedestrian network,
routing assumptions, and station locations constant?

## 2. Standardized comparison design

This analysis estimates `metro_access_pct_standardized` for each year from
2015 through 2026. It changes two inputs: the source-backed set of stations
open in the selected year and that year's WorldPop R2025A v1 model weights. It
holds the current pedestrian network, current station-centre coordinates,
walking assumptions, routing method, and current 12-district geography fixed.

This is a **standardized temporal comparison**, not a historical
reconstruction. It does not claim to recreate historical streets, station
entrances, construction barriers, or pedestrian conditions.

## 3. Fixed current pedestrian network

Every year uses the exact current `tashkent_walk_network.graphml` snapshot from
the audited current analysis. The graph is analysed in EPSG:32642 and validated
against the existing source and analysis manifests before routing. The graph is
not reacquired for Phase 2B.

Holding the graph fixed makes changes comparable, but it also means the series
cannot measure historical changes in the street or footpath network.

## 4. Station-centre proxy

All 50 stations use the current longitude and latitude recorded in
`metro_station_history.csv`. Those station-centre points are transformed to
EPSG:32642 and snapped once to the fixed pedestrian network. A station enters
the source set when `opening_year <= year`; its point never moves between
years.

The standardized series does not use mapped entrances. Station centres are a
consistent temporal proxy, not a claim about the precise place where riders
entered each station in each historical year.

## 5. Metro opening states

Opening years imply four distinct source sets in the analytical period:

- 29 stations for 2015–2019;
- 43 stations for 2020–2022;
- 48 stations for 2023;
- 50 stations for 2024–2026.

The pipeline derives these sets from station history and runs one multi-source
shortest-path calculation per distinct set. Event years are 2020, 2023, and
2024. Station names in the event table also come from station history rather
than a hard-coded list.

## 6. Annual WorldPop weighting

Population weights come from WorldPop Global 2 constrained population counts,
R2025A v1, for 2015–2026. Every year is a modelled estimate with a January 1
temporal reference. The weights are not calibrated to SIAT.

For each year, the denominator is the sum of finite annual model values and the
numerator is the sum of those values on cells whose standardized metro distance
is at most 800 metres. District and city denominators reconcile with the
committed Phase 2A district-year table.

Phase 2A serializes individual cache cells to six decimal places but computed
its committed district totals before that serialization. Phase 2B therefore
applies a minute district-year reconciliation factor equal to the committed
Phase 2A total divided by the sum of its finite serialized cells. This restores
the authoritative WorldPop aggregate while preserving relative cell weights
and missingness. It is not SIAT calibration and is not used to make the temporal
series agree with the current headline.

## 7. NoData treatment

The population cache contains a fixed union of 65,169 cells that are valid in
at least one requested year. If a cell is NoData in a particular year, that
annual value remains missing. It is excluded from that year's numerator and
denominator and is never relabelled as numeric zero.

## 8. Edge-aware routing

The analysis reuses the audited primitives in `accessibility_utils.py`:
`load_walk_network`, `build_edge_index`, `snap_points_to_edges`,
`build_augmented_network`, `multi_source_distances`, and `query_positions`.
Station sources and population cells attach to the nearest walkable edge, not
the nearest graph node.

The model uses a 4.8 km/h walking speed, 10 minutes, and an 800 metre network
budget. Each station connector and each population-cell connector is charged
once. Unrounded distances determine whether a cell is accessible. No service-
area polygon or route trace is used.

Because later states only add sources, fixed-cell distances cannot increase and
accessible-cell masks must be nested. Both invariants are validated directly.
Annual access percentages need not increase when the network state is unchanged
because annual modelled population weights can shift.

## 9. City aggregation

`metro_access_temporal_city.csv` contains one row for each year. It reports the
metro state, open-station count, available modelled population, accessible
modelled population, standardized percentage, change from 2015, model status,
projection flag, WorldPop release, temporal reference, and fixed-geography
version.

## 10. District aggregation

`metro_access_temporal_district.csv` contains 12 districts by 12 years. Cells
retain the `district_id` assigned in the Phase 2A fixed cache, so no annual
spatial reassignment occurs. Each district-year denominator reconciles with
`worldpop_district_year.csv`; annual district totals reconcile with the city.

## 11. Counterfactual diagnostics

The counterfactual table reports three descriptive series:

1. actual standardized access, using the network state and population model
   for year Y;
2. network change on 2015 population, using the network state for year Y with
   fixed 2015 population weights;
3. population change under the 2015 network, using the fixed 2015 source state
   with population weights for year Y.

The second series isolates source-set changes under one modelled population
surface. The third isolates population-surface changes under one source set.
They are counterfactual diagnostics, **not an additive causal decomposition**.

## 12. Difference from the current 13.56% headline

The audited current headline is `13.563595724255597%`. It is entrance-aware,
uses current SIAT-calibrated population, and answers the current-period access
question. The Phase 2B series uses station centres and raw annual WorldPop model
weights to support a controlled temporal comparison.

The current headline and the standardized temporal series use different
methodologies and should not be joined into one supposedly identical metric.
The 2026 values are not forced to agree, and neither is labelled correct or
wrong merely because they differ.

## 13. What the series can tell us

The series describes how modelled metro walking access changes when station
opening states and annual modelled population weights vary inside a fixed
analytical frame. It identifies the years in which the source set expands,
shows district differences, and supports controlled diagnostics of network-
state and population-surface change.

## 14. What the series cannot tell us

It cannot reconstruct historical pedestrian networks or entrance locations,
establish causal effects of metro construction, measure observed residential
relocation, or describe historical bus access. Annual event changes combine
metro expansion and annual modelled population change, so they are labelled
combined annual standardized changes rather than pure infrastructure effects.

## 15. Limitations

- WorldPop R2025A is a modelled alpha product and all years are estimates.
- Current station-centre positions proxy historical source placement.
- The current pedestrian graph is held fixed across the full period.
- Straight-line off-network connectors may cross unmapped barriers.
- Physical access omits frequency, service span, transfers, reliability,
  crowding, fares, and destination usefulness.
- No historical bus series is included because the available evidence cannot
  support a defensible operational history.

## 16. Planned visualization use

After analytical review, the city series, district series, event table, and
counterfactual diagnostics can support a temporal frontend. Phase 2B itself
does not modify `site/`, add a slider or animation, publish web data, or change
deployment configuration.
