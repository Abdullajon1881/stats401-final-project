# Tashkent Transit & Walkability: Who Can Reach the Metro in Ten Minutes?

**STATS 401 — Final Project Report**
**Group members:** Doniyor Erkinov, Saidkamolkhon Bakhodirov
**Project repository:** https://github.com/Abdullajon1881/stats401-final-project
**Live site:** https://tashkent-transit-walkability.saidkamolbahodirov.workers.dev/

---

## 1. Introduction

Tashkent has grown quickly, and its metro has grown with it. But a metro line drawn on a map does not tell residents whether they can actually *reach* it on foot: a station two hundred metres away across a rail corridor, a canal, or a walled block can be a long walk in practice. This project asks a deliberately concrete question: **what share of Tashkent's analysed population lives within a modelled ten-minute walk of metro access, and where does the bus network fill the gap?**

We study this through five linked research questions from our proposal:

1. What share of the population is within a ten-minute walk of a metro station?
2. Which districts have the highest and lowest metro-access coverage?
3. Which districts have little or no metro access and depend mostly on buses?
4. Are some dense residential areas relatively underserved by public transport?
5. How does access to bazaars (markets) overlap with metro and bus access?

The audience is Tashkent residents and commuters, with a secondary planning audience. The subject is spatial, multi-attribute and comparative, so an **interactive visualization** rather than a static table is the right medium: readers can locate their district, compare it with others, filter to a transit category, and explore density against access at their own pace. Every figure is a **model estimate** of pedestrian-network *proximity*, not an observation of where people live or how they commute.

## 2. Method

**Data acquisition.** *OpenStreetMap* (OSM, ODbL) supplies the pedestrian network, metro stations and entrances, bus stops, marketplaces, facilities, and district boundaries. The *Statistics Agency of the Republic of Uzbekistan* (SIAT) supplies official 2026-Q2 district population totals. *WorldPop R2025A* supplies a ~100 m gridded surface used **only** to distribute each district's official total within its boundary, so every district sums back to its SIAT number. Basemap tiles come from OpenFreeMap / OpenMapTiles.

**Cleaning and correspondence.** Names were standardised, duplicates removed, and OSM district polygons matched to SIAT rows through a documented crosswalk. **Yangi Toshkent** has an OSM boundary but no SIAT population row; rather than invent a denominator it is excluded, and the exclusion is recorded as a validator warning. The analysed geography is **12 matched districts** with a calibrated population of **3,212,200**.

**The walking model.** Accessibility is pedestrian-network shortest-path distance, not a straight-line buffer. Each population-cell centre is joined by a straight connector to its nearest mapped walkable edge, then routed along the OSM network (projected, EPSG:32642) to the nearest metro access point and the nearest bus stop. The budget is **ten minutes at 4.8 km/h = 800 m of network distance**. Metro routing is *entrance-aware*: of 154 access points, 144 are mapped entrances and 10 are station-point fallbacks, which adds positional uncertainty for those stations.

**The three transit categories.** Each cell falls into one of three mutually exclusive classes that sum to 100%: **Metro access** (metro within 800 m), **Bus-only** (no metro within 800 m but a bus stop within it), and **Underserved** (neither). "Bus-only" is a *walking-access category defined by proximity*; it is not a measure of bus usage, dependence, frequency, fares, or reliability.

**Implementation.** Analysis is Python (`geopandas`, `networkx`, `shapely`, `pyproj`). The site is a static, dependency-light dashboard — vanilla ES modules, **D3 7.9.0** for charts, **MapLibre GL JS 5.24.0** for the map, served from Cloudflare Workers. Analytical values reach the browser as typed copies of audited outputs with recorded content hashes; the site computes no accessibility figure at runtime.

**The standardized temporal method (separate).** To study change over 2015–2026 we use a deliberately *different* frame: today's geography and boundaries are fixed, station-*centre* proxies replace entrances, and only station opening-state and annual WorldPop weights vary by year. Its yearly values are comparable with one another but **not** with the entrance-aware current headline, and we never subtract one from the other.

## 3. Results

The headline estimate is **13.56% of the analysed population (435,690 residents) within a modelled ten-minute walk of metro access**, **72.04% (2,314,113) bus-only**, and **14.40% (462,397) underserved**. Metro walking access is narrow and concentrated along the lines; most residents can walk to a bus stop but not the metro. Five coordinated idioms tell this story.

**Figure 1 — Geographic access map.** *Addresses Q1.* The primary geographic idiom is the interactive **MapLibre** map: the modelled ten-minute metro service area as shaded context, district outlines, the 154 metro access points, and a population-density grid, with pan, zoom and layer toggles. Its value is locating *where* the 13.56% lives — the access area is a ribbon along the lines, not a blanket, and the reported share comes from per-cell network distances, not the drawn shading. *(The production screenshot of this map is supplied by the project owner from the deployed site; see the figure inventory.)* A supplementary D3 routing-source map shows the district geography and mapped source points — illustrating that routing follows the network, not a circle; it depicts source locations, **not** metro-access coverage.

**Figure 2 — Ranked district comparison.** *Addresses Q2.* Districts ranked by modelled metro access let the reader rank and compare at a glance. The spread is wide: **Mirabad leads at 24.89%**, while **Uchtepa is 0.00%** — though its nearest analysed cell is only about **19.7 m** beyond the 800 m budget, so that zero is threshold-sensitive, not an absence of metro.

**Figure 3 — Metro / bus-only / underserved composition.** *Addresses Q3.* A 100% stacked bar per district, sorted by bus-only share, shows how each district's population splits across the three classes. **Uchtepa is 95.17% bus-only** (highest) and **Bektemir is 50.70% underserved**. A high bus-only share means the metro is not a ten-minute walk away — not that the buses are good or bad.

**Figure 4 — Density-versus-access scatterplot.** *Addresses Q4.* Population density against metro access, with median guides, lets the reader find outliers. The insight is a negative one worth stating: there is no clean upward trend, so density alone does not explain who gets metro access.

**Figure 5 — Parallel-coordinates comparison.** *Addresses Q2 and Q4.* Six axes — population, density, metro %, bus %, mapped bus stops/km², mapped bazaars/100k — let the reader pin and compare whole district profiles at once. The two MAPPED axes are labelled so, because OSM coverage varies and a thin count may mean a thinly *surveyed* district, not a thinly *served* one.

**Everyday destinations and bazaar–transit overlap (extensions).** Using the same 800 m model, an estimated **46.89%** of residents reach mapped healthcare, **72.48%** education, and **14.44%** a mapped bazaar; the committed healthcare-and-education intersection is **43.65%** (residents reaching *both*, not a sum). These are proximity estimates to *mapped points*; they do not measure service use, capacity or quality. **Figure 6** answers Q5: of the 463,682 residents within reach of a bazaar, **metro+bazaar is 91,272 (19.68% of bazaar-accessible residents)**, **bus-only+bazaar 370,580 (79.92%)**, and **underserved+bazaar 1,831 (0.39%)**. These *conditional* shares are kept distinct from the city-population percentages in the tables, and bazaar *proximity* is not a record of shopping.

**Standardized temporal series (Figure 7).** On the separate standardized frame, modelled access rises from **6.87% (2015) to 10.03% (2026)** (+3.16 points), with steps where stations opened. These diagnostics are **descriptive, not causal**: station openings and population change occur together, so the series attributes no change to any single opening, and its 10.03% is not the same quantity as the current 13.56% headline.

## 4. Discussion

Framed by **What–Why–How**: the *what* is spatial population cells carrying one quantitative access distance and one categorical transit class; the *why* is locating, ranking, comparing and correlating; the *how* is five idioms whose marks and channels fit those tasks — position on a common scale for the ranking and composition, position-plus-position for the scatter, aligned axes for the parallel view, and a geographic projection for the map. All are wired to one shared selection store, so selecting a district highlights it everywhere, with a separate bounded axis to pin up to four for comparison. That coordination is the main interaction contribution: the views behave as one instrument, not five disconnected charts.

**Strengths:** every share comes from network routing rather than drawn buffers, the three categories are exact and mutually exclusive, and the uncertainty is on the page. **Limitations:** OSM completeness bounds the network, entrances and stops; the cell-to-network connector is a straight line that may cross an unmapped barrier; ten stations use station-point fallbacks; WorldPop R2025A is an alpha product used only for within-district distribution. The headline is **sensitive to walking speed** (10.0% at 4.0 km/h to 17.3% at 5.6 km/h) but essentially **insensitive** to swapping the 2026 surface for 2020 (~0.01 points) — insensitivity to that substitution, not proof the surface is correct. The model measures **proximity, not usage**: nothing here reflects frequency, fare, transfer, reliability, or whether anyone walks or rides. Defensible improvements include validating connectors against real footpaths, mapping more entrances, and adding an official bus-stop register.

## 5. Conclusion

On this model, metro walking access in Tashkent is narrow and uneven: about one analysed resident in seven can reach the metro on foot in ten minutes, the majority have only bus-stop proximity for that first leg, and the pattern is very unequal across districts — from Mirabad's 24.89% to Uchtepa's threshold-sensitive zero. The destination and bazaar overlaps show the same geography of proximity, and the standardized history shows access growing with new lines without being confused for the current measure. The contribution is not that five charts exist, but that a reader can interrogate a defensible model, see what it does and does not claim, and reach grounded conclusions with the uncertainty visible.

## 6. Roles and Responsibilities

The proposal assigns the division of work below, reproduced as the documented basis. **These precise final contributions require confirmation by the project owners before submission; they must not be inferred from commit authorship.**

- **Doniyor Erkinov (Group Leader, per proposal):** project coordination, data acquisition and documentation, transport-data validation, data cleaning, and presentation organisation.
- **Saidkamolkhon Bakhodirov (per proposal):** geospatial analysis, visualization design, D3.js implementation, linked interactions, interface development, and testing.

Both members contributed to the research questions, interpretation, debugging, and presentation. **[ACTION REQUIRED: confirm or revise each person's final contribution before this report is submitted. Until then this report is not submission-approved.]**

---

*All numerical values are drawn from the committed, audited analytical outputs in `site/data/` and `data/processed/` at the approved release (`main` = `aa2b494`). Figures are unaltered screenshots of the real build; see `submission/figures/figure_inventory.md`. Report body length and method are reported in the submission cover note.*
