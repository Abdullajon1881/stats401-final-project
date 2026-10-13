# Presentation quick reference

A one-page companion to the full walkthrough in `docs/final_presentation_rehearsal.md`.
No duration is assumed and **no rehearsal is claimed** — adjust depth to the time given.
Demo order follows the assignment: **Motivation → Questions → Data → Visualization story → Key insights → Conclusion.**

## Opening (30 seconds)

> "A metro line on a map doesn't tell you who can actually *reach* it on foot. We modelled walking access
> along Tashkent's real pedestrian network and asked: what share of the analysed population is within a
> ten-minute walk of the metro, and where do buses fill the gap?"

## The five numbers to remember

- **13.6%** metro access · **72.0%** bus-only · **14.4%** underserved (mutually exclusive, sum to 100%).
- **3,212,200** residents across **12** districts (Yangi Toshkent excluded — no official total).
- **Mirabad 24.9%** highest metro; **Uchtepa 0.0%** lowest (its nearest cell is ~**19.7 m** beyond the 800 m budget).
- **Uchtepa 95.2%** highest bus-only dependence.
- Bazaar overlap: of residents near a bazaar, **19.7% metro+bazaar, 79.9% bus-only+bazaar, 0.4% underserved+bazaar.**

## Which interaction demonstrates each of the five visualizations

| Idiom | Demo move | Point to make |
|---|---|---|
| Geographic access map | Zoom to street level; toggle **Bus stops** | Access follows the network, not a circle; bus reach is far wider. |
| Ranked district comparison | Hover the top row | Wide spread; every other view highlights the same district. |
| Metro/bus-only/underserved composition | Read the top (Uchtepa) bar | High bus-only ≠ "bad service"; it means metro isn't a 10-min walk. |
| Density-vs-access scatter | Hover two dense districts | Density alone does **not** predict access. |
| Parallel coordinates | Pin 2–3 districts to compare | Whole-profile comparison; MAPPED axes reflect OSM coverage, not service. |

Also show: destination cards (healthcare/education/bazaar), the **bazaar–transit overlap** bar + tables,
the **temporal** year slider, and the **District Explorer** (select → clear with Escape → select a station to
show the district selection clears).

## The current ↔ historical distinction (say this verbatim if asked)

> "The 13.6% headline is the current, entrance-aware, SIAT-calibrated model. The 2015–2026 line uses a
> **different** method — station-centre proxies and annual WorldPop weights on fixed geography — so its 10.0%
> for 2026 is **not** the same quantity. They answer different questions; we never subtract one from the other."

## Likely questions — strong answers

- **"Why is it only 13.6%?"** — It's walking access to the metro *specifically*, along the real network within
  800 m. Most residents can still reach a bus stop in that time (72% bus-only). It's an estimate, not a count.
- **"Why a network model, not circles?"** — Circles assume you can walk through rail lines and canals. The
  network respects barriers; two points equidistant from a station can be very different walks.
- **"Is the 0.0% district really cut off?"** — No. Uchtepa's nearest analysed cell is ~19.7 m outside the
  800 m budget; that zero is threshold-sensitive, not an absence of metro.
- **"How complete is OpenStreetMap?"** — Coverage varies; we label mapped bus-stop and bazaar axes MAPPED and
  treat them as lower bounds, not service measures. Ten of 50 stations lack mapped entrances (station-point fallback).
- **"Is WorldPop reliable?"** — It's an alpha product used **only** to distribute official SIAT district totals;
  every district sums back to its official number. Swapping the 2026 surface for 2020 moves the city result by
  ~0.01 points — insensitivity to that substitution, not proof it's correct.
- **"Would a different walking speed change it?"** — Yes, materially: 10.0% at 4.0 km/h to 17.3% at 5.6 km/h.
  The direction of the finding holds, so we quote it as an estimate.
- **"Does the bazaar overlap show where people shop?"** — No. It's simultaneous modelled *proximity* to mapped
  markets and transit, not trips, transfers, frequency or use.

## Closing takeaway

> "On this model, metro walking access in Tashkent is narrow and concentrated along the lines — about one
> analysed resident in seven. Most depend on buses for that first leg, very unevenly across districts.
> Everything is reproducible from audited outputs, and the uncertainty is on the page, not buried."

---

## Suggested speaking division — **requires owner confirmation**

The proposal lists Doniyor Erkinov (coordination, data acquisition, cleaning, presentation) and
Saidkamolkhon Bakhodirov (geospatial analysis, visualization/D3, interactions, interface, testing).
A natural split would have one present motivation/data/method and the other the visualization story and
live demo — **but confirm the actual division with both members before presenting.** Do not assume it from
commit history.
