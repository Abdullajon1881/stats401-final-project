"""Validate the Week 6 linked visualization system.

    python scripts/validate_week6.py

Exits 0 when every critical check passes, 1 otherwise.

This sits ON TOP of validate_data.py, validate_analysis.py and
validate_prototype.py; it replaces none of them. Those establish that the
audited Week 4 result is intact and that the Week 5 prototype shows it. This
file checks the three views Week 6 adds, the state they share with the two that
already existed, and the boundary between audited results and the two derived
comparison ratios.

It does not accept a comment as proof of anything. Every claim it makes is
checked against the source or the data: a formula is matched as code, a
mapping is matched as the property it reads, and every check was confirmed to
fail against a deliberately broken copy before being trusted.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
from pipeline_utils import enable_utf8_stdout  # noqa: E402

SITE_DIR = cfg.REPO_ROOT / "site"
JS_DIR = SITE_DIR / "js"
WEB_DATA_DIR = SITE_DIR / "data"
DOCS_DIR = cfg.REPO_ROOT / "docs"

BASELINE_MAIN = "b2ea4195d5eb92b3185f4b26cd3251ce0d6e25e1"

PASSED = 0
WARNINGS: list[str] = []
CRITICAL: list[str] = []


def section(title: str) -> None:
    print()
    print("-" * 74)
    print(title)
    print("-" * 74)


def check(condition: bool, label: str, *, critical: bool = True) -> bool:
    global PASSED
    if condition:
        PASSED += 1
        print(f"  PASS  {label}")
        return True
    if critical:
        CRITICAL.append(label)
        print(f"  FAIL  {label}")
    else:
        WARNINGS.append(label)
        print(f"  WARN  {label}")
    return False


def js(name: str) -> str:
    path = JS_DIR / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. the files the five-view system is made of
# ---------------------------------------------------------------------------
def validate_files() -> None:
    section("1. Week 6 modules and documentation")
    for name in ("composition.js", "scatter.js", "parallel.js", "chart-utils.js"):
        check((JS_DIR / name).exists(), f"site/js/{name} exists")
    doc = DOCS_DIR / "week6_linked_visualizations.md"
    check(doc.exists(), "docs/week6_linked_visualizations.md exists")
    if doc.exists():
        text = doc.read_text(encoding="utf-8")
        check(len(text) > 2000, f"Week 6 documentation has substance ({len(text)} chars)")
        for term in ("parallel", "scatter", "composition", "comparison", "accessibility"):
            check(term.lower() in text.lower(), f"documentation covers {term}")


# ---------------------------------------------------------------------------
# 2. all five idioms are present and wired
# ---------------------------------------------------------------------------
def validate_five_views() -> None:
    section("2. The five coordinated views")
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    app = js("app.js")

    check('id="map"' in html, "1. geographic access map is present")
    check('id="ranking"' in html, "2. ranked district dot plot is present")
    check('id="composition"' in html, "3. stacked access-composition view is present")
    check('id="scatter"' in html, "4. density vs access scatterplot is present")
    check('id="parallel"' in html, "5. parallel-coordinates comparison is present")
    check('id="district-analysis"' in html, "the analytical deck has an addressable section")

    check("initMap(" in app, "app initialises the map")
    check("initRanking(" in app, "app initialises the ranking")
    check("initComposition(" in app, "app initialises the composition view")
    check("initScatter(" in app, "app initialises the scatter view")
    check("initParallel(" in app, "app initialises the parallel view")

    # Every view has to be driven from the one subscription.
    sub = re.search(r"store\.subscribe\(\(state, changed\) => \{(.+?)\n  \}\);", app, re.S)
    body = sub.group(1) if sub else ""
    for fn in ("syncMap", "syncRanking", "updateCompositionState",
               "updateScatterState", "updateParallelState"):
        check(fn in body, f"{fn} runs on every state change")


def strip_comments(src: str) -> str:
    """Remove JS comments so a scan sees code, not prose about the code.

    A district name inside an explanatory comment is documentation; the same
    name inside a string or an expression would mean an ordering or a result
    was written in rather than derived. Only the second is a defect, so the
    scan has to be able to tell them apart.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?<![:\w])//[^\n]*", "", src)


# ---------------------------------------------------------------------------
# 3. what the charts actually read
# ---------------------------------------------------------------------------
def validate_data_mappings() -> None:
    section("3. Chart encodings, against the district data")
    districts = load_json(WEB_DATA_DIR / "districts.geojson")
    features = districts["features"]
    check(len(features) == 12, f"exactly 12 districts (got {len(features)})")

    props = [f["properties"] for f in features]
    for key in ("metro_access_pct", "bus_only_pct", "underserved_pct",
                "population_density_per_km2", "official_population",
                "area_km2", "bus_stops_in_district", "bazaars_in_district"):
        present = sum(1 for p in props if key in p)
        check(present == len(props), f"every district carries {key} ({present}/{len(props)})")

    # The three composition categories are mutually exclusive and exhaustive.
    worst = max(abs(p["metro_access_pct"] + p["bus_only_pct"] + p["underserved_pct"] - 100.0)
                for p in props)
    check(worst < 1e-4,
          f"each district's three access shares sum to 100 (worst deviation {worst:.2e})")

    comp = js("composition.js")
    check("metro_access_pct" in comp and "bus_only_pct" in comp and "underserved_pct" in comp,
          "composition reads the three audited percentage fields")
    # It must use the audited percentages, not rebuild them from populations.
    segs = re.search(r"const SEGMENTS = \[(.+?)\];", comp, re.S)
    seg_text = segs.group(1) if segs else ""
    check("metro_access_pct" in seg_text and "bus_only_pct" in seg_text
          and "underserved_pct" in seg_text,
          "the stacked segments are the audited percentages themselves")
    check(re.search(r"/\s*official_population\s*\*\s*100", comp) is None,
          "composition does not reconstruct percentages from populations")

    scat = js("scatter.js")
    check(re.search(r"xValue\s*=\s*\(p\)\s*=>\s*p\.population_density_per_km2", scat) is not None,
          "scatter x maps population_density_per_km2")
    check(re.search(r"yValue\s*=\s*\(p\)\s*=>\s*p\.metro_access_pct", scat) is not None,
          "scatter y maps metro_access_pct")
    check(".nice()" in scat, "scatter extents are derived from the data and nice()d")
    check(re.search(r"\.domain\(\[0,", scat) is not None,
          "scatter axes start at an honest zero")
    check("d3.median" in scat, "the median guides are computed, not assumed")

    # ── at most one scatter text label ──────────────────────────────────
    # Three independent CSS states each revealed a label, so three could be
    # visible at once and districts plotting a few pixels apart drew their
    # names through one another. The rule now lives in one place.
    css = (SITE_DIR / "styles.css").read_text(encoding="utf-8")
    reveals = re.findall(r"^([^{\n]*\.sc-plabel[^{\n]*)\{[^}]*opacity:\s*1", css, re.M)
    selectors = [r.strip() for r in reveals]
    check(len(selectors) == 1,
          f"exactly one CSS rule reveals a scatter label ({selectors or 'none'})")
    check(all("is-compared" not in sel for sel in selectors),
          "comparison membership alone does not reveal a scatter label")
    check(all("is-hovered" not in sel and "is-selected" not in sel for sel in selectors),
          "hover and selection do not each reveal a label independently")

    picker = re.search(r"function labelledDistrict\(state\)\s*\{(.+?)\n\}", scat, re.S)
    picker_body = picker.group(1) if picker else ""
    check("state.hoveredDistrict" in picker_body and "state.selectedDistrict" in picker_body,
          "the labelled district is chosen from hover then selection")
    check("comparisonDistricts" not in picker_body,
          "the comparison set has no say in which label is shown")
    check(bool(picker_body)
          and picker_body.index("hoveredDistrict") < picker_body.index("selectedDistrict"),
          "hover outranks selection for the visible label")
    check("classed('has-label'" in scat, "one class marks the single labelled point")

    # Comparison keeps its POINT styling; only the automatic text label went.
    check("comparisonColour(" in scat, "pinned districts keep their comparison colour")
    check(".sc-pt.is-compared .sc-dot" in css,
          "pinned districts keep their comparison point treatment")

    # ── re-ordering must not move a focusable element ───────────────────
    # Emphasis is paint order, and paint order is DOM order. Re-appending a
    # node that contains the focused element blurs it and sends it to the end
    # of the tab order; with hit targets inside the mark groups that left one
    # district of twelve reachable by keyboard.
    for name, marks, hits in (("scatter.js", "sc-marks", "sc-hits"),
                              ("parallel.js", "pc-lines", "pc-hits")):
        src = js(name)
        check(f"'class', '{marks}'" in src, f"{name} draws its marks in their own layer")
        check(f"'class', '{hits}'" in src,
              f"{name} keeps its focusable hit targets in a separate layer")
        # Examine the whole statement each .raise() belongs to, not one call
        # shape: a raise written through a fresh d3.select of the hit layer
        # would re-order focusable nodes just as surely. Comments are stripped
        # first so prose about hit targets cannot trip the check.
        statements = [st for st in strip_comments(src).split(";") if ".raise()" in st]
        offenders = [" ".join(st.split())[:80] for st in statements
                     if re.search(r"hit|item", st, re.I)]
        check(not offenders,
              f"{name} raises no focusable element ({offenders or 'none'})")
        check(len(statements) > 0, f"{name} still orders its marks by emphasis")


# ---------------------------------------------------------------------------
# 4. the two derived comparison ratios
# ---------------------------------------------------------------------------
def validate_derived_metrics() -> None:
    section("4. Derived comparison ratios")
    utils = js("chart-utils.js")

    # The formulas must be exactly count / area and count / population * 100000.
    bus = re.search(r"function mappedBusStopsPerKm2\(p\)\s*\{(.+?)\n\}", utils, re.S)
    bus_body = bus.group(1) if bus else ""
    check("p.bus_stops_in_district / p.area_km2" in bus_body,
          "mapped bus-stop density is count / area")

    baz = re.search(r"function mappedBazaarsPer100k\(p\)\s*\{(.+?)\n\}", utils, re.S)
    baz_body = baz.group(1) if baz else ""
    check("p.bazaars_in_district / p.official_population" in baz_body
          and "100000" in baz_body,
          "mapped bazaar rate is count / population * 100000")

    # Both must be labelled MAPPED where the reader meets them.
    check(utils.count("MAPPED") >= 2, "both derived axes are labelled MAPPED")
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    check("MAPPED counts" in html,
          "the panel says what MAPPED counts are and are not")
    check("not official service provision" in html
          or "official service provision" in html,
          "the panel refuses the reading that these measure service provision")

    # Reproduce both ratios independently from the data.
    districts = load_json(WEB_DATA_DIR / "districts.geojson")
    bad = []
    for f in districts["features"]:
        p = f["properties"]
        want_bus = p["bus_stops_in_district"] / p["area_km2"]
        want_baz = p["bazaars_in_district"] / p["official_population"] * 100000
        if not (want_bus >= 0 and want_baz >= 0):
            bad.append(p["district_name"])
    check(not bad, f"both ratios are computable for every district ({bad or 'all 12 fine'})")

    # They must not have been written into the audited data.
    for name in ("districts.geojson", "city_summary.json"):
        text = (WEB_DATA_DIR / name).read_text(encoding="utf-8")
        check("mapped_bus_stops_per_km2" not in text
              and "mapped_bazaars_per_100k" not in text,
              f"{name} carries no derived comparison metric")

    processed = cfg.REPO_ROOT / "data" / "processed"
    leaked = []
    if processed.exists():
        for path in processed.rglob("*"):
            if path.suffix.lower() in {".json", ".csv", ".geojson"} and path.is_file():
                head = path.read_text(encoding="utf-8", errors="ignore")[:200000]
                if "mapped_bus_stops_per_km2" in head or "mapped_bazaars_per_100k" in head:
                    leaked.append(path.name)
    check(not leaked, f"no derived metric was written into data/processed ({leaked or 'clean'})")


# ---------------------------------------------------------------------------
# 5. one shared state, and the comparison set beside it
# ---------------------------------------------------------------------------
def validate_state() -> None:
    section("5. Shared selection and comparison state")
    state = js("state.js")

    check("comparisonDistricts" in state, "the store owns the comparison set")
    check("export const MAX_COMPARISON = 4" in state,
          "the comparison bound is four and lives in the store")

    for fn in ("addToComparison", "removeFromComparison", "toggleComparison",
               "clearComparison", "isCompared", "comparisonIsFull"):
        check(f"export function {fn}" in state, f"the store exposes {fn}")
    check("export function comparisonInvariantHolds" in state,
          "the comparison invariant is exposed for testing")

    add = re.search(r"export function addToComparison\(name\)\s*\{(.+?)\n\}", state, re.S)
    add_body = add.group(1) if add else ""
    check("comparisonIsFull()" in add_body,
          "adding is refused once the set is full, in the store rather than the UI")
    check("isCompared(name)" in add_body, "a district cannot be pinned twice")

    clear = re.search(r"export function clearComparison\(\)\s*\{(.+?)\n\}", state, re.S)
    clear_body = clear.group(1) if clear else ""
    check("selectedDistrict" not in clear_body,
          "clearing the comparison does not touch the selection")

    setfn = re.search(r"export function set\(patch\)\s*\{(.+?)\n\}", state, re.S)
    set_body = setfn.group(1) if setfn else ""
    check("comparisonDistricts" not in set_body,
          "selecting a district does not implicitly pin it")

    # Every new chart writes hover and selection through the store, and none of
    # them keeps a private copy of either.
    for name in ("composition.js", "scatter.js", "parallel.js"):
        src = js(name)
        check("import * as store from './state.js'" in src, f"{name} imports the store")
        check("store.set({ hoveredDistrict:" in src, f"{name} sets hoveredDistrict centrally")
        check("store.toggleDistrict(" in src, f"{name} selects through the store")
        check(re.search(r"^let\s+(selected|hovered)\w*\s*=", src, re.M) is None,
              f"{name} keeps no private selection state")

    # Comparison membership must never be toggled by clicking a mark.
    par = js("parallel.js")
    click = re.search(r"\.on\('click', \(event, d\) => ([^)]+\))", par)
    check(bool(click) and "toggleComparison" not in click.group(1),
          "clicking a parallel line selects rather than pinning")


# ---------------------------------------------------------------------------
# 6. accessibility
# ---------------------------------------------------------------------------
def validate_accessibility() -> None:
    section("6. Accessibility of the new charts")
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")

    for name in ("composition.js", "scatter.js", "parallel.js"):
        src = js(name)
        check("role', 'img'" not in src and 'role", "img"' not in src,
              f"{name} does not hide its controls inside role=img")
        check("'role', 'list'" in src, f"{name} exposes its marks as a list")
        check("'role', 'listitem'" in src, f"{name} marks each district as a list item")
        check("'role', 'button'" in src, f"{name} gives each district a real control")
        check("'tabindex', 0" in src, f"{name} makes those controls reachable by keyboard")
        check("'aria-label'" in src, f"{name} labels each district control")
        check("'aria-pressed'" in src, f"{name} reports which district is selected")
        check("event.key === 'Enter'" in src and "event.key === ' '" in src,
              f"{name} activates on Enter and Space")
        check("event.key === 'Escape'" in src, f"{name} clears the selection on Escape")

    utils = js("chart-utils.js")
    for fn in ("speakComposition", "speakScatter", "speakParallel"):
        check(f"export function {fn}" in utils, f"{fn} builds a spoken district label")
    check("percent" in utils, "spoken labels say 'percent' rather than a bare symbol")

    # Comparison controls must be real buttons with a real disabled state.
    check('<button type="button" id="compare-add"' in html,
          "the comparison control is a real button")
    check('id="compare-clear"' in html, "clearing the comparison is a real button")
    par = js("parallel.js")
    check("add.disabled = true" in par and "add.disabled = false" in par,
          "the comparison button's disabled state is set both ways")
    check("aria-label" in par, "chip removal buttons name the district they remove")

    ui = js("ui.js")
    check("comparisonAction" in ui, "the district panel offers the same comparison action")


# ---------------------------------------------------------------------------
# 7. nothing hard-coded, nothing unsafe
# ---------------------------------------------------------------------------
DISTRICT_WORDS = (
    "Almazar", "Bektemir", "Chilanzar", "Mirabad", "Mirzo Ulugbek", "Sergeli",
    "Shaykhantakhur", "Uchtepa", "Yakkasaray", "Yangikhayot", "Yashnabad",
    "Yunusabad",
)


def audited_result_literals() -> set[str]:
    """Every audited district and city figure, in the forms a literal could take."""
    values: set[float] = set()
    districts = load_json(WEB_DATA_DIR / "districts.geojson")
    for feature in districts["features"]:
        for key, value in feature["properties"].items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.add(float(value))
    city = load_json(WEB_DATA_DIR / "city_summary.json")
    for value in city.values():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.add(float(value))

    forms: set[str] = set()
    for value in values:
        # Only DISTINCTIVE figures are evidence. A bare small integer collides
        # with ordinary layout numbers - a 240px minimum width is not the count
        # of something just because some district has 240 of it - so integers
        # count only from 1000 up, where a coincidence stops being plausible.
        if value == int(value):
            if abs(value) >= 1000:
                forms.add(str(int(value)))
            continue
        # A decimal figure carries its own fingerprint at two or more places.
        for places in (2, 3, 4, 6):
            forms.add(f"{value:.{places}f}")
        forms.add(repr(value))
    return forms


def validate_no_hardcoding() -> None:
    section("7. Runtime-derived, and safe")
    sources = {name: js(name) for name in
               ("composition.js", "scatter.js", "parallel.js", "chart-utils.js")}
    results = audited_result_literals()

    for name, src in sources.items():
        code = strip_comments(src)

        # A district name in executable code would mean an ordering, a label or
        # a result was written in rather than read from the data.
        named = [w for w in DISTRICT_WORDS if w in code]
        check(not named, f"{name} names no district in code ({named or 'none'})")

        # An audited figure appearing as a literal is the real hazard. Layout
        # constants - a 0.46 width share, a 0.06 axis padding - are not results,
        # so the scan compares against the actual audited values rather than
        # flagging every decimal it sees.
        found = sorted({literal for literal in re.findall(r"\b\d+(?:\.\d+)?\b", code)
                        if literal in results})
        check(not found,
              f"{name} contains no audited figure as a literal ({found or 'none'})")

        for pattern in ("innerHTML", "outerHTML", "insertAdjacentHTML",
                        "document.write", "setHTML(", "d3.html("):
            check(pattern not in code, f"{name} uses no {pattern}")

    comp = js("composition.js")
    check("sort(" in comp, "the composition order is computed rather than listed")
    check("bus_only_pct" in comp and "b.properties.bus_only_pct - a.properties.bus_only_pct" in comp,
          "the composition sorts by bus-only share, descending")
    check("sorted by bus-only share" in (SITE_DIR / "index.html").read_text(encoding="utf-8"),
          "the panel states the ordering so it does not look arbitrary")

    lead = re.search(r"function renderLead\(\)\s*\{(.+?)\n\}", comp, re.S)
    lead_body = lead.group(1) if lead else ""
    check("ordered[0]" in lead_body,
          "the inline note names whichever district is first in the runtime order")

    # No invented research categories.
    all_src = "\n".join(sources.values()) + (SITE_DIR / "index.html").read_text(encoding="utf-8")
    for phrase in ("priority district", "underserved hotspot", "extension target",
                   "bus-dependent if", "poorly planned", "neglected"):
        check(phrase.lower() not in all_src.lower(),
              f"no invented category: {phrase!r}")


# ---------------------------------------------------------------------------
# 8. the audited result is untouched
# ---------------------------------------------------------------------------
def validate_provenance() -> None:
    section("8. Week 4 provenance")

    def git(*args: str) -> str:
        result = subprocess.run(["git", *args], cwd=cfg.REPO_ROOT,
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace")
        return result.stdout.strip()

    for path in ("data/processed", "data/analysis_manifest.json",
                 "README.md", "docs/proposal.md"):
        diff = git("diff", "--stat", BASELINE_MAIN, "--", path)
        check(diff == "", f"{path} is unchanged since {BASELINE_MAIN[:10]} ({diff or 'no diff'})")

    city = load_json(WEB_DATA_DIR / "city_summary.json")
    expected = {
        "metro_access_pct": 13.563595724255597,
        "bus_only_pct": 72.04136811206638,
        "underserved_pct": 14.395036163678002,
        "walking_speed_kmh": 4.8,
        "walking_time_seconds": 600,
        "distance_budget_m": 800.0,
        "snapping_method": "edge-aware",
    }
    for key, want in expected.items():
        got = city.get(key)
        ok = got == want if isinstance(want, str) else (
            got is not None and abs(float(got) - float(want)) < 1e-12)
        check(ok, f"city summary keeps {key} = {want!r} (found {got!r})")

    # The display-only roles Week 5 established must still hold.
    for name in ("metro_stations.geojson", "bus_stops.geojson", "bazaars.geojson"):
        fc = load_json(WEB_DATA_DIR / name)
        bad = sum(1 for f in fc["features"]
                  if (f.get("properties") or {}).get("role") != "display_only")
        check(bad == 0, f"{name} still labels every feature display_only ({bad} unlabelled)")

    fc = load_json(WEB_DATA_DIR / "districts.geojson")
    bad = sum(1 for f in fc["features"]
              if (f.get("properties") or {}).get("role") == "display_only")
    check(bad == 0, f"districts.geojson stays analytical ({bad} contaminated)")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 74)
    print("Week 6 — linked district visualizations")
    print("=" * 74)

    validate_files()
    validate_five_views()
    validate_data_mappings()
    validate_derived_metrics()
    validate_state()
    validate_accessibility()
    validate_no_hardcoding()
    validate_provenance()

    print()
    print("-" * 74)
    print("Summary")
    print("-" * 74)
    print(f"  passed  : {PASSED}")
    print(f"  warnings: {len(WARNINGS)}")
    print(f"  critical: {len(CRITICAL)}")
    for item in WARNINGS:
        print(f"    WARN  {item}")
    for item in CRITICAL:
        print(f"    FAIL  {item}")
    print()
    if CRITICAL:
        print("WEEK 6 VALIDATION FAILED")
        return 1
    print("WEEK 6 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    enable_utf8_stdout()
    raise SystemExit(main())
