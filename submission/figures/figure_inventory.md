# Figure inventory

The chart figures (02–07) are **unaltered screenshots of the real build** (merged `main` =
`aa2b494dcf07b2a6de840a8c7c7975e17b416dfd`), captured locally over HTTP with Chromium at a
1440 px viewport and 2× device scale. No numerical labels, cartography, or values were added,
removed, or edited. Every value shown is read from the committed analytical data in `site/data/`.

## Core visualizations

| File | Visualization (idiom) | Research question | What it shows |
|---|---|---|---|
| `01-current-metro-access-map.png` *(PENDING — see below)* | Geographic **metro-access** map (MapLibre) | **Q1** | The modelled ten-minute metro service area, district outlines, 154 metro access points and the population-density grid — *where* the 13.6% lives. **This file is not yet present; it must be the project owner's production screenshot (see "Main map" below).** |
| `02-district-ranking.png` | Ranked district comparison | Q2 | Districts ranked by modelled metro-access share; Mirabad highest (24.89%), Uchtepa lowest (0.00%). |
| `03-population-composition.png` | 100% metro / bus-only / underserved composition | Q3 | Per-district split across the three mutually exclusive transit classes, sorted by bus-only share (Uchtepa 95.2% highest). |
| `04-density-vs-access.png` | Density-vs-access scatterplot | Q4 | Population density against metro access with median guides; no clean upward trend. |
| `05-parallel-coordinates.png` | Parallel coordinates | Q2 + Q4 | Six-axis district profiles (population, density, metro %, bus %, MAPPED bus stops/km², MAPPED bazaars/100k). |
| `06-bazaar-transit-overlap.png` | Bazaar–transit overlap composition + native tables | Q5 | Conditional composition of bazaar-accessible residents (metro+bazaar 19.68%, bus-only+bazaar 79.92%, underserved+bazaar 0.39%) plus city and 12-district tables. |
| `07-temporal-access.png` | Standardized temporal line chart | Extension (temporal) | Standardized metro access 2015 (6.87%) → 2026 (10.03%), with station-change markers; a methodologically separate frame, not comparable to the current headline. |

## Supplementary figure

| File | What it is | Honest scope |
|---|---|---|
| `01-geographic-routing-map.png` | **Destinations routing-source map** (D3), drawn from the same build. Shows the 12 district outlines and the mapped healthcare routing-source points. | **Supplementary only.** It illustrates the analysis district geography and that routing follows the pedestrian network (hollow points lie outside the analysis districts). **It depicts facility source locations — it does NOT depict metro-access coverage** and must not be presented as the Q1 metro-access map. |

## Main map (Q1) — status: PENDING owner-supplied production screenshot

The project's **primary geographic idiom for Q1 is the interactive MapLibre metro-access map** (teal
service-area shading, station/entrance points, population-density grid). It renders correctly on the
**production sites** (owner-confirmed).

In this sandboxed build environment the MapLibre map **cannot be screenshotted**, because the remote
basemap host (`tiles.openfreemap.org`) is blocked by the environment's egress proxy (HTTP 403) and the
map's data overlays only draw after the basemap style loads. Therefore the authentic main-map screenshot
must be the **project owner's production screenshot**, saved here as
`01-current-metro-access-map.png`, captioned as *supplied by the project owner from the deployed site*
(not captured in this sandbox). **That image was not available when this revision was prepared**, so the
file is a placeholder entry; it must be added before the package is submission-ready. No synthetic or
AI-generated map is used in its place.
