# Accessibility methodology (Week 4)

How the Week 3 datasets become the metro/bus access numbers. Results produced by
this method are **preliminary and pending independent audit**; the computed
figures live in [week4_analysis_summary.md](week4_analysis_summary.md).

Everything here is produced by `scripts/analyze_accessibility.py` and checked by
`scripts/validate_analysis.py`. Run parameters and diagnostics are recorded in
[`data/analysis_manifest.json`](../data/analysis_manifest.json).

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

## Pedestrian network

The real walk network from Week 3 (`data/external/tashkent_walk_network.graphml`,
111,386 nodes / 308,272 edges), not straight-line buffers. No result in this
analysis comes from an 800 m circle.

The graph is stored in EPSG:4326 and **projected to EPSG:32642** for every metric
operation: snapping, offsets, service-area geometry. No distance is computed from
raw lon/lat.

Edge weights use OSMnx's `length` attribute, which is already metres along the
way geometry. We verified this independently rather than assuming it: across
307,458 edges the ratio of `length` to the straight-line distance between the
projected endpoints has median 1.0005 and 95th percentile 1.267, and **no edge is
shorter than its own straight line** — impossible if the units were anything else.

Edges are treated as **undirected**: a pedestrian may walk either way along any
way in a walk network.

> One implementation detail worth recording, because it silently changed the
> answer. Building the sparse adjacency with `scipy.sparse.coo_matrix` **sums**
> duplicate `(row, col)` entries. The OSMnx graph stores both directions of a
> way, so symmetrising it produced duplicate pairs whose weights were summed —
> doubling every edge and cutting modelled metro access from 13.05% to 3.93%.
> The code now collapses repeated pairs to their minimum weight. This is exactly
> the kind of error that produces a plausible-looking but wrong number.

## Metro access points

Entering the metro means walking to an **entrance**, so the 144 mapped
`railway=subway_entrance` points are the access points.

A station centre is used **only as a fallback**, for a station with no mapped
entrance associated with it. Using every station centre *as well* would let a
resident "reach" a deep underground station at its surface centroid, flattering
stations whose real entrances are further away.

Association rule: a station counts as having a mapped entrance if one lies within
**400 m** of it, measured in EPSG:32642. Stations beyond that contribute their
own point, and every fallback is recorded in
`data/processed/metro_access_points.csv` with the station, the reason, the
distance to the nearest mapped entrance, and the geometry. `access_type` is
`entrance` or `station_fallback`. The fallback count is computed, not
hard-coded — Week 3's observation of roughly ten such stations is a cross-check,
not an input.

## Snapping and the off-network connector

Metro access points, bus stops and population-cell centres are all snapped to the
nearest projected graph node with a k-d tree, and the straight-line offset is
recorded. Offsets are reported (`data/processed/transit_snap_diagnostics.csv`
and the manifest), never used to quietly discard points.

Total modelled walking distance from a population cell to a transit point is:

```
cell centre -> nearest graph node        (straight-line offset)
+ network shortest path between nodes    (real pedestrian network)
+ transit point -> its graph node        (straight-line offset)
```

**Both end connectors are straight-line approximations.** A cell centre and a
transit point do not sit exactly on the network, and the true walk to the network
may be longer than the straight line — so these figures are, if anything, mildly
optimistic. This is the single largest modelling approximation here.

## Source-specific initial cost

A transit point is not free to enter. Access points are grouped by snapped node,
the smallest offset per node is kept, and a temporary super-source is attached to
those nodes with **edge weight equal to that offset**. One Dijkstra from the
super-source then gives, for every graph node:

```
min over access points of (offset to network + network distance)
```

A zero-cost super-source would have thrown the offsets away. This runs once for
metro and once for bus; every walking-speed scenario is derived from the same two
distance vectors rather than repeating the search.

Nodes on a component with no access point come back as **+inf**, never 0 and
never missing, and the population sitting on them is reported.

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

There is **no city-wide factor**. Each district gets its own, so calibrated
district totals reproduce the official SIAT totals and sum to 3,212,200.

WorldPop therefore contributes only *within-district* spatial weights. Week 3
found those weights to be effectively 2020-vintage and of unverified accuracy;
section "Sensitivity" below tests how much that matters.

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

Bus access uses all cleaned Week 3 bus stops with the same offset + network +
offset treatment.

## Sensitivity

**Walking speed** — 4.0, 4.8 and 5.6 km/h, all at 10 minutes
(`walking_speed_sensitivity.csv`). The research question stays 10 minutes; these
are scenarios, not alternative questions. Metro access and combined access must
not fall as speed rises, and underserved must not rise; the validator enforces
this. Bus-only is *not* required to be monotonic, because both the metro and the
bus boundary move at once and cells can cross from bus-only into metro.

**Population surface** — the whole classification is recomputed using the
WorldPop **2020** surface instead of 2026
(`population_surface_sensitivity.csv`). Both surfaces are calibrated to the
**same SIAT 2026-Q2 district totals**, so the comparison isolates differences in
*within-district spatial weights*, not changes in district population. This is a
sensitivity test; 2020 is not treated as ground truth.

## Service-area polygons are for display only

`metro_isochrone_10min.geojson` and `bus_isochrone_10min.geojson` exist so the
Week 5+ D3 map has a geographic layer. **The population statistics do not depend
on them at all** — classification is done on network distances directly.

Construction: take the reachable network edges within the 800 m budget; include
an edge whole when both endpoints are inside, and cut it at the budget by linear
interpolation along the straight segment between its nodes when only one endpoint
is inside (the graph is simplified, so partial traversal is approximated). Buffer
the result by 40 m in EPSG:32642, dissolve, simplify at 10 m, and write as WGS84.

Buffering is done in chunks and then dissolved, which is equivalent to one union
of per-segment buffers but does not exhaust memory on the bus network.

This is deliberately **not** a convex hull and not a circle: both would bridge
rivers, rail corridors and other barriers the pedestrian network does not cross.

## Districts that depend on buses

No arbitrary threshold such as "bus-dependent if metro access < 20%" is invented
here. Week 4 produces the continuous metrics — metro access %, bus-only % and
underserved % per district — and a district with 0% modelled metro access is
reported as 0%. Interpretation belongs to the write-up, on the evidence of the
actual distribution.

## Limitations

1. Physical walking access only — no frequency, span, transfers, in-vehicle time,
   reliability, crowding, fare or destination usefulness.
2. The cell-to-network and transit-to-network connectors are straight lines; real
   walks may be longer, so access is if anything slightly overstated.
3. WorldPop R2025A is an **alpha** product supplying within-district weights of
   unverified accuracy.
4. Bus stops are OSM-only; no official open-data bus layer was reachable in
   Week 3, so bus coverage is unvalidated against an operator list.
5. Stations without a mapped entrance fall back to the station point, which
   slightly flatters deep stations.
6. Yangi Toshkent is outside the population denominator.
7. Population is modelled at ~100 m cell centres, so sub-cell detail is lost.
8. The service-area polygons are display artifacts and carry the partial-edge
   approximation described above.
