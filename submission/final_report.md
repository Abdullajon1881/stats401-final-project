# Tashkent Transit & Walkability: Who Can Reach the Metro in Ten Minutes?

**STATS 401 — Final Project Report**
**Group members:** Doniyor Erkinov, Saidkamolkhon Bakhodirov
**Project repository:** https://github.com/Abdullajon1881/stats401-final-project
**Live site:** https://tashkent-transit-walkability.saidkamolbahodirov.workers.dev/

---

## 1. Introduction

Tashkent has grown quickly, and its metro has grown with it. But a metro line drawn on a map does not tell residents whether they can actually *reach* it on foot. A station two hundred metres away across a rail corridor, a canal, or a walled block can be a long walk in practice. This project asks a deliberately concrete question: **what share of Tashkent's analysed population lives within a modelled ten-minute walk of metro access, and where does the bus network fill the gap?**

We study this through five linked research questions, taken directly from our proposal:

1. What share of the population is within a ten-minute walk of a metro station?
2. Which districts have the highest and lowest metro-access coverage?
3. Which districts have little or no metro access and depend mostly on buses?
4. Are some dense residential areas relatively underserved by public transport?
5. How does access to bazaars (markets) overlap with metro and bus access?

The intended audience is Tashkent residents and commuters, with a secondary audience interested in transport planning. The subject is spatial, multi-attribute and comparative, which is why an **interactive visualization** rather than a static table is the right medium: readers can locate their district, compare it against others, filter to a transit category, spot outliers, and explore the relationship between density and access at their own pace.

Throughout, we present every figure as a **model estimate**, not an observed fact: walking speed, network completeness, entrance mapping, and modelled population all introduce uncertainty, which we treat as part of the finding rather than hiding it.

## 2. Method

**Data acquisition.** Three sources each do one job. *OpenStreetMap* (OSM, ODbL) supplies the pedestrian network, metro stations and entrances, bus stops, marketplaces, facility locations, and district boundaries, obtained programmatically. The *Statistics Agency of the Republic of Uzbekistan* (SIAT) supplies official 2026-Q2 population totals for each district. *WorldPop R2025A* supplies a ~100 m gridded population surface used **only** to distribute each district's official total within its boundary, so every district sums back to its SIAT number. The map's basemap tiles come from OpenFreeMap / OpenMapTiles.

**Cleaning and correspondence.** Names were standardised, duplicates removed, and OSM district polygons matched to SIAT population rows through a documented crosswalk. One district, **Yangi Toshkent**, has an OSM boundary but no SIAT population row; rather than invent a denominator, it is excluded and the exclusion is recorded as a validator warning. The analysed geography is therefore **12 matched districts** with a calibrated population of **3,212,200**.

**The walking model.** Accessibility is measured as pedestrian-network shortest-path distance, not a straight-line buffer. Each population-cell centre is connected by a straight line to its nearest mapped walkable edge, then routed along the OSM pedestrian network (in projected coordinates, EPSG:32642) to the nearest metro access point and the nearest bus stop. The budget is **ten minutes at 4.8 km/h, i.e. 800 m of network distance**. Metro routing is *entrance-aware*: of 154 access points, 144 are mapped entrances and 10 are station-point fallbacks where no entrance is mapped, which adds positional uncertainty for those stations.

**The three transit categories.** Every cell is classified into one of three mutually exclusive classes that sum to 100%: **Metro access** (metro within 800 m), **Bus-only** (no metro within 800 m, but a bus stop within 800 m), and **Underserved** (neither). "Bus-only" is a walking-access category; it says nothing about bus frequency, fares, or reliability.

**Implementation.** Analysis is Python (`geopandas`, `networkx`, `shapely`, `pyproj`). The site is a static, dependency-light dashboard: vanilla ES modules, **D3 7.9.0** for charts, **MapLibre GL JS 5.24.0** for the map, served from Cloudflare Workers. All analytical values reach the browser as typed copies of audited outputs with recorded content hashes; the site computes no new accessibility figure at runtime.

**The standardized temporal method (separate).** To look at change over 2015–2026 we use a deliberately *different* frame: today's pedestrian geography and district boundaries are held fixed, station-*centre* proxies replace entrances, and only station opening-state and annual WorldPop weights vary by year. This series is internally comparable across its own years but is **not** comparable with the entrance-aware current headline, and we never subtract one from the other.

## 3. Results

The headline estimate is that **13.56% of the analysed population (435,690 residents) is within a modelled ten-minute walk of metro access**, **72.04% (2,314,113) is bus-only**, and **14.40% (462,397) is underserved**. Metro walking access in Tashkent is narrow and concentrated along the lines; the large majority can reach a bus stop but not the metro on foot. The project tells this story through five coordinated visualization idioms.

**Figure 1 — Geographic access map (routing sources).** *Addresses Q1.* The main view is a MapLibre map of the modelled service area, district outlines, metro access points and population density; Figure 1 shows the D3 routing-source map from the same build, with the 12 district outlines and mapped source points. It lets users locate a district and see that access follows the street network rather than a circle. The insight: the access ribbon hugs the lines and stops where the network stops.

**Figure 2 — Ranked district comparison.** *Addresses Q2.* A dot/bar ranking of districts by modelled metro access lets users rank and compare at a glance. The spread is wide: **Mirabad leads at 24.89%**, while **Uchtepa sits at 0.00%** — though its nearest analysed cell is only about **19.7 m** beyond the 800 m budget, so that zero is threshold-sensitive, not an absence of metro.

**Figure 3 — Metro / bus-only / underserved composition.** *Addresses Q3.* A 100% stacked bar per district, sorted by bus-only share, shows how each district's population splits across the three classes. Users read dependence directly: **Uchtepa is 95.17% bus-only**, the highest, while **Bektemir is 50.70% underserved**, reflecting its peripheral position.

**Figure 4 — Density-versus-access scatterplot.** *Addresses Q4.* Population density against metro access, with median guide lines, lets users identify outliers. The insight is a negative one worth stating plainly: there is no clean upward trend, so density alone does not explain who gets metro access.

**Figure 5 — Parallel-coordinates comparison.** *Addresses Q2 and Q4 jointly.* Six axes — population, density, metro %, bus %, mapped bus stops/km², mapped bazaars/100k — let users pin and compare whole district profiles across several attributes at once. The two MAPPED axes are labelled as such, because OSM coverage varies and a thin count may mean a thinly *surveyed* district, not a thinly *served* one.

**Everyday destinations and the bazaar–transit overlap (extensions).** Using the same 800 m model, an estimated **46.89%** of residents reach mapped healthcare, **72.48%** reach education, and **14.44%** reach a mapped bazaar; the committed healthcare-and-education intersection is **43.65%** (residents reaching *both*, not a sum of shares). **Figure 6** then answers Q5: among the 463,682 residents within reach of a bazaar, the three transit classes partition into **metro+bazaar 91,272 (19.68% of bazaar-accessible residents)**, **bus-only+bazaar 370,580 (79.92%)**, and **underserved+bazaar 1,831 (0.39%)**. The interface carefully separates these *conditional* shares of bazaar-accessible residents from the city-population percentages shown in the native tables.

**Standardized temporal series (Figure 7).** On the separate standardized frame, modelled metro access rises from **6.87% in 2015 to 10.03% in 2026** (+3.16 points), with visible steps where new stations opened. These diagnostics are descriptive: station openings and population change occur together, so the series does not attribute change causally to any single opening, and its 10.03% is not the same quantity as the current 13.56% headline.

## 4. Discussion

Framed by the **What–Why–How** model: the *what* is spatial population cells carrying one quantitative access distance and one categorical transit class; the *why* is the reader's tasks of locating, ranking, comparing and correlating; the *how* is five idioms whose marks and channels fit those tasks — position on a common scale for the ranking and composition, position-plus-position for the scatter, and multiple aligned axes for the parallel view — all wired to a single shared selection store so that hovering or selecting a district highlights it everywhere, and a separate, bounded comparison axis lets up to four districts be pinned. This coordination is the project's main interaction contribution: the five views behave as one instrument, not five disconnected charts.

The design's **strengths** are that every reported share comes from network routing rather than drawn buffers, the three categories are exact and mutually exclusive, and uncertainty is placed on the page. The **limitations** are real and documented: OSM completeness bounds the network, entrances and stops; the cell-to-network connector is a straight line that may cross an unmapped barrier; ten stations rely on station-point fallbacks; and WorldPop is an alpha product used only for within-district distribution. The headline is **sensitive to walking speed** — it moves from 10.0% at 4.0 km/h to 17.3% at 5.6 km/h — but is essentially **insensitive** to swapping the 2026 WorldPop surface for 2020 (~0.01 points), which is insensitivity to that substitution, not proof the surface is correct. The model measures **physical proximity, not usage**: nothing here reflects frequency, fare, transfer, reliability, or whether anyone actually walks or rides. Defensible future improvements would include validating a sample of connectors against real footpaths, mapping more station entrances, and incorporating an official bus-stop register if one becomes available.

## 5. Conclusion

On this model, metro walking access in Tashkent is narrow and uneven: about one analysed resident in seven can reach the metro on foot in ten minutes, the large majority depend on buses for that first leg, and the burden is distributed very unequally across districts — from Mirabad's 24.89% to Uchtepa's threshold-sensitive zero. The everyday-destination and bazaar overlaps show the same pattern extends to where people shop and seek services, and the standardized history shows access growing with new lines without letting that trend be mistaken for the current entrance-aware measure. The contribution is not that five charts exist, but that a reader can interrogate a defensible accessibility model, see exactly what it does and does not claim, and reach their own grounded conclusions — with the uncertainty visible rather than buried.

## 6. Roles and Responsibilities

The proposal assigns the following division of work, which we reproduce here as the documented basis. **The precise final contributions below require confirmation by the project owners before submission; they must not be inferred from commit authorship.**

- **Doniyor Erkinov (Group Leader, per proposal):** project coordination, data acquisition and documentation, transport-data validation, data cleaning, and presentation organisation.
- **Saidkamolkhon Bakhodirov (per proposal):** geospatial analysis, visualization design, D3.js implementation, linked interactions, interface development, and testing.

Both members contributed to the research questions, interpretation, debugging, and presentation. **[ACTION REQUIRED: confirm or revise each person's final contribution before this report is submitted.]**

*Report body length: ≈ 1,755 words (target ≈ 1,500; the extra length carries the rubric-required per-visualization explanations and the What–Why–How discussion).*

---

*All numerical values in this report are drawn from the committed, audited analytical outputs in `site/data/` and `data/processed/` at the approved release (`main` = `aa2b494`). Figures are unaltered screenshots of the real production build; see `submission/figures/figure_inventory.md`.*
