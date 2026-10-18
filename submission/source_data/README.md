# Source datasets

The raw source data is not stored in this repository because of its size: the
pedestrian network is about 113 MB and each WorldPop raster about 35 MB. Every
source is public, and it can be downloaded again from the links below. The
committed acquisition scripts fetch each one automatically.

## Download links

**WorldPop population rasters** (direct downloads, about 35 MB each, CC BY 4.0)
- 2026 (main analysis): <https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2026/UZB/v1/100m/constrained/uzb_pop_2026_CN_100m_R2025A_v1.tif>
- 2015–2026 annual series: the same link with the year changed in both places, e.g. 2015: <https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2015/UZB/v1/100m/constrained/uzb_pop_2015_CN_100m_R2025A_v1.tif>
- Dataset page: <https://hub.worldpop.org/geodata/summary?id=76048>
- DOI: <https://doi.org/10.5258/SOTON/WP00839>

**SIAT official population** (CC BY 4.0). Open each page and use its CSV download button.
- Dataset 3890, district population 2026-Q2 (main denominator): <https://siat.stat.uz/data/3890/?lang=en>
- Dataset 3891, rural population (checked to be 0 for Tashkent): <https://siat.stat.uz/data/3891/?lang=en>
- Dataset 246, annual population series: <https://siat.stat.uz/data/246/?lang=en>

**OpenStreetMap** (ODbL). Our run queried OSM live through the Overpass API rather than downloading a single file.
- Full Uzbekistan extract (about 125 MB, containing every layer we used): <https://download.geofabrik.de/asia/uzbekistan-latest.osm.pbf>
- Tashkent city boundary: <https://www.openstreetmap.org/relation/2216724>
- Our exact queries: `scripts/overpass_client.py`, run by `python scripts/acquire_data.py` against <https://overpass-api.de/api>

**Basemap** (website display only, not an analysis dataset): <https://openfreemap.org/>

## Source details

| Source | What we used it for | Link | Licence | Acquired by |
|---|---|---|---|---|
| **OpenStreetMap**: Tashkent city boundary (relation 2216724) and its 13 district relations | Analysis boundary, district polygons | <https://www.openstreetmap.org/relation/2216724> | ODbL 1.0, <https://www.openstreetmap.org/copyright> | `scripts/acquire_data.py` (OSMnx) |
| **OpenStreetMap**: pedestrian network (111,386 nodes, 308,272 edge records) | Walking-distance routing | <https://www.openstreetmap.org/> via OSMnx / Overpass API <https://overpass-api.de/api> | ODbL 1.0 | `scripts/acquire_data.py` |
| **OpenStreetMap**: metro stations and entrances, bus stops, marketplaces (`amenity=marketplace`) | Transit access points, bazaars | Overpass API <https://overpass-api.de/api> (queries written out in `scripts/overpass_client.py`) | ODbL 1.0 | `scripts/acquire_data.py` |
| **OpenStreetMap**: hospitals, clinics, schools, kindergartens, colleges, universities | Everyday-destination access | Overpass API | ODbL 1.0 | `scripts/acquire_urban_dimensions.py` |
| **OpenStreetMap**: metro route relations | Metro lines drawn on the map (display only) | Overpass API | ODbL 1.0 | `scripts/acquire_metro_lines.py` |
| **SIAT** (Statistics Agency of Uzbekistan): dataset 3890, permanent population (city), 2026-Q2; dataset 3891 (rural, checked to be 0) | Official district population totals (3,212,200) | <https://siat.stat.uz/data/3890/?lang=en> · CSV API <https://api.siat.stat.uz/sdmx/3890/table/download/?download_format=csv> | CC BY 4.0 | `scripts/acquire_data.py` |
| **SIAT**: dataset 246, annual population series | Population context for the temporal chapter | <https://siat.stat.uz/data/246/?lang=en> | CC BY 4.0 | `scripts/acquire_temporal_population.py` |
| **WorldPop** Global 2015–2030 R2025A, Uzbekistan, constrained 100 m, 2026 | Within-district population weights (calibrated to SIAT) | <https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2026/UZB/v1/100m/constrained/uzb_pop_2026_CN_100m_R2025A_v1.tif> · DOI [10.5258/SOTON/WP00839](https://doi.org/10.5258/SOTON/WP00839) | CC BY 4.0, <https://hub.worldpop.org/data/licence.txt> | `scripts/acquire_data.py` |
| **WorldPop** R2025A annual rasters, 2015–2026 (same product, one file per year) | Standardized 2015–2026 series; 2020 vs 2026 sensitivity check | Same URL pattern with the year changed, e.g. `.../R2025A/2015/UZB/v1/100m/constrained/uzb_pop_2015_CN_100m_R2025A_v1.tif` | CC BY 4.0 | `scripts/acquire_temporal_population.py`, `scripts/audit_population_surface.py` |
| **OpenFreeMap / OpenMapTiles** | Basemap tiles on the website only | <https://openfreemap.org/> | OpenMapTiles / ODbL attribution | loaded at runtime |

Release notes for WorldPop R2025A, which WorldPop describes as an alpha release:
<https://data.worldpop.org/repo/prj/Global_2015_2030/R2025A/doc/Global2_Release_Statement_R2025A_v1.pdf>

## Provenance of the run behind our results

The committed manifests record, for each source, the exact URL or Overpass
endpoint, the acquisition timestamp (the base data was acquired on 2026-09-08),
feature counts and SHA-256 checksums:

- `data/source_manifest.json`: boundaries, walk network, metro, bus stops, bazaars, SIAT, WorldPop 2026
- `data/phase2_source_manifest.json`: annual WorldPop rasters, SIAT annual series, station opening dates
- `data/phase2c_urban_dimensions_manifest.json`: healthcare and education layers
- `data/display/metro_lines_provenance.json`: metro route relations

Full source notes, including the cleaning rules and known issues with each
source: [`docs/data_sources.md`](../../docs/data_sources.md).

## Re-downloading

```bash
pip install -r requirements.txt
python scripts/acquire_data.py
python scripts/acquire_urban_dimensions.py
python scripts/acquire_metro_lines.py
python scripts/acquire_temporal_population.py
```

Raw files are written to `data/raw/` and `data/external/`, both gitignored.
WorldPop and SIAT downloads can be checked against the SHA-256 values in the
manifests. OpenStreetMap is edited continuously, so a new download is a newer
snapshot and its counts may differ slightly from the committed run.

The cleaned and processed datasets derived from these sources are committed
in [`data/processed/`](../../data/processed/).
