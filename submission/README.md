# Final submission — Tashkent Transit & Walkability

**Group:** Doniyor Erkinov (de82) · Saidkamolkhon Bakhodirov (sb932) — STATS 401

This folder is the entry point for grading. It maps every required deliverable
to where it lives in the repository and explains how to reproduce each one.

| | |
|---|---|
| Live website | <https://tashkent-transit-walkability.saidkamolbahodirov.workers.dev/> (mirror: <https://stats401-final-project.saidkamolbahodirov.workers.dev/>) |
| Repository | <https://github.com/Abdullajon1881/stats401-final-project> |
| Final report | [`report/Tashkent_Transit_Walkability_Final_Report.pdf`](report/Tashkent_Transit_Walkability_Final_Report.pdf) (+ [`.docx`](report/Tashkent_Transit_Walkability_Final_Report.docx), source [`final_report.md`](report/final_report.md)) |
| Poster (A0 portrait) | [`poster/Tashkent_Transit_Walkability_Poster_A0.pdf`](poster/Tashkent_Transit_Walkability_Poster_A0.pdf) (preview [`poster_preview.png`](poster/poster_preview.png), source [`poster.html`](poster/poster.html)) |

## Deliverables checklist

| # | Required deliverable | Where it is |
|---|---|---|
| 1 | **Source dataset(s)** | [`source_data/README.md`](source_data/README.md) gives the download link, licence and acquisition script for every raw source (OpenStreetMap, SIAT, WorldPop). The raw files are too large for the repository. Provenance for every source is committed in `data/source_manifest.json`, `data/phase2_source_manifest.json`, `data/phase2c_urban_dimensions_manifest.json`, `data/display/metro_lines_provenance.json`. |
| 2 | **Cleaned / processed dataset(s)** | [`data/processed/`](../data/processed/) — audited analytical outputs (district metrics, city summary, cleaned OSM layers, calibrated population tables, temporal series, destination and bazaar-overlap tables). Browser-ready copies with hashes: [`site/data/`](../site/data/). Field definitions: [`docs/data_dictionary.md`](../docs/data_dictionary.md). |
| 3 | **Data collection / crawler code** | [`scripts/acquire_data.py`](../scripts/acquire_data.py) (OSMnx walk network, Overpass point layers, SIAT CSV API, WorldPop), [`scripts/overpass_client.py`](../scripts/overpass_client.py) (hand-written Overpass QL, 3-mirror failover), [`scripts/acquire_urban_dimensions.py`](../scripts/acquire_urban_dimensions.py), [`scripts/acquire_metro_lines.py`](../scripts/acquire_metro_lines.py), [`scripts/acquire_temporal_population.py`](../scripts/acquire_temporal_population.py), [`scripts/build_metro_history.py`](../scripts/build_metro_history.py) |
| 4 | **Data cleaning and analysis code** | Cleaning: `scripts/osm_features.py`, `scripts/config.py` (district crosswalk, tag rules), `scripts/audit_population_surface.py`. Analysis: `scripts/analyze_accessibility.py` + `scripts/accessibility_utils.py` (edge-aware routing), `scripts/analyze_temporal_accessibility.py` + `scripts/temporal_accessibility.py`, `scripts/analyze_urban_dimensions.py` + `scripts/urban_dimensions.py`, `scripts/analyze_transit_bazaar_overlap.py`. Validation: `scripts/validate_*.py`, `scripts/test_*.py`. |
| 5 | **Complete visualization source code** | [`site/`](../site/) — `index.html`, `styles.css`, `js/*.js` (D3 v7 charts, MapLibre map, shared state store), vendored libraries in `site/vendor/`; web-data builder `scripts/build_web_data.py`. |
| 6 | **Published website** | <https://tashkent-transit-walkability.saidkamolbahodirov.workers.dev/> — verified identical to `site/` in this commit (only line endings differ). |
| 7 | **Final report (~1,500 words)** | [`report/`](report/) — about 1,670 words of prose in five sections (Introduction, Method, Results, Discussion, Conclusion), plus tables, nine screenshot figures and references; 8 pages. |
| 8 | **Final project poster** | [`poster/`](poster/) — A0 portrait (841 × 1189 mm), print-ready PDF. |
| 9 | **Reproduction documentation** | This file, the root [`README.md`](../README.md), [`docs/final_integration.md`](../docs/final_integration.md), [`docs/data_sources.md`](../docs/data_sources.md), [`docs/analysis_methodology.md`](../docs/analysis_methodology.md), the phase method notes in [`docs/`](../docs/), and [`source_data/README.md`](source_data/README.md). |

Screenshots used in the report and poster are in [`screenshots/`](screenshots/);
the tools that regenerate the report, poster and screenshots are in [`tools/`](tools/).

## Reproducing the project

All commands run from the repository root unless noted. Windows PowerShell and
POSIX shells both work.

### 1. View the website locally (no Python packages needed)

```bash
python -m http.server 8000 -d site
# open http://localhost:8000
```

A server is required because the page loads JSON and ES modules. The only
network request is the OpenFreeMap basemap; the analysis works without it.

### 2. Validate the committed results (no raw data needed)

```bash
python -m venv .venv && .venv/Scripts/activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python scripts/validate_data.py --repo
python scripts/validate_analysis.py
python scripts/validate_week6.py
python scripts/validate_final.py
python scripts/validate_phase2f_bazaar_transit_overlap.py --committed
python scripts/test_accessibility_utils.py
python scripts/test_temporal_accessibility.py
python scripts/test_urban_dimensions.py
python scripts/test_transit_bazaar_overlap.py
python scripts/test_phase2_manifest.py
```

All of these pass on this commit (verified for the submission). The warnings
they print only note that gitignored raw caches are absent. One exception:
`python scripts/validate_prototype.py` also checks that the gitignored cell cache
`data/external/population_cells.parquet` still exists, so it reports one
failure on a fresh clone (923 other checks pass). It passes once step 3 has
rebuilt the caches.

> `requirements.txt` was missing `scipy` and `pyarrow`, which the routing code
> and parquet caches import. Both are now pinned, at versions verified with
> the suites above.

### 3. Rebuild everything from raw sources

Each step writes the committed outputs it owns and records hashes in a manifest.
OpenStreetMap changes continuously, so a fresh acquisition gives a *newer*
snapshot. Counts can differ slightly from the committed run, and the manifests
record which snapshot each output came from.

| Step | Command | Produces |
|---|---|---|
| Acquire base data | `python scripts/acquire_data.py` then `python scripts/validate_data.py` | boundaries, walk graph, metro/bus/bazaar layers, SIAT totals, WorldPop 2026 |
| Population audit | `python scripts/audit_population_surface.py` | WorldPop vs SIAT diagnostics |
| Current access (headline) | `python scripts/analyze_accessibility.py` then `python scripts/validate_analysis.py` | district/city metro, bus-only, underserved |
| Display metro lines | `python scripts/acquire_metro_lines.py` | `data/display/` (drawn only, never measured) |
| Station history | `python scripts/build_metro_history.py` | `metro_station_history.csv`, opening timeline |
| Annual population | `python scripts/acquire_temporal_population.py` then `python scripts/validate_phase2_temporal.py` | 2015–2026 WorldPop district tables |
| Standardized series | `python scripts/analyze_temporal_accessibility.py` then `python scripts/validate_phase2_accessibility.py` | temporal city/district/event/counterfactual tables |
| Destinations | `python scripts/acquire_urban_dimensions.py`, `python scripts/analyze_urban_dimensions.py`, `python scripts/validate_phase2_urban_dimensions.py` | healthcare/education/bazaar access |
| Bazaar × transit | `python scripts/analyze_transit_bazaar_overlap.py` then `python scripts/validate_phase2f_bazaar_transit_overlap.py --full` | overlap tables |
| Web data | `python scripts/build_web_data.py` then `python scripts/validate_prototype.py` and `python scripts/validate_final.py` | `site/data/` |

### 4. Rebuild the report, poster and screenshots

Requires Python with `python-docx` and `Pillow`, Node.js 18+, Google Chrome and
(for the PDF export) Microsoft Word on Windows.

```bash
cd submission/tools && npm install                 # installs puppeteer-core only
node capture_screenshots.js                        # -> submission/screenshots/*.png (from the live site)
node render_poster.js                              # -> submission/poster/*.pdf + preview; fails on overflow
cd ../..
python submission/tools/build_report.py            # final_report.md -> .docx
powershell -ExecutionPolicy Bypass -File submission/tools/export_pdf.ps1 -Docx submission/report/Tashkent_Transit_Walkability_Final_Report.docx
```

Set `SITE_URL=http://localhost:8000/` to capture from a local server instead,
and `CHROME_PATH` if Chrome is installed somewhere else.

## Where the report and poster numbers come from

| Figure in report / poster | Committed source |
|---|---|
| 13.6% metro, 72.0% bus-only, 14.4% underserved; 3,212,200 residents | `data/processed/city_access_summary.json` |
| District shares, densities, station / stop / bazaar counts | `data/processed/district_access_metrics.csv` |
| Uchtepa 19.7 m threshold margin | `docs/final_integration.md`, `min_cell_metro_margin_m` in the district table |
| Healthcare 46.9%, education 72.5%, bazaar 14.4%, both 43.7% | `data/processed/urban_dimensions_city.csv` |
| Bazaar × transit: 91,272 / 370,580 / 1,831 of 463,682 | `data/processed/transit_bazaar_overlap_city.csv` |
| Standardized 6.9% (2015) → 10.0% (2026), +14 stations in 2020 | `data/processed/metro_access_temporal_city.csv` |
| Sensitivity 10.0% / 13.6% / 17.3% | `site/data/sensitivity.json` (from `data/processed/walking_speed_sensitivity.csv`) |
| Spearman ρ ≈ 0.01 (density vs metro share, n = 12) | computed for the report from `district_access_metrics.csv`; descriptive only |
| 62% of metro-accessible residents in the top four districts | computed for the report from `district_access_metrics.csv` |

## Design notes for the poster

The poster follows the three academic-poster templates supplied for the course:

- a split title band;
- full-width tinted section bands with icon-circle headings;
- numbered method steps joined by chevrons;
- lettered result figures (A–E);
- big-number infographic callouts and a donut with direct labels;
- a references / QR-code footer.

It reuses the website's colour code (teal = metro, amber = bus-only, slate =
underserved). Light-surface steps of those colours were checked with a
colour-vision-deficiency palette validator. The slate is deliberately neutral
because it stands for "neither mode". Every chart segment is labelled directly,
so no class depends on colour alone.
