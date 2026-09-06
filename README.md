# Tashkent Transit & Walkability: Who Can Reach the Metro in Ten Minutes?

**Group members:** Doniyor Erkinov (de82), Saidkamolkhon Bakhodirov (sb932)

## 1. Topic, Goals, and Questions

Tashkent has expanded quickly, and the metro has expanded with it. But a metro line on a city map does not automatically mean that most residents can actually reach it on foot. Our project asks: **What share of Tashkent lives within a 10-minute walk of the metro, and which districts depend entirely on buses without having access to subway?**

We want to turn that question into an interactive view of transit access across the city. The main audience is Tashkent residents and commuters, with a secondary audience of people interested in transport planning or comparing districts. Our goals are to estimate metro walking access, show where bus service fills the gap.

Main questions:

1. What share of Tashkent’s population lives within 10-minute walk of a metro station? (less than 1km)
2. Which districts have the highest and lowest metro-access coverage?
3. Which districts have little or no metro coverage and depend mostly on buses?
4. Are some dense residential areas relatively underserved with public transport?
5. How does access to bazaars (markets) overlap with metro and bus access?

We will present the 10-minute result as an estimate, not an exact fact. Walking speed, street-network completeness, station entrances, and modeled population distribution all introduce uncertainty in calculation.

## 2. Datasets

We plan to combine four sources.

**OpenStreetMap (OSM):** pedestrian streets, metro stations and entrances, district boundaries, and some bus/POI locations. We will obtain the data programmatically with OSMnx and use the walking network to calculate network-based catchments instead of drawing simple circles around stations.

**WorldPop:** approximately 100 m gridded population estimates for Uzbekistan. We will clip the raster to Tashkent to estimate where people live within each district.

**Uzbekistan National Statistics Committee / SIAT:** official population totals for Tashkent and its districts. We will use these totals to calibrate the WorldPop distribution so our district estimates stay consistent with official statistics.

**Transport/open data:** current bus stops and routes will come from Uzbekistan’s transport/open-data sources where usable machine-readable records are available, supplemented by OSM and collected from Yandex Maps. 

Processing will be done in Python. We will standardize names, remove duplicates, project the data into a metric coordinate system, calculate walking time on the street network, merge overlapping catchments, and intersect them with population cells. We expect tens of thousands of street-network edges, hundreds to thousands of transit points, all across 12 Tashkent districts. Final D3-ready outputs will be compact CSV and GeoJSON files.

Data links:

- https://siat.stat.uz/data/3890/?lang=en
- https://hub.worldpop.org/project/categories?id=3
- https://www.openstreetmap.org/
- https://data.egov.uz/

## 3. Analysis and Visualization Methods

We will use Python with `pandas`, `geopandas`, `osmnx`, `networkx`, `shapely`, and raster-processing tools. The final interface will use HTML/CSS and D3.js.

Our main walking-speed assumption will be about 5 km/h. Residents inside overlapping station catchments will be counted once. For the “bus-only” category, we plan to count residents outside the 10-minute metro catchment but inside a 10-minute walking catchment of at least one bus stop. This measures physical access, not bus frequency or reliability, which we will state clearly.

The project will contain five connected visualization idioms:

1. **Interactive access map** — metro walking isochrones, population density, bus stops, bazaars, and district boundaries.
2. **Ranked district dot plot** — percentage of residents within a 10-minute metro walk.
3. **100% stacked bar chart** — metro-accessible, bus-only, and underserved population by district.
4. **Scatterplot** — population density versus metro coverage to identify dense but poorly served districts.
5. **Parallel-coordinates view** — compare selected districts across metro coverage, bus availability, density, and bazaar access.

Users should be able to locate, compare, filter, identify outliers, and explore relationships.

## 4. Initial Visualization Sketches

**Access map**
```text
+------------- Tashkent -------------+
|  [10-min metro areas]              |
|  ○ station   • bus   ▒ population  |
|  click district → update views     |
+------------------------------------+
```
*Interactive map: shows where metro walking access overlaps with residential population.*

**District ranking**
```text
Yunusabad    -----------●
Mirabad      --------●
...
Yangikhayot  --●
```
*Dot plot: makes access differences between districts easy to compare.*

**Access composition**
```text
District A |████ metro ███ bus ░ underserved|
District B |██ metro █████ bus ░░░░          |
```
*100% stacked bars: shows how each district’s population is split across access categories.*

**Density vs. coverage**
```text
coverage ↑      •
         |  •       •
         |      ×
         +------------→ density
```
*Scatterplot: reveals dense districts with unexpectedly weak metro access.*

**District comparison**
```text
Population  Metro  Bus  Bazaar  Density
      \       /\    \      /      /
       \_____/  \____\____/______/
```
*Parallel coordinates: compares several districts across multiple access measures.*

## 5. Group Roles and Responsibilities

**Doniyor Erkinov (Group Leader)** will coordinate the project, manage data acquisition and documentation, help validate transport data, lead cleaning, and organize presentations.

**Saidkamolkhon Bakhodirov** will lead the geospatial analysis, visualization design, D3.js implementation, linked interactions, interface development, and testing.

Both members will contribute to the research questions, interpretation, debugging, and presentation.

## 6. Interim Presentation Deliverables

By the interim presentation, we expect to have a cleaned pedestrian network, verified metro locations, district boundaries, initial population calibration, and a first set of 10-minute walking catchments. We also plan to show district summaries, a fixed definition of “bus-only” access, and have at least one working D3 prototype.

## 7. Timeline and Milestones

| Week | Milestone | Tasks | Responsible | Expected output |
|---|---|---|---|---|
| 2 | Project definition | Finalize questions, sources, assumptions | Both | Proposal + source plan |
| 3 | Data preparation | Acquire and clean OSM, WorldPop, SIAT, transit data | Doniyor + Saidkamolkhon | Clean datasets |
| 4 | Geospatial analysis | Walking network, isochrones, population calibration, district metrics | Saidkamolkhon + Doniyor review | Analysis tables + GeoJSON |
| 5 | Interim prototype | Exploratory analysis, map, first linked chart | Both | Interim demo |
| 6 | Full visualization | Remaining views, filters, tooltips, linked highlighting, sensitivity tests | Both | Five connected views |
| 7 | Final integration | Validate results, refine design, test, document limitations, rehearse | Both | Final site + presentation |
