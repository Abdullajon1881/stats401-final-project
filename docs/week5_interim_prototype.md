# Week 5 — interim interactive prototype

A working, demonstrable prototype of the final visualisation: an interactive
geographic access map and a linked ranked district dot plot, sharing one
selection.

This milestone adds **no analysis**. Every number it shows is copied from the
audited Week 4 result. Method for those numbers:
[analysis_methodology.md](analysis_methodology.md); figures:
[week4_analysis_summary.md](week4_analysis_summary.md).

## Purpose

Week 5 in the submitted timeline is an interim prototype, not the finished
interface. It exists to prove three things:

1. the audited analysis can drive a real interactive interface;
2. the two central visual idioms — a geographic access map and a ranked district
   dot plot — work and are genuinely linked;
3. the code is arranged so Week 6 can add the remaining three views without
   rebuilding anything.

Three of the five planned views are deliberately **not** built yet: the 100%
stacked access-composition bars, the density-vs-access scatterplot, and the
parallel-coordinates comparison. The district features already carry every field
those charts need.

## How to run it

The page loads JSON with `fetch`, which browsers block on `file://`. Serve it
over HTTP:

```bash
python -m http.server 8000 -d site
```

Then open <http://localhost:8000>. D3 v7.9.0 is vendored at
`site/vendor/d3.v7.min.js`, so the prototype needs no network access.

## Data flow

```
data/processed/*            (audited Week 4 outputs, unchanged)
data/analysis_manifest.json
data/external/population_cells.parquet
            │
            ▼
scripts/build_web_data.py   deterministic, no timestamps
            │
            ▼
site/data/*.json|geojson    compact web artifacts
            │
            ▼
site/app.js                 D3 reads them at runtime
```

`scripts/build_web_data.py` never writes outside `site/`, and
`scripts/validate_prototype.py` re-hashes every source it consumed to prove the
audited analysis was not touched.

### Consumed

| Audited input | Used for |
|---|---|
| `data/processed/city_access_summary.json` | the three headline estimates |
| `data/processed/district_access_metrics.csv` | every district figure |
| `data/processed/tashkent_districts.geojson` | district geometry (12 SIAT districts) |
| `data/processed/metro_isochrone_10min.geojson` | the access-shading display layer |
| `data/processed/metro_access_points.csv` | 154 metro access points |
| `data/processed/metro_stations.geojson` | 50 station centres |
| `data/processed/bus_stops.geojson` | 2,163 bus stops |
| `data/processed/bazaars.geojson` | 83 marketplaces |
| `data/analysis_manifest.json` | reference period and provenance |
| `data/external/population_cells.parquet` | the display population grid |

### Generated

| File | Role | Features | Size |
|---|---|---:|---:|
| `city_summary.json` | analytical | — | 1.6 KB |
| `districts.geojson` | analytical | 12 | 120 KB |
| `metro_isochrone_10min.geojson` | display only | 1 | 148 KB |
| `metro_access_points.geojson` | display only | 154 | 42 KB |
| `metro_stations.geojson` | display only | 50 | 9.7 KB |
| `bus_stops.geojson` | display only | 2,163 | 281 KB |
| `bazaars.geojson` | display only | 83 | 16 KB |
| `population_density.geojson` | display only | 1,855 | 463 KB |
| `manifest.json` | provenance | — | 4.2 KB |

Roughly 1.1 MB in total, plus 280 KB of vendored D3.

Coordinates are written at five decimal places (~1.1 m). Polygons go through
GEOS precision reduction rather than naive rounding, because rounding alone
collapsed a small ring in the service area below three distinct points and made
it invalid.

## Analytical and display data are kept apart

This separation is the point of the whole project, so the prototype enforces it
in three places.

* **Analytical** — `city_summary.json` and `districts.geojson` carry values
  copied at full precision from the audited files. The validator compares every
  one of them back against `data/processed/`.
* **Display only** — the service-area polygon, the population grid and every
  point layer are labelled `display_only` in `manifest.json` and in their own
  feature properties. None of them produces a number the interface reports.
* The page itself carries the caveat: *"Access shading is a display layer.
  Population estimates use pedestrian-network distance, not polygon
  intersection."* Week 4 measured that difference: counting by polygon would
  give 14.71% rather than 13.56%.

## The display population grid

The proposal asks for population density on the map. Drawing 65,169 individual
cells would be both slow and unreadable, so the audited per-cell table is
aggregated for display:

* projected to EPSG:32642;
* summed into **500 m** square bins;
* clipped to the union of the 12 SIAT districts;
* density computed as population ÷ **clipped** area, so an edge bin is not
  diluted by the part of it outside the study area;
* zero-population bins dropped;
* reprojected to EPSG:4326, ordered by (row, column) for a stable file.

That yields **1,855 bins** holding all 3,212,200 people. It is context, not
evidence: no access percentage depends on it.

## Map

D3 `geoMercator`, fitted to the 12 districts, drawn as SVG. Layers bottom to top:

| Layer | Default | Notes |
|---|---|---|
| Population density | on | sequential teal, low opacity, `people/km²` legend |
| Metro 10-minute access area | on | the audited display isochrone |
| Bus stops | off | 2,163 points; off by default because they dominate |
| Bazaars | off | 83 marketplaces |
| District outlines | always | the interactive layer |
| Metro stations | off | 50 station centres, opt-in |
| Metro access points | on | 154 points |

Bus stops and bazaars sit below the district outlines so the interactive layer is
never blocked; metro points sit above it because they carry their own tooltips.

**Metro entrances and station fallbacks are drawn differently** — a filled circle
for the 144 mapped entrances, a larger hollow ring for the 10 station fallbacks —
so the distinction survives without relying on colour. Their tooltips say which
is which, and a fallback's says why: *"No mapped entrance within 400 m."*

## Ranked dot plot

The second idiom: all 12 districts ranked by modelled metro access, highest at
the top. A leader rule runs from the axis to the dot, with the value beside it.
A dot plot rather than a bar chart, as the proposal specifies.

**The order is derived from the data at runtime**, never hard-coded. Label
gutters are measured from the rendered text rather than estimated, because a
fixed estimate clipped "Shaykhantakhur" at phone width.

## Linked interaction

One shared state object; both views read from it.

```js
state = { selectedDistrict, hoveredDistrict, layers }
```

| Action | Effect |
|---|---|
| Hover a district on the map | emphasises it on the map, emphasises its dot-plot row, shows a tooltip |
| Hover a dot-plot row | same, in reverse |
| Click either | pins the district: it stays highlighted in both views and fills the detail panel |
| Click the pinned district again | clears the pin |
| Click empty map space | clears the pin |
| "Clear selection" button, or Escape | clears the pin |

A pinned district also dims bus stops outside it, so the pin reads on that layer
too. The detail panel shows population, the three access shares with populations,
density, and counts of metro stations, access points, bus stops and bazaars.

### The zero-access note

A district can only report 0% metro access because no analysed cell fell inside
the budget. When the nearest one missed by a very small margin, that is a
knife-edge result rather than a robust finding, and the panel says so:

> No analysed population cell falls within the 800 m metro budget. The nearest is
> 819.7 m — only about 20 m outside the threshold, so this result is sensitive to
> mapping and walking assumptions.

Both the rule and the wording are derived from the district's own audited
numbers, so no district is named in the code. Today only Uchtepa triggers it.

## Visual encoding

Editorial, not dashboard. Warm paper ground, hairline rules, a serif for
headings, tabular figures wherever numbers are compared.

| Meaning | Colour |
|---|---|
| Metro | indigo `#2b4a8b` |
| Bus-only | amber `#b4762a` |
| Underserved | warm grey `#8a8681` |
| Population density | single-hue teal ramp, sequential, low opacity |

Text uses darker variants of the same hues so the amber and grey keep enough
contrast on paper. Selection never relies on colour alone: a pinned district also
gets a thicker stroke, a white halo, a bolder dot-plot label and a larger dot.

Headline copy is careful. "An estimated 13.6% of the analysed population lives
within a modelled 10-minute walk of a metro access point" — with the speed, the
time and the distance budget stated immediately beside it, and a note that these
are model estimates rather than observed walking behaviour.

## Responsive behaviour

Verified in a browser at 1440, 1024, 768 and 390 px: no horizontal overflow, no
clipped labels, no value labels outside the plot.

* ≥ 1080 px — map and detail panel side by side, panel 310 px, sticky.
* 900–1080 px — same, narrower panel.
* < 900 px — single column, panel below the map, not sticky.
* < 660 px — headline figures stack, layer chips wrap.

A debounced `ResizeObserver` re-renders both charts only when their width
actually changes.

## Accessibility

* Semantic headings, a skip link, and landmark elements.
* Layer toggles are real `<button>`s with `aria-pressed`, not clickable divs.
* District shapes and dot-plot rows are keyboard focusable with `role="button"`
  and descriptive `aria-label`s; Enter or Space pins, Escape clears.
* Visible focus outlines throughout.
* A polite live region announces each selection change.
* Tooltips are never the only route to a figure — the detail panel carries the
  same numbers, and every mark's `aria-label` states its values.
* Both SVGs carry `role="img"` and a describing label.

## Known limitations

1. **Interim scope.** Three of the five planned views are not built yet.
2. **SVG at this scale.** With every layer on, the map holds roughly 4,300 SVG
   nodes. It is smooth here, but a canvas layer for bus stops is the obvious
   move if Week 6 adds more marks.
3. **The bus layer is 281 KB.** Fine locally, worth converting to TopoJSON or
   quantised coordinates before any public deployment.
4. **No basemap.** Districts, the network layers and the population grid supply
   the geographic context; there are no streets or labels underneath.
5. **The display grid is not the analysis.** 500 m bins are far coarser than the
   ~100 m cells the classification used.
6. **Everything Week 4 could not measure still applies** — frequency, span,
   transfers, in-vehicle time, reliability, crowding, fare — plus the uncertain
   off-network connectors and the unverified within-district WorldPop weights.
7. **Not deployed.** No GitHub Pages, no publishing; the prototype runs locally.

## Verification

```bash
python scripts/build_web_data.py     # deterministic; run twice, byte-identical
python scripts/validate_prototype.py # 135 checks, 0 warnings, 0 critical
node --check site/app.js             # syntax
```

`scripts/validate_prototype.py` checks that the web figures equal the audited
ones, that there are exactly 12 analytical districts and no Yangi Toshkent, that
each district's three shares partition 100%, that every numeric field is a JSON
number rather than a string, that the display layers carry the right counts and
are labelled display-only, that the manifest counts match the files, and that
neither `app.js` nor `index.html` hard-codes a city or district metric instead of
reading it from JSON.
