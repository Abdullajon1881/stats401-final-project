# STATS 401 — final submission checklist

Release audited: `main = aa2b494dcf07b2a6de840a8c7c7975e17b416dfd` (tree `471d4a56…`).
Status key: ✅ complete · 🟡 complete pending owner confirmation · ⛔ requires owner-supplied input · 📝 recommendation only.

## A. Required submission deliverables (rubric §"Required submission deliverables")

| # | Deliverable | Status | Evidence / location |
|---|---|---|---|
| 1 | Source dataset(s) | ⛔ PENDING | OSM/SIAT **processed** data committed with provenance+SHA256, but the two **original source binaries** (WorldPop raster, OSM walk-network GraphML) are gitignored and **not yet delivered**. The rubric requires source datasets; no evidence the team accepts links in place of files. Owner must supply a separate archive. See `submission/source_dataset_inventory.md` §6. |
| 2 | Cleaned / processed dataset(s) | ✅ | 37 files in `data/processed/` + 23 typed browser copies in `site/data/` (hashed in `site/data/manifest.json`). |
| 3 | Collection / crawler code | ✅ | `scripts/acquire_data.py`. |
| 4 | Data cleaning & analysis code | ✅ | `scripts/analyze_accessibility.py`, `analyze_transit_bazaar_overlap.py`, `build_web_data.py`, validators/tests. |
| 5 | Complete visualization source code | ✅ | `site/` (vanilla ES modules, D3 7.9.0, MapLibre 5.24.0). |
| 6 | Published website / dashboard | ✅ | https://tashkent-transit-walkability.saidkamolbahodirov.workers.dev/ and https://stats401-final-project.saidkamolbahodirov.workers.dev/ (owner confirmed production render). |
| 7 | Final report (~1,500 words) | 🟡 | `submission/final_report.md` (+ `final_report.pdf`, ≈ 1,713 words). Figure 1 is the authentic owner metro-access screenshot. Roles section still needs owner confirmation. |
| 8 | Final project poster | ✅ | `submission/poster.html` (editable) + `submission/poster.pdf` (A1 landscape). Geographic panel now shows the authentic metro-access map. |
| 9 | Reproducibility documentation | ✅ | `README.md`, `docs/final_integration.md`, `docs/data_sources.md`, `submission/source_dataset_inventory.md`. |

## B. Required visualization features (rubric §"Required visualization features")

| Requirement | Status | Evidence |
|---|---|---|
| ≥5 interactive visualizations | ✅ | Map, ranking, composition, scatter, parallel coordinates (+ destinations map, bazaar overlap, temporal, District Explorer). |
| Multiple appropriate idioms | ✅ | Geographic, ranking, part-to-whole, scatter, multidimensional. |
| ≥1 complex visualization | ✅ | Geographic MapLibre access map; multidimensional parallel coordinates. |
| ≥5 meaningful interactions | ✅ | Coordinated district selection across all views; hover highlight; Escape/clear; up-to-4 comparison pinning; destination switching; temporal year slider; station selection (mutually exclusive); map layer toggles; search combobox. |
| Programmatic generation (D3/approved) | ✅ | All charts are D3; map is MapLibre GL. |
| Coherent HTML dashboard telling a story | ✅ | Single scrolling narrative, question → findings → extensions → history → limitations. |
| Exploration beyond tooltips | ✅ | Linked selection/comparison reshape every view, not just tooltips. |

## C. Required final report sections (rubric §"Required final report")

| Section | Status |
|---|---|
| Introduction (motivation, 5 questions, audience, why interactive) | ✅ |
| Method (OSM/SIAT/WorldPop, cleaning, routing, 10-min model, 3 classes, D3/MapLibre, temporal frame separate) | ✅ |
| Results (each of 5 idioms: what / which RQ / what users do / insight; + destinations, overlap, temporal) | ✅ |
| Discussion (What–Why–How; strengths, limitations, improvements) | ✅ |
| Conclusion | ✅ |
| Roles & Responsibilities | 🟡 reproduced from proposal; **owner must confirm final contributions** |
| Screenshots of finished visualizations | ✅ Figure 1 authentic metro-access map (owner screenshot) + charts 02–07 embedded; D3 facilities map kept as a labelled supplementary figure |
| Word count ~1,500 | ✅ body ≈ 1,678 words (tightened from 1,755; target ≈ 1,500–1,600; counts the per-visualization explanations as report content) |

## D. Poster (rubric §"Required final project poster")

| Requirement | Status |
|---|---|
| Print-friendly layout, editable source retained | ✅ A1 landscape; `poster.html` source + `poster.pdf` export (841×594 mm documented) |
| Title + research question | ✅ |
| 10-minute model explained | ✅ |
| Data-source/method summary | ✅ |
| Main metro/bus-only/underserved findings | ✅ stat tiles 13.6 / 72.0 / 14.4 |
| Selected original charts/screenshots | ✅ authentic metro-access map, composition, bazaar overlap, temporal |
| Geographic context | ✅ authentic MapLibre metro-access map (access shading, stations, density grid) |
| Bazaar–transit finding | ✅ |
| Limitations | ✅ |
| Takeaway for non-site viewers | ✅ |
| Authors + course | ✅ (no invented institution/logo) |
| QR to live site | ✅ `figures/qr-primary-site.png` (also printed as text; not machine-decoded in this env — see limitations) |

## E. Presentation (rubric §"Required presentation")

| Item | Status |
|---|---|
| Live-demo running order (Motivation→Questions→Data→Story→Insights→Conclusion) | ✅ `docs/final_presentation_rehearsal.md` (existing) + `submission/presentation_quick_reference.md` (new companion) |
| Speaking division | 🟡 pending owner confirmation |
| Emphasis on interactions & findings | ✅ |

## F. Website quality review (rubric high-weight criteria) — recommendations only

The deployed site already passed production + academic acceptance and is treated as a **protected stable
release**. The focused review against Visualization (25%), Technical (20%) and Storytelling (15%) found
**no rubric-relevant defect that justifies modifying the frozen release.** Optional, non-blocking ideas
(recorded, **not implemented**):

- 📝 The main map depends on a remote basemap; consider a bundled minimal fallback style so the geographic
  idiom degrades to outlines+points (not a blank panel) when tiles are unavailable. *Semantics-neutral, but
  touches map code — defer to project lead.*
- 📝 Consider a one-line on-page pointer from the headline to the Method dialog's sensitivity table, so the
  13.6%↔walking-speed dependence is discoverable without opening the dialog. *Cosmetic.*

Neither is required; both are deferred pending project-lead authorization because the release is frozen.

## G. Integrity

| Check | Status |
|---|---|
| Frozen analytical data untouched | ✅ no `data/`, `site/data/`, or `site/js/` file modified on this branch |
| Report/poster numbers match committed data | ✅ verified against `site/data/` |
| No secrets/private data in deliverables | ✅ |
| New files confined to `submission/` | ✅ |

## Outstanding items that block "submission-approved"

1. ⛔ **Team contributions** — confirm each member's final role (report §6, presentation division). Do not infer from commit history.
2. ⛔ **Source-dataset delivery** — supply the two original source binaries (WorldPop raster, OSM GraphML) as a separate archive, or confirm with evidence that provider links + provenance manifests are accepted (see inventory §6).

*(The authentic metro-access map for Figure 1 and the poster has been integrated — `figures/01-current-metro-access-map.png`, the owner's production screenshot.)*
