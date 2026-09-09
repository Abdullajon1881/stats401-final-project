# Accessibility methodology (Week 4)

How the Week 3 datasets become the metro/bus access numbers. Results produced by
this method are **preliminary and pending independent audit**; the computed
figures live in [week4_analysis_summary.md](week4_analysis_summary.md).

Everything here is produced by `scripts/analyze_accessibility.py`, checked by
`scripts/validate_analysis.py`, and gated by the synthetic routing tests in
`scripts/test_accessibility_utils.py`. Run parameters and diagnostics are
recorded in [`data/analysis_manifest.json`](../data/analysis_manifest.json).

## Correction: nearest-node snapping was replaced with edge-aware snapping

The first Week 4 implementation snapped population cells and transit points to
the nearest graph **node**. Independent review found that this is not defensible
on a simplified OSM pedestrian graph, and the analysis was rebuilt before any
Week 4 result was merged.

> Independent review found that nearest-node snapping on the simplified OSM
> pedestrian graph could add hundreds of metres to some population cells simply
> because no graph vertex existed near the middle of a long edge. Before any
> Week 4 result was merged, the analysis was recomputed using edge-aware network
> snapping.

The problem is structural, not a coding slip. OSMnx simplification puts vertices
at intersections and endpoints, **not** continuously along every path. On this
graph:

* the longest single canonical edge is **6,845.9 m**, and **336** canonical edges
  are longer than the entire 800 m walking budget;
* **2,147 population cells (30,943 people)** sit on such an edge, and along those
  edges the nearest vertex is a median of **307.9 m** away, p95 **1,348.1 m**,
  worst **3,393.8 m**;
* the old model's measured straight-line cell-to-vertex offsets ran to a median
  of 39.6 m, a 99th percentile of **367.5 m** and a maximum of **905.9 m** — all
  against an 800 m budget.

Nearest-node snapping distorts in **both** directions, which is why the
correction was not a one-way shift. It charged some cells a walk to the end of a
long edge that they never had to make, and it handed others a free straight-line
jump to a vertex that the pedestrian network does not actually offer. The
corrected city figures moved by +0.52 pp for metro access and −1.43 pp for the
underserved share, and one district's metro share went **down**.

Everything below describes the corrected method.

## What this measures, and what it does not

It measures **physical walking access**: can a resident reach a metro entrance
(or a bus stop) on foot, along the real pedestrian network, within 10 minutes.

It says nothing about **route frequency, service span, transfers, in-vehicle
travel time, reliability, crowding, fare, or whether the service goes anywhere
useful**. A stop served twice a day counts exactly as much as one served every
three minutes. Any interpretation of these numbers has to carry that caveat.

## Analysis boundary

The population denominator is the **union of the 12 SIAT-matched districts**,
written to `data/processed/analysis_boundary.geojson` and derived reproducibly
from the `in_siat == true` features of `tashkent_districts.geojson`.

**Yangi Toshkent is excluded from the population denominator.** Week 3
established that it is a real 13th district in the OSM city relation
(`start_date=2024`) but has no SIAT population row. Every population figure here
depends on calibrating WorldPop to an official district total, and for Yangi
Toshkent there is no official total to calibrate against — including it would
mean inventing one. It stays in the district file and on the map for geographic
context; it is simply not in the denominator.

So the denominator is the official SIAT 2026-Q2 total for those 12 districts:
**3,212,200 people**.

## The canonical pedestrian network

The real walk network from Week 3
(`data/external/tashkent_walk_network.graphml`), not straight-line buffers. No
result in this analysis comes from an 800 m circle.

Edge counting is stated precisely, because the previous manifest called 308,272
"undirected edges" and that is wrong:

| Quantity | Count |
|---|---:|
| Nodes | 111,386 |
| **Stored** OSMnx edge records (directional) | 308,272 |
| **Usable** edge records (finite, positive `length`) | 308,272 |
| **Canonical undirected routing edges** | **154,133** |
| of which self-loops (`u == v`) | 350 |
| distinct node pairs among them | 152,736 |
| node pairs carrying parallel edges | 1,380 |

OSMnx stores every undirected way twice, once per direction. Each record is
re-oriented so that `u <= v` — reversing its geometry with it — and records are
then deduplicated on `(u, v, length, geometry)`. The result is exact, not
approximate: **154,130 canonical edges are backed by exactly 2 records and 3 by
exactly 4**, which accounts for all 308,272 records with none left over and none
double-counted.

Parallel ways between the same node pair are **kept as separate canonical
edges**, each carrying its own geometry *and* its own routing cost. Collapsing
them to the shorter one would discard the longer way as a snap target: here
1,380 node pairs carry parallel edges, 547 of them where the longer way is more
than twice the shorter, and the extreme case is 57.8×. A cell standing beside a
long riverside path would otherwise have been costed against a short direct link
it is not on.

Self-loops are kept too. 350 of them are real closed walkable paths, up to
1,592 m long, and a population cell can legitimately stand beside one.

All metric geometry is in **EPSG:32642**. Routing weights are OSMnx's `length`
(geodesic metres along the way); the projected geometry length differs from it
only by the UTM scale factor, measured across this graph as **0.9984 to 1.0022**.
Positions along an edge are therefore carried as a dimensionless **fraction** and
converted with that same edge's routing cost, never by subtracting projected
metres from geodesic metres.

Edges are **undirected**: a pedestrian may walk either way along any way in a
walk network.

> One implementation detail worth recording, because it silently changed the
> answer. Building the sparse adjacency with `scipy.sparse.coo_matrix` **sums**
> duplicate `(row, col)` entries. The OSMnx graph stores both directions of a
> way, so symmetrising it produced duplicate pairs whose weights were summed —
> doubling every edge and cutting modelled metro access to 3.93%. Canonicalisation
> now removes the directional copies before any matrix is built, and the matrix
> builder additionally collapses any repeated pair to its minimum weight. **TEST C**
> in `scripts/test_accessibility_utils.py` reconstructs that exact situation from
> a GraphML file and fails if a walking cost doubles.

## Metro access points

Entering the metro means walking to an **entrance**, so the 144 mapped
`railway=subway_entrance` points are the access points.

A station centre is used **only as a fallback**, for a station with no mapped
entrance associated with it. Using every station centre *as well* would let a
resident "reach" a deep underground station at its surface centroid, flattering
stations whose real entrances are further away.

Association rule: a station counts as having a mapped entrance if one lies within
**400 m** of it, measured in EPSG:32642. This assumption is carried over from the
first implementation unchanged — it was not re-tuned, and changing it to move the
headline percentage would not be legitimate. Stations beyond that radius
contribute their own point, and every fallback is recorded in
`data/processed/metro_access_points.csv` with the station, the reason, the
distance to the nearest mapped entrance, and the geometry.

The counts are **derived, never hard-coded**: 40 of 50 stations have an
associated mapped entrance and **10 fall back**, giving **154** metro access
points (144 entrances + 10 fallbacks). Week 3's independent observation of ten
such stations is a cross-check, not an input.

## Edge-aware snapping and the off-network connector

Metro access points, bus stops and population-cell centres are all snapped to the
nearest walkable **edge**, not the nearest vertex. For each point the model
records the canonical edge, the straight-line **off-network connector** to it,
the snapped position, the fraction along the edge, and the routing cost from that
position to each of the edge's two endpoints:

```
cost_to_u = fraction       * edge_cost
cost_to_v = (1 - fraction) * edge_cost
```

Connectors are reported in full (`data/processed/transit_snap_diagnostics.csv`
and the manifest) and never used to quietly discard a point.

### What an off-network connector does and does not mean

**Off-network connectors are straight-line approximations to the nearest mapped
walkable edge. They may not represent a physically walkable connection in every
case, so their effect on individual cells is uncertain.**

A connector may cross a fence, a parcel boundary, a building, a railway, a canal,
private land or another unmapped barrier. The model does not know. No directional
claim is made about whether they overstate or understate access — the earlier
statement that they made access "slightly overstated" was not supportable and has
been removed.

## Sources enter the middle of edges

A transit source is spliced into the canonical edge it stands beside. Each edge
is cut at the snapped positions of the sources lying on it, ordered along the
edge, producing an **augmented graph** in which every source is a real vertex.
Sources within 1 µm of each other share one vertex; a source that lands on an
existing endpoint reuses that endpoint rather than adding a duplicate at distance
zero, so the endpoint case behaves exactly like ordinary graph routing
(**TEST B**).

A source is not free to enter. A temporary super-source is joined to each source
vertex with **edge weight equal to that source's off-network connector**, and one
Dijkstra from the super-source gives, for every augmented vertex:

```
min over access points of (connector to the network + network distance)
```

This runs **once for metro and once for bus** — two shortest-path passes in
total, not one per cell. Vertices on a component holding no source of that mode
come back as **+inf**, never 0 and never missing, and the population sitting on
them is reported.

## Population cells query from edge interiors

Every population-cell centre is snapped to an edge in the same way, and its
network distance is read off directly at its own position along that edge.

A queried position lies inside exactly one **segment** of its (possibly split)
edge, between two consecutive breaks `a` and `b`. That segment's interior holds
no vertex and no source by construction, so any path reaching the position must
enter through `a` or through `b`. Therefore

```
d(position) = min( d(a) + cost(a -> position),
                   d(b) + cost(position -> b) )
```

is **exact**, with `d(a)` and `d(b)` taken from the multi-source Dijkstra above.

### The same-edge case

This is what makes the model right where the old one was wrong. If a metro
entrance sits 500 m along a 1,000 m edge and a population cell sits at 550 m, the
entrance is one of the cell's bracketing breaks and the answer is **50 m** — not
a walk out to an endpoint and back. **TEST A** asserts exactly that, and it is
verified on the real data too: 39 population cells sit on an edge that also
carries a metro access point, and their distances reproduce
`cell connector + source connector + |Δfraction| × edge cost` exactly. For
example cell `r156c196` on canonical edge 35327 (cost 66.73 m, cell at fraction
0.8904, the Toshkent entrance at 0.8324):

```
0.86 + 0.00 + |0.8904 - 0.8324| x 66.73 = 4.729 m   (pipeline: 4.729 m)
```

A self-loop needs no special case: its two breaks are the same vertex, so the
formula returns `min(d(u) + f·L, d(u) + (1-f)·L)` — round the loop the short way.

### Total walking distance

```
population cell -> nearest walkable edge   (off-network connector)
+ exact network distance along the pedestrian network
+ transit point  -> nearest walkable edge  (off-network connector)
```

Each connector is charged **exactly once** (**TEST G**). The validator re-derives
the connector distribution from the cached per-cell table and checks that no
cell's total is ever smaller than its own connector.

## Complexity and why it is fast enough

The graph is 111,386 nodes and 154,133 canonical edges; there are 65,169
population cells, 2,163 bus stops and 154 metro access points. A Dijkstra per
cell would be 65,169 searches. Instead:

| Step | Cost |
|---|---|
| Build the canonical network (streamed GraphML parse) | O(records) |
| Snap all points to edges (`shapely.STRtree`, built once and reused) | O((s + c) log m) |
| Split edges at sources | O(s log s) |
| **One multi-source Dijkstra per mode** | 2 × O(E log V) |
| Answer every cell by bracketing its position | O(c log m) |

Two shortest-path passes answer every cell for every mode. Walking-speed
sensitivity **reuses those distances** and recomputes no path — only the budget
changes.

Correctness is checked two ways. Ten synthetic tests cover the same-edge case,
endpoint equivalence, directional duplicates, several sources on one edge,
parallel edges, disconnected components, connector double-counting, self-loops
and a long mid-edge source. On top of that, **TEST I** compares the fast path
against an independent brute-force reference — an all-pairs Dijkstra over the
canonical vertices plus explicit enumeration of the four endpoint combinations
and the same-edge shortcut — over 1,000 random queries on 40 random networks,
with a worst disagreement of 4.6 × 10⁻¹³ m.

## Population: SIAT totals, WorldPop weights

Week 3 established that WorldPop disagrees with SIAT between districts
(correlation −0.077, ratios 0.31–3.33). So WorldPop is **not allowed to decide
how population splits between districts**. SIAT does.

1. Each WorldPop 2026 raster cell is assigned to **exactly one** district: the
   one whose polygon contains the **cell centre**. `rasterio.features.rasterize`
   with `all_touched=False` tests exactly that, so no boundary cell is counted
   twice. Cells whose centre falls in no district, or that carry nodata, are
   excluded.
2. Per district: `calibration_factor = official_SIAT / raw_WorldPop_sum`.
3. Every cell in that district is multiplied by its district's factor.

There is **no city-wide factor**. Each district gets its own — they span a 10.84×
range — so calibrated district totals reproduce the official SIAT totals and sum
to 3,212,200.

WorldPop therefore contributes only *within-district* spatial weights. Week 3
found those weights to be of unverified accuracy; "Sensitivity" below tests how
much that matters.

## Walking model

**4.8 km/h = 1.3333… m/s**, and **10 minutes = 600 s**, giving a distance budget
of exactly **800 m** at the headline speed.

A cell is metro-accessible when `metro_distance / speed <= 600 s`. Times are
compared **unrounded**.

## Access categories

At the main scenario, every cell falls into exactly one category:

| Category | Condition |
|---|---|
| `metro_accessible` | metro time ≤ 600 s |
| `bus_only` | metro time > 600 s **and** bus time ≤ 600 s |
| `underserved` | metro time > 600 s **and** bus time > 600 s |

Mutually exclusive by construction. The analysis asserts the partition at cell
level, and the validator re-derives it independently from the cached per-cell
table and checks that the three populations sum to the district total and the
three percentages sum to 100.

Bus access uses all 2,163 cleaned Week 3 bus stops with the same edge-aware
treatment.

## Sensitivity

**Walking speed** — 4.0, 4.8 and 5.6 km/h, all at 10 minutes
(`walking_speed_sensitivity.csv`). The research question stays 10 minutes; these
are scenarios, not alternative questions. Metro access and combined access must
not fall as speed rises, and underserved must not rise; the validator enforces
this at city *and* district level. Bus-only is *not* required to be monotonic,
because both boundaries move at once and cells can cross from bus-only into
metro — and here it does move non-monotonically (69.64 → 72.04 → 71.98).

**Population surface** — the whole classification is recomputed using the
WorldPop **2020** surface instead of 2026
(`population_surface_sensitivity.csv`). Both surfaces are calibrated to the
**same SIAT 2026-Q2 district totals**, so the comparison isolates differences in
*within-district spatial weights*, not changes in district population. This is a
sensitivity test; neither surface is treated as ground truth.

## Service-area polygons are for display only

`metro_isochrone_10min.geojson` and `bus_isochrone_10min.geojson` exist so the
Week 5+ D3 map has a geographic layer. **The population statistics do not depend
on them at all** — classification is done on network distances directly, never by
intersecting a polygon with the population raster.

Construction is edge-aware too. The reachable set is built from the **augmented
segments**, so a stop in the middle of a long edge produces reachable geometry
around itself even when both of that edge's original endpoints lie beyond the
budget. A segment with both ends inside the budget contributes its real geometry;
a segment with one end inside is cut where the budget runs out, **along the true
edge geometry** rather than along the straight chord between vertices; a segment
with neither end inside contributes nothing, which is correct because a segment
interior can only be entered through one of its own two ends. The result is
buffered by 40 m in EPSG:32642, dissolved, simplified at 10 m and written as
WGS84.

Buffering is done in chunks and then dissolved, which is equivalent to one union
of per-segment buffers but does not exhaust memory on the bus network.

This is deliberately **not** a convex hull and not a circle: both would bridge
rivers, rail corridors and other barriers the pedestrian network does not cross.

### Why the polygon must not be used to count people

The 40 m buffer makes the polygon a generous visual envelope, not a
classification boundary. Counting the same run both ways makes the size of that
difference concrete:

| How metro access is counted | Population | Share |
|---|---:|---:|
| Network distance ≤ 800 m — **the reported statistic** | 435,690 | **13.56%** |
| Cell centre inside the 40 m-buffered display polygon | 472,641 | 14.71% |

The polygon disagrees in **both** directions: 942 cells (56,046 people) fall
inside it while being 800–1,965 m from the metro by network, because the 40 m
buffer spills past the end of the reachable stretch; and 390 cells (19,095
people) are within the 800 m budget yet outside it, because their off-network
connector is 33–320 m and the buffer is only 40 m wide. The net effect, **+1.15
percentage points**, is larger than the entire nearest-node → edge-aware
correction. Uchtepa's nearest cell is a case in point: it is 819.70 m from the
metro by network and therefore *not* metro-accessible, but it lies inside the
display polygon.

Every population figure in this project comes from the network distance. The
polygon is drawn on the map and counts nobody.

## Districts that depend on buses

No arbitrary threshold such as "bus-dependent if metro access < 20%" is invented
here. Week 4 produces the continuous metrics — metro access %, bus-only % and
underserved % per district — and a district with 0% modelled metro access is
reported as 0%, **together with the distance that produced it**. The district
table now carries `min_cell_metro_distance_m` and `min_cell_metro_margin_m`, and
the manifest carries a full traced `district_focus` entry per district, so a
zero share is a checkable statement rather than an assertion. The validator
requires every 0.00% district to have its nearest cell genuinely beyond the
budget, and every positive district to have one inside it.

## Limitations

1. Physical walking access only — no frequency, span, transfers, in-vehicle time,
   reliability, crowding, fare or destination usefulness.
2. The cell-to-network and transit-to-network links are **straight-line
   off-network connectors** to the nearest mapped walkable edge. They may not
   represent a physically walkable connection in every case, so their effect on
   individual cells is uncertain, in an unknown direction. This is the largest
   remaining modelling approximation: cell connectors have a median of 16.5 m but
   a 99th percentile of 324.3 m and a maximum of 899.9 m. 1,423 cells (12,021
   people, 0.37% of the city) have a connector over 200 m.
3. Routing runs on the **simplified** OSM walk graph. Positions along an edge are
   exact, but the edge's own shape is OSM's generalisation of the real path.
4. WorldPop R2025A is an **alpha** product supplying within-district weights of
   unverified accuracy.
5. Bus stops are OSM-only; no official open-data bus layer was reachable in
   Week 3, so bus coverage is unvalidated against an operator list.
6. Stations without a mapped entrance fall back to the station point, which
   slightly flatters deep stations.
7. Yangi Toshkent is outside the population denominator.
8. Population is modelled at ~100 m cell centres, so sub-cell detail is lost.
9. 13,091 people sit on pedestrian-network components that hold no metro access
   point at all, so their metro distance is +inf rather than a large number.
10. The service-area polygons are display artifacts and play no part in any
    reported population figure.
