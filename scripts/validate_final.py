"""Validate the final integrated project.

    python scripts/validate_final.py

Exits 0 when every critical check passes, 1 otherwise.

This sits ON TOP of validate_data.py, validate_analysis.py,
validate_prototype.py and validate_week6.py, and replaces none of them. Those
establish that the audited result is intact, that the site shows it, and that
the five views are coordinated. This file checks the things that only matter
once the project is finished: that no stale claim survives anywhere a reader can
see it, that the sensitivity published on the site is the audited sensitivity,
that the headline is worded as an estimate from a model, and that the frozen
files are still frozen.

Checks are structural or data-driven. A comment is never accepted as evidence.
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

BASELINE_MAIN = "158f9ba2e2fff171db35281df83e836d565ca6eb"

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
    (CRITICAL if critical else WARNINGS).append(label)
    print(f"  {'FAIL' if critical else 'WARN'}  {label}")
    return False


def js(name: str) -> str:
    path = JS_DIR / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def strip_comments(src: str) -> str:
    """Remove JS/CSS comments so a scan sees shipped copy, not prose about it."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?<![:\w])//[^\n]*", "", src)


def product_copy() -> dict[str, str]:
    """Everything a reader can end up seeing, with source comments removed.

    Vendored libraries are excluded: they are third-party and their contents are
    not this project's claims.
    """
    out: dict[str, str] = {}
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    out["index.html"] = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    for path in sorted(JS_DIR.glob("*.js")):
        out[path.name] = strip_comments(path.read_text(encoding="utf-8"))
    out["styles.css"] = strip_comments((SITE_DIR / "styles.css").read_text(encoding="utf-8"))
    return out


# ---------------------------------------------------------------------------
# 1. the finished shape of the project
# ---------------------------------------------------------------------------
def validate_baseline() -> None:
    section("1. Final project shape")

    for name in ("map.js", "ranking.js", "composition.js", "scatter.js", "parallel.js",
                 "chart-utils.js", "state.js", "app.js", "ui.js", "dom.js", "data.js"):
        check((JS_DIR / name).exists(), f"site/js/{name} exists")

    for doc in ("final_integration.md", "final_presentation_rehearsal.md",
                "week6_linked_visualizations.md"):
        path = DOCS_DIR / doc
        check(path.exists(), f"docs/{doc} exists")
        if path.exists():
            check(len(path.read_text(encoding="utf-8")) > 1500,
                  f"docs/{doc} has substance")

    integration = (DOCS_DIR / "final_integration.md")
    if integration.exists():
        text = integration.read_text(encoding="utf-8").lower()
        for topic in ("research question", "bus-only", "sensitivity", "limitations",
                      "yangi toshkent", "accessibility", "dependencies",
                      "publication status", "running the site"):
            check(topic in text, f"final_integration.md covers {topic}")
        check("not deployed" in text,
              "final_integration.md does not claim the site is deployed")

    rehearsal = (DOCS_DIR / "final_presentation_rehearsal.md")
    if rehearsal.exists():
        text = rehearsal.read_text(encoding="utf-8")
        check("Doniyor" not in text, "the rehearsal notes invent no one's actions")
        check("no rehearsal has been performed" in text.lower(),
              "the rehearsal notes do not claim a rehearsal happened")


# ---------------------------------------------------------------------------
# 2. no stale claim survives in product copy
# ---------------------------------------------------------------------------
OBSOLETE_NUMBERS = ("37.8", "28.4", "33.8", "2,998,000", "2998000")
OBSOLETE_COUNTS = (
    (r"\b49\s+(metro\s+)?stations?\b", "49 stations"),
    (r"\b96\s+(bazaars?|marketplaces?)\b", "96 bazaars"),
)
DEV_LABELS = ("Week 3", "Week 4", "Week 5", "Week 6", "Week 7", "PRELIMINARY",
              "pending audit", "open for review", "interim prototype", "TODO", "FIXME")


def validate_no_stale_copy() -> None:
    section("2. Stale claims and development language")
    sources = product_copy()

    for name, src in sources.items():
        found = [n for n in OBSOLETE_NUMBERS if n in src]
        check(not found, f"{name}: no obsolete headline value ({found or 'none'})")

        stale = [label for pattern, label in OBSOLETE_COUNTS
                 if re.search(pattern, src, re.I)]
        check(not stale, f"{name}: no obsolete count claim ({stale or 'none'})")

        labels = [d for d in DEV_LABELS if d.lower() in src.lower()]
        check(not labels, f"{name}: no development label in shipped copy ({labels or 'none'})")

    # The QA hook keeps its name; it is gated and is not product copy. Any OTHER
    # use of the word in text a reader sees would be a development leftover.
    html = sources["index.html"]
    visible = re.sub(r"<[^>]+>", " ", html)
    check("prototype" not in visible.lower(),
          "no user-visible text calls this a prototype")


# ---------------------------------------------------------------------------
# 3. the sensitivity on the site is the audited sensitivity
# ---------------------------------------------------------------------------
def validate_sensitivity() -> None:
    section("3. Sensitivity artifact against its audited sources")
    import pandas as pd

    path = WEB_DATA_DIR / "sensitivity.json"
    if not check(path.exists(), "site/data/sensitivity.json exists"):
        return
    published = load_json(path)

    check(published.get("role") == "analytical",
          "the sensitivity artifact is labelled analytical")

    speed = pd.read_csv(cfg.WALK_SPEED_SENSITIVITY_FILE)
    audited = speed[speed.scope == "city"].sort_values("speed_kmh")
    rows = published.get("walking_speed", {}).get("rows", [])
    check(len(rows) == len(audited),
          f"every audited city row is published ({len(rows)} of {len(audited)})")

    speeds = sorted(round(r["speed_kmh"], 3) for r in rows)
    for want in (4.0, 4.8, 5.6):
        check(want in speeds, f"the {want} km/h row is present")
    check(abs(published["walking_speed"].get("headline_speed_kmh", 0)
              - cfg.MAIN_WALK_SPEED_KMH) < 1e-9,
          f"the headline speed is {cfg.MAIN_WALK_SPEED_KMH} km/h")

    # Every published figure must equal its audited source exactly.
    mismatches = []
    for row in rows:
        src = audited[abs(audited.speed_kmh - row["speed_kmh"]) < 1e-9]
        if len(src) != 1:
            mismatches.append(f"{row['speed_kmh']}: no unique audited row")
            continue
        src = src.iloc[0]
        for key in ("metro_access_pct", "combined_pct", "underserved_pct",
                    "metro_access_population", "budget_m"):
            if abs(float(row[key]) - float(src[key])) > 1e-9:
                mismatches.append(f"{row['speed_kmh']} {key}: {row[key]} vs {src[key]}")
    check(not mismatches,
          f"published sensitivity equals the audited CSV exactly ({mismatches or 'all match'})")

    # The headline row must agree with the city summary the site already shows.
    city = load_json(WEB_DATA_DIR / "city_summary.json")
    headline = [r for r in rows if abs(r["speed_kmh"] - cfg.MAIN_WALK_SPEED_KMH) < 1e-9]
    check(len(headline) == 1, "exactly one headline row")
    if headline:
        # The sensitivity CSV is written to six decimals and city_summary.json
        # keeps full precision, so they can only agree to the CSV's own
        # resolution. Anything looser would let a genuinely different number
        # through; anything tighter fails on the rounding.
        gap = abs(headline[0]["metro_access_pct"] - city["metro_access_pct"])
        check(gap < 1e-5,
              f"the headline sensitivity row matches the published city metro share "
              f"(differ by {gap:.2e}, within the CSV's six decimals)")

    surface = pd.read_csv(cfg.POPULATION_SURFACE_SENSITIVITY_FILE)
    city_row = surface[surface.scope == "city"].iloc[0]
    pub = published.get("population_surface", {})
    check(abs(pub.get("percentage_point_difference", 99)
              - float(city_row.percentage_point_difference)) < 1e-9,
          "the population-surface difference equals its audited source")
    check("does not validate" in pub.get("interpretation", "").lower(),
          "the surface result is not presented as validating the population surface")

    # The site must read the file rather than carrying the numbers itself.
    ui = js("ui.js")
    check("data.sensitivity" in ui, "the interface reads the sensitivity artifact")
    literals = [f"{v:.6f}" for v in (9.958364, 13.563596, 17.298466,
                                     79.602043, 85.604964, 89.273760)]
    for name, src in product_copy().items():
        hits = [lit for lit in literals if lit[:7] in src]
        check(not hits, f"{name}: no sensitivity figure written into the source ({hits or 'none'})")

    # Nothing on the site may recompute an access share.
    for name, src in product_copy().items():
        if not name.endswith(".js"):
            continue
        check("distance_budget" not in src or "computeAccess" not in src,
              f"{name}: performs no access computation")


# ---------------------------------------------------------------------------
# 4. the five views, the shared state, the bounded comparison
# ---------------------------------------------------------------------------
def validate_five_views() -> None:
    section("4. Five coordinated views")
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    app, state = js("app.js"), js("state.js")

    for view_id in ("map", "ranking", "composition", "scatter", "parallel"):
        check(f'id="{view_id}"' in html, f"the {view_id} view is present")
    for init in ("initMap(", "initRanking(", "initComposition(", "initScatter(", "initParallel("):
        check(init in app, f"app calls {init}")

    sub = re.search(r"store\.subscribe\(\(state, changed\) => \{(.+?)\n  \}\);", app, re.S)
    body = sub.group(1) if sub else ""
    for fn in ("syncMap", "syncRanking", "updateCompositionState",
               "updateScatterState", "updateParallelState"):
        check(fn in body, f"{fn} runs on every state change")

    check("export const MAX_COMPARISON = 4" in state, "the comparison bound is four")
    clear = re.search(r"export function clearComparison\(\)\s*\{(.+?)\n\}", state, re.S)
    check(bool(clear) and "selectedDistrict" not in clear.group(1),
          "clearing the comparison leaves the selection alone")


# ---------------------------------------------------------------------------
# 5. how the finding is worded
# ---------------------------------------------------------------------------
def validate_copy() -> None:
    section("5. Claims and framing")
    ui = js("ui.js")

    key = re.search(r"function keyFinding\(\)\s*\{(.+?)\n\}", ui, re.S)
    body = key.group(1) if key else ""
    check(bool(key), "the interface states a key finding")
    check("estimated" in body and "modelled" in body,
          "the headline is framed as an estimate from a model")
    check("analysed population" in body,
          "the headline names the analysed population as its denominator")
    check("metro_access_pct" in body,
          "the headline share is read from the data, not written in")
    check("bus_only_pct" in body and "sort" in body,
          "the bus-only district is derived at runtime by sorting")

    # No district may be named in the copy that describes one.
    districts = load_json(WEB_DATA_DIR / "districts.geojson")
    names = {f["properties"]["label"] for f in districts["features"]}
    named = sorted(n for n in names if n in strip_comments(ui))
    check(not named, f"no district is named in the interface source ({named or 'none'})")

    # No unsupported categorical claim, anywhere a reader can see it.
    forbidden = ("entirely depends on buses", "entirely dependent on buses",
                 "no metro access at all", "worst district", "neglected",
                 "poorly planned", "priority district", "underserved by government")
    for name, src in product_copy().items():
        hits = [p for p in forbidden if p.lower() in src.lower()]
        check(not hits, f"{name}: no unsupported claim ({hits or 'none'})")

    # The OSM-coverage caveat must survive.
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    check("MAPPED" in html and "OpenStreetMap coverage" in html,
          "the mapped-service caveat is still shown")


# ---------------------------------------------------------------------------
# 6. accessibility, security, licences, provenance
# ---------------------------------------------------------------------------
def validate_hardening() -> None:
    section("6. Accessibility, security, licences, provenance")
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    ui = js("ui.js")

    # Sensitivity table structure.
    sens = re.search(r"function sensitivitySection\(\)\s*\{(.+?)\n\}", ui, re.S)
    body = sens.group(1) if sens else ""
    check(bool(sens), "the sensitivity section is built in one place")
    for part in ("'table'", "'thead'", "'tbody'", "'caption'", "scope: 'col'", "scope: 'row'"):
        check(part in body, f"the sensitivity table uses {part}")
    check("headline assumption" in body,
          "the headline row is named in text, not marked by weight alone")

    check("<dialog" in html, "the method window is a native dialog")
    check('aria-labelledby="method-h"' in html, "the dialog is labelled")

    for name, src in product_copy().items():
        if not name.endswith(".js"):
            continue
        # Assignment is the injection path. A READ of innerHTML is how the
        # hostile-text regression proves that a malicious OSM name became
        # literal text, so banning the substring outright would forbid the very
        # check that demonstrates safety.
        for prop in ("innerHTML", "outerHTML"):
            assigned = re.search(rf"\.{prop}\s*(?:\+)?=[^=]", src)
            check(assigned is None,
                  f"{name}: nothing is assigned to {prop} "
                  f"({assigned.group(0).strip() if assigned else 'none'})")
        for pattern in ("insertAdjacentHTML", "document.write", "setHTML(",
                        "eval(", "new Function"):
            check(pattern not in src, f"{name}: no {pattern}")
        check(re.search(r"^window\.__prototype", src, re.M) is None,
              f"{name}: the QA hook is not published unguarded")

    app = js("app.js")
    check("URLSearchParams" in app and re.search(r"if\s*\(QA\)\s*\{", app) is not None,
          "the QA hook exists only behind ?qa=1")

    for notice in ("D3-LICENSE.txt", "MAPLIBRE-LICENSE.txt"):
        path = SITE_DIR / "vendor" / notice
        check(path.exists() and path.stat().st_size > 400, f"site/vendor/{notice} is present")
    mapjs = js("map.js")
    check("AttributionControl" in mapjs, "the attribution control is not removed")
    check("attributionControl: false" in mapjs and "addControl(new maplibregl.AttributionControl"
          in mapjs, "attribution is replaced by an explicit control, not suppressed")

    display = ("metro_isochrone_10min", "metro_access_points", "metro_stations",
               "bus_stops", "bazaars", "population_density", "metro_lines", "analysis_mask")
    total = 0
    for stem in display:
        fc = load_json(WEB_DATA_DIR / f"{stem}.geojson")
        feats = fc["features"]
        bad = sum(1 for f in feats
                  if (f.get("properties") or {}).get("role") != "display_only")
        total += len(feats)
        check(bad == 0, f"{stem}: all {len(feats):,} features are display_only ({bad} unlabelled)")
    print(f"    {total:,} display features checked")

    districts = load_json(WEB_DATA_DIR / "districts.geojson")
    contaminated = sum(1 for f in districts["features"]
                       if (f.get("properties") or {}).get("role") == "display_only")
    check(contaminated == 0,
          f"analytical districts carry no display label ({contaminated} contaminated)")

    # No published figure may be derived from the display isochrone.
    for name, src in product_copy().items():
        if not name.endswith(".js"):
            continue
        suspicious = re.search(r"isochrone[^;\n]{0,60}(population|pct|share)", src, re.I)
        check(suspicious is None,
              f"{name}: no coverage figure is derived from the display isochrone")


# ---------------------------------------------------------------------------
# 7. publication readiness
# ---------------------------------------------------------------------------
def validate_publishable() -> None:
    section("7. Publication readiness")
    sources = product_copy()

    for name, src in sources.items():
        for pattern, label in ((r"http://localhost", "localhost URL"),
                               (r"127\.0\.0\.1", "loopback address"),
                               (r"[A-Za-z]:\\\\", "absolute Windows path"),
                               (r"file:///", "file:// URL")):
            check(re.search(pattern, src) is None, f"{name}: no {label}")

    # Only one remote origin should appear in application code.
    origins = set()
    for name, src in sources.items():
        origins.update(re.findall(r"https?://([a-z0-9.\-]+)", src, re.I))
    allowed = {"tiles.openfreemap.org", "www.w3.org", "creativecommons.org",
               "openstreetmap.org", "www.openstreetmap.org", "openfreemap.org",
               "openmaptiles.org", "www.openmaptiles.org"}
    unexpected = sorted(o for o in origins if o not in allowed)
    check(not unexpected, f"no unexpected remote origin ({unexpected or 'none'})")

    for pattern in (r"api[_-]?key", r"access[_-]?token", r"secret", r"Bearer "):
        hits = [n for n, s in sources.items() if re.search(pattern, s, re.I)]
        check(not hits, f"no {pattern!r} in application code ({hits or 'none'})")

    # Every first-party asset the page pulls must be a relative path.
    html = sources["index.html"]
    absolute = re.findall(r'(?:src|href)="(/[^"]*)"', html)
    check(not absolute, f"first-party assets use relative URLs ({absolute or 'all relative'})")


# ---------------------------------------------------------------------------
# 8. the frozen files
# ---------------------------------------------------------------------------
def validate_frozen() -> None:
    section("8. Frozen files")

    def git(*args: str) -> str:
        r = subprocess.run(["git", *args], cwd=cfg.REPO_ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        return r.stdout.strip()

    for path in ("README.md", "docs/proposal.md", "data/processed",
                 "data/analysis_manifest.json"):
        diff = git("diff", "--stat", BASELINE_MAIN, "--", path)
        check(diff == "", f"{path} is unchanged since {BASELINE_MAIN[:10]}")

    city = load_json(WEB_DATA_DIR / "city_summary.json")
    frozen = {
        "metro_access_population": 435689.82185453834,
        "metro_access_pct": 13.563595724255597,
        "bus_only_population": 2314112.8264957964,
        "bus_only_pct": 72.04136811206638,
        "underserved_population": 462397.3516496648,
        "underserved_pct": 14.395036163678002,
        "combined_walk_access_pct": 85.60496383632197,
        "walking_speed_kmh": 4.8,
        "walking_time_seconds": 600,
        "distance_budget_m": 800.0,
        "snapping_method": "edge-aware",
    }
    for key, want in frozen.items():
        got = city.get(key)
        ok = got == want if isinstance(want, str) else (
            got is not None and abs(float(got) - float(want)) < 1e-12)
        check(ok, f"{key} = {want!r} (found {got!r})")
    check(abs(float(city.get("analysis_population", 0)) - 3_212_200) < 1e-9,
          f"analysis population = 3,212,200 (found {city.get('analysis_population')!r})")


def main() -> int:
    print("=" * 74)
    print("Final integration validation")
    print("=" * 74)

    validate_baseline()
    validate_no_stale_copy()
    validate_sensitivity()
    validate_five_views()
    validate_copy()
    validate_hardening()
    validate_publishable()
    validate_frozen()

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
        print("FINAL VALIDATION FAILED")
        return 1
    print("FINAL VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    enable_utf8_stdout()
    raise SystemExit(main())
