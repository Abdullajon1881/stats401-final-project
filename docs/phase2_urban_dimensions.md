# Phase 2C — Current urban dimensions

Phase 2C answers the second expansion the professor asked for: more dimensions
than public transport versus population density. It adds healthcare, education,
bazaars, facility supply and walk-network density to the **current-period**
analysis.

This phase is data and analysis only. It builds no interface, changes no
frontend file and alters no Phase 2A or Phase 2B result.

## What this phase is, and is not

Healthcare, education and bazaar layers are **current OpenStreetMap snapshots**.
OpenStreetMap carries no audited opening history for these facilities, so Phase
2C deliberately computes **no** historical healthcare, education or bazaar
availability. The temporal series in Phase 2B remains metro-only for exactly
that reason.

Phase 2C also produces **no composite score and no district ranking**. The
district table reports each dimension separately so that a reader can see the
trade-offs rather than a single number that hides them.

## Population and geography

The denominator is unchanged from the current headline:

- 12 SIAT-matched Tashkent districts
- Yangi Toshkent Tumani stays excluded because it has no matching official SIAT
  district population row
- official denominator **3,212,200 people**
- WorldPop 2026 cells calibrated independently within each district to SIAT
  2026-Q2 district totals — the same surface behind the frozen
  `13.563595724255597%` current headline

This is a current-period multidimensional analysis, so the raw annual WorldPop
weights used by the Phase 2B standardized temporal series are **not** used here.

## Walking definition

Every destination class uses the same physical walking definition as the
current headline, so the four accessibility percentages are directly
comparable:

| parameter | value |
|---|---|
| walking speed | 4.8 km/h |
| walking time | 10 minutes |
| distance budget | 800 m |
| classification | unrounded network distance ≤ 800.0 m |

Routing uses the audited edge-aware engine in `scripts/accessibility_utils.py`
against the fixed current pedestrian network (111,386 nodes, 308,272 stored
edge records, 154,133 canonical undirected routing edges, EPSG:32642). No
straight-line buffer and no nearest-node routing is used anywhere.

Each destination class is routed with **one** multi-source Dijkstra over an
augmented network, for **three** runs in total. A source pays its own
off-network connector inside the augmented network, and the population cell
pays its own connector exactly once on top.

## Sources

### Healthcare

Overpass union over node, way and relation for
`amenity=hospital`, `amenity=clinic`, `healthcare=hospital`,
`healthcare=clinic`, returned with `out geom` so relations keep their member
geometry. Scope is deliberately narrow: pharmacies, dentists, doctors'
surgeries, laboratories, nursing homes and social facilities are **not**
included, so "healthcare facility" means a hospital-class or clinic-class
institution and nothing looser.

An object carrying both an `amenity` and a `healthcare` tag is one object and
is classified once, with `hospital` outranking `clinic`.

### Education

Overpass union over node, way and relation for `amenity=school`,
`amenity=college`, `amenity=university`, `amenity=kindergarten`. Training
centres, language schools, tutoring services and driving schools are **not**
included. Category precedence is `university`, `college`, `school`,
`kindergarten`.

### Bazaars

The existing audited `data/processed/bazaars.geojson` layer is reused
unchanged: `amenity=marketplace` only, 83 mapped features. Phase 2C does not
reacquire it and does not broaden the definition.

## Representative points

OpenStreetMap does not provide audited pedestrian entrances for these
facilities. Routing therefore uses a deterministic representative point:

| geometry | routing point |
|---|---|
| node | the node itself |
| polygon or multipolygon | shapely representative point, guaranteed inside the feature |
| line | the line midpoint |

A bounding-box centre is **not** used, because it can fall outside a concave
building.

> **Facility representative points are routing proxies, not verified pedestrian
> entrances.**

This is a material difference from the current metro model, which uses actual
mapped subway entrances where they exist and falls back to the station point
only where they do not.

## Deduplication

Both accessibility sources and facility counts have to be meaningful, so
obvious duplicate representations of one institution are collapsed under fixed
rules:

1. one object per OSM element type and id;
2. records sharing a category **and** a non-empty normalized name within
   **150 m** collapse to a single facility, keeping the areal representation
   over a bare node;
3. unnamed facilities are **never** proximity-merged — two adjacent unnamed
   kindergartens are not evidence of one kindergarten;
4. different categories are **never** merged.

Name normalization folds case, whitespace and the several apostrophe characters
OSM uses for Uzbek names. Raw, cleaned and removed counts are recorded per
category in the manifest and travel with each committed layer.

## Walk-network density

`walk_network_km` and `walk_network_density_km_per_km2` are computed from the
**canonical undirected routing edges**, using their projected EPSG:32642
geometry clipped to each district polygon. The 308,272 stored directional
GraphML records are never summed, because that would double the network.
Parallel mapped ways stay distinct, because they are genuinely separate
walkable paths, and self-loops are retained.

Tashkent's district boundaries follow major roads, so a substantial length of
walkable way lies exactly on a shared border and a plain clip returns it in
full to **both** neighbours. Each edge is therefore partitioned individually:
its clip against the alphabetically first district is taken first, and every
later district receives only what remains of that same edge. 53.39 km of
network lies on shared borders and is assigned once. District lengths are a
true partition, and they reconcile with the network clipped to the union of the
12 districts to 0.000000000 km.

`analysis_boundary.geojson` stores that same area with GeoJSON-rounded
coordinates, which moves the long outer perimeter by up to a centimetre and
clips about 0.70 km differently. The reconciliation target is the district
union computed from the district polygons themselves.

> This is **walk-network density**, a pedestrian-infrastructure and urban-form
> proxy. It is **not** a walkability score.

## Normalized supply

Facility supply is reported both raw and population-normalized:
`healthcare_facilities_per_10k`, `education_facilities_per_10k`,
`bazaars_per_10k` and `bus_stops_per_10k`.

Metro stations stay a **raw count** with no per-capita rate. At 50 stations
across 12 districts, a per-capita metro rate is dominated by whether a district
happens to contain one extra station, which would read as precision the sparse
network cannot support.

## Outputs

| file | contents |
|---|---|
| `data/processed/healthcare_facilities.geojson` | cleaned current healthcare facilities |
| `data/processed/education_facilities.geojson` | cleaned current education facilities |
| `data/processed/urban_dimensions_city.csv` | one city row |
| `data/processed/urban_dimensions_district.csv` | 12 district rows |
| `data/phase2c_urban_dimensions_manifest.json` | provenance, counts, diagnostics, limitations |

All generated JSON is canonical UTF-8 with LF newlines, and CSV output uses LF
line endings, following the cross-platform provenance conventions audited
earlier in Phase 2. Tracked text inputs are hashed as `canonical_utf8_lf` and
external artifacts as `raw_file_bytes`.

## Limitations

1. Healthcare, education and bazaar data are **current OpenStreetMap
   snapshots**, not historical records.
2. OpenStreetMap facility coverage is **incomplete and is not a census**.
3. Facility counts reflect mapped OSM objects after the documented
   deduplication above, not an official facility register.
4. Representative points are **not verified facility entrances**.
5. Ten-minute access is **physical pedestrian-network proximity only**.
6. Nothing here measures **quality, capacity, staffing, opening hours,
   affordability, eligibility, school catchment rules or medical
   specialization**. A cell counted as within 10 minutes of a hospital is not
   thereby entitled to care at it.
7. Bazaar coverage remains an `amenity=marketplace` **mapped lower bound**.
8. Walk-network density is a **network-density proxy, not a general walkability
   score**: it says nothing about pavement quality, shade, crossings, lighting,
   severance or perceived safety.
9. Transit supply counts do **not** measure service frequency, span or
   reliability. A district with more bus stops does not necessarily have more
   bus service.

Descriptive district comparisons in this phase are exactly that. They identify
highest and lowest values per dimension; they do not establish a "best"
district, and they do not support a causal claim about why a district sits
where it does.
