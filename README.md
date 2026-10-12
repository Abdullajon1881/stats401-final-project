# Tashkent Transit & Walkability — completed project

An interactive, reproducible study of current walking access to Tashkent’s metro, mapped bus stops and everyday destinations. It explains what the network model estimates without presenting access as observed travel or service quality.

**Live production sites:** [main project site](https://stats401-final-project.saidkamolbahodirov.workers.dev/) and [transit & walkability site](https://tashkent-transit-walkability.saidkamolbahodirov.workers.dev/).

The historical assignment proposal remains unchanged at [docs/proposal.md](docs/proposal.md).

## Research question

> What share of the analysed Tashkent population is within a modelled ten-minute walk of metro access, and how do metro, bus-only and underserved access vary by district and everyday destination?

The completed study answers five linked questions: the citywide metro share; district variation in metro access; where access is bus-only rather than metro access; how density and access sit together; and how mapped bazaar access overlaps with the three current transit classes.

## Findings and scope

The current, entrance-aware model covers **12 Tashkent districts** and an analysed population of **3,212,200**. Yangi Toshkent is excluded because it has no matching official SIAT population row; including it would invent a denominator.

At the 10-minute / 800 m / 4.8 km/h walking assumption, the model estimates **13.56%** of the analysed population has metro access, **72.04%** is bus-only, and **14.40%** reaches neither mapped transit class. “Bus-only” means within the mapped bus-stop threshold while outside the metro threshold; it says nothing about bus frequency, reliability, routes, fares or actual use.

The current destination chapter uses the same pedestrian-network framework for mapped healthcare, education and marketplace sources. It preserves the committed healthcare-and-education intersection rather than adding two shares.

### Bazaar–transit overlap

Among residents with modelled access to a mapped bazaar, 91,271.537286 are in the metro-and-bazaar class, 370,579.615668 are bus-only-and-bazaar, and 1,830.726976 are underserved-and-bazaar. These mutually exclusive intersections partition 463,681.879929 bazaar-accessible residents. The site distinguishes this conditional composition from the source CSV percentages, which use the entire city or named district population as denominator.

Mapped bazaars are OpenStreetMap `amenity=marketplace` sources, not a market census. The overlap describes simultaneous modelled proximity, not journeys, transfers, frequency, affordability, opening hours, service quality or actual market use. It is a current-period result and is not comparable to the standardized temporal frame.

## Website and interactions

Five coordinated district visualization idioms make up the current story:

- MapLibre access map with display-only context layers;
- ranked metro-access comparison;
- 100% metro / bus-only / underserved population composition;
- density-versus-access scatterplot; and
- parallel-coordinate comparison of selected districts.

The site also has a current everyday-destinations chapter, a methodological bridge to the separate standardized series, a 2015–2026 temporal chapter with station-state events and descriptive counterfactual diagnostics, and a linked District Explorer. A district selection coordinates the main views and explorer; station selection is separate and mutually exclusive. Destination switching is local to its chapter, while the static bazaar-overlap tables add no second selection store.

## Methods and data

The current headline uses pedestrian-network shortest-path distance from each population-cell centre, connected by a straight line to its nearest mapped walkable edge, to a metro access point. Mapped entrances are used when available; ten stations use station-point fallbacks, creating positional uncertainty.

| Input | Role |
|---|---|
| OpenStreetMap | Pedestrian network, metro access points, stations, bus stops, marketplaces, destinations and boundaries |
| SIAT | Official 2026-Q2 district population totals |
| WorldPop R2025A | Within-district population weights, calibrated to official totals |
| OpenFreeMap / OpenMapTiles | Basemap style and tiles |

The **standardized 2015–2026 temporal series** is methodologically separate: it holds current pedestrian geography and station-centre proxies fixed, uses annual WorldPop model weights, and changes station opening state. It supports comparison between its own years, not with the entrance-aware current headline.

Analytical files in `site/data/` are typed copies of audited outputs. Isochrones, density grids, lines and point layers are visualization-only context; no published population share is calculated from their drawn geometry.

## Limits and uncertainty

- Modelled physical walking proximity is not observed behaviour.
- OpenStreetMap completeness affects networks, entrances, stops and POIs.
- The cell-centre connector is straight-line and may cross an unmapped barrier; it is not asserted to be walkable.
- The tested 4.0–5.6 km/h walking-speed range changes the metro share materially. This does not validate every other assumption.
- Display isochrones are cartographic context, not population estimates.
- Mapped facilities and marketplaces are not measures of capacity or quality.

## Repository guide

| Path | Contents |
|---|---|
| `site/` | Static production site, vendored D3/MapLibre assets and generated browser data |
| `scripts/` | Reproducible builders, validators and analysis tooling |
| `data/processed/` | Audited committed analytical outputs |
| `data/phase2f_bazaar_transit_overlap_manifest.json` | Phase F1 provenance and hashes for bazaar–transit overlap |
| `docs/` | Methodology, sources, integration notes, archival proposal and presentation guide |

## Run and validate

The committed website is already built. Serve it over HTTP (not `file://`):

```powershell
python -m http.server 8000 -d site
```

Then browse to `http://localhost:8000`. Regenerate only browser data from audited committed artifacts with:

```powershell
python scripts/build_web_data.py
python scripts/validate_prototype.py
```

Release checks:

```powershell
python scripts/validate_data.py
python scripts/validate_analysis.py
python scripts/validate_week6.py
python scripts/validate_final.py
python scripts/validate_phase2f_bazaar_transit_overlap.py --committed
python scripts/validate_phase2f_bazaar_transit_overlap.py --full
python scripts/test_transit_bazaar_overlap.py
```

Phase F1 `--committed` validates its committed-artifact contract and provenance. `--full` additionally exercises the reproducible analysis path, requiring gitignored routing and source-data caches. A fresh clone can serve the committed site and validate committed artifacts, but cannot recreate every geospatial input without acquiring the documented external sources.

## Dependencies and licensing

The static site has no package-manager build step. It vendors D3 7.9.0 (ISC) and MapLibre GL JS 5.24.0 (BSD-3-Clause), with license files under `site/vendor/`. OpenStreetMap data are used under ODbL and map attribution is retained. No API key, token or secret is embedded.

For detailed methods and reproduction, read [final integration](docs/final_integration.md), [Phase F1 overlap methods](docs/phase2f_bazaar_transit_overlap.md), and the [presentation guide](docs/final_presentation_rehearsal.md).
