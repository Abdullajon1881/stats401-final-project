# Week 5 — interim interactive prototype

A spatial-analysis workspace for the audited Week 4 result: a real pan/zoom map
of Tashkent with the 10-minute metro access area, the metro network, population
and transit layers, beside a linked D3 ranking of the twelve districts.

This milestone adds **no analysis**. Every figure it shows is copied from the
audited Week 4 outputs. Method for those numbers:
[analysis_methodology.md](analysis_methodology.md); figures:
[week4_analysis_summary.md](week4_analysis_summary.md).

## Purpose

Week 5 in the submitted timeline is an interim prototype. It exists to prove:

1. the audited analysis can drive a genuine interactive spatial tool;
2. the two central idioms — a geographic access map and a ranked district dot
   plot — work and are truly linked through one selection;
3. the shell is arranged so Week 6 can add the remaining three views without a
   second redesign.

Three of the five planned views are deliberately **not** built: the 100% stacked
access-composition bars, the density-vs-access scatterplot and the
parallel-coordinates comparison. The district features already carry every field
those charts need, and the sidebar is structured to take them.

## How to run it

```bash
python -m http.server 8000 -d site
```

Then <http://localhost:8000>. The page reads JSON with `fetch` and loads ES
modules, both of which browsers block on `file://`, so the server is required.
Basemap tiles come from OpenFreeMap over the network; everything else is local.

## Why MapLibre for the map and D3 for the charts

The first prototype drew the map as a static D3 SVG projection. That cannot pan
or zoom through scales, has no basemap, and put 2,163 bus stops into the DOM as
individual nodes. Those are not D3's problems to solve.

The two libraries now do what each is good at:

| | |
|---|---|
| **MapLibre GL JS 5.24.0** | vector basemap, camera, WebGL rendering, clustering, zoom-driven layer rules, geographic hit-testing, feature-state |
| **D3 7.9.0** | the ranked dot plot, its scales and axis, and every analytical chart Week 6 adds |

D3 remains the analytical visualisation layer, which is what the course project
is about. It simply stopped doing the job a map engine does better.

**MapLibre 5.24.0 was pinned deliberately.** At the time of writing npm's
`latest` was 6.9.0, released that same day, and the v6 line was seven weeks old
with eleven releases — still stabilising. Everything used here (feature-state,
clustering, `fitBounds`/`flyTo`, expressions) has been present since v2. Both
libraries are vendored under `site/vendor/` with their upstream licence notices:
D3 is ISC, MapLibre is BSD-3-Clause.

## Basemap

**OpenFreeMap**, `dark` style — verified live before use, not assumed: the style
is MapLibre style spec v8 with 47 layers over an OpenMapTiles vector source, and
tiles were confirmed to carry real data over Tashkent at z9, z11, z12 and z14.

OpenFreeMap requires no API key, no registration and no cookies, and states no
limit on views or requests. **Attribution is required and is not suppressed**:
the source TileJSON carries it and MapLibre renders it via an
`AttributionControl` that the validator checks is present. The map shows
*OpenFreeMap © OpenMapTiles Data from OpenStreetMap* at the bottom right.

The style's background, water, park and building colours are nudged onto this
application's ground so the overlays sit on a surface rather than on an
unrelated black.

## Layout

At 1200 px and wider the whole experience fits one viewport:

```
┌───────────────────────────── 64px header ─────────────────────────────┐
│ Tashkent Transit & Walkability   question        Overview Districts Method │
├──────────────────────────────────────┬────────────────────────────────┤
│  MAP                        ~63%     │  SIDEBAR              ~37%     │
│  search · layers · zoom · reset      │  Tashkent at a glance          │
│  legend · scale · attribution        │    3 stats + composition strip │
│                                      │  ─────────────────────────────  │
│                                      │  Metro access by district (D3) │
└──────────────────────────────────────┴────────────────────────────────┘
```

The sidebar is 400 px, narrowing to 320 px by 1180 px. The context panel shows
**either** the city overview **or** the selected district — one slot, so
selecting a district never leaves an empty box, and the ranking stays visible
underneath at all times. Ranking rows size themselves to fill the panel, so
there is no dead band under the chart at any height.

Below 940 px the map goes full width at 62 vh with the analysis stacked beneath
it; below 620 px the header wraps, the legend compacts, and the map takes 56 vh.
Verified with no horizontal overflow at **1920, 1440, 1366, 1024, 768 and 390**.

## Map layers

Bottom to top:

| # | Layer | Default | Notes |
|---|---|---|---|
| 1 | Population density | **on** | 500 m bins, neutral dark ramp, fades out by z15.4 |
| 2 | District fill | always | invisible until hovered or selected |
| 3 | 10-minute metro access | **on** | audited isochrone; fill recedes with zoom, outline firms up |
| 4 | Metro lines | **on** | OSM route geometry, real line colours |
| 5 | District boundaries | always | plus a heavier stroke for hover and selection |
| 6 | Outside-area mask | always | dims everything beyond the 12 districts |
| 7 | Bus stops | off | clustered; individual points only when zoomed in |
| 8 | Bazaars | off | from z11 |
| 9 | Metro access points | **on** | entrances filled, station fallbacks hollow, from z11.5 |
| 10 | Stations + labels | **on** | labels from z12.4 |
| 11 | Searched-station ring | — | while a station is selected |

The mask sits **above** the whole basemap rather than under its first symbol
layer, because OpenFreeMap draws roads and place labels after that anchor — a
mask placed there left the surrounding road network at full brightness.

### Zoom-dependent detail

Tuned by looking at the map at each scale, not guessed:

* **z9–11 city** — population, access area, metro lines, districts, stations. No
  access outline (at that size it is only noise), no access points, no bus stops.
* **z11.5–13.5 district** — access points appear, the access outline firms up,
  station labels from z12.4, bazaars from z11, bus clusters if enabled.
* **z14+ street** — population fades out entirely (500 m squares are honest at
  city scale and merely blocky over individual buildings), the access fill
  recedes to a hint while its outline carries the boundary, individual bus stops
  replace clusters, and the basemap's own street detail takes over.

### Population

The audited 500 m display bins are kept — no smoothing, no invented sub-grid
precision — but rendered with a **deliberately dark, neutral ramp**. An earlier
pass used a light ramp and the city became one grey mass that buried both the
access area and the district boundaries. Population is the backdrop; it is never
the loudest layer, and it carries a `people/km²` legend.

### Metro lines

New display data, acquired once by `scripts/acquire_metro_lines.py` from
OpenStreetMap `route=subway` relations and frozen into `data/display/` with full
provenance — the exact Overpass query, the relations returned and their tags.
The web build reads that snapshot, so it stays offline and deterministic.

Four lines, each with a colour every one of its route relations agrees on:
Chilonzor (red), Oʻzbekiston (blue), Yunusobod (green), Circle (`#9933FF`). The
named colours are tuned for a dark ground; **a line whose relations disagreed
would carry no colour and be drawn in a neutral network grey rather than a
guessed one**. No geometry is synthesised.

The snapshot records `mapped_track_length_km`, not route length: OSM maps part of
each line as one shared way and part as separate per-direction tracks, so the
merged geometry is roughly twice the route length on the split sections. It is
recorded for provenance and never shown as a line length.

**This layer is drawn, never measured.** The audited access result is computed
from metro entrances and station points and is unaffected by it.

## Interaction

One state object; both views read from it and neither owns it.

```js
state = { selectedDistrict, hoveredDistrict, selectedStation, searchQuery, view, layers, mapReady }
```

| Action | Effect |
|---|---|
| Hover a district on the map | ranking row highlights, tooltip |
| Hover a ranking row | map district highlights via feature-state, tooltip |
| Click either | pins the district in both views and fills the detail panel |
| Click the pinned district again | releases it |
| Click empty map | releases it |
| Escape, or **Clear** | releases it |
| Search a district | selects it and fits the map to it |
| Search a station | flies to it at z14.4 and rings it |
| **Overview** | clears the selection and refits the city |
| **Districts** | scrolls to and focuses the ranking |
| **Method** | opens the method dialog |
| +, −, ⤢ | zoom in, zoom out, refit Tashkent |

Camera: fitted to the twelve districts on load (≈ z10.5), `minZoom` 8.5,
`maxZoom` 17.5, and `maxBounds` 0.55° around the districts so the city cannot be
lost. Rotation is disabled — it adds nothing to a north-up analytical map.

### The zero-access note

A district can only report 0% because no analysed cell fell inside the budget.
When the nearest missed by a small margin that is a knife-edge result, and the
panel says so, using the district's own audited numbers. No district is named in
the code; today only Uchtepa triggers it, at 819.7 m against an 800 m budget.

## Security

Every label the interface shows can come from OpenStreetMap, which is
world-editable. The previous implementation built tooltip and detail markup as
HTML strings and assigned them with `innerHTML` — anything a mapper typed into a
name tag would have executed.

All DOM construction now goes through `site/js/dom.js`, which only ever assigns
through `textContent`; map popups use `setDOMContent`, not `setHTML`. The
validator fails on any `innerHTML`/`outerHTML` assignment, `insertAdjacentHTML`,
`document.write`, `d3.html()` or `setHTML(` in the application source.

Verified, not asserted: rendering `<img src=x onerror="window.__xss_test=1">`
through the same path used for every OSM label produces the literal text, no
`<img>` element, and no execution.

## Accessibility

The previous version put `role="img"` on SVG roots that contained
`role="button"` descendants, which hides the very controls it exposes. The chart
root is now `role="list"`, rows are `listitem`, and each row carries a focusable
`role="button"` with a descriptive label. `role="application"` is not used.

The map canvas is wrapped in a titled section; every control is a real
`<button>` or `<input>`; the search results are a keyboard-navigable listbox with
arrow-key and Enter support; a polite live region announces each selection; and
every district figure is available in the sidebar and the ranking, so nothing is
reachable only by hovering the canvas.

## Data

`scripts/build_web_data.py` builds `site/data/` from the audited outputs. It
never writes outside `site/`, and the validator re-hashes every source it
consumed to prove the analysis was untouched.

| File | Role | Features |
|---|---|---:|
| `city_summary.json` | analytical | — |
| `districts.geojson` | analytical | 12 |
| `metro_isochrone_10min.geojson` | display only | 1 |
| `metro_lines.geojson` | display only | 4 |
| `metro_access_points.geojson` | display only | 154 |
| `metro_stations.geojson` | display only | 50 |
| `bus_stops.geojson` | display only | 2,163 |
| `bazaars.geojson` | display only | 83 |
| `population_density.geojson` | display only | 1,855 |
| `analysis_mask.geojson` | display only | 1 |
| `manifest.json` | provenance | — |

No timestamp is written anywhere, ordering and rounding are fixed, and sources
are identified by content hash, so consecutive builds are byte-identical.

## Known limitations

1. **Interim scope** — three of the five planned views are not built.
2. **Basemap needs the network.** Tiles come from OpenFreeMap; the application
   code and all analytical data are local, but the map background is not.
3. **The 500 m display grid is far coarser** than the ~100 m cells the
   classification used, and is switched off entirely at street zoom.
4. **Metro line geometry is a frozen OSM snapshot**, refreshed only by running
   the acquisition script deliberately.
5. Everything Week 4 could not measure still applies — frequency, span,
   transfers, in-vehicle time, reliability, crowding, fare — plus the uncertain
   off-network connectors and the unverified within-district WorldPop weights.
6. **Not deployed.** No GitHub Pages, no repository settings changed.

## Verification

```bash
python scripts/build_web_data.py       # deterministic; run twice, byte-identical
python scripts/validate_prototype.py   # 193 checks, 0 warnings, 0 critical
```

Beyond the analytical equality checks, the validator asserts the architecture:
MapLibre and D3 are both present and used for their stated jobs, the map
container and every control exist and are wired, attribution is added rather
than suppressed, the map and the ranking share one selection state, search is
built from the loaded data with no external geocoder, both vendored licences are
present, no city or district metric appears as a literal in the source, there is
no markup-from-string path, and the chart carries list semantics rather than a
contradictory `role="img"`.

Browser testing was performed with headless Chrome driven over the DevTools
protocol, waiting for a genuinely rendered map rather than a timer, at six
viewports and four map zooms, exercising selection in both directions, search,
all six layer toggles, zoom, reset, keyboard interaction and the hostile-string
regression.
