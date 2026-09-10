# Week 6 — Linked district visualizations

Week 5 delivered a map-first spatial workspace with two coordinated views. Week 6
completes the planned system: three more D3 idioms sit beneath the map in a
**District analysis** deck, and all five views now answer to one district
selection.

Nothing analytical was recomputed. Every figure on screen is read at runtime
from `site/data/districts.geojson` and `site/data/city_summary.json`, which are
themselves checked against the audited Week 4 outputs by
`scripts/validate_prototype.py`. `data/processed/` and
`data/analysis_manifest.json` have zero diff against the Week 5 merge.

## Purpose

The research question has two halves:

> What share of Tashkent's population lives within a 10-minute walk of the
> metro, **and which districts depend mostly on buses?**

Week 5 answered the first half well and the second only implicitly — a reader
had to infer bus reliance from the absence of metro access. The composition view
answers it directly, and the other two put that answer in context: whether
density explains access, and how a district's whole profile compares with its
neighbours'.

## The five idioms and the task each serves

| # | View | Reader's task |
|---|------|---------------|
| 1 | Interactive access map | Where is the 10-minute metro catchment, and who lives inside it? |
| 2 | Ranked dot plot | Which districts have the highest modelled metro access? |
| 3 | 100% stacked composition | Which districts depend most on buses? |
| 4 | Density vs access scatter | Do denser districts have better modelled metro access? |
| 5 | Parallel coordinates | How does one district's whole profile compare with others? |

Views 1 and 2 are unchanged from the audited Week 5 product.

## 3. Access composition — `site/js/composition.js`

**Encoding.** Twelve horizontal rows, one per district, each a 100% stacked bar
of three mutually exclusive categories drawn from the audited fields
`metro_access_pct`, `bus_only_pct` and `underserved_pct`. Those three sum to 100
by construction (worst observed deviation 1×10⁻⁶), so the bar is drawn from the
percentages directly rather than reconstructed from populations.

Colour is the product's existing semantic palette: metro cyan, bus-only amber,
underserved slate.

**Order.** Sorted by `bus_only_pct` descending, because bus reliance is what
this chart exists to show. Ties break on district name so the order is
deterministic. The order is computed from the data at runtime — no district name
or position appears in the source — and the panel says *sorted by bus-only
share* so the ordering does not look arbitrary.

**Direct labels.** The district name on the left, the bus-only percentage on the
right (the value the chart is ordered by), and a 0 / 50 / 100% guide. Segments
are not labelled individually: at this row height the numbers would be
unreadable. The full three-way breakdown with population counts is in the
tooltip and in each row's accessible label.

**Inline note.** One data-derived sentence names the highest modelled bus-only
share. Both the district and the figure come from `ordered[0]`, so it cannot go
stale or disagree with the bars above it. It is descriptive — a measured
maximum, not a judgement about that district.

## 4. Density vs metro access — `site/js/scatter.js`

**Encoding.** x = `population_density_per_km2`, y = `metro_access_pct`, twelve
points.

**Scales.** Both linear, both starting at zero. The y axis is a share and a
truncated baseline would exaggerate the differences between districts. Upper
extents come from the data and are `.nice()`d, so a future data revision cannot
push a point off the top. A log x scale was considered and rejected: these
densities span roughly one order of magnitude, so a log axis would add reading
cost without separating anything the linear scale merges.

**Median guides.** Dashed lines at the median of the twelve districts on screen,
computed with `d3.median`. They are descriptive — they say where the middle of
this particular set falls. The quadrants they create are deliberately
**unlabelled**: naming them ("priority", "underserved quadrant") would assert a
judgement the analysis does not support. The panel footnote says so explicitly.

**Labels.** Hidden by default; shown on hover, selection, keyboard focus, or
comparison membership. Twelve permanent labels collide at this size, and a
force simulation to avoid that would be motion for decoration's sake. Each
visible label picks its side from the point's position, so a label near the
right edge anchors right rather than overhanging the panel, and one near the top
drops below its point rather than sitting on the district above.

## 5. Compare district profiles — `site/js/parallel.js`

Six axes, each with its own scale and its own real-world unit. Normalising all
six to a unitless 0–1 would draw exactly the same lines and make every tick
label meaningless.

| Axis | Source | Unit |
|------|--------|------|
| Population | `official_population` | people |
| Density | `population_density_per_km2` | people / km² |
| Metro access | `metro_access_pct` | % |
| Bus-only | `bus_only_pct` | % |
| Bus stops | derived (below) | MAPPED stops / km² |
| Bazaars | derived (below) | MAPPED per 100k residents |

### The two derived comparison ratios

Computed at runtime in `site/js/chart-utils.js` from audited fields:

```
mappedBusStopsPerKm2  =  bus_stops_in_district / area_km2
mappedBazaarsPer100k  =  bazaars_in_district / official_population * 100000
```

**These are not Week 4 analytical results.** They are deterministic ratios that
exist so the comparison has more than access on it. They are computed in the
browser and written nowhere: `data/processed/` is untouched, and neither
`districts.geojson` nor `city_summary.json` gained a field.

They are labelled **MAPPED** on the axis itself and in every tooltip and spoken
label, because OpenStreetMap completeness is not guaranteed and varies by
district. A district with few mapped bus stops may be thinly surveyed rather
than thinly served, and this data cannot distinguish the two. The panel says
plainly that they are not a measure of official service provision.

### Lines

All twelve districts are drawn as quiet context. Hovering raises one to full
contrast; selecting one gives it a persistent stronger treatment. Pinned
comparison districts get a colour from a restrained four-colour palette that
deliberately avoids the semantic metro/bus/underserved colours — reusing those
would say a pinned district *is* an access category. Colour is never the only
cue: pinned lines also carry width and opacity, and every one has a matching
labelled chip.

## Shared selection

One store (`site/js/state.js`) owns the selection. All five views read it and
none of them keeps a copy.

| Action | Result |
|--------|--------|
| Hover a district in **any** view | that district highlights in all five |
| Click a district mark in **any** view | `selectedDistrict` changes globally |
| Click the selected district again | releases it |
| Escape, or **Clear** | returns to the city overview |

Click means the same thing in all five views: **select this district**. No view
overloads it.

### Selection survives navigation

Week 5's Overview button called `clearSelection()`, so moving between sections
silently discarded the district a reader was studying — a side effect of
navigating rather than something they asked for. Week 6 removes that. Overview
scrolls to the map workspace, Districts scrolls to and focuses the analysis
deck, and both preserve `selectedDistrict`, `selectedStation` and the comparison
set. Selection is released only through Clear, Escape, or re-clicking the same
district.

## Multi-district comparison

`comparisonDistricts` is a separate axis of state, bounded at four
(`MAX_COMPARISON`), enforced inside the store rather than in the UI.

| | `selectedDistrict` | `comparisonDistricts` |
|---|---|---|
| Cardinality | 0 or 1 | 0 to 4 |
| Meaning | the one district the whole application is currently about | districts pinned for simultaneous profile comparison |
| Set by | clicking any district mark, or search | the explicit comparison control only |
| Cleared by | Clear, Escape, re-click | **Clear comparison**, or a chip's × |

Selecting a district never pins it, and clearing the comparison never deselects
anything. Comparison membership is never toggled by clicking a line, so click
keeps one meaning everywhere.

The control is in the parallel panel and mirrored in the district sidebar; both
call the same store functions. It reads *Select a district to compare* when
nothing is selected, *Add [district]* / *Remove [district]* otherwise, and is
disabled with *Maximum 4 districts — remove one to add another* when the set is
full. Pinned districts appear as removable chips that double as the colour
legend.

## Accessibility

- No interactive chart root uses `role="img"`. Each is `role="list"`, each
  district is a `listitem` carrying one `role="button"` control. Twelve controls
  per chart, not hundreds of focusable SVG children.
- Every district control has a meaningful label, e.g.
  *"Uchtepa. Metro 0.0 percent. Bus-only 95.2 percent. Underserved 4.8 percent.
  Activate to select this district."*
- Enter and Space select; Escape clears, matching the global behaviour.
- `aria-pressed` reports which district is selected.
- Comparison controls are real buttons with a real disabled state; chip removal
  buttons name the district they remove.
- Selection and comparison changes are announced through the existing live
  region.
- Camera flights and section scrolling collapse to no motion under
  `prefers-reduced-motion`.
- All chart text is built with `textContent` through `site/js/dom.js`. No
  dynamic `innerHTML` anywhere; the district and station names these charts
  display are world-editable OpenStreetMap strings.

## Responsive behaviour

| Width | Deck layout |
|-------|-------------|
| ≥ 1400 px | three panels in one row, about 36 / 27 / 37 |
| 941–1399 px | two rows: composition full width, scatter and parallel beneath |
| ≤ 940 px | one column, read top to bottom |

The map workspace keeps its full-viewport shape at every width; the page scrolls
so the deck sits beneath it rather than competing with the map for the same
screen.

At phone width the parallel chart keeps all six axes: captions abbreviate, units
stay on a second line and the tick count drops. It redraws rather than scrolling
sideways. The composition chart's label gutter is measured from the longest
district name at the current font rather than taken as a share of the width — a
percentage guess clipped the longest name at 320 px.

Tested at 1920×1080, 1440×900, 1366×768, 1024×768, 768×1024, 390×844 and
320×568: no page-level horizontal overflow and no clipped chart text at any of
them.

## Limitations

- The two MAPPED ratios describe OpenStreetMap coverage, not service provision.
  They are comparable across districts only to the extent that survey effort is,
  which is unknown.
- The scatter's median guides describe these twelve districts. They are not
  thresholds and carry no policy meaning.
- The composition chart's ordering is descriptive. A high bus-only share is a
  measured share of modelled walking access, not a statement about service
  quality, ridership or need.
- All three views inherit every Week 4 limitation: the shares are modelled from
  pedestrian-network distance to metro entrances at 4.8 km/h within 600 s and an
  800 m budget, and are sensitive to those assumptions. The Method dialog states
  them.
- The comparison set holds four districts because a fifth line on six axes stops
  being readable, not because four is analytically meaningful.
