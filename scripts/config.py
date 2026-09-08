"""Shared paths, constants and small helpers for the Week 3 data foundation.

Everything that both acquire_data.py and validate_data.py need to agree on lives
here so the two scripts cannot drift apart.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# --- Repository layout -------------------------------------------------------
# All paths are derived from this file's location, so the scripts work from the
# repository root regardless of the machine they run on.
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
EXTERNAL_DIR = DATA_DIR / "external"  # gitignored: large / rebuildable files
RAW_DIR = DATA_DIR / "raw"            # gitignored: untouched source downloads
DOCS_DIR = REPO_ROOT / "docs"
OSM_CACHE_DIR = EXTERNAL_DIR / "osm_cache"
MANIFEST_PATH = DATA_DIR / "source_manifest.json"

# --- Coordinate reference systems -------------------------------------------
# Storage/interchange CRS. GeoJSON is defined in WGS84 (RFC 7946) and D3 consumes
# lon/lat directly, so every processed .geojson is written in EPSG:4326.
GEOGRAPHIC_CRS = "EPSG:4326"

# Metric CRS for every distance/area computation. Tashkent sits at ~69.24 deg E,
# which is 0.24 deg from the UTM zone 42N central meridian (69 deg E), so scale
# distortion is negligible across the whole city. Verified in acquire_data.py.
METRIC_CRS = "EPSG:32642"  # WGS 84 / UTM zone 42N

# --- Study area --------------------------------------------------------------
TASHKENT_CITY_OSM_RELATION = 2216724
# Buffer applied to the city boundary when downloading the pedestrian network so
# that walking routes near the city edge are not artificially truncated.
NETWORK_BUFFER_M = 1000

# --- Official statistics -----------------------------------------------------
# SIAT dataset 3890 = "Permanent population (city)", code 2.01.02.0056.
# Tashkent city has zero rural population, so this urban series equals the total
# population for the city and every one of its districts (proved in acquire_data).
SIAT_DATASET_ID = 3890
SIAT_LANDING_URL = f"https://siat.stat.uz/data/{SIAT_DATASET_ID}/?lang=en"
SIAT_DOWNLOAD_API = (
    f"https://api.siat.stat.uz/sdmx/{SIAT_DATASET_ID}/table/download/?download_format=csv"
)
SIAT_RURAL_DATASET_ID = 3891  # used only to verify Tashkent rural population == 0
SIAT_RURAL_DOWNLOAD_API = (
    f"https://api.siat.stat.uz/sdmx/{SIAT_RURAL_DATASET_ID}/table/download/?download_format=csv"
)
# SOATO prefix for Tashkent city; the 12 district rows extend it with 3 digits.
TASHKENT_SOATO = "1726"
SIAT_REFERENCE_PERIOD = "2026-Q2"
SIAT_UNITS = "thousand people"

# --- WorldPop ----------------------------------------------------------------
WORLDPOP_YEAR = 2026  # chosen to match SIAT_REFERENCE_PERIOD
WORLDPOP_RELEASE = "R2025A"
WORLDPOP_PRODUCT = "Global_2015_2030 constrained, 100m, individual countries"
WORLDPOP_FILENAME = f"uzb_pop_{WORLDPOP_YEAR}_CN_100m_{WORLDPOP_RELEASE}_v1.tif"
WORLDPOP_URL = (
    f"https://data.worldpop.org/GIS/Population/Global_2015_2030/{WORLDPOP_RELEASE}/"
    f"{WORLDPOP_YEAR}/UZB/v1/100m/constrained/{WORLDPOP_FILENAME}"
)
WORLDPOP_LANDING = "https://hub.worldpop.org/geodata/summary?id=76048"
WORLDPOP_LICENCE_URL = "https://hub.worldpop.org/data/licence.txt"
WORLDPOP_DOI = "10.5258/SOTON/WP00839"
# WorldPop's own release statement calls R2025A an alpha product. Recorded so the
# manifest never presents this raster as settled ground truth.
WORLDPOP_RELEASE_STATEMENT_URL = (
    "https://data.worldpop.org/repo/prj/Global_2015_2030/R2025A/doc/"
    "Global2_Release_Statement_R2025A_v1.pdf"
)
WORLDPOP_RELEASE_STATUS = (
    "alpha. The official release statement (worldpop.org, September 2025) says: "
    "\"The dataset currently represents an alpha version (R2025A) public release "
    "product and may change over the coming year as improvements are made.\" "
    "Treat as candidate within-district spatial weights, not validated truth."
)

# --- Networking --------------------------------------------------------------
USER_AGENT = "stats401-final-project/1.0 (academic coursework; contact via GitHub)"
HTTP_TIMEOUT = 120        # seconds, per request
HTTP_RETRIES = 3
OVERPASS_TIMEOUT = 300

# The main Overpass instance enforces a small concurrent-slot limit and refuses
# connections when busy. Mirrors are tried in order so a transient outage does
# not fail the whole run. All of them serve the same OSM data.
# The walk graph needs far longer than a point query, and the bbox must be split
# into smaller Overpass requests or every mirror times out on it.
GRAPH_TIMEOUT = 600
MAX_OVERPASS_QUERY_AREA_M2 = 100_000_000  # 100 km2 per sub-query

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
]
# Mirror outages are usually transient, so the whole list is tried more than once
# before a run is abandoned.
OVERPASS_ROUNDS = 3

# --- Processed outputs -------------------------------------------------------
BOUNDARY_FILE = PROCESSED_DIR / "tashkent_boundary.geojson"
DISTRICTS_FILE = PROCESSED_DIR / "tashkent_districts.geojson"
METRO_STATIONS_FILE = PROCESSED_DIR / "metro_stations.geojson"
METRO_ENTRANCES_FILE = PROCESSED_DIR / "metro_entrances.geojson"
BUS_STOPS_FILE = PROCESSED_DIR / "bus_stops.geojson"
BAZAARS_FILE = PROCESSED_DIR / "bazaars.geojson"
SIAT_POPULATION_FILE = PROCESSED_DIR / "siat_district_population.csv"
DISTRICT_NAME_MAP_FILE = PROCESSED_DIR / "district_name_crosswalk.csv"
WORLDPOP_DIAGNOSTIC_FILE = PROCESSED_DIR / "worldpop_siat_diagnostic.csv"
WALK_GRAPH_FILE = EXTERNAL_DIR / "tashkent_walk_network.graphml"
WORLDPOP_RASTER = EXTERNAL_DIR / WORLDPOP_FILENAME

# The 12 districts that official SIAT statistics report for Tashkent city, keyed
# by SOATO code. Names are the SIAT English labels, trimmed. This is an explicit
# crosswalk to the OSM relation ids - deliberately not fuzzy string matching.
SIAT_TO_OSM_DISTRICT = {
    "1726262": {"siat_name_en": "Uchtepa district",        "osm_relation": 2434059},
    "1726264": {"siat_name_en": "Bektemir district",       "osm_relation": 2447560},
    "1726266": {"siat_name_en": "Yunusabad district",      "osm_relation": 2448072},
    "1726269": {"siat_name_en": "Mirzo Ulugbek district",  "osm_relation": 5620904},
    "1726273": {"siat_name_en": "Mirabad district",        "osm_relation": 2447634},
    "1726277": {"siat_name_en": "Shaykhantakhur district", "osm_relation": 2439529},
    "1726280": {"siat_name_en": "Almazar district",        "osm_relation": 2441651},
    "1726283": {"siat_name_en": "Sergeli district",        "osm_relation": 2447546},
    "1726287": {"siat_name_en": "Yakkasaray district",     "osm_relation": 2443769},
    "1726290": {"siat_name_en": "Yashnabad district",      "osm_relation": 1751444},
    "1726292": {"siat_name_en": "Yangikhayot district",    "osm_relation": 12030887},
    "1726294": {"siat_name_en": "Chilanzar district",      "osm_relation": 2441810},
}
EXPECTED_ANALYSIS_DISTRICTS = 12

# OSM relation 17389398 "Yangi Toshkent Tumani" (start_date=2024) is a member of
# the Tashkent city relation but has no SIAT population row. It is kept in the
# districts file with in_siat=False so the discrepancy stays visible instead of
# being silently dropped. See docs/data_sources.md.
UNMATCHED_OSM_DISTRICTS = {17389398: "Yangi Toshkent Tumani"}
EXPECTED_OSM_DISTRICTS = EXPECTED_ANALYSIS_DISTRICTS + len(UNMATCHED_OSM_DISTRICTS)


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """Return the SHA-256 hex digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_size_bytes(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def ensure_directories() -> None:
    for directory in (PROCESSED_DIR, EXTERNAL_DIR, RAW_DIR, OSM_CACHE_DIR, DOCS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
