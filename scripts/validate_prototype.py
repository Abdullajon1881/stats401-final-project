"""Validate the Week 5 interim prototype.

    python scripts/validate_prototype.py

Exits 0 when every critical check passes, 1 otherwise.

The point of this file is to prove that the prototype shows the AUDITED Week 4
numbers and nothing else. So it does not trust `site/data/` on its own: for every
analytical value it re-reads the audited artifact under `data/` and compares. It
also checks that the audited artifacts themselves were not modified while the web
data was being built, and that no city metric is hard-coded into the JavaScript
or the HTML instead of being read from JSON at runtime.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import pandas as pd
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
from build_web_data import WEB_DATA_DIR, WEB_FILES, content_hash  # noqa: E402

SITE_DIR = cfg.REPO_ROOT / "site"

CRITICAL: list[str] = []
WARNINGS: list[str] = []
PASSED: list[str] = []

# Web values are copied from the audited files, so they should agree exactly;
# the tolerances only absorb JSON float round-tripping.
PCT_TOL = 1e-9
POP_TOL = 1e-6

EXPECTED_BUS_STOPS = 2163
EXPECTED_BAZAARS = 83
EXPECTED_METRO_STATIONS = 50
EXPECTED_ACCESS_POINTS = 154
EXPECTED_ENTRANCES = 144
EXPECTED_FALLBACKS = 10
EXCLUDED_DISTRICT = "Yangi Toshkent Tumani"


def check(condition: bool, description: str, *, critical: bool = True) -> bool:
    if condition:
        PASSED.append(description)
        print(f"  PASS  {description}")
    elif critical:
        CRITICAL.append(description)
        print(f"  FAIL  {description}")
    else:
        WARNINGS.append(description)
        print(f"  WARN  {description}")
    return condition


def section(title: str) -> None:
    print("\n" + "-" * 74)
    print(title)
    print("-" * 74)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. files
# ---------------------------------------------------------------------------
REQUIRED_SITE_FILES = [
    SITE_DIR / "index.html",
    SITE_DIR / "styles.css",
    SITE_DIR / "js" / "app.js",
    SITE_DIR / "js" / "state.js",
    SITE_DIR / "js" / "map.js",
    SITE_DIR / "js" / "ranking.js",
    SITE_DIR / "js" / "ui.js",
    SITE_DIR / "js" / "dom.js",
    SITE_DIR / "js" / "data.js",
]

VENDOR = SITE_DIR / "vendor"
VENDOR_FILES = {
    "d3.v7.min.js": "D3-LICENSE.txt",
    "maplibre-gl.js": "MAPLIBRE-LICENSE.txt",
}

JS_DIR = SITE_DIR / "js"


def js_sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(JS_DIR.glob("*.js"))}


def validate_files() -> bool:
    section("1. Prototype files")
    ok = True
    for path in REQUIRED_SITE_FILES:
        ok &= check(path.exists() and path.stat().st_size > 0,
                    f"{path.relative_to(cfg.REPO_ROOT)} exists and is non-empty")
    for name in sorted(WEB_FILES.values()):
        path = WEB_DATA_DIR / name
        ok &= check(path.exists() and path.stat().st_size > 0,
                    f"site/data/{name} exists and is non-empty "
                    f"({cfg.human_size(cfg.file_size_bytes(path))})")

    for lib, licence in VENDOR_FILES.items():
        lib_path = VENDOR / lib
        licence_path = VENDOR / licence
        ok &= check(lib_path.exists(),
                    f"site/vendor/{lib} vendored "
                    f"({cfg.human_size(cfg.file_size_bytes(lib_path))})")
        ok &= check(licence_path.exists() and licence_path.stat().st_size > 200,
                    f"site/vendor/{licence} present "
                    f"({cfg.file_size_bytes(licence_path)} bytes)")

    d3_head = (VENDOR / "d3.v7.min.js").read_text(encoding="utf-8", errors="ignore")[:200]
    check("d3js.org v7" in d3_head, "vendored D3 is v7")
    ml_head = (VENDOR / "maplibre-gl.js").read_text(encoding="utf-8", errors="ignore")[:300]
    check("MapLibre GL JS" in ml_head, "vendored MapLibre identifies itself")
    check("v5." in ml_head, "vendored MapLibre is a pinned v5 release")
    check((VENDOR / "maplibre-gl.css").exists(), "MapLibre stylesheet vendored")

    d3_licence = (VENDOR / "D3-LICENSE.txt").read_text(encoding="utf-8", errors="ignore")
    check("Mike Bostock" in d3_licence, "D3 licence carries the upstream copyright")
    ml_licence = (VENDOR / "MAPLIBRE-LICENSE.txt").read_text(encoding="utf-8", errors="ignore")
    check("MapLibre contributors" in ml_licence and "BSD" in ml_licence.upper(),
          "MapLibre licence is the upstream BSD notice")
    return ok


# ---------------------------------------------------------------------------
# 2. the audited sources are untouched
# ---------------------------------------------------------------------------
def validate_sources_untouched() -> None:
    """Week 5 consumes the analysis. It must not have rewritten any of it."""
    section("2. Audited analytical sources unmodified by the web build")
    manifest = load_json(WEB_DATA_DIR / WEB_FILES["manifest"])
    recorded = manifest.get("analysis_source", {}).get("files", {})
    check(bool(recorded), "web manifest records its analysis sources with content hashes")

    for name, entry in sorted(recorded.items()):
        path = cfg.REPO_ROOT / entry["path"]
        if not path.exists():
            check(False, f"recorded source still present: {entry['path']}")
            continue
        actual = content_hash(path)
        recorded = entry["sha256_lf_normalised"]
        check(actual == recorded,
              f"{entry['path']} unchanged since the web build "
              f"({actual[:12]} vs {recorded[:12]})")

    for name in ("not_recomputed",):
        check(bool(manifest.get(name)), f"web manifest records {name}")


# ---------------------------------------------------------------------------
# 3. city metrics agree with the audited summary
# ---------------------------------------------------------------------------
def validate_city() -> dict:
    section("3. City metrics match data/processed/city_access_summary.json")
    web = load_json(WEB_DATA_DIR / WEB_FILES["city_summary"])
    audited = load_json(cfg.CITY_ACCESS_SUMMARY_FILE)

    for key, tol in (
        ("analysis_population", POP_TOL),
        ("metro_access_population", POP_TOL),
        ("bus_only_population", POP_TOL),
        ("underserved_population", POP_TOL),
        ("combined_walk_access_population", POP_TOL),
        ("metro_access_pct", PCT_TOL),
        ("bus_only_pct", PCT_TOL),
        ("underserved_pct", PCT_TOL),
        ("combined_walk_access_pct", PCT_TOL),
    ):
        check(abs(float(web[key]) - float(audited[key])) <= tol,
              f"{key} matches the audited summary ({web[key]!r})")

    check(abs(float(web["analysis_population"]) - 3_212_200) <= POP_TOL,
          f"analysis population is 3,212,200 (got {web['analysis_population']:,.4f})")
    check(web["walking_speed_kmh"] == cfg.MAIN_WALK_SPEED_KMH,
          f"walking speed is {cfg.MAIN_WALK_SPEED_KMH} km/h")
    check(web["walking_time_seconds"] == cfg.WALK_TIME_LIMIT_SECONDS,
          f"threshold is {cfg.WALK_TIME_LIMIT_SECONDS} seconds")
    check(abs(float(web["distance_budget_m"]) - cfg.walk_budget_m(cfg.MAIN_WALK_SPEED_KMH)) < 1e-9,
          "distance budget is 800 m")
    check(web["snapping_method"] == "edge-aware", "snapping method is edge-aware")
    check(web["analysis_district_count"] == cfg.EXPECTED_ANALYSIS_DISTRICTS,
          f"district count is {cfg.EXPECTED_ANALYSIS_DISTRICTS}")

    total = web["metro_access_pct"] + web["bus_only_pct"] + web["underserved_pct"]
    check(abs(total - 100.0) <= 1e-6, f"city percentages partition 100% (got {total:.10f})")

    for key in ("metro_access", "bus_only", "underserved"):
        check(bool(web.get("definitions", {}).get(key)),
              f"city summary carries a definition for {key}")
    check("estimate" in str(web.get("estimate_note", "")).lower(),
          "city summary states these are model estimates")
    check("display layer" in str(web.get("display_layer_note", "")).lower(),
          "city summary carries the display-layer caveat")

    print(f"    metro {web['metro_access_pct']:.6f}%   bus-only {web['bus_only_pct']:.6f}%   "
          f"underserved {web['underserved_pct']:.6f}%")
    return web


# ---------------------------------------------------------------------------
# 4. districts
# ---------------------------------------------------------------------------
REQUIRED_DISTRICT_FIELDS = [
    "district_name", "label", "official_population",
    "metro_access_population", "metro_access_pct",
    "bus_only_population", "bus_only_pct",
    "underserved_population", "underserved_pct",
    "combined_walk_access_pct", "area_km2", "population_density_per_km2",
    "metro_stations_in_district", "metro_access_points_in_district",
    "bus_stops_in_district", "bazaars_in_district",
    "min_cell_metro_distance_m", "min_cell_metro_margin_m",
]


def validate_districts(city: dict) -> None:
    section("4. District features match data/processed/district_access_metrics.csv")
    web = load_json(WEB_DATA_DIR / WEB_FILES["districts"])
    features = web["features"]
    audited = pd.read_csv(cfg.DISTRICT_ACCESS_METRICS_FILE).set_index("district_name")

    check(web.get("type") == "FeatureCollection", "districts file is a FeatureCollection")
    check(len(features) == cfg.EXPECTED_ANALYSIS_DISTRICTS,
          f"exactly {cfg.EXPECTED_ANALYSIS_DISTRICTS} analytical district features "
          f"(got {len(features)})")

    names = [f["properties"]["district_name"] for f in features]
    check(len(set(names)) == len(names), "district names unique")
    check(set(names) == set(audited.index), "district names match the audited table")
    check(EXCLUDED_DISTRICT not in names,
          f"'{EXCLUDED_DISTRICT}' is absent from the analytical districts")
    check(not any(EXCLUDED_DISTRICT.lower() in n.lower() for n in names),
          "no Yangi Toshkent feature under any spelling")

    missing_fields = set()
    worst = 0.0
    for f in features:
        p = f["properties"]
        missing_fields |= {k for k in REQUIRED_DISTRICT_FIELDS if k not in p}
        row = audited.loc[p["district_name"]]
        for key in REQUIRED_DISTRICT_FIELDS:
            if key in ("district_name", "label") or key not in row.index:
                continue
            worst = max(worst, abs(float(p[key]) - float(row[key])))
    check(not missing_fields, f"every district carries the required fields "
                              f"(missing: {sorted(missing_fields) or 'none'})")
    check(worst <= 1e-9, f"every district metric equals the audited value "
                         f"(worst difference {worst:.3e})")

    # A number serialised as a string would reach the browser quoted and break
    # every format and comparison downstream, silently.
    numeric_fields = [k for k in REQUIRED_DISTRICT_FIELDS
                      if k not in ("district_name", "label")]
    stringy = sorted({
        key for f in features for key in numeric_fields
        if not isinstance(f["properties"].get(key), (int, float))
        or isinstance(f["properties"].get(key), bool)
    })
    check(not stringy,
          f"every numeric district field is a JSON number, not a string "
          f"(offenders: {stringy or 'none'})")

    pct_worst = 0.0
    neg = []
    for f in features:
        p = f["properties"]
        total = p["metro_access_pct"] + p["bus_only_pct"] + p["underserved_pct"]
        pct_worst = max(pct_worst, abs(total - 100.0))
        if min(p["metro_access_pct"], p["bus_only_pct"], p["underserved_pct"],
               p["official_population"]) < 0:
            neg.append(p["district_name"])
    check(pct_worst <= 1e-6,
          f"each district's three shares partition 100% (worst drift {pct_worst:.3e})")
    check(not neg, f"no negative district values (offenders: {neg or 'none'})")

    populations = sum(f["properties"]["official_population"] for f in features)
    check(abs(populations - float(city["analysis_population"])) <= 1e-6,
          f"district populations sum to the city denominator ({populations:,.4f})")

    geom_ok = all(shape(f["geometry"]).is_valid and not shape(f["geometry"]).is_empty
                  for f in features)
    check(geom_ok, "every district geometry is valid and non-empty")

    ranked = sorted(features, key=lambda f: -f["properties"]["metro_access_pct"])
    print("    ranked by metro access (derived from the file, not hard-coded):")
    for f in ranked:
        p = f["properties"]
        print(f"      {p['label']:18s} {p['metro_access_pct']:6.2f}%   "
              f"bus-only {p['bus_only_pct']:6.2f}%   underserved {p['underserved_pct']:6.2f}%")


# ---------------------------------------------------------------------------
# 5. display layers
# ---------------------------------------------------------------------------
def validate_display_layers() -> dict:
    section("5. Display layers")
    counts: dict[str, int] = {}

    iso = load_json(WEB_DATA_DIR / WEB_FILES["metro_isochrone"])
    counts["metro_isochrone"] = len(iso["features"])
    check(len(iso["features"]) > 0, "metro isochrone is non-empty")
    geoms = [shape(f["geometry"]) for f in iso["features"]]
    check(all(g.is_valid for g in geoms), "metro isochrone geometry is valid")
    check(all(not g.is_empty for g in geoms), "metro isochrone geometry is not empty")
    check(all(str(f["properties"].get("role")) == "display_only" for f in iso["features"]),
          "metro isochrone is labelled display_only")
    check(all("polygon intersection" in str(f["properties"].get("note", ""))
              for f in iso["features"]),
          "metro isochrone carries the polygon-intersection caveat")

    access = load_json(WEB_DATA_DIR / WEB_FILES["metro_access_points"])
    counts["metro_access_points"] = len(access["features"])
    audited_access = pd.read_csv(cfg.METRO_ACCESS_POINTS_FILE)
    check(len(access["features"]) == EXPECTED_ACCESS_POINTS,
          f"{EXPECTED_ACCESS_POINTS} metro access points (got {len(access['features'])})")
    check(len(access["features"]) == len(audited_access),
          "access-point count matches the audited CSV")
    types = pd.Series([f["properties"]["access_type"] for f in access["features"]])
    check(int((types == "entrance").sum()) == EXPECTED_ENTRANCES,
          f"{EXPECTED_ENTRANCES} mapped entrances (got {int((types == 'entrance').sum())})")
    check(int((types == "station_fallback").sum()) == EXPECTED_FALLBACKS,
          f"{EXPECTED_FALLBACKS} station fallbacks "
          f"(got {int((types == 'station_fallback').sum())})")
    check(all(f["properties"].get("kind_label") for f in access["features"]),
          "every access point carries a human-readable kind label")
    fallbacks = [f for f in access["features"]
                 if f["properties"]["access_type"] == "station_fallback"]
    check(all("No mapped entrance" in str(f["properties"].get("detail", ""))
              for f in fallbacks),
          "fallbacks are described as fallbacks, not as mapped entrances")

    for key, expected, label in (
        ("metro_stations", EXPECTED_METRO_STATIONS, "metro stations"),
        ("bus_stops", EXPECTED_BUS_STOPS, "bus stops"),
        ("bazaars", EXPECTED_BAZAARS, "bazaars"),
    ):
        layer = load_json(WEB_DATA_DIR / WEB_FILES[key])
        counts[key] = len(layer["features"])
        check(len(layer["features"]) == expected,
              f"{label}: {expected} features (got {len(layer['features'])})")
        check(all(f["geometry"]["type"] == "Point" for f in layer["features"]),
              f"{label} are all points")

    density = load_json(WEB_DATA_DIR / WEB_FILES["population_density"])
    features = density["features"]
    counts["population_density"] = len(features)
    check(len(features) > 0, f"population-density layer is non-empty ({len(features)} bins)")
    values = [f["properties"]["density_per_km2"] for f in features]
    pops = [f["properties"]["population"] for f in features]
    check(all(math.isfinite(v) for v in values), "all density values finite")
    check(all(v >= 0 for v in values), "all density values non-negative")
    check(all(math.isfinite(p) and p > 0 for p in pops),
          "all binned populations finite and positive (zero bins removed)")
    total = sum(pops)
    check(abs(total - 3_212_200) <= 1.0,
          f"binned population reproduces the audited total ({total:,.3f})")
    check(len(features) < 20000,
          f"population-density layer is a compact display grid ({len(features)} features)")
    size = cfg.file_size_bytes(WEB_DATA_DIR / WEB_FILES["population_density"])
    check(size < 1_500_000,
          f"population-density file stays light ({cfg.human_size(size)})", critical=False)
    print(f"    density bins {len(features):,}  people {total:,.0f}  "
          f"max {max(values):,.0f}/km²")
    return counts


# ---------------------------------------------------------------------------
# 6. web manifest
# ---------------------------------------------------------------------------
def validate_manifest(counts: dict, city: dict) -> None:
    section("6. Web data manifest")
    manifest = load_json(WEB_DATA_DIR / WEB_FILES["manifest"])
    layers = manifest.get("layers", {})

    check(bool(layers), "manifest records its layers")
    for key, expected in counts.items():
        entry = layers.get(key, {})
        check(entry.get("features") == expected,
              f"manifest feature count for {key} matches the file "
              f"({entry.get('features')} vs {expected})")
    check(layers.get("districts", {}).get("features") == cfg.EXPECTED_ANALYSIS_DISTRICTS,
          f"manifest records {cfg.EXPECTED_ANALYSIS_DISTRICTS} district features")

    for key, expected_role in (
        ("city_summary", "analytical"), ("districts", "analytical"),
        ("metro_isochrone", "display_only"), ("metro_access_points", "display_only"),
        ("metro_stations", "display_only"), ("bus_stops", "display_only"),
        ("bazaars", "display_only"), ("population_density", "display_only"),
    ):
        check(layers.get(key, {}).get("role") == expected_role,
              f"manifest labels {key} as {expected_role}")

    for key, entry in layers.items():
        path = WEB_DATA_DIR / entry["file"]
        check(path.exists(), f"manifest file exists: site/data/{entry['file']}")
        if path.exists() and entry.get("bytes") is not None:
            check(entry["bytes"] == path.stat().st_size,
                  f"manifest byte count for {key} matches the file "
                  f"({entry['bytes']} vs {path.stat().st_size})")

    params = manifest.get("analysis_parameters", {})
    check(abs(float(params.get("analysis_population", 0)) -
              float(city["analysis_population"])) <= POP_TOL,
          "manifest analysis population matches the city summary")
    check(params.get("snapping_method") == "edge-aware",
          "manifest records the edge-aware snapping method")
    check(params.get("district_count") == cfg.EXPECTED_ANALYSIS_DISTRICTS,
          f"manifest records {cfg.EXPECTED_ANALYSIS_DISTRICTS} districts")

    # Look for an actual timestamp value or key, not for the word - the manifest
    # legitimately explains that it records none.
    text = (WEB_DATA_DIR / WEB_FILES["manifest"]).read_text(encoding="utf-8")
    iso_like = re.findall(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", text)
    timestamp_keys = re.findall(r'"(generated_at\w*|timestamp\w*|built_at\w*)"\s*:', text)
    check(not iso_like and not timestamp_keys,
          f"manifest carries no timestamp value or key, so the build stays "
          f"byte-deterministic (found {iso_like + timestamp_keys or 'none'})")

    density_layer = layers.get("population_density", {})
    check(float(density_layer.get("bin_size_m", 0)) > 0,
          f"manifest records the density bin size ({density_layer.get('bin_size_m')} m)")


# ---------------------------------------------------------------------------
# 7. the page reads its numbers from JSON, and builds its DOM safely
# ---------------------------------------------------------------------------
# Any of these appearing literally in the application source would mean a
# headline figure was typed in rather than read from site/data at runtime.
FORBIDDEN_LITERALS = [
    "3212200", "3,212,200", "3212200.0",
    "435689", "435,690", "435,689",
    "2314112", "2,314,113", "2,314,112",
    "462397", "462,397",
    "13.56", "13.6%", "72.04", "72.0%", "14.39", "14.4%", "85.60", "85.6%",
    "24.89", "23.07", "95.17", "819.7",
]


def validate_no_hardcoded_metrics() -> None:
    section("7. Figures come from JSON; DOM is built safely")
    sources = js_sources()
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")

    for name, text in {**sources, "index.html": html}.items():
        found = sorted({lit for lit in FORBIDDEN_LITERALS if lit in text})
        check(not found, f"{name} hard-codes no city or district metric "
                         f"(found: {found or 'none'})")

    joined = "\n".join(sources.values())

    # --- injection surface -------------------------------------------------
    # Every label the interface shows can come from OpenStreetMap, which is
    # world-editable. Assigning such a string into markup is the defect the
    # previous implementation carried; these checks assert it cannot return.
    unsafe = []
    for name, text in sources.items():
        for pattern, label in (
            (r"\.innerHTML\s*=", "innerHTML assignment"),
            (r"\.outerHTML\s*=", "outerHTML assignment"),
            (r"insertAdjacentHTML", "insertAdjacentHTML"),
            (r"document\.write", "document.write"),
            (r"\.html\s*\(", "d3 .html()"),
            (r"setHTML\s*\(", "maplibre setHTML()"),
        ):
            if re.search(pattern, text):
                unsafe.append(f"{name}: {label}")
    check(not unsafe,
          f"no markup-from-string path in the application source "
          f"(found: {unsafe or 'none'})")

    check("textContent" in joined, "text reaches the DOM through textContent")
    check("setDOMContent" in joined,
          "map popups are built as DOM nodes, not from an HTML string")
    check("replaceChildren" in joined, "panels are replaced as nodes, not as markup")

    # --- the libraries are actually used for what the design claims ---------
    check("maplibregl.Map" in joined, "MapLibre GL JS renders the map")
    check("new maplibregl.AttributionControl" in joined,
          "basemap attribution control is added, not suppressed")
    check("openfreemap.org" in joined, "a real basemap style is loaded")
    check("d3.select" in joined and "scaleLinear" in joined,
          "D3 drives the analytical chart")
    check("d3.scaleLinear" in sources.get("ranking.js", ""),
          "the ranked dot plot is a D3 chart")

    # --- genuine map controls ---------------------------------------------
    for element_id, label in (
        ("map", "map container"),
        ("search-input", "search input"),
        ("search-results", "search results list"),
        ("zoom-in", "zoom in control"),
        ("zoom-out", "zoom out control"),
        ("zoom-reset", "reset/fit control"),
        ("layers-toggle", "layer menu control"),
        ("ranking", "ranking container"),
        ("context-body", "context panel"),
        ("method-dialog", "method dialog"),
    ):
        check(f'id="{element_id}"' in html, f"{label} exists in the page")

    for handler in ("zoom-in", "zoom-out", "zoom-reset"):
        check(f"getElementById('{handler}')" in joined,
              f"{handler} is wired to real behaviour, not a dead control")
    check("fitBounds" in joined and "flyTo" in joined,
          "the map really moves: fitBounds and flyTo are used")
    check("getClusterExpansionZoom" in joined, "bus clusters expand on click")
    check("cluster: true" in joined, "the 2,163 bus stops are clustered, not all drawn")

    # --- one shared selection state ---------------------------------------
    check("state.js" in joined or "from './state.js'" in joined,
          "a single shared state module exists")
    for consumer in ("map.js", "ranking.js", "ui.js"):
        check("state.js" in sources.get(consumer, ""),
              f"{consumer} reads the shared selection state")
    check("selectedDistrict" in sources.get("map.js", "")
          and "selectedDistrict" in sources.get("ranking.js", ""),
          "map and ranking share the same district selection")
    check("setFeatureState" in sources.get("map.js", ""),
          "map selection uses MapLibre feature-state")

    # --- search is local and driven by the real data ----------------------
    ui = sources.get("ui.js", "")
    check("data.stations.features" in ui and "index.ranked" in ui,
          "search is built from the loaded district and station data")
    check("geocod" not in ui.lower(), "search needs no external geocoding service")

    # --- accessibility: no contradictory roles on the interactive chart ----
    ranking = sources.get("ranking.js", "")
    check("'role', 'img'" not in ranking and '"role", "img"' not in ranking,
          "the interactive chart root is not role=img")
    check("'role', 'list'" in ranking, "the chart root uses list semantics")
    check("'role', 'listitem'" in ranking, "chart rows are list items")
    check("'role', 'button'" in ranking, "chart rows expose a real control role")
    check("role=\"application\"" not in html and "'role', 'application'" not in joined,
          "role=application is not used")
    check('aria-live' in html, "a live region announces selection changes")
    check("<button" in html, "controls are real buttons, not clickable divs")
    check('aria-pressed' in html or 'aria-pressed' in joined,
          "toggle state is exposed to assistive technology")

    check("polygon intersection" in ui or "display_layer_note" in ui,
          "the display-layer caveat is surfaced in the interface")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 74)
    print("Week 5 interim prototype - validation")
    print("=" * 74)

    if not validate_files():
        section("Summary")
        print(f"  critical: {len(CRITICAL)}")
        print("\nVALIDATION FAILED - run scripts/build_web_data.py first")
        return 1

    validate_sources_untouched()
    city = validate_city()
    validate_districts(city)
    counts = validate_display_layers()
    validate_manifest(counts, city)
    validate_no_hardcoded_metrics()

    section("Summary")
    print(f"  passed  : {len(PASSED)}")
    print(f"  warnings: {len(WARNINGS)}")
    print(f"  critical: {len(CRITICAL)}")
    for item in WARNINGS:
        print(f"    WARN  {item}")
    for item in CRITICAL:
        print(f"    FAIL  {item}")

    if CRITICAL:
        print("\nVALIDATION FAILED")
        return 1
    print("\nVALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
