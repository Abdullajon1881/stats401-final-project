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

import csv
import json
import math
import re
import sys
from pathlib import Path

import pandas as pd
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
from pipeline_utils import enable_utf8_stdout  # noqa: E402
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
# 5b. the analytical/display boundary, checked on the features themselves
# ---------------------------------------------------------------------------
# Every display-only web layer, and the layers that must stay analytical. A
# GeoJSON file is fetched on its own by the map, so a manifest entry alone does
# not travel with it; the boundary has to be readable from any single file.
DISPLAY_ONLY_LAYERS = (
    "metro_isochrone",
    "metro_access_points",
    "metro_stations",
    "bus_stops",
    "bazaars",
    "population_density",
    "metro_lines",
    "analysis_mask",
    "metro_station_history",
    "healthcare_points",
    "education_points",
)
ANALYTICAL_LAYERS = ("districts",)


def validate_feature_provenance() -> None:
    section("5b. Display/analytical provenance, feature by feature")

    total_display = 0
    for key in DISPLAY_ONLY_LAYERS:
        layer = load_json(WEB_DATA_DIR / WEB_FILES[key])
        features = layer.get("features", [])
        check(len(features) > 0, f"{key}: layer is non-empty")

        missing_props = [i for i, f in enumerate(features) if not isinstance(f.get("properties"), dict)]
        check(not missing_props,
              f"{key}: every feature carries a properties object "
              f"(missing on {len(missing_props)} of {len(features)})")

        wrong = [
            (i, (f.get("properties") or {}).get("role"))
            for i, f in enumerate(features)
            if (f.get("properties") or {}).get("role") != "display_only"
        ]
        # Name the first offenders: "one feature is wrong" is not actionable.
        sample = "; ".join(f"#{i} role={r!r}" for i, r in wrong[:3])
        check(not wrong,
              f"{key}: all {len(features):,} features are role=display_only "
              f"({len(wrong)} not labelled{': ' + sample if sample else ''})")
        total_display += len(features)

    print(f"    {total_display:,} display features across "
          f"{len(DISPLAY_ONLY_LAYERS)} layers, every one labelled")

    # The other direction matters just as much: an analytical layer that picked
    # up the display label would quietly exempt itself from scrutiny.
    for key in ANALYTICAL_LAYERS:
        layer = load_json(WEB_DATA_DIR / WEB_FILES[key])
        features = layer.get("features", [])
        contaminated = [
            i for i, f in enumerate(features)
            if (f.get("properties") or {}).get("role") == "display_only"
        ]
        check(not contaminated,
              f"{key}: no analytical feature claims display_only "
              f"({len(contaminated)} of {len(features)} contaminated)")

    city = load_json(WEB_DATA_DIR / WEB_FILES["city_summary"])
    check(city.get("role") != "display_only",
          "city_summary is not labelled display_only")

    # Feature-level and manifest-level roles must tell the same story.
    manifest = load_json(WEB_DATA_DIR / WEB_FILES["manifest"])
    layers = manifest.get("layers", {})
    for key in DISPLAY_ONLY_LAYERS:
        check(layers.get(key, {}).get("role") == "display_only",
              f"{key}: manifest role agrees with the feature-level role")
    for key in ANALYTICAL_LAYERS + ("city_summary",):
        check(layers.get(key, {}).get("role") == "analytical",
              f"{key}: manifest records it as analytical")

    # The build must have no second way to make a display feature.
    build_src = (cfg.REPO_ROOT / "scripts" / "build_web_data.py").read_text(encoding="utf-8")
    check("def display_feature(" in build_src,
          "the build has a single constructor for display features")
    check('return feature(geometry, {**properties, "role": DISPLAY_ROLE}' in build_src,
          "that constructor stamps the role rather than trusting each call site")


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
# 8. selection state, combobox semantics, modal, and QA gating
# ---------------------------------------------------------------------------
def validate_state_and_a11y() -> None:
    section("8. Selection invariants, combobox, modal, QA gating")
    sources = js_sources()
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    state = sources.get("state.js", "")
    ui = sources.get("ui.js", "")
    app = sources.get("app.js", "")
    mapjs = sources.get("map.js", "")

    # --- the three selection modes are mutually exclusive by construction ---
    check("export function selectStation" in state,
          "state exposes a single station-selection path")
    check("export function selectDistrict" in state,
          "state exposes a single district-selection path")
    # The invariant must live in set(), not be re-implemented per caller.
    normaliser = re.search(
        r"export function set\(patch\)\s*\{(.+?)\n\}", state, re.S)
    body = normaliser.group(1) if normaliser else ""
    check("selectedStation" in body and "selectedDistrict = null" in body,
          "set() clears the district when a station is selected")
    check("selectedStation = null" in body,
          "set() clears the station when a district is selected")
    check("hoveredDistrict = null" in body,
          "set() clears the district hover when entering station mode")
    check("export function invariantHolds" in state,
          "the mode invariant is exposed for testing")

    # No caller may write the selection keys directly and bypass the invariant.
    direct = []
    for name, text in sources.items():
        if name == "state.js":
            continue
        for pattern in (r"set\(\s*\{[^}]*selectedStation",
                        r"set\(\s*\{[^}]*selectedDistrict"):
            if re.search(pattern, text):
                direct.append(name)
    check(not set(direct),
          f"no module sets a selection key directly around the invariant "
          f"(offenders: {sorted(set(direct)) or 'none'})")
    check("store.selectStation(" in ui, "the search selects stations through the state path")
    check("store.selectDistrict(" in ui, "the search selects districts through the state path")

    # --- station context and announcement -------------------------------
    check("function stationDetail" in ui, "a station context renderer exists")
    check("state.selectedStation" in ui,
          "the context panel branches on the selected station")
    check("Metro station" in ui, "the station context names what it is showing")
    check("selectedStation" in app and "metro station selected" in app,
          "the live region announces a station selection")
    check("district_name" in ui,
          "the station context can show its district when the data carries one")

    # --- combobox -------------------------------------------------------
    check('role="combobox"' in html, "the search input is a combobox")
    check('aria-controls="search-results"' in html, "the combobox controls its listbox")
    check('role="listbox"' in html, "the results are a listbox")
    check("aria-activedescendant" in ui,
          "the combobox names its active option with aria-activedescendant")
    check("removeAttribute('aria-activedescendant')" in ui,
          "aria-activedescendant is cleared, not only set")
    check("setAttribute('aria-selected'" in ui, "each option carries aria-selected")
    check("function setActiveOption" in ui and "function clearActiveOption" in ui,
          "one code path moves the visual and the semantic active option together")
    hide = re.search(r"function hideResults\(\)\s*\{(.+?)\n\}", ui, re.S)
    check(bool(hide) and "clearActiveOption()" in hide.group(1),
          "closing the results clears the active descendant")
    check("id: 'sr-opt-'" in ui or 'id: "sr-opt-"' in ui,
          "every rendered option gets a stable id to be named by")
    check("mouseover" in ui,
          "pointer hover updates the same active option, so ARIA cannot contradict it")

    # DOM focus must stay on the input. A rendered option that is natively
    # tabbable would be a second focus model, and Tab would walk every result
    # instead of leaving the search.
    option_render = re.search(
        r"role: 'option'.*?\}, \[", ui, re.S)
    check(bool(option_render) and "tabindex: '-1'" in option_render.group(0),
          "each rendered option is removed from the tab order (tabindex=-1)")
    check("focusout" in ui,
          "the popup closes when focus leaves the search, not only on outside click")
    check("aria-expanded" in ui,
          "the combobox reports whether its listbox is open")

    # --- modal ----------------------------------------------------------
    check("<dialog" in html, "the method window is a native <dialog>")
    check(re.search(r'<div[^>]*role="dialog"', html) is None,
          "no hand-rolled role=dialog element remains")
    check(re.search(r'<div[^>]*aria-modal', html) is None,
          "aria-modal is left to the native dialog rather than asserted on a div")
    check("showModal()" in ui, "the dialog is opened as a modal")
    check("dialog.close()" in ui or ".close()" in ui, "the dialog is closed natively")
    check("addEventListener('close'" in ui,
          "focus is restored from the dialog's own close event")
    check("::backdrop" in (SITE_DIR / "styles.css").read_text(encoding="utf-8"),
          "the native backdrop is styled")
    check("focusableWithin" in ui,
          "Tab is wrapped at both ends of the dialog")

    # --- QA gating ------------------------------------------------------
    check("qa" in app and "URLSearchParams" in app,
          "the QA hook is gated on a URL parameter")
    check(re.search(r"if\s*\(QA\)\s*\{", app) is not None,
          "window.__prototype is created only inside the QA guard")
    # There must be no unconditional publication anywhere.
    # A genuinely unguarded assignment sits at column zero; everything inside
    # the QA guard is indented, so indentation is the signal here.
    unconditional = []
    for name, text in sources.items():
        for line in text.splitlines():
            if line.startswith("window.__prototype") and "=" in line:
                unconditional.append(f"{name}: {line.strip()[:60]}")
    check(not unconditional,
          f"no module assigns window.__prototype unguarded at top level "
          f"(found: {unconditional or 'none'})")
    check("qaMode" in mapjs,
          "the map publishes its instance only when QA mode is on")
    check(re.search(r"if\s*\(qaMode\s*&&", mapjs) is not None,
          "the MapLibre instance is not reachable from the ordinary product")
    check("renderProbe" in app, "the hostile-text render probe exists for QA")


# ---------------------------------------------------------------------------
# 5c-5f. Phase A frontend data contract
# ---------------------------------------------------------------------------
# These checks do not reuse the build's CSV reader. Each committed cell is read
# back as text with the csv module and compared against the web value on the
# value's own terms, so a parsing or typing mistake in the build cannot certify
# itself.
TEMPORAL_YEARS = list(range(2015, 2027))
STANDARDIZED_2026_METRO_PCT = 10.028085007
EXPECTED_OPEN_STATIONS = {
    2015: 29, 2016: 29, 2017: 29, 2018: 29, 2019: 29,
    2020: 43, 2021: 43, 2022: 43,
    2023: 48,
    2024: 50, 2025: 50, 2026: 50,
}
EXPECTED_URBAN_CITY = {
    "population_total": 3212200.0,
    "population_cells": 65169,
    "healthcare_10min_pct": 46.891988202,
    "education_10min_pct": 72.482732459,
    "bazaar_10min_pct": 14.435025214,
    "healthcare_and_education_10min_pct": 43.653596349,
    "walk_network_km": 8946.844384,
    "healthcare_routing_sources": 436,
    "healthcare_facilities_in_analysis_districts": 432,
    "healthcare_facilities_outside_analysis_districts": 4,
    "education_routing_sources": 1215,
    "education_facilities_in_analysis_districts": 1190,
    "education_facilities_outside_analysis_districts": 25,
    "bazaar_routing_sources": 83,
    "bazaar_facilities_in_analysis_districts": 83,
}
FACILITY_CONTRACT = {
    "healthcare_points": {
        "source": cfg.HEALTHCARE_FACILITIES_FILE,
        "features": 436,
        "category_field": "facility_category",
        "categories": {"clinic": 230, "hospital": 206},
        "assignments": {"within": 432, "outside_analysis_districts": 4, "boundary_tie": 0},
    },
    "education_points": {
        "source": cfg.EDUCATION_FACILITIES_FILE,
        "features": 1215,
        "category_field": "education_category",
        "categories": {"school": 532, "college": 104, "university": 98, "kindergarten": 481},
        "assignments": {"within": 1190, "outside_analysis_districts": 25, "boundary_tie": 0},
    },
}
FACILITY_SHARED_FIELDS = ("facility_id", "name", "district_name", "district_assignment",
                          "osm_type", "osm_id", "representative_point_method")
STATION_HISTORY_FIELDS = (
    "station_id", "station_name_current", "station_name_historical", "line",
    "opening_date", "opening_year", "date_precision", "opening_batch_id",
    "district_name", "source_provider", "source_quality",
)
ANALYTICAL_CONTRACT = {
    "temporal_city": (cfg.PHASE2_ACCESS_CITY_FILE, 12),
    "temporal_district": (cfg.PHASE2_ACCESS_DISTRICT_FILE, 144),
    "temporal_events": (cfg.PHASE2_ACCESS_EVENTS_FILE, 3),
    "temporal_counterfactual": (cfg.PHASE2_ACCESS_COUNTERFACTUAL_FILE, 12),
    "urban_dimensions_city": (cfg.URBAN_DIMENSIONS_CITY_FILE, 1),
    "urban_dimensions_district": (cfg.URBAN_DIMENSIONS_DISTRICT_FILE, 12),
}
DISPLAY_CONTRACT = {
    "metro_station_history": (cfg.METRO_STATION_HISTORY_FILE, 50),
    "healthcare_points": (cfg.HEALTHCARE_FACILITIES_FILE, 436),
    "education_points": (cfg.EDUCATION_FACILITIES_FILE, 1215),
}
# Words that would mean the build invented a score or an ordering the audited
# analysis never produced.
FORBIDDEN_DERIVED_KEYS = ("composite", "rank", "score", "best_district", "walkability")


def read_source_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def cell_matches(web, text: str) -> bool:
    """True when a web value is exactly what the committed CSV text denotes."""
    if text == "":
        return web is None
    if isinstance(web, bool):
        return text == str(web)
    if isinstance(web, int):
        return re.fullmatch(r"-?\d+", text) is not None and int(text) == web
    if isinstance(web, float):
        try:
            return float(text) == web and math.isfinite(web)
        except ValueError:
            return False
    if isinstance(web, str):
        # A numeric cell must never reach the browser quoted.
        try:
            float(text)
            return False
        except ValueError:
            return web == text
    return False


def compare_records(label: str, web: list[dict], path: Path) -> None:
    columns, rows = read_source_csv(path)
    check(len(web) == len(rows), f"{label}: {len(web)} records for {len(rows)} source rows")
    check(all(list(r.keys()) == columns for r in web),
          f"{label}: every record carries exactly the {len(columns)} source columns, in order")
    bad = [
        f"row {i} {c}={r.get(c)!r} vs {row[c]!r}"
        for i, (r, row) in enumerate(zip(web, rows)) for c in columns
        if not cell_matches(r.get(c), row[c])
    ]
    check(not bad,
          f"{label}: every one of {len(rows) * len(columns):,} values equals the committed "
          f"CSV exactly, with its proper scalar type ({len(bad)} differ"
          f"{': ' + '; '.join(bad[:3]) if bad else ''})")


def load_contract(key: str) -> dict:
    return load_json(WEB_DATA_DIR / WEB_FILES[key])


def validate_contract_tables() -> dict:
    section("5c. Analytical tables: committed CSV -> typed JSON, value for value")
    counts: dict[str, int] = {}
    for key, (source, expected_rows) in ANALYTICAL_CONTRACT.items():
        payload = load_contract(key)
        check(payload.get("role") == "analytical", f"{key}: labelled analytical")
        check(payload.get("source") == str(source.relative_to(cfg.REPO_ROOT)).replace("\\", "/"),
              f"{key}: names its committed source ({payload.get('source')})")
        records = payload.get("records") if "records" in payload else [payload.get("record")]
        counts[key] = len(records)
        check(len(records) == expected_rows,
              f"{key}: {expected_rows} records (got {len(records)})")
        compare_records(key, records, source)
        keys = {k.lower() for r in records for k in r}
        invented = sorted(k for k in keys if any(w in k for w in FORBIDDEN_DERIVED_KEYS))
        check(not invented, f"{key}: no composite, rank or score field ({invented or 'none'})")

    city = load_contract("temporal_city")["records"]
    years = [r["year"] for r in city]
    check(years == TEMPORAL_YEARS and len(set(years)) == 12,
          "temporal city: one record per year, 2015 through 2026 in order")
    by_year = {r["year"]: r for r in city}
    got_2026 = by_year.get(2026, {}).get("metro_access_pct_standardized")
    check(got_2026 == STANDARDIZED_2026_METRO_PCT,
          f"temporal city: standardized 2026 metro access is exactly "
          f"{STANDARDIZED_2026_METRO_PCT} (got {got_2026!r})")
    headline = load_json(cfg.CITY_ACCESS_SUMMARY_FILE)["metro_access_pct"]
    check(got_2026 != headline,
          "temporal city: the standardized series is not the current headline metric")
    state_ok = [
        r["year"] for r in city
        if r["metro_state_id"] == f"metro_state_{r['open_station_count']}"
        and r["open_station_count"] == EXPECTED_OPEN_STATIONS[r["year"]]
    ]
    check(len(state_ok) == 12,
          f"temporal city: every year's metro_state_id and open_station_count agree with "
          f"the expected network state ({12 - len(state_ok)} disagree)")

    district = load_contract("temporal_district")["records"]
    grid = [(r["year"], r["district_name"]) for r in district]
    names = {n for _, n in grid}
    analysis_districts = set(pd.read_csv(cfg.DISTRICT_ACCESS_METRICS_FILE).district_name)
    check(len(set(grid)) == len(grid) == 144, "temporal district: 144 unique (year, district) keys")
    check(set(grid) == {(y, n) for y in TEMPORAL_YEARS for n in names},
          "temporal district: complete year x district grid")
    check(names == analysis_districts,
          f"temporal district: district universe is exactly the "
          f"{len(analysis_districts)} analysis districts")
    check(EXCLUDED_DISTRICT not in names, f"temporal district: '{EXCLUDED_DISTRICT}' absent")
    drift = [
        r["year"] for r in district
        if r["open_station_count"] != by_year[r["year"]]["open_station_count"]
        or r["metro_state_id"] != by_year[r["year"]]["metro_state_id"]
    ]
    check(not drift, f"temporal district: network state agrees with the city table "
                     f"every year ({len(drift)} disagree)")

    counter = load_contract("temporal_counterfactual")["records"]
    cyears = [r["year"] for r in counter]
    check(sorted(cyears) == TEMPORAL_YEARS and len(set(cyears)) == 12,
          "temporal counterfactual: 12 unique years, 2015-2026")
    events = load_contract("temporal_events")["records"]
    check(len(events) == 3 and all(r["year"] in TEMPORAL_YEARS for r in events),
          f"temporal events: 3 network-change events inside 2015-2026 "
          f"({[r['year'] for r in events]})")
    check("not causal inference" in load_contract("temporal_counterfactual").get("note", ""),
          "temporal counterfactual: described as descriptive decomposition, not causal")

    urban = load_contract("urban_dimensions_city")["record"]
    wrong = {k: urban.get(k) for k, v in EXPECTED_URBAN_CITY.items()
             if not (urban.get(k) == v and type(urban.get(k)) is type(v))}
    check(not wrong, f"urban city: every audited invariant holds exactly "
                     f"({wrong or 'all ' + str(len(EXPECTED_URBAN_CITY))})")
    udistrict = load_contract("urban_dimensions_district")["records"]
    unames = [r["district_name"] for r in udistrict]
    check(len(set(unames)) == 12 and set(unames) == analysis_districts,
          "urban district: 12 unique districts, exactly the analysis districts")
    check(len(udistrict[0]) == 34, f"urban district: full {len(udistrict[0])}-column record")
    return counts


def validate_station_history() -> int:
    section("5d. Historical station points (display only)")
    fc = load_contract("metro_station_history")
    features = fc["features"]
    columns, rows = read_source_csv(cfg.METRO_STATION_HISTORY_FILE)
    source = {r["station_id"]: r for r in rows}

    check(fc.get("type") == "FeatureCollection" and len(features) == 50,
          f"station history: 50 features (got {len(features)})")
    check(all(f["geometry"]["type"] == "Point" for f in features),
          "station history: Point geometry only - no line geometry, no service area")
    ids = [f["properties"]["station_id"] for f in features]
    check(len(set(ids)) == len(ids) and set(ids) == set(source),
          "station history: unique station IDs, exactly the committed set")
    coords = [f["geometry"]["coordinates"] for f in features]
    check(all(len(c) == 2 and all(isinstance(v, float) and math.isfinite(v) for v in c)
              and 68 < c[0] < 71 and 40 < c[1] < 42 for c in coords),
          "station history: every coordinate is a finite lon/lat pair over Tashkent")
    moved = [f["properties"]["station_id"] for f in features
             if f["geometry"]["coordinates"] != [
                 float(source[f["properties"]["station_id"]]["longitude"]),
                 float(source[f["properties"]["station_id"]]["latitude"])]]
    check(not moved, f"station history: every point is exactly the committed "
                     f"longitude/latitude ({len(moved)} moved)")
    bad = [
        f"{f['properties']['station_id']}.{k}"
        for f in features for k in STATION_HISTORY_FIELDS
        if not cell_matches(f["properties"].get(k), source[f["properties"]["station_id"]][k])
    ]
    check(not bad, f"station history: every carried property equals the committed CSV "
                   f"({bad[:3] or 'none differ'})")
    check(not any(k in f["properties"] for f in features
                  for k in ("source_url", "notes", "current_osm_id")),
          "station history: long notes, URLs and OSM ids are not shipped")

    open_by_year = {y: sum(1 for f in features if f["properties"]["opening_year"] <= y)
                    for y in TEMPORAL_YEARS}
    check(open_by_year == EXPECTED_OPEN_STATIONS,
          f"station history: open stations by year (opening_year <= year) "
          f"are {open_by_year}")
    temporal = {r["year"]: r["open_station_count"]
                for r in load_contract("temporal_city")["records"]}
    check(open_by_year == temporal,
          "station history: open-station counts agree with the temporal city table")
    states = load_json(cfg.PHASE2_ROUTING_STATES_FILE)["states"]
    mismatched = [
        y for state in states for y in state["years"]
        if sorted(f["properties"]["station_id"] for f in features
                  if f["properties"]["opening_year"] <= y)
        != sorted(state["active_station_ids"])
    ]
    check(not mismatched,
          f"station history: the stations open each year are exactly the audited routing "
          f"state's active station IDs ({mismatched or 'all 12 years agree'})")
    return len(features)


def validate_facility_points(key: str) -> int:
    spec = FACILITY_CONTRACT[key]
    section(f"5e. {key}: audited routing-proxy points (display only)")
    fc = load_contract(key)
    features = fc["features"]
    source = load_json(spec["source"])["features"]
    by_id = {s["properties"]["facility_id"]: s["properties"] for s in source}

    check(fc.get("type") == "FeatureCollection" and len(features) == spec["features"],
          f"{key}: {spec['features']} features (got {len(features)})")
    types = sorted({f["geometry"]["type"] for f in features})
    check(types == ["Point"], f"{key}: Point geometry only ({types})")
    ids = [f["properties"]["facility_id"] for f in features]
    check(len(set(ids)) == len(ids) and set(ids) == set(by_id),
          f"{key}: exactly the committed facility_id set, each once")

    # The point the browser draws must be the point accessibility was routed
    # from: equal as doubles, not merely close.
    drift = [
        i for i, f in enumerate(features)
        if f["geometry"]["coordinates"] != [by_id[ids[i]]["longitude"], by_id[ids[i]]["latitude"]]
    ]
    check(not drift,
          f"{key}: every coordinate equals the audited representative longitude/latitude "
          f"exactly ({len(drift)} drifted)")
    check(all(isinstance(v, float) and math.isfinite(v)
              for f in features for v in f["geometry"]["coordinates"]),
          f"{key}: every coordinate is a finite number")

    fields = FACILITY_SHARED_FIELDS + (spec["category_field"],)
    differs = [
        f"{f['properties']['facility_id']}.{k}"
        for f in features for k in fields
        if f["properties"].get(k) != by_id[f["properties"]["facility_id"]].get(k)
    ]
    check(not differs, f"{key}: every carried property equals the audited record "
                       f"({differs[:3] or 'none differ'})")

    props = [f["properties"] for f in features]
    categories = {c: sum(1 for p in props if p[spec["category_field"]] == c)
                  for c in spec["categories"]}
    check(categories == spec["categories"] and
          sum(categories.values()) == len(props),
          f"{key}: category counts {categories}")
    assignments = {a: sum(1 for p in props if p["district_assignment"] == a)
                   for a in spec["assignments"]}
    check(assignments == spec["assignments"] and
          sum(assignments.values()) == len(props),
          f"{key}: district-assignment counts {assignments}")
    outside = [p for p in props if p["district_assignment"] == "outside_analysis_districts"]
    check(all(p["district_name"] is None for p in outside),
          f"{key}: all {len(outside)} outside-analysis facilities carry district_name = null")
    inside_names = {p["district_name"] for p in props if p["district_assignment"] == "within"}
    analysis_districts = set(pd.read_csv(cfg.DISTRICT_ACCESS_METRICS_FILE).district_name)
    check(inside_names <= analysis_districts,
          f"{key}: facilities within the study area name only analysis districts")

    shipped = {k for p in props for k in p}
    internals = sorted(shipped & {"normalized_name", "geometry_assembly", "osm_relation_type",
                                  "amenity", "healthcare", "operator", "longitude", "latitude"})
    check(not internals, f"{key}: no dedupe or assembly internals shipped ({internals or 'none'})")

    source_bytes = spec["source"].stat().st_size
    web_bytes = (WEB_DATA_DIR / WEB_FILES[key]).stat().st_size
    reduction = (1 - web_bytes / source_bytes) * 100
    check(web_bytes < source_bytes * 0.5,
          f"{key}: browser layer is materially smaller than the source "
          f"({source_bytes:,} -> {web_bytes:,} bytes, {reduction:.2f}% smaller)")
    return len(features)


def validate_contract_manifest(counts: dict[str, int]) -> None:
    section("5f. Phase A manifest entries and source provenance")
    manifest = load_json(WEB_DATA_DIR / WEB_FILES["manifest"])
    layers = manifest.get("layers", {})
    recorded = manifest.get("analysis_source", {}).get("files", {})
    by_path = {entry["path"]: entry for entry in recorded.values()}
    phase2 = load_json(cfg.PHASE2_ANALYSIS_MANIFEST_PATH)
    phase2c = load_json(cfg.PHASE2C_MANIFEST_PATH)
    audited_hashes = {
        **{p: e["sha256"] for p, e in phase2.get("input_files", {}).items()},
        **{p: e["sha256"] for p, e in phase2.get("output_files", {}).items()},
        **{p: e["sha256"] for p, e in phase2c.get("output_files", {}).items()},
    }

    contract = {
        **{k: ("analytical", src) for k, (src, _) in ANALYTICAL_CONTRACT.items()},
        **{k: ("display_only", src) for k, (src, _) in DISPLAY_CONTRACT.items()},
    }
    for key, (role, source) in contract.items():
        entry = layers.get(key, {})
        src = str(source.relative_to(cfg.REPO_ROOT)).replace("\\", "/")
        path = WEB_DATA_DIR / WEB_FILES[key]
        check(entry.get("file") == WEB_FILES[key] and path.exists(),
              f"manifest {key}: records {WEB_FILES[key]}, which exists")
        check(entry.get("role") == role, f"manifest {key}: role {role}")
        check(entry.get("features") == counts[key],
              f"manifest {key}: {counts[key]} features/records")
        check(entry.get("bytes") == path.stat().st_size,
              f"manifest {key}: bytes exact ({entry.get('bytes')} vs {path.stat().st_size})")
        check(entry.get("source") == src, f"manifest {key}: source {src}")
        hashed = by_path.get(src, {}).get("sha256_lf_normalised")
        check(hashed is not None and hashed == content_hash(source),
              f"manifest {key}: source content hash recorded and current "
              f"({(hashed or 'missing')[:12]})")
        check(audited_hashes.get(src) == hashed,
              f"manifest {key}: source hash equals the Phase 2 audited manifest's "
              f"({(audited_hashes.get(src) or 'unrecorded')[:12]})")

    station = layers.get("metro_station_history", {})
    check({int(y): n for y, n in station.get("open_stations_by_year", {}).items()}
          == EXPECTED_OPEN_STATIONS,
          "manifest metro_station_history: open-station counts by year recorded correctly")
    for key, spec in FACILITY_CONTRACT.items():
        entry = layers.get(key, {})
        check(entry.get("source_bytes") == spec["source"].stat().st_size,
              f"manifest {key}: source byte count exact")
        check(entry.get("by_category") == spec["categories"],
              f"manifest {key}: category counts recorded")
        assigned = {k: v for k, v in spec["assignments"].items() if v}
        check(entry.get("by_district_assignment") == assigned,
              f"manifest {key}: district-assignment counts recorded")


def validate_contract() -> dict[str, int]:
    counts = validate_contract_tables()
    counts["metro_station_history"] = validate_station_history()
    for key in FACILITY_CONTRACT:
        counts[key] = validate_facility_points(key)
    validate_contract_manifest(counts)
    return counts


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
    validate_feature_provenance()
    counts.update(validate_contract())
    validate_manifest(counts, city)
    validate_no_hardcoded_metrics()
    validate_state_and_a11y()

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
    enable_utf8_stdout()
    raise SystemExit(main())
