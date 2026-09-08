# Data sources (Week 3 data foundation)

This document records where every dataset comes from, how it was acquired, and
what we know is wrong or missing. It covers the Week 3 milestone only: the
sources are assembled and checked here, but no accessibility result is computed.

Everything below is produced by `scripts/acquire_data.py` and checked by
`scripts/validate_data.py`. Machine-readable details (URLs, counts, checksums,
acquisition timestamps) are in [`data/source_manifest.json`](../data/source_manifest.json).

## Coordinate reference systems

| Purpose | CRS | Why |
|---|---|---|
| Storage / web output | `EPSG:4326` (WGS 84) | GeoJSON is defined in WGS84 (RFC 7946) and D3 consumes lon/lat directly. |
| All distances and areas | `EPSG:32642` (WGS 84 / UTM zone 42N) | Metric, and Tashkent sits almost on its central meridian. |

`EPSG:32642` was checked rather than assumed. UTM zone 42N spans 66°E–72°E; its
central meridian is 69°E and Tashkent is at roughly 69.24°E, i.e. 0.24° away.
Scale distortion is therefore negligible across the whole city. The check runs
at the start of every acquisition (`verify_metric_crs`) and fails the run if the
CRS ever stops covering Tashkent or stops being metric.

No distance is ever computed in degrees.

## 1. OpenStreetMap

**Licence:** Open Database License (ODbL) v1.0 — <https://www.openstreetmap.org/copyright>. Verified.

OSM supplies the city boundary, district boundaries, the pedestrian network, and
every transit/POI point layer. We use it because it is the only openly licensed
source with consistent city-wide coverage of footpaths, metro entrances and bus
stops for Tashkent.

Boundaries and the walk graph are fetched with **OSMnx**; the point layers use
**hand-written Overpass QL** (`scripts/overpass_client.py`). The queries are
written out in full in the source so the tag rules can be audited, and a small
explicit query completes in seconds where OSMnx's slot-polling against the busy
public instance repeatedly stalled. Three Overpass mirrors are tried in order,
because the main instance returns 429/504 under load often enough to break a run.

Point queries use the city **bounding box** and are then clipped to the exact
boundary. The Tashkent boundary polygon has thousands of vertices; embedding it
in Overpass QL makes a query large enough to time out on every mirror.

### 1.1 City boundary and districts

City = OSM relation [2216724](https://www.openstreetmap.org/relation/2216724).

Districts are the `admin_level=6` boundary relations that are **members of that
relation**, not the result of a spatial query. A bounding-box query also returns
seven Tashkent *region* districts (Zangiata, Qibray, Yangiyul and others) that
merely touch the city, which is exactly the kind of silent contamination this
milestone is meant to catch.

**The 13th district.** The city relation has 13 members, not 12. Twelve match the
official SIAT district list. The thirteenth is **Yangi Toshkent Tumani** (relation
17389398, tagged `start_date=2024`), the "New Tashkent" development area east of
the city. It has no SIAT population row.

The geometry makes the situation unambiguous:

| | Area |
|---|---|
| OSM city boundary | 633.89 km² |
| 13 districts combined | 633.89 km² |
| 12 SIAT districts combined | 437.72 km² |
| Yangi Toshkent alone | 196.17 km² |

So the OSM city boundary already includes Yangi Toshkent, and the 12 official
districts leave a 196 km² hole in it. OSM reflects a newer administrative
reality than the official statistics do; English Wikipedia still lists 12
districts too.

We keep all 13 features in `tashkent_districts.geojson` with an `in_siat` flag
rather than dropping one silently. The 12 SIAT-matched districts are the
analysis set, because the project's research question is population-weighted and
Yangi Toshkent has no official population. **Whether Week 4 includes it, and how
the city boundary is defined for the denominator, is an open decision that
belongs to the analysis milestone.**

District names differ between OSM and SIAT (`Yunusobod Tumani` vs
`Yunusabad district`), so the two are linked by an **explicit crosswalk keyed on
OSM relation id** in `scripts/config.py`, exported as
`data/processed/district_name_crosswalk.csv`. No fuzzy string matching is used
anywhere.

### 1.2 Pedestrian network

`osmnx.graph_from_bbox(network_type="walk", simplify=True)` over the city bbox,
then truncated to the city boundary buffered by 1 km. The buffer stops walking
routes being cut off at the city edge; OSMnx's `walk` filter keeps footways and
sidewalks and drops motorways and private access.

The graph is **not committed**. It is large and fully reproducible, so it is
written to `data/external/` (gitignored) and rebuilt by the acquisition script.

### 1.3 Metro

Candidate tags queried: `railway=station`, `railway=halt`,
`railway=subway_entrance`, `station=subway`, `subway=yes`,
`public_transport=station`.

* **Station** = (`station=subway` OR `subway=yes`) AND NOT `railway=subway_entrance`.
* **Entrance** = `railway=subway_entrance`.

`railway=station` on its own is deliberately **not** enough: Tashkent's national
railway terminal carries that tag and is not a metro station.

**Deduplication.** Two station objects within 200 m that share *any* name variant
(`name`, `name:en`, `name:ru`) are treated as one station. This matters because
OSM maps several Tashkent stations twice — once with a Latin name and once with a
Cyrillic one (`Olmos`/`Алмас`, `Minor`/`Минор`, `Mashinasozlar`/`Машиносозлар`,
`Oʻzbekiston`/`Узбекистан`, `Alisher Navoiy`/`Алишер Навоий`). Only the
transliterated variants reveal these are single stations. When a pair merges, a
node beats a way and a Latin name beats a Cyrillic one; both are real OSM names,
nothing is transliterated by us.

Genuine interchanges stay separate because they share no name variant:
Oybek/Mingoʻrik, Paxtakor/Alisher Navoiy, Amir Temur xiyoboni/Yunus Rajabiy,
Doʻstlik/Texnopark.

**External cross-check.** The cleaned output is **50 stations**, which matches
English Wikipedia's [Tashkent Metro](https://en.wikipedia.org/wiki/Tashkent_Metro)
infobox exactly (4 lines; 17 + 11 + 8 + 14 = 50, interchanges counted once).
Before the cross-script rule was added the pipeline produced 56, and every one of
the six extra features was a confirmed double-mapping. Note that other web
sources quote 50, 52 and 59 depending on whether interchange platforms and
under-construction stations are counted; we use the per-line breakdown because it
is checkable rather than the largest number.

`line` is not tagged on Tashkent station nodes in OSM, so that column is empty;
`network` and `operator` are populated. We did not invent line assignments.

### 1.4 Bus stops

Candidate tags: `highway=bus_stop`, `public_transport=platform`,
`public_transport=stop_position`, `bus=yes`.

Kept when `highway=bus_stop` OR (`public_transport` in {platform, stop_position}
AND `bus=yes`). Rail, metro and tram platforms share the `public_transport` tags
and are excluded.

**Deduplication** — two rules, both narrow on purpose:

* **Rule A.** A `stop_position` (a node on the carriageway) within 50 m of a
  platform sharing a name variant is the same physical stop, so the
  `stop_position` is dropped. Unnamed pairs use 25 m.
* **Rule B.** Two objects of the *same* role sharing a name variant within 5 m
  are genuine double-mapping and collapse.

Stops on opposite sides of a road are both platforms, so Rule A never touches
them and Rule B's 5 m radius cannot reach across a carriageway. They stay as two
separate stops, which is correct: they serve opposite directions.

Bus data is noisier than metro data and this is a *foundation*, not a finished
layer. Week 4 should revisit it before any bus-only figure is published.

### 1.5 Bazaars

`amenity=marketplace` only. No other tag is treated as a bazaar, and no location
is added by hand.

This is a secondary dimension of the project, and the count is a **lower bound**.
Smaller neighbourhood and informal markets are very likely missing from OSM, and
several features carry only a generic name (`базарчик`, "little market"). There is
no target count to hit.

## 2. Official district population — SIAT

**Source:** Statistics Agency under the President of the Republic of Uzbekistan,
SIAT portal, dataset **3890** (code 2.01.02.0056), "Permanent population (city)".
Landing page: <https://siat.stat.uz/data/3890/?lang=en>

**Licence: unclear.** No licence statement appears on the dataset page or the
portal footer. We treat it as official public statistics used with attribution
and have flagged it in the manifest for review before publication. We did not
claim a licence we could not verify.

**Acquisition.** The portal's `download_format=csv` endpoint returns JSON metadata
pointing at the real CSV, so the script follows that pointer and downloads the
file. Nothing is typed by hand.

**Reference period:** 2026-Q2 (dataset last updated 2026-07-24).
**Source units:** thousands of people. Stored as persons (×1000).

**Is dataset 3890 the right source?** It needed checking, because 3890 is the
*urban* series: nationally it reports 19.6 million against a total population of
about 38.5 million. For Tashkent it is nevertheless the correct total, and the
script proves this on every run rather than assuming it:

* the companion rural series (dataset 3891) reports **0** for Tashkent city and
  for all 12 districts, so urban = total here;
* the male and female series (3888 + 3889) sum exactly to the 3890 value for
  every district;
* the 12 districts sum to **3,212.2 thousand**, exactly the SIAT city row.

The acquisition fails loudly if Tashkent's rural population ever stops being
zero. The proposal's cited link is therefore correct and was not changed.

## 3. WorldPop gridded population

**Product:** WorldPop Global 2015–2030, release **R2025A**, constrained,
individual countries, 100 m, Uzbekistan, **2026**.
**File:** `uzb_pop_2026_CN_100m_R2025A_v1.tif`
**DOI:** [10.5258/SOTON/WP00839](https://doi.org/10.5258/SOTON/WP00839)
**Licence:** Creative Commons Attribution 4.0 International (CC BY 4.0) — verified at <https://hub.worldpop.org/data/licence.txt>.

The 2026 layer was chosen because it aligns with the SIAT 2026-Q2 reference
period. R2025A is the current release; R2024B is the older beta. The exact URL
came from the WorldPop REST API rather than being guessed.

**Values are estimated persons per grid cell**, not density. CRS is EPSG:4326,
cells are 3 arc-seconds — about 93 m north–south and about 70 m east–west at
Tashkent's latitude. Nodata is `-99999`.

At 36 MB the raster is **not committed**. It lives in `data/external/`
(gitignored) and is re-downloaded by the acquisition script; the manifest records
its SHA-256 so a future download can be checked against the file we used.

WorldPop is a modelled distribution, not a count. It is used here to say *where*
people are within a district; district totals still come from SIAT. Calibrating
the two is Week 4 work and is deliberately not done yet.

### WorldPop does not agree with SIAT at district level

This is the most important finding of the milestone, so it is stated plainly.

Aggregating the raster over the 12 district polygons and comparing with the
official totals gives:

| | WorldPop 2026 | SIAT 2026-Q2 | ratio |
|---|---|---|---|
| City total | 2,381,987 | 3,212,200 | 0.74 |
| Bektemir | 245,092 | 73,600 | **3.33** |
| Yakkasaray | 281,045 | 147,000 | 1.91 |
| Chilanzar | 85,243 | 277,600 | **0.31** |
| Sergeli | 57,933 | 182,500 | 0.32 |

The per-district ratio spans **0.31 to 3.33 — a 10.8x spread** — and the
correlation between WorldPop and SIAT district totals is **−0.077**, i.e. no
relationship at all. WorldPop puts more people in industrial Bektemir
(6,866/km²) than in Chilanzar (2,809/km²), which is Tashkent's densest Soviet
mikrorayon housing. That ordering is clearly wrong.

We checked whether this is an artifact of the 2026 projection by downloading the
2020 layer of the same product and repeating the aggregation. It is not:

* every district scales by **exactly 1.12** from 2020 to 2026, so the 2026 layer
  is a uniform rescaling of the 2020 surface and adds no new spatial detail;
* the correlation with SIAT is **−0.077 in 2020 as well**.

So the disagreement is inherent to WorldPop's constrained surface for Tashkent,
not to the year we picked. We verified our own aggregation independently with
`rasterstats`, which reproduced the same totals exactly, and confirmed the
district polygons are correctly placed (centroids and metro-station containment
both check out), so this is not a pipeline bug.

**What this means for Week 4.** Calibration is not a cosmetic step. WorldPop
cannot be used to distribute population *between* districts; it can only supply
*within-district* spatial structure, and each district's cells must be rescaled
to its SIAT total. Even the within-district structure deserves scepticism given
how poorly the between-district allocation performs, and the sensitivity of the
final access percentage to that assumption should be tested.

`scripts/validate_data.py` computes this correlation on every run and warns when
it falls below 0.5, so the problem cannot quietly disappear.

## 4. Transport open data — attempted, not available

`https://data.egov.uz/` is cited in the proposal. **It could not be reached from
our network at all**: HTTPS and HTTP both fail to connect (not a 403 or a 404 —
the TCP connection is refused/times out), and `https://data.gov.uz/` behaves the
same way. We could not confirm whether this is a geographic block, a temporary
outage, or a decommissioned portal.

Consequence: **no open-data bus layer was acquired**, and bus stops rest on OSM
alone. This is a real gap in the proposal's plan and is recorded here rather than
glossed over. Week 4 should retry the portal, ideally from a different network.

**Yandex Maps was not scraped.** The proposal mentions collecting bus data from
Yandex, but automated extraction is not clearly permitted by its terms, so no
automated collection was performed and nothing from Yandex is in this repository.
It may still be used as a manual visual sanity check. Every dataset here comes
from a source we are entitled to use.

## Reproducibility notes

* Run everything from the repository root: `python scripts/acquire_data.py`,
  then `python scripts/validate_data.py`.
* `data/external/` and `data/raw/` are gitignored. Nothing in them is required to
  read the processed outputs, and everything in them is rebuilt by the script.
* OSM is edited continuously, so re-running gives *current* data, not identical
  data. Between two runs minutes apart we already saw the raw bus candidate count
  move by one and one marketplace appear and disappear. The manifest stores the
  acquisition timestamp and the counts for the run that produced the committed
  files.
* Overpass mirrors fail intermittently; the client retries across three of them
  and prints which one answered.

## Known limitations

1. `data.egov.uz` unreachable — no independent bus source, OSM is unvalidated
   against an official list.
2. Yangi Toshkent district exists in OSM but not in SIAT; the analysis set of 12
   districts covers 437.72 km² of the 633.89 km² OSM city boundary.
3. Bus stops are OSM-only and noisy; 231 of 2,163 have no name.
4. Bazaar coverage is incomplete by nature; 83 marketplaces is a lower bound,
   and 7 of them are unnamed.
5. Ten of the 50 metro stations have no mapped entrance nearby — these are mostly surface
   and elevated Circle Line stations, where `railway=subway_entrance` is not the
   right tag. Week 4 should fall back to the station point for those.
6. SIAT licensing is unverified.
7. WorldPop disagrees with SIAT at district level (correlation −0.077, ratios
   0.31–3.33). Per-district calibration is mandatory in Week 4; a single
   city-wide scale factor would be wrong.
8. 64 of 2,163 bus stops sit exactly on a district border, because Tashkent's
   district lines follow major roads. They are assigned to the nearest district
   and flagged `district_assignment = boundary_nearest`.
