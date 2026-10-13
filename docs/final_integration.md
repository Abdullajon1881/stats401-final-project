# Final integration

The finished state of the project: what it asks, what it answers, how much that
answer depends on its assumptions, and where it stops.

## Research question

> What share of Tashkent's population lives within a 10-minute walk of the
> metro, and which districts depend mostly on buses?

## Headline result

**An estimated 13.6% of the analysed population is within a modelled 10-minute
walk of metro access.**

Every word there is load-bearing:

- **estimated / modelled** — this is the output of a pedestrian-network routing
  model, not an observation of where people live or how they travel.
- **analysed population** — 3,212,200 residents across the twelve Tashkent
  districts that have official statistics. It is not the whole city.
- **10-minute walk** — 600 s at 4.8 km/h, giving an 800 m network-distance
  budget along the OpenStreetMap pedestrian network to the nearest metro access
  point.

| Category | Share | Population |
|---|---:|---:|
| Metro | 13.563595724255597% | 435,689.82185453834 |
| Bus-only | 72.04136811206638% | 2,314,112.8264957964 |
| Underserved | 14.395036163678002% | 462,397.3516496648 |
| Metro or bus combined | 85.60496383632197% | — |

The interface rounds to one decimal. The full precision above is for
validation, not for communication.

### What "bus-only" means, and does not mean

Bus-only is the modelled share of a district's analysed population that reaches
a mapped bus stop within the same 10-minute walking budget but does **not**
reach metro access within it. The three categories are mutually exclusive and
sum to 100%.

It says nothing about bus frequency, reliability, crowding, fare, route
coverage, journey time, or whether anyone actually takes the bus. A high
bus-only share means "the metro is not within a modelled ten-minute walk of most
of this district's population", not "this district is badly served".

The site names the district with the highest modelled bus-only share, derived at
runtime by sorting the district data. It does not call that district neglected,
under-served by government, or a priority — the analysis does not support any of
those readings.

## The five visualization idioms

| # | View | Reader's task | Module |
|---|------|---------------|--------|
| 1 | Interactive access map | Where is the catchment, and who lives inside it? | `site/js/map.js` |
| 2 | Ranked dot plot | Which districts have the highest modelled metro access? | `site/js/ranking.js` |
| 3 | 100% stacked composition | Which districts depend most on buses? | `site/js/composition.js` |
| 4 | Density vs access scatter | Do denser districts have better modelled access? | `site/js/scatter.js` |
| 5 | Parallel coordinates | How does one district's whole profile compare? | `site/js/parallel.js` |

## Destination access and bazaar–transit overlap

The current-destinations chapter uses the same current-period 800 m,
ten-minute, 4.8 km/h pedestrian-network model as the headline. It reports
healthcare, education and mapped bazaar access separately, keeps the committed
healthcare-and-education intersection as an intersection, and gives its source
points a routing-proxy map rather than treating point density as access.

Phase F1 adds the audited bazaar–transit intersection. Of the population with
modelled access to an OpenStreetMap `amenity=marketplace` source, the three
mutually exclusive current classes are metro-and-bazaar (91,271.537286),
bus-only-and-bazaar (370,579.615668), and underserved-and-bazaar
(1,830.726976). They partition the 463,681.879929 bazaar-accessible residents.
The website's composition bar labels these as conditional shares of
bazaar-accessible population; its native city and 12-district tables label the
published CSV percentages as shares of the entire city or named district.

“Bus-only” remains a mutually exclusive threshold class, not a claim that a
metro-accessible resident cannot use a bus. Marketplaces are a mapped lower
bound, not a market census. The intersection measures simultaneous modelled
walking proximity, not journeys, transfers, service frequency, affordability,
opening hours, reliability or use. Its cell/source connectors are straight-line
links to a mapped walkable edge. These current results are not comparable to
the standardized temporal frame.

The standardized chapter covers 2015–2026 using station-centre proxies, fixed
current geography and annual WorldPop weights. It contains station-state events
and descriptive counterfactual diagnostics; neither is causal attribution. The
method bridge explicitly keeps this series separate from the entrance-aware,
SIAT-calibrated current frame. The linked District Explorer joins current
district profile data with standardized history without changing either method.

## Interaction model

One store (`site/js/state.js`) owns the selection; all five views read it and
none keeps a copy.

- Hovering a district in **any** view highlights it in all five.
- Clicking a district mark in **any** view sets `selectedDistrict` globally.
  Click means the same thing everywhere.
- Escape, **Clear**, or re-clicking the same district releases it. Navigating
  between sections does not.
- `comparisonDistricts` is a separate axis, bounded at four in the store. Up to
  four districts can be pinned for profile comparison. Selecting never pins;
  clearing the comparison never deselects.
- In the scatter, at most one text label is visible: hover (including keyboard
  focus) first, selection second, otherwise none.

## Sensitivity

Published in the Method dialog, read from `site/data/sensitivity.json`, which
the build copies from the audited Week 4 outputs. Nothing is recomputed by the
build or by the site.

| Walking speed | Metro | Metro + bus | Underserved |
|---|---:|---:|---:|
| 4.0 km/h | 10.0% | 79.6% | 20.4% |
| **4.8 km/h** (headline) | **13.6%** | **85.6%** | **14.4%** |
| 5.6 km/h | 17.3% | 89.3% | 10.7% |

The headline is sensitive to the walking-speed assumption: across the tested
4.0–5.6 km/h range, the modelled metro share moves by several percentage points
(a 0.8 km/h change in either direction moves it by roughly 3.6–3.7 points).
Only the walking speed and the population surface were sensitivity-tested; no
claim is made about how the headline ranks against untested assumptions such as
OSM network completeness, connector validity, entrance completeness or fallback
positioning.

Changing the within-district population surface from 2026 to 2020 moves the city
metro estimate by about **0.01 percentage points** once both surfaces are
calibrated to the same official district totals. That means the result is
insensitive to *this particular substitution*. It does **not** show that the
population surface is accurate.

## Data sources

| Source | Used for | Licence / note |
|---|---|---|
| OpenStreetMap | pedestrian network, metro stations and entrances, metro route relations, bus stops, bazaars, district boundaries | ODbL |
| Statistics Agency of the Republic of Uzbekistan (SIAT) | official district population totals, 2026-Q2 | official totals |
| WorldPop R2025A | within-district population distribution only | alpha product; within-district accuracy unverified |
| OpenFreeMap / OpenMapTiles | basemap tiles and style | attribution required and displayed |

District totals come from SIAT. WorldPop is used **only** to distribute those
totals within each district; every district sums back to its official total.

## Analysis boundary

Twelve districts, 3,212,200 residents.

**Yangi Toshkent is excluded.** The OSM boundary relation exists, but SIAT
publishes no population row for it, so there is no official total to calibrate
against. Including it would have meant inventing a denominator. Its exclusion is
recorded as a documented warning in `validate_data.py` rather than being
silently dropped.

## Limitations

- Model estimates, not observed behaviour. Physical walking access only —
  nothing here reflects frequency, fare, reliability, crowding, safety,
  accessibility for wheelchair users, or whether people choose to walk.
- The link from a population cell to the network is a straight line to the
  nearest mapped walkable edge. It may not be physically walkable; its effect on
  any individual cell is uncertain and in an unknown direction.
- Ten of the fifty stations have no mapped entrance and therefore use the
  station point as a fallback, introducing additional positional uncertainty
  for those stations.
- Bus stops come from OpenStreetMap alone, with no official operator list.
  Coverage varies by district and is not a measure of service provision — the
  parallel chart's mapped bus-stop and bazaar axes are labelled MAPPED for this
  reason.
- Uchtepa's modelled metro access is 0.0% at the headline assumption, but the
  nearest analysed population cell is only about **19.7 m** beyond the 800 m
  budget. That result is threshold-sensitive: a slightly different walking
  speed, a slightly better-mapped footpath, or a mapped entrance a few metres
  nearer would change it. It should not be read as "no metro access exists in
  Uchtepa".
- The display isochrone on the map is a cartographic layer. No reported figure
  is derived from it; every share comes from the per-cell network-distance
  classification.

## Running the site locally

```bash
python -m http.server 8000 -d site
```

Then open <http://localhost:8000>. A server is required: the page reads JSON
with `fetch` and loads ES modules, both of which browsers block on `file://`.

To rebuild the web data from the audited outputs:

```bash
python scripts/build_web_data.py
python scripts/validate_prototype.py
```

The build is deterministic — consecutive runs produce byte-identical files.

## Dependencies

Vendored, no build step, no package manager, no framework:

- MapLibre GL JS 5.24.0 — `site/vendor/maplibre-gl.js`, BSD-3-Clause,
  `site/vendor/MAPLIBRE-LICENSE.txt`
- D3 7.9.0 — `site/vendor/d3.v7.min.js`, ISC, `site/vendor/D3-LICENSE.txt`

The only runtime network dependency is the OpenFreeMap basemap. If it cannot be
loaded the page says so and the district analysis, which reads only local data,
continues to work.

No API key, no token, no secret.

## Accessibility

- Each chart is a list of twelve list items, each carrying one focusable control
  with a spoken label — twelve controls per chart, not hundreds of focusable SVG
  nodes. No interactive chart root uses `role="img"`.
- Enter and Space select; Escape clears. `aria-pressed` reports the selection.
- The search is a standards-shaped combobox: focus stays on the input,
  `aria-activedescendant` names the active option, and results are not tab
  stops.
- The Method dialog is a native `<dialog>` opened with `showModal()`, with Tab
  wrapped at both ends and focus restored to the opener.
- The sensitivity table is a real `<table>` with a caption and column/row
  scopes; the headline row is named in text, not marked by weight alone.
- Selection and comparison changes are announced through a live region.
- Every figure on the map is also in the sidebar or the charts, so nothing is
  reachable only by hovering the canvas.
- Motion respects `prefers-reduced-motion`.

## Publication status

The completed static site is published in production at:

- <https://stats401-final-project.saidkamolbahodirov.workers.dev/>
- <https://tashkent-transit-walkability.saidkamolbahodirov.workers.dev/>

Both deployments serve the same relative first-party static assets from `site/`;
the only runtime network request is the attributed OpenFreeMap basemap. The
build records hashes, source paths, row counts and byte sizes for analytical
web artifacts. Phase F1 sources are authenticated against their committed
manifest before browser JSON is emitted. `validate_prototype.py` exercises the
actual pre-render contracts and malformed-data failures; `validate_final.py`
protects completed copy, frozen analytical sources, accessibility, provenance,
sensitivity and evidence-limited claims.

The MapLibre `wood-pattern` image diagnostic has been observed as a nonblocking
third-party basemap-style warning. No safe, independently verified remediation
was established without changing basemap semantics, so it remains a known minor
console limitation rather than a change to the style or an error-suppression
rule.
