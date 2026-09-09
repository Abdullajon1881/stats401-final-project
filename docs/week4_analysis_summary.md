# Week 4 analysis result — pending independent audit

**These figures are PRELIMINARY.** They have not been independently audited, they
are not in the README, and they are not a final project result. Method:
[analysis_methodology.md](analysis_methodology.md). Parameters and diagnostics:
[`data/analysis_manifest.json`](../data/analysis_manifest.json).

Everything below measures **physical walking access only** — not frequency,
service span, transfers, in-vehicle time, reliability, crowding, fare, or whether
the service goes anywhere useful.

## Headline

Analysis population: **3,212,200** — the official SIAT 2026-Q2 total for the 12
SIAT-matched districts. Walking at **4.8 km/h** for **10 minutes** (an 800 m
budget) along the real pedestrian network.

| Category | Population | Share |
|---|---|---|
| Within a 10-minute walk of a metro entrance | **419,055** | **13.05%** |
| Bus-only (no metro, but a bus stop within 10 minutes) | 2,284,774 | 71.13% |
| Underserved (neither within 10 minutes) | 508,371 | 15.83% |
| *Combined metro-or-bus walking access* | *2,703,829* | *84.17%* |

So roughly **one Tashkent resident in eight** can reach the metro on foot in ten
minutes, while **seven in ten** have a bus stop but no metro within that walk.

## By district

Sorted by metro access. `metro pts` counts access points physically inside the
district — it is *not* the same as accessibility, because residents walk across
district boundaries.

| District | Population | Metro | Metro % | Bus-only | Bus-only % | Underserved | Unserved % | km² | per km² | metro pts | bus stops |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Mirabad | 157,500 | 37,681 | **23.92** | 113,892 | 72.31 | 5,927 | 3.76 | 16.7 | 9,406 | 17 | 155 |
| Chilanzar | 277,600 | 62,486 | **22.51** | 191,911 | 69.13 | 23,203 | 8.36 | 30.3 | 9,148 | 39 | 203 |
| Yunusabad | 396,800 | 88,015 | **22.18** | 234,882 | 59.19 | 73,904 | 18.62 | 41.4 | 9,595 | 29 | 249 |
| Shaykhantakhur | 375,000 | 75,908 | 20.24 | 282,905 | 75.44 | 16,187 | 4.32 | 26.9 | 13,915 | 20 | 206 |
| Sergeli | 182,500 | 23,439 | 12.84 | 76,482 | 41.91 | 82,579 | 45.25 | 51.5 | 3,545 | 5 | 126 |
| Mirzo Ulugbek | 345,300 | 38,767 | 11.23 | 269,576 | 78.07 | 36,958 | 10.70 | 38.7 | 8,919 | 19 | 240 |
| Yangikhayot | 205,200 | 21,370 | 10.41 | 104,805 | 51.07 | 79,025 | 38.51 | 42.2 | 4,862 | 7 | 105 |
| Yashnabad | 322,300 | 30,158 | 9.36 | 208,187 | 64.59 | 83,955 | 26.05 | 78.2 | 4,121 | 10 | 250 |
| Yakkasaray | 147,000 | 10,905 | 7.42 | 130,172 | 88.55 | 5,923 | 4.03 | 14.1 | 10,424 | 3 | 96 |
| Almazar | 421,300 | 28,109 | 6.67 | 351,127 | 83.34 | 42,064 | 9.98 | 33.7 | 12,498 | 4 | 213 |
| Bektemir | 73,600 | 2,219 | 3.01 | 32,752 | 44.50 | 38,629 | 52.49 | 35.7 | 2,062 | 1 | 56 |
| **Uchtepa** | 308,100 | **0** | **0.00** | 288,084 | **93.50** | 20,016 | 6.50 | 28.2 | 10,925 | **0** | 182 |

### Uchtepa is 0.00%, and that is a real result

Uchtepa contains **no metro station at all**, and its closest population cell is
**815.2 m** from the nearest metro access point — 15 m past the 800 m budget. So
the zero is genuine, not a rounding artifact or a bug, but it is a knife-edge: at
5.6 km/h (a 933 m budget) it becomes 0.11%. With 308,100 residents and 93.50%
bus-only, Uchtepa is the clearest bus-dependent district in the city.

No arbitrary "bus-dependent" threshold has been invented. On the continuous
measures, the most bus-dependent districts are **Uchtepa (93.50% bus-only)**,
**Yakkasaray (88.55%)** and **Almazar (83.34%)**. The highest *underserved*
shares are **Bektemir (52.49%)**, **Sergeli (45.25%)** and **Yangikhayot
(38.51%)** — peripheral districts where neither mode is within a 10-minute walk.

## Walking-speed sensitivity

The question stays 10 minutes; only the assumed speed moves.

| Speed | Budget | Metro | Metro % | Bus-only % | Underserved % | Combined % |
|---|---|---|---|---|---|---|
| 4.0 km/h | 666.7 m | 305,894 | 9.52 | 67.94 | 22.54 | 77.46 |
| **4.8 km/h** | **800.0 m** | **419,055** | **13.05** | **71.13** | **15.83** | **84.17** |
| 5.6 km/h | 933.3 m | 536,463 | 16.70 | 71.61 | 11.69 | 88.31 |

Metro access rises and underserved falls monotonically with speed, as they must.
The headline is sensitive to the speed assumption: ±0.8 km/h moves metro access
by roughly ±3.5 percentage points, so the figure should always be quoted with its
speed.

## Population-surface sensitivity (WorldPop 2020 vs 2026)

Both surfaces calibrated to the **same** SIAT 2026-Q2 district totals, so this
isolates within-district spatial weights.

City metro access: **13.05% on the 2020 surface, 13.05% on the 2026 surface —
a difference of −0.01 percentage points.** The largest district difference is
Yakkasaray at −0.11 pp; every other district moves by less than 0.09 pp.

This is consistent with the Week 3 finding that the two modelled surfaces are
nearly interchangeable. It means the headline is **not** sensitive to which
WorldPop year is used — but it does **not** show that either surface distributes
population correctly within a district. Two runs of the same model agreeing tells
us nothing about accuracy.

## Diagnostics

| | |
|---|---|
| Population cells | 65,169 (~100 m, cell centre in exactly one district) |
| Metro access points | 154 = 144 mapped entrances + 10 station fallbacks |
| Bus stops | 2,163 |
| Metro snap offset | median 6.7 m, p95 39.7 m, max 55.4 m |
| Bus snap offset | median 20.5 m, p95 50.6 m, max 244.1 m (Food City SM) |
| Cell snap offset | median 39.6 m, p95 175.6 m, max 905.9 m |
| Nodes reachable from metro / bus | 99.46% / 99.93% |
| Population on components with no metro source | 13,096 (0.41%) |
| Population on components with no bus source | 5 |
| Calibrated total vs official | 3,212,200.0000 vs 3,212,200 (difference 0.000000) |

The 10 fallback stations — Matonat, Choshtepa, Oʻzgarish, Yangihayot, Chinor,
Qipchok, Turon, Tuzel, Rohat, Olmos — were computed from a 400 m association
radius, not carried over from Week 3. That they match Week 3's independent
observation of "about ten" is a useful cross-check.

## Display layers

`metro_isochrone_10min.geojson` — 47.78 km², 349 KB, 12 separate parts that trace
the metro corridors rather than forming one blob.
`bus_isochrone_10min.geojson` — 282.85 km², 2.1 MB.

**These polygons are for visualisation only.** Every population figure above is
computed from network distances and does not depend on them. The bus layer at
2.1 MB is heavy for a web page; Week 5 may want to simplify it further or convert
to TopoJSON.

## What would change these numbers

1. **Walking speed.** ±0.8 km/h moves metro access by ~3.5 pp (see above).
2. **The off-network connector.** Cell centres and transit points are joined to
   the network by a straight line; real walks are longer, so access is if
   anything slightly overstated.
3. **Metro entrance completeness.** 10 of 50 stations have no mapped entrance and
   fall back to the station point, which flatters those stations.
4. **Bus stop completeness.** OSM only; no official operator list was reachable,
   so the 71.13% bus-only figure is unvalidated against ground truth.
5. **Within-district population distribution.** WorldPop R2025A is an alpha
   product and its within-district accuracy is unverified — the 2020/2026 test
   above does not address that.

## One correction worth recording

An earlier run of this analysis produced 3.93% metro access. The cause was that
`scipy.sparse.coo_matrix` **sums** duplicate `(row, col)` entries, and the OSMnx
graph stores both directions of every way — so symmetrising it doubled every edge
weight. The number looked plausible and was wrong. It was caught because a
47.78 km² service area is what ~50 stations at an 800 m budget should produce,
while the 18.52 km² the buggy version produced is not. Edge units were then
verified independently: across 307,458 edges, no edge is shorter than the
straight line between its own endpoints, and the median ratio is 1.0005.
