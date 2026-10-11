# Phase 2F: Current bazaar--transit overlap

## Purpose and scope

The original project question asks how access to bazaars overlaps with metro and
bus access. Earlier current-period outputs reported the three mutually
exclusive transit classes and bazaar walking access separately. Phase 2F adds
their population-weighted intersections without replacing any existing
accessibility or destination result.

This is a current-period, simultaneous-proximity result. It does **not** show
that a resident travels by transit to a bazaar, can make a convenient transfer,
or receives useful, frequent, reliable or affordable service.

## Inputs and common method

The analysis uses the same 12 SIAT-matched districts and the same calibrated
2026-Q2 population denominator of 3,212,200 residents as the current
accessibility headline. `Yangi Toshkent Tumani` remains excluded because it
has no matching SIAT population row.

The population cache supplies each cell's calibrated population, current
entrance-aware metro distance, current bus-stop distance, and edge-aware
network position. The marketplace sources are the existing committed OSM
`amenity=marketplace` layer. The edge-aware pedestrian network is routed in
EPSG:32642 at 4.8 km/h for ten minutes, an exact 800 m network-distance
budget. Source and population-cell off-network connectors use the established
straight-line-to-nearest-walkable-edge method.

The deterministic provenance records, including full hashes and hash bases,
are in `data/phase2f_bazaar_transit_overlap_manifest.json`.

## Definitions

For each population cell, using unrounded distances in metres:

```python
metro = metro_distance_m <= 800.0
bus_only = (metro_distance_m > 800.0) & (bus_distance_m <= 800.0)
underserved = (metro_distance_m > 800.0) & (bus_distance_m > 800.0)

bazaar = bazaar_distance_m <= 800.0

metro_and_bazaar = metro & bazaar
bus_only_and_bazaar = bus_only & bazaar
underserved_and_bazaar = underserved & bazaar
```

`metro`, `bus_only`, and `underserved` partition every current population cell
exactly once. “Bus-only” does not mean a metro-accessible resident cannot also
walk to a bus stop. It means that the resident is outside the 800 m metro
threshold and inside the 800 m bus-stop threshold, keeping the reported
classes mutually exclusive.

Every reported intersection is a sum of calibrated cell population. Percentages
use the entire current analysed city population or the named district's entire
current analysed population, never the bazaar-accessible subset.

## Results

The produced city artifact, `data/processed/transit_bazaar_overlap_city.csv`,
reports 463,681.879929 residents (14.435025214%) within 800 m network walking
distance of a mapped marketplace. Its complete mutually exclusive overlap is:

| Current class and mapped bazaar | Population | Share of analysed city population |
|---|---:|---:|
| Metro and bazaar | 91,271.537286 | 2.841402692% |
| Bus-only and bazaar | 370,579.615668 | 11.536629589% |
| Underserved and bazaar | 1,830.726976 | 0.056992932% |

These three populations sum to the existing bazaar-accessible total. The
district artifact, `data/processed/transit_bazaar_overlap_district.csv`, holds
one deterministic district-name-sorted record per district:

| District | Metro and bazaar | Bus-only and bazaar | Underserved and bazaar |
|---|---:|---:|---:|
| Almazar | 11,362.695569 (2.697056%) | 82,000.627836 (19.463714%) | 183.520718 (0.043561%) |
| Bektemir | 534.972162 (0.726864%) | 7,222.359413 (9.812988%) | 104.845637 (0.142453%) |
| Chilanzar | 20,944.952939 (7.545012%) | 56,656.547546 (20.409419%) | 147.634508 (0.053182%) |
| Mirabad | 6,494.817734 (4.123694%) | 13,098.373812 (8.316428%) | 0.000000 (0.000000%) |
| Mirzo Ulugbek | 5,169.436355 (1.497086%) | 53,406.073742 (15.466572%) | 1,052.304762 (0.304751%) |
| Sergeli | 2,328.818908 (1.276065%) | 8,275.609912 (4.534581%) | 342.421352 (0.187628%) |
| Shaykhantakhur | 10,466.766507 (2.791138%) | 19,437.785574 (5.183409%) | 0.000000 (0.000000%) |
| Uchtepa | 0.000000 (0.000000%) | 50,180.223787 (16.286992%) | 0.000000 (0.000000%) |
| Yakkasaray | 266.970778 (0.181613%) | 20,198.396927 (13.740406%) | 0.000000 (0.000000%) |
| Yangikhayot | 6,134.057114 (2.989307%) | 8,115.919085 (3.955126%) | 0.000000 (0.000000%) |
| Yashnabad | 8,549.567147 (2.652674%) | 27,956.794059 (8.674153%) | 0.000000 (0.000000%) |
| Yunusabad | 19,018.482072 (4.792964%) | 24,030.903976 (6.056175%) | 0.000000 (0.000000%) |

## Reconciliation and validation

Before writing Phase 2F outputs, the analysis reproduces the frozen current
metro, bus-only and underserved city and district totals, then independently
reroutes the committed bazaar layer and reproduces the Phase 2C city and
district bazaar totals. The validator independently repeats the mask arithmetic
and verifies that:

- transit classes are disjoint and complete;
- overlap masks are pairwise disjoint;
- intersections sum to bazaar-accessible population;
- district sums equal city results;
- each intersection is bounded by its parent transit class and the bazaar
  population; and
- output percentages use their explicitly recorded city or district denominator.

The focused synthetic tests also reject duplicate or missing cell identities,
negative/nonfinite population, NaN distances, values just beyond 800 m,
unreachable infinite distances, invalid overlap labels, corrupted results and
district-row reordering.

## Reproduction and validation modes

The analysis requires the previously validated, gitignored inputs at their
recorded paths: `data/external/population_cells.parquet` and
`data/external/tashkent_walk_network.graphml`. No download or source
regeneration is performed.

The validator has two deliberately distinct modes:

- `--committed` runs from a clean clone without either large cache. It checks
  the tracked output schemas, deterministic district identities and order,
  arithmetic, frozen transit and Phase 2C reconciliation, manifest structure,
  tracked input/output hashes, and the recorded cache pins. Cache provenance is
  reported as recorded only: this mode does not inspect caches and does not
  reroute.
- `--full` requires both caches. In addition to the committed-artifact checks,
  it verifies the actual cache hashes, validates cache records, and
  independently reroutes the committed bazaar layer to reconstruct the overlap
  outputs. Missing caches fail this mode; it never falls back to `--committed`.

```powershell
# Fresh-clone, tracked-artifact evidence (no large caches required)
.venv\Scripts\python.exe scripts\validate_phase2f_bazaar_transit_overlap.py --committed

# Stronger cached-input and independent-routing evidence
.venv\Scripts\python.exe scripts\validate_phase2f_bazaar_transit_overlap.py --full

# Phase 2F analysis and synthetic regression tests
.venv\Scripts\python.exe scripts\analyze_transit_bazaar_overlap.py
.venv\Scripts\python.exe scripts\test_transit_bazaar_overlap.py
```

The permanent frozen-file guard compares only named pre-Phase-2F analytical
artifacts with the authorized base. It does not prohibit separately authorized
future documentation, site, or other new-phase files.

## Limitations

The OSM `amenity=marketplace` layer is a mapped lower bound, not a census of
all bazaars. Cell and source connectors are straight-line approximations and
may cross fences, parcels, waterways, rail corridors or other unmapped
barriers. The calibrated WorldPop R2025A surface provides within-district
weights, not validated ground truth. These results remain modelled physical
walking proximity, not observed travel behaviour or a causal estimate.
