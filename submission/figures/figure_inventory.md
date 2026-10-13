# Figure inventory

All figures are **unaltered screenshots of the real production build** (merged `main` =
`aa2b494dcf07b2a6de840a8c7c7975e17b416dfd`), captured locally over HTTP with Chromium at a
1440 px viewport and 2× device scale. No numerical labels, cartography, or values were added,
removed, or edited. Every value shown is read from the committed analytical data in `site/data/`.

| File | Visualization (idiom) | Research question | What it shows |
|---|---|---|---|
| `01-geographic-routing-map.png` | Geographic map — routing sources (D3, programmatic) | Q1 | 12 district outlines and mapped routing-source points; access follows the pedestrian network, not a circle. Hollow points are sources kept outside the analysis districts. |
| `02-district-ranking.png` | Ranked district comparison | Q2 | Districts ranked by modelled metro-access share; Mirabad highest (24.89%), Uchtepa lowest (0.00%). |
| `03-population-composition.png` | 100% metro / bus-only / underserved composition | Q3 | Per-district split across the three mutually exclusive transit classes, sorted by bus-only share (Uchtepa 95.2% highest). |
| `04-density-vs-access.png` | Density-vs-access scatterplot | Q4 | Population density against metro access with median guides; no clean upward trend. |
| `05-parallel-coordinates.png` | Parallel coordinates | Q2 + Q4 | Six-axis district profiles (population, density, metro %, bus %, MAPPED bus stops/km², MAPPED bazaars/100k). |
| `06-bazaar-transit-overlap.png` | Bazaar–transit overlap composition + native tables | Q5 | Conditional composition of bazaar-accessible residents (metro+bazaar 19.68%, bus-only+bazaar 79.92%, underserved+bazaar 0.39%) plus city and 12-district tables. |
| `07-temporal-access.png` | Standardized temporal line chart | Extension (temporal) | Standardized metro access 2015 (6.87%) → 2026 (10.03%), with station-change markers; a methodologically separate frame, not comparable to the current headline. |

## Note on the main MapLibre access map

The project's primary geographic idiom (research question Q1) is an interactive **MapLibre GL** map with
teal service-area shading, station/entrance points and a population-density grid. It renders correctly on the
**production sites** (the project owner has confirmed this with browser screenshots). It **could not be
screenshotted in this sandboxed build environment** because the remote basemap host
(`tiles.openfreemap.org`) is blocked by the environment's egress proxy (HTTP 403), and the map's data
overlays are only drawn after the basemap style loads. The site handles this gracefully with a visible
"basemap unavailable" notice, and the district analysis below the map is unaffected.

`01-geographic-routing-map.png` is therefore provided as an **authentic, basemap-independent** geographic
figure (the destinations routing-source map, drawn with D3 from the same committed data). For the final
submission, the main MapLibre access-map screenshot should be taken from the **production site** or supplied
from the **project owner's existing production screenshots**. This substitution is an environment constraint,
not a defect in the visualization.
