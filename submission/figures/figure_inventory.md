# Figure inventory

The chart figures (02–07) are **unaltered screenshots of the real build** (merged `main` =
`aa2b494dcf07b2a6de840a8c7c7975e17b416dfd`), captured locally over HTTP with Chromium at a
1440 px viewport and 2× device scale. Figure 1 is the **project owner's authentic production
screenshot** of the deployed MapLibre map (1920×1037), saved to PNG without recolouring, redrawing,
stretching, or any change to map features or values. No numerical labels or cartography were added or
edited. Every value shown is read from the committed analytical data in `site/data/`.

## Core visualizations

| File | Visualization (idiom) | Research question | What it shows |
|---|---|---|---|
| `01-current-metro-access-map.png` | Geographic **metro-access** map (MapLibre) | **Q1** | The modelled ten-minute metro-access areas (teal shading), metro lines, station and entrance markers, and the population-density grid over the city, with the glance panel (13.6% / 72.0% / 14.4% over 3,212,200 residents) and the per-district metro-access ranking. Authentic production screenshot supplied by the project owner from the deployed site (not captured in the build sandbox). |
| `02-district-ranking.png` | Ranked district comparison | Q2 | Districts ranked by modelled metro-access share; Mirabad highest (24.89%), Uchtepa lowest (0.00%). |
| `03-population-composition.png` | 100% metro / bus-only / underserved composition | Q3 | Per-district split across the three mutually exclusive transit classes, sorted by bus-only share (Uchtepa 95.2% highest). |
| `04-density-vs-access.png` | Density-vs-access scatterplot | Q4 | Population density against metro access with median guides; no clean upward trend. |
| `05-parallel-coordinates.png` | Parallel coordinates | Q2 + Q4 | Six-axis district profiles (population, density, metro %, bus %, MAPPED bus stops/km², MAPPED bazaars/100k). |
| `06-bazaar-transit-overlap.png` | Bazaar–transit overlap composition + native tables | Q5 | Conditional composition of bazaar-accessible residents (metro+bazaar 19.68%, bus-only+bazaar 79.92%, underserved+bazaar 0.39%) plus city and 12-district tables. |
| `07-temporal-access.png` | Standardized temporal line chart | Extension (temporal) | Standardized metro access 2015 (6.87%) → 2026 (10.03%), with station-change markers; a methodologically separate frame, not comparable to the current headline. |

## Supplementary figure

| File | What it is | Honest scope |
|---|---|---|
| `01-geographic-routing-map.png` | **Destination facilities routing-source map** (D3), drawn from the same build. Shows the 12 district outlines and the mapped healthcare routing-source points. | **Supplementary only.** It illustrates the analysis district geography and that routing follows the pedestrian network (hollow points lie outside the analysis districts). **It depicts facility source locations — it does NOT depict metro-access coverage** and is not the Q1 metro-access map. |

## Provenance of Figure 1

`01-current-metro-access-map.png` is the **project owner's production screenshot** of the deployed
MapLibre metro-access map (OpenFreeMap basemap, OpenStreetMap data — attribution visible in the figure).
It was supplied because the live map could not be screenshotted inside the build environment, where the
remote basemap host (`tiles.openfreemap.org`) is blocked by the egress proxy. The image was saved to PNG
as supplied (1920×1037), with no colour, geometry, marker, value, or feature alteration. No synthetic or
AI-generated map is used anywhere in this package.
