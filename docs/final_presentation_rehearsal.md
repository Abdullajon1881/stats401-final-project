# Final presentation — walkthrough narrative

A running order for demonstrating the project live, in the interface itself.

This is **not** a slide deck and not a script to read aloud. No slide count and
no duration are assumed here, because none has been specified for the course.
Adjust the depth of each section to whatever time is given.

No rehearsal has been performed yet. This document is the plan for one.

Before starting: `python -m http.server 8000 -d site`, open
<http://localhost:8000>, and confirm the map has drawn.

---

## 1. The question

**Say:** Tashkent has a metro, and it has buses. The question is how much of the
city can actually reach the metro on foot, and which districts are left
depending on buses instead.

**Show:** The page at rest — the map of the city with the access area on it.

**Number:** none yet. Let the map do the talking.

**Next:** "The obvious way to answer this is to draw circles around stations.
That answer is wrong, and it is worth seeing why."

---

## 2. Why circles around stations are not enough

**Say:** A circle assumes you can walk straight through whatever is in the way —
railway lines, canals, walled blocks, motorways. People walk on streets and
paths. Two points the same distance from a station can be a very different walk
apart. This project measures distance **along the pedestrian network** instead,
from each population cell's own position on the footway.

**Show:** Zoom to street level near a station. Point at the access area's shape:
it follows streets, and it stops where the network stops.

**Number:** 800 m of network distance, not 800 m as the crow flies.

**Next:** "That requires knowing where people are, and where the network is."

---

## 3. Data sources

**Say:** Three sources, each doing one job. OpenStreetMap gives the pedestrian
network, the stations and their entrances, the bus stops and the district
boundaries. The Statistics Agency gives the official population total for each
district. WorldPop is used only to spread each district's official total across
roughly 100 m cells inside that district — every district still sums back to its
official number.

**Show:** Method & limitations dialog, the "What is measured" section.

**Number:** 3,212,200 analysed residents across 12 districts.

**Next:** "One district is missing from that count, and that is deliberate."

---

## 4. Method, and the boundary of the analysis

**Say:** Yangi Toshkent has an OSM boundary but no published SIAT population row,
so there is no official total to calibrate against. Rather than invent a
denominator, it is excluded and the exclusion is recorded. Within the twelve
that remain, each cell is routed along the network to the nearest metro
entrance and the nearest bus stop, at 4.8 km/h for ten minutes.

**Show:** Method dialog, "Known limits". Mention the ten stations with no mapped
entrance that fall back to the station point.

**Number:** 154 metro access points — 144 mapped entrances and 10 fallbacks.

**Next:** "So what is the answer?"

---

## 5. The headline

**Say:** An estimated 13.6% of the analysed population is within a modelled
ten-minute walk of metro access. Roughly 72% can reach a bus stop in that time
but not the metro. About 14% reach neither.

Stress the framing: this is a model estimate over the analysed population, not a
measurement of where people live or how they travel.

**Show:** The sidebar — the three figures and the Key finding block underneath.

**Number:** 13.6%.

**Next:** "The map shows where that 13.6% is."

---

## 6. Map walkthrough

**Say:** The teal area is everything within the ten-minute network walk. The
white dots are stations, the small cyan dots are individual entrances. The
darker grid underneath is where people are.

**Show:** Start at city zoom. Point out how the access area is a ribbon along the
lines rather than a blanket. Zoom to a district. Then zoom to street level so
the entrances and the street grid resolve. Toggle **Bus stops** on to show how
much wider the bus network's reach is.

**Number:** at most one — the combined metro-or-bus figure, 85.6%.

**Next:** "That gap between 13.6% and 85.6% is the bus-only population, and it is
not spread evenly."

---

## 7. Where access depends most on buses

**Say:** This chart is sorted by bus-only share, because that is the second half
of the question. Read the top row.

Be careful here: a high bus-only share means the metro is not within a modelled
ten-minute walk for most of that district's population. It says nothing about
how good the buses are.

**Show:** Scroll to District analysis. Point at the top of the stacked chart.
Hover one row and show every other view responding.

**Number:** the top district's bus-only share, read off the chart.

**If asked about the 0.0% metro district:** its nearest analysed population cell
is about 19.7 m outside the 800 m budget. That result is threshold-sensitive and
should not be read as "no metro access exists there".

**Next:** "A natural question is whether density explains any of this."

---

## 8. Density vs access

**Say:** If the metro followed population density, we would expect a clear upward
trend. The dashed lines are the medians of these twelve districts — descriptive,
not thresholds.

**Show:** The scatter. Hover two or three points. Let the audience see the
pattern themselves rather than asserting one.

**Number:** none. This chart is about shape, not a value.

**Next:** "Access is only one dimension of a district."

---

## 9. Comparing whole districts

**Say:** Six axes, each in its own real units. Pin a few districts and compare
their profiles side by side.

Flag the two MAPPED axes explicitly: bus stops per km² and bazaars per 100k come
from OpenStreetMap, whose coverage varies. A thin count may mean a thinly
surveyed district rather than a thinly served one.

**Show:** Select a district, **Add to comparison**, repeat for two or three
more. Point at the chips and the coloured lines.

**Number:** none needed.

**Next:** "Everything so far assumes people walk at 4.8 km/h."

---

## 10. Sensitivity

**Say:** Walking speed is the assumption the headline is most exposed to. At
4.0 km/h the metro share falls to 10.0%; at 5.6 km/h it rises to 17.3%. The
direction of the finding does not change, but the number moves by several
percentage points, so quote it as an estimate.

Then the population surface: swapping the within-district WorldPop surface from
2026 to 2020 moves the city estimate by about 0.01 percentage points. That means
the result is insensitive to *that* substitution — it does not prove the
population surface is right.

**Show:** Method & limitations → the sensitivity table.

**Number:** 10.0% / 13.6% / 17.3%.

**Next:** "Which leads to what this project does not claim."

---

## 11. Limitations

**Say:** Physical walking access only — no frequency, no fare, no reliability,
no crowding. The cell-to-network link is a straight line and may not be
walkable. Bus stops are OSM-only. Ten stations lack mapped entrances. One
district's 0.0% is decided by about twenty metres.

**Show:** Method dialog, "Known limits" and "What is not measured".

**Number:** 19.7 m, if the threshold-sensitivity point comes up.

**Next:** "So what does it add up to?"

---

## 12. Takeaway

**Say:** On this model, metro walking access in Tashkent is narrow and
concentrated along the lines: about one resident in seven of the analysed
population. The large majority are within walking distance of a bus stop but not
the metro, and that dependence is very unevenly distributed across districts.
Everything shown is reproducible from the audited outputs, and the uncertainty
is on the page rather than buried in a repository.

**Show:** Return to Overview, the city view.

**Number:** 13.6%.

**Close:** offer the Method dialog for questions about assumptions.

---

## Questions worth preparing for

- *Why not a straight-line buffer?* — Section 2. Offer to zoom in and show the
  network shape.
- *Why is one district at 0.0%?* — 19.7 m outside the budget; threshold-
  sensitive; do not overclaim.
- *Is WorldPop reliable?* — It is an alpha product and is used only to
  distribute official district totals. The sensitivity test shows the city
  result barely moves between two surfaces; that is insensitivity, not
  validation.
- *Why exclude Yangi Toshkent?* — No official population row to calibrate
  against.
- *Does bus-only mean bad service?* — No. It is a modelled walking-access
  category and carries no information about service quality.
- *Would the answer change with a different walking speed?* — Yes, by several
  percentage points. The table is in the Method dialog.
