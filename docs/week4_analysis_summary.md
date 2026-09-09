# Week 4 analysis result — pending independent audit

**These figures are PRELIMINARY.** They have not been independently audited, they
are not in the README, and they are not a final project result. Method:
[analysis_methodology.md](analysis_methodology.md). Parameters and diagnostics:
[`data/analysis_manifest.json`](../data/analysis_manifest.json).

Everything below measures **physical walking access only** — not frequency,
service span, transfers, in-vehicle time, reliability, crowding, fare, or whether
the service goes anywhere useful.

> **These numbers replace the first Week 4 run.** Independent review found that
> nearest-node snapping on the simplified OSM pedestrian graph could add hundreds
> of metres to some population cells simply because no graph vertex existed near
> the middle of a long edge. Before any Week 4 result was merged, the analysis was
> recomputed using edge-aware network snapping. The superseded figures are kept
> below only for comparison.

## Headline

Analysis population: **3,212,200** — the official SIAT 2026-Q2 total for the 12
SIAT-matched districts. Walking at **4.8 km/h** for **10 minutes** (an 800 m
budget) along the real pedestrian network.

| Category | Population | Share |
|---|---|---|
| Within a 10-minute walk of a metro entrance | **435,690** | **13.56%** |
| Bus-only (no metro, but a bus stop within 10 minutes) | 2,314,113 | 72.04% |
| Underserved (neither within 10 minutes) | 462,397 | 14.40% |
| *Combined metro-or-bus walking access* | *2,749,803* | *85.60%* |

So roughly **one Tashkent resident in seven** can reach the metro on foot in ten
minutes, while **seven in ten** have a bus stop but no metro within that walk.

### What the correction changed

| Metric | Old (nearest-node) | New (edge-aware) | Change |
|---|---:|---:|---:|
| Metro accessible | 419,055 (13.05%) | **435,690 (13.56%)** | +16,635 (+0.52 pp) |
| Bus-only | 2,284,774 (71.13%) | **2,314,113 (72.04%)** | +29,339 (+0.91 pp) |
| Underserved | 508,371 (15.83%) | **462,397 (14.40%)** | −45,973 (−1.43 pp) |
| Combined metro-or-bus | 84.17% | **85.60%** | +1.43 pp |

The shift is not one-directional, which is the point. Nearest-node snapping both
charged some cells a walk to the end of a long edge they never had to make and
handed others a free straight-line jump to a vertex the network does not offer.
Eleven districts' metro shares rose (most, Yangikhayot, by +1.94 pp) and one
**fell** — Bektemir, from 3.01% to 2.46%.

## By district

Sorted by metro access. `metro pts` counts access points physically inside the
district — it is *not* the same as accessibility, because residents walk across
district boundaries. `nearest cell` is the shortest total walking distance from
any population cell in the district to a metro access point.

| District | Population | Metro | Metro % | Bus-only | Bus-only % | Underserved | Unserved % | Nearest cell | km² | per km² | metro pts | bus stops |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Mirabad | 157,500 | 39,199 | **24.89** | 113,846 | 72.28 | 4,456 | 2.83 | 4.7 m | 16.7 | 9,406 | 17 | 155 |
| Chilanzar | 277,600 | 64,049 | **23.07** | 188,977 | 68.08 | 24,574 | 8.85 | 16.9 m | 30.3 | 9,148 | 39 | 203 |
| Yunusabad | 396,800 | 91,317 | **23.01** | 238,150 | 60.02 | 67,333 | 16.97 | 12.2 m | 41.4 | 9,595 | 29 | 249 |
| Shaykhantakhur | 375,000 | 76,700 | 20.45 | 285,100 | 76.03 | 13,199 | 3.52 | 2.8 m | 26.9 | 13,915 | 20 | 206 |
| Sergeli | 182,500 | 25,454 | 13.95 | 79,285 | 43.44 | 77,761 | 42.61 | 36.6 m | 51.5 | 3,545 | 5 | 126 |
| Yangikhayot | 205,200 | 25,347 | 12.35 | 107,751 | 52.51 | 72,102 | 35.14 | 18.2 m | 42.2 | 4,862 | 7 | 105 |
| Mirzo Ulugbek | 345,300 | 39,168 | 11.34 | 275,839 | 79.88 | 30,293 | 8.77 | 8.7 m | 38.7 | 8,919 | 19 | 240 |
| Yashnabad | 322,300 | 32,497 | 10.08 | 210,759 | 65.39 | 79,044 | 24.53 | 22.7 m | 78.2 | 4,121 | 10 | 250 |
| Yakkasaray | 147,000 | 11,104 | 7.55 | 130,608 | 88.85 | 5,288 | 3.60 | 49.8 m | 14.1 | 10,424 | 3 | 96 |
| Almazar | 421,300 | 29,045 | 6.89 | 356,122 | 84.53 | 36,134 | 8.58 | 35.4 m | 33.7 | 12,498 | 4 | 213 |
| Bektemir | 73,600 | 1,810 | 2.46 | 34,473 | 46.84 | 37,317 | 50.70 | 55.7 m | 35.7 | 2,062 | 1 | 56 |
| **Uchtepa** | 308,100 | **0** | **0.00** | 293,205 | **95.17** | 14,895 | 4.83 | **819.7 m** | 28.2 | 10,925 | **0** | 182 |

### Uchtepa is still 0.00% — but by 19.7 m, which is not robust

Uchtepa survived the correction as the only district with zero modelled metro
access, and the traced evidence is now on the record rather than asserted:

| | |
|---|---|
| Calibrated population | 308,100 |
| Metro-access population | 0 |
| Metro-access share | 0.00% |
| Nearest population cell | `r172c90` at 69.19708 E, 41.27875 N (71.3 people) |
| Its total walking distance to metro | **819.70 m** |
| Margin against the 800 m budget | **+19.70 m** |
| That cell's off-network connector | 5.00 m |
| Nearest metro access point | `entrance:5431967358` — **Chilonzor** station entrance, in **Chilanzar district**, connector 0.00 m |
| Does the access path leave Uchtepa? | **Yes** — 19 network nodes, crossing the district boundary |
| Metro access at 4.0 km/h (667 m) | 0.00% |
| Metro access at 4.8 km/h (800 m) | 0.00% |
| Metro access at 5.6 km/h (933 m) | 0.09% (280 people) |

Two things follow, and only two.

**The zero is not a bug and not a rounding artifact.** Uchtepa contains no metro
station at all, its 0 access points are a fact of the data, and the nearest cell's
819.70 m was re-derived by a second, independent route — a plain node-to-node
Dijkstra with each source attached to both endpoints of its edge, plus explicit
same-edge handling — agreeing to 0.00 × 10⁰ m. The cell's own connector is 5.00 m,
so the result is not an artefact of the off-network approximation either.

**The zero is not robust.** A 19.70 m margin is about fifteen seconds of walking.
Anything of that order — a missing OSM footpath, a mapped entrance that is one
building away from where people actually enter, the 400 m entrance-association
radius, the simplified edge geometry — could flip it. It should be reported as
*"no cell within the 800 m budget, the nearest missing by 20 m"*, never as
*"robustly zero"*. At 5.6 km/h it is already nonzero.

With 308,100 residents and 95.17% bus-only, Uchtepa is nonetheless the clearest
bus-dependent district in the city on the continuous measures.

No arbitrary "bus-dependent" threshold has been invented. The most bus-dependent
districts are **Uchtepa (95.17% bus-only)**, **Yakkasaray (88.85%)** and
**Almazar (84.53%)**. The highest *underserved* shares are **Bektemir (50.70%)**,
**Sergeli (42.61%)** and **Yangikhayot (35.14%)** — peripheral districts where
neither mode is within a 10-minute walk.

## Walking-speed sensitivity

The question stays 10 minutes; only the assumed speed moves. Distances are
speed-independent, so all three scenarios reuse the same two shortest-path
passes.

| Speed | Budget | Metro | Metro % | Bus-only % | Underserved % | Combined % |
|---|---|---|---|---|---|---|
| 4.0 km/h | 666.7 m | 319,883 | 9.96 | 69.64 | 20.40 | 79.60 |
| **4.8 km/h** | **800.0 m** | **435,690** | **13.56** | **72.04** | **14.40** | **85.60** |
| 5.6 km/h | 933.3 m | 555,661 | 17.30 | 71.98 | 10.73 | 89.27 |

Metro access and combined access rise monotonically and underserved falls
monotonically, as they must. Bus-only does **not** move monotonically
(69.64 → 72.04 → 71.98) and is not required to: as the budget grows, cells enter
the bus-only category from *underserved* and leave it for *metro* at the same
time.

The headline is sensitive to the speed assumption: ±0.8 km/h moves metro access
by roughly ±3.7 percentage points, so the figure should always be quoted with its
speed.

## Population-surface sensitivity (WorldPop 2020 vs 2026)

Both surfaces calibrated to the **same** SIAT 2026-Q2 district totals, so this
isolates within-district spatial weights.

City metro access: **13.57% on the 2020 surface, 13.56% on the 2026 surface — a
difference of −0.01 percentage points.** The largest district difference is
Yakkasaray at −0.11 pp; Mirabad is −0.09 pp and every other district moves by
less than 0.06 pp.

It means the headline is **not** sensitive to which WorldPop year is used — but
it does **not** show that either surface distributes population correctly within
a district. Two runs of the same model agreeing tells us nothing about accuracy.

## Diagnostics

### Network

| | |
|---|---|
| Nodes | 111,386 |
| Stored OSMnx edge records (directional) | 308,272 |
| Usable edge records | 308,272 |
| **Canonical undirected routing edges** | **154,133** |
| Records backing each canonical edge | 154,130 × 2 records, 3 × 4 records |
| Canonical self-loops | 350 |
| Node pairs carrying parallel edges | 1,380 |
| Longest canonical edge | 6,845.9 m |
| Canonical edges longer than the 800 m budget | 336 |

### Off-network connectors — distance to the nearest walkable **edge**

| Points | n | min | mean | median | p95 | p99 | max |
|---|---|---|---|---|---|---|---|
| Metro access points | 154 | 0.0 m | 2.1 m | 0.0 m | 14.5 m | 25.7 m | 42.8 m |
| Bus stops | 2,163 | 0.0 m | 1.4 m | 0.0 m | 8.3 m | 16.5 m | 244.1 m |
| Population cells (2026) | 65,169 | 0.0002 m | 33.4 m | 16.5 m | 122.3 m | 324.3 m | 899.9 m |
| Population cells (2020) | 64,920 | 0.0002 m | 33.4 m | 16.5 m | 122.4 m | 324.2 m | 899.9 m |

Against the superseded **nearest-node** offsets — metro median 6.7 / max 55.4 m,
bus median 20.5 / max 244.1 m, cells median 39.6 / p95 175.6 / p99 367.5 /
max 905.9 m — every statistic improved, as it must, since the nearest edge is
never farther than the nearest vertex. The improvement is large at the median
(cells 39.6 → 16.5 m) and modest in the tail (p99 367.5 → 324.3 m): the far tail
is genuine remoteness from any mapped walkable way, not a vertex artefact.

**Off-network connectors are straight-line approximations to the nearest mapped
walkable edge. They may not represent a physically walkable connection in every
case, so their effect on individual cells is uncertain.** A connector may cross a
fence, a parcel boundary, a building, a railway, a canal, private land or another
unmapped barrier; the model does not know. No claim is made about the direction
of the effect.

The tail is small in population terms:

| Cell connector | Cells | People | Share of city |
|---|---|---|---|
| > 200 m | 1,423 | 12,021 | 0.374% |
| > 400 m | 427 | 3,217 | 0.100% |
| > 800 m | 16 | 280 | 0.009% |

The worst cells cluster in the far north-east of Mirzo Ulugbek around
69.452 E, 41.414 N, and carry 8–29 people each. Only two of 2,163 bus stops have
a connector over 100 m; the worst is **Food City SM** in Bektemir at 244.1 m, a
stop inside a large wholesale market complex whose internal paths are not mapped
as public walkable ways. It is reported, not removed.

### Source placement

| | Metro | Bus |
|---|---|---|
| Sources | 154 | 2,163 |
| Spliced into an edge **interior** (>1 m from either endpoint) | 128 | 2,119 |
| Effectively at an existing endpoint | 26 | 44 |
| Distinct canonical edges containing sources | 151 | 2,090 |
| Most sources on one edge | 2 | 4 |
| Augmented nodes added | 129 | 2,124 |
| Augmented routing segments (canonical 154,133) | 154,262 | 156,257 |
| Augmented nodes reachable | 110,917 / 111,515 (99.46%) | 113,427 / 113,510 (99.93%) |

The 128 vs 129 difference is a reporting threshold, not a discrepancy: placement
counts use a 1 m endpoint tolerance, while the splitter uses 1 µm, so one source
sitting under a metre from an endpoint gets its own vertex but is reported as
"effectively at an endpoint".

### Population and coverage

| | |
|---|---|
| Population cells | 65,169 (~100 m, cell centre in exactly one district) |
| Metro access points | 154 = 144 mapped entrances + 10 station fallbacks |
| Bus stops | 2,163 |
| Calibration factors | 12, one per district, spanning a 10.84× range |
| Calibrated total vs official | 3,212,200.0000 vs 3,212,200 (difference 0.000000) |
| Population on components with **no metro** source | 13,091 (0.41%) |
| Population on components with **no bus** source | 0 |
| Cells: metro / bus-only / underserved | 7,157 / 40,087 / 17,925 |

The 13,091 people with no metro source on their component are 436 cells in the
far north-east of Mirzo Ulugbek (69.441–69.470 E, 41.400–41.422 N). Their
pedestrian-network component carries bus stops but no metro access point, so
their metro distance is **+inf** rather than a large finite number.

The 10 fallback stations — Matonat, Choshtepa, Oʻzgarish, Yangihayot, Chinor,
Qipchok, Turon, Tuzel, Rohat, Olmos — were computed from a 400 m association
radius, not carried over from Week 3. That they match Week 3's independent
observation of ten such stations is a useful cross-check.

## Display layers

`metro_isochrone_10min.geojson` — **49.68 km²**, 333 KB, 12 separate parts
(largest 30.19 km²) that trace the metro corridors rather than forming one blob.
`bus_isochrone_10min.geojson` — **295.74 km²**, 2.0 MB, 10 parts.

Both are built from the augmented segments, so a stop in the middle of a long
edge produces reachable geometry around itself. They grew from the superseded
47.78 km² and 282.85 km² for that reason, and because partial segments are now
cut along the real edge geometry rather than along the straight chord between
vertices.

**These polygons are for visualisation only.** Every population figure above is
computed from network distances and does not depend on them — and the difference
is not academic. Counting the same run both ways:

| How metro access is counted | Population | Share |
|---|---:|---:|
| Network distance ≤ 800 m — **the reported statistic** | 435,690 | **13.56%** |
| Cell centre inside the 40 m-buffered display polygon | 472,641 | 14.71% |

The polygon disagrees in both directions — 942 cells (56,046 people) inside it are
800–1,965 m from the metro by network, while 390 cells (19,095 people) within the
budget fall outside it because their connector exceeds the 40 m buffer — and the
net **+1.15 pp** is larger than the whole nearest-node → edge-aware correction.
Uchtepa's nearest cell sits inside the polygon while being 819.70 m from the metro
by network. The polygon is drawn on the map and counts nobody.

The bus layer at 2.0 MB is heavy for a web page; Week 5 may want to simplify it
further or convert to TopoJSON.

## What would change these numbers

1. **Walking speed.** ±0.8 km/h moves metro access by ~3.7 pp (see above).
2. **The off-network connector.** Cell centres and transit points are joined to
   the network by a straight line to the nearest mapped walkable edge. Whether a
   given connector is physically walkable is unknown, so its effect on individual
   cells is uncertain in an unknown direction.
3. **The simplified graph geometry.** Positions along an edge are exact, but the
   edge's shape is OSM's generalisation of the real path.
4. **Metro entrance completeness.** 10 of 50 stations have no mapped entrance and
   fall back to the station point, which flatters those stations. Uchtepa's 19.7 m
   margin is well inside the range this could move.
5. **Bus stop completeness.** OSM only; no official operator list was reachable,
   so the 72.04% bus-only figure is unvalidated against ground truth.
6. **Within-district population distribution.** WorldPop R2025A is an alpha
   product and its within-district accuracy is unverified — the 2020/2026 test
   above does not address that.

## Two corrections worth recording

**Edge-aware snapping (this run).** The first Week 4 implementation snapped
population cells and transit points to the nearest graph *node*. On a simplified
OSM graph that is not defensible: 336 canonical edges are longer than the entire
800 m budget, 2,147 cells (30,943 people) sit on such an edge, and along those
edges the nearest vertex is a median 307.9 m away and up to 3,393.8 m. Cells and
sources are now snapped to the nearest walkable edge and spliced into it, and a
cell's distance is read off at its own position along its own edge.

**Duplicate-edge doubling (caught during the first run).** An earlier run
produced 3.93% metro access. The cause was that `scipy.sparse.coo_matrix` **sums**
duplicate `(row, col)` entries, and the OSMnx graph stores both directions of
every way — so symmetrising it doubled every edge weight. The number looked
plausible and was wrong. Canonicalisation now removes the directional copies
before any matrix is built, and **TEST C** in
`scripts/test_accessibility_utils.py` reconstructs that exact situation from a
GraphML file and fails if a walking cost doubles.

## Verification

`python scripts/test_accessibility_utils.py` — 10 synthetic routing tests, all
passing: same-edge source and cell, endpoint equivalence against a plain
Dijkstra, OSM directional duplicates, several sources on one edge, parallel edges
keeping geometry and cost together, disconnected components returning +inf,
connectors charged once each, self-loops, a mid-edge source on a 6 km edge, and
agreement with an independent brute-force reference over 1,000 random queries
(worst disagreement 4.6 × 10⁻¹³ m).

`python scripts/validate_analysis.py` — 217 checks passing, 0 warnings, 0
critical.

`python scripts/validate_data.py` — the Week 3 foundation still validates: 157
passing, 2 documented warnings, 0 critical. No source dataset was re-acquired or
modified for this correction.
