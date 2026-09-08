"""Small helpers shared by the acquisition and validation scripts."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

import config as cfg

# Free-text notes about data-quality issues, surfaced at the end of a run and
# written into data/source_manifest.json.
NOTES: list[str] = []


def log(message: str) -> None:
    print(message, flush=True)


def step(title: str) -> None:
    log("\n" + "=" * 74)
    log(title)
    log("=" * 74)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def http_get(url: str, *, stream: bool = False) -> requests.Response:
    """GET with an explicit timeout and bounded retries on transient failures."""
    last_error: Exception | None = None
    for attempt in range(1, cfg.HTTP_RETRIES + 1):
        try:
            response = requests.get(
                url,
                timeout=cfg.HTTP_TIMEOUT,
                stream=stream,
                headers={"User-Agent": cfg.USER_AGENT},
            )
            response.raise_for_status()
            return response
        except Exception as error:  # noqa: BLE001 - re-raised after the retry budget
            last_error = error
            wait = 2**attempt
            log(f"  ! attempt {attempt}/{cfg.HTTP_RETRIES} failed ({error}); retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"could not download {url}") from last_error


def overpass_failover(operation, description: str):
    """Run `operation(endpoint)` against each Overpass mirror until one succeeds.

    The public instance regularly refuses connections when its slots are full,
    which would otherwise abort an entire acquisition run.
    """
    last_error: Exception | None = None
    for round_number in range(1, cfg.OVERPASS_ROUNDS + 1):
        for endpoint in cfg.OVERPASS_ENDPOINTS:
            try:
                log(f"    [overpass] {description} via {endpoint} (round {round_number})")
                return operation(endpoint)
            except Exception as error:  # noqa: BLE001 - re-raised once rounds run out
                last_error = error
                log(f"    [overpass] {endpoint} failed: {type(error).__name__}: {error}")
                time.sleep(3)
        if round_number < cfg.OVERPASS_ROUNDS:
            wait = 20 * round_number
            log(f"    [overpass] all mirrors failed; waiting {wait}s before round "
                f"{round_number + 1}")
            time.sleep(wait)
    raise RuntimeError(
        f"all Overpass endpoints failed for {description} after "
        f"{cfg.OVERPASS_ROUNDS} rounds: {last_error}"
    ) from last_error


def overpass_post(query: str, description: str) -> dict:
    """POST a raw Overpass QL query, with mirror failover."""

    def run(endpoint: str) -> dict:
        response = requests.post(
            f"{endpoint}/interpreter",
            data={"data": query},
            timeout=cfg.OVERPASS_TIMEOUT,
            headers={"User-Agent": cfg.USER_AGENT},
        )
        response.raise_for_status()
        return response.json()

    result = overpass_failover(run, description)
    time.sleep(2)  # be polite between queries
    return result


def normalise_name(value) -> str | None:
    """Collapse internal whitespace and trim. Names are never translated."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def name_key(value) -> str:
    """Case- and punctuation-insensitive key used only for duplicate detection.

    Uzbek station names appear with several apostrophe characters (' vs U+2018
    vs U+02BB), so those are folded together before comparison. The original
    name string is always preserved in the output.
    """
    text = normalise_name(value) or ""
    text = text.lower()
    text = re.sub(r"[‘’ʻʼ'`´]", "", text)
    text = re.sub(r"[^a-z0-9Ѐ-ӿ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_latin_name(value) -> bool:
    """True when a name is written in Latin script.

    OSM carries some Tashkent stations twice, once with a Latin name and once
    with a Cyrillic one. When such a pair is merged this decides which of the
    two existing OSM names is kept. Nothing is transliterated or invented.
    """
    text = normalise_name(value)
    if not text:
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if "a" <= c.lower() <= "z")
    return latin >= len(letters) / 2


def to_points(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reduce every feature to one representative point.

    OSM models the same physical stop as a node, a platform way, or a small
    area. Catchment analysis needs one access point per feature, so non-point
    geometries become a representative point guaranteed to lie inside them.
    """
    out = gdf.copy()
    is_point = out.geometry.geom_type == "Point"
    out["geometry"] = out.geometry.where(is_point, out.geometry.representative_point())
    return out


def tag_series(gdf: gpd.GeoDataFrame, column: str) -> pd.Series:
    """Return an OSM tag column, or an all-NA column if the tag is absent."""
    if column in gdf.columns:
        return gdf[column]
    return pd.Series([pd.NA] * len(gdf), index=gdf.index, dtype="object")


def write_geojson(gdf: gpd.GeoDataFrame, path: Path, columns: list[str]) -> gpd.GeoDataFrame:
    """Write WGS84 GeoJSON with a fixed column order and no index column."""
    keep = [c for c in columns if c in gdf.columns]
    out = gdf[keep + ["geometry"]].copy()
    out = out.to_crs(cfg.GEOGRAPHIC_CRS).reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    out.to_file(path, driver="GeoJSON")
    return out


def local_file_record(path: Path, *, checksum: bool = False) -> dict:
    size = cfg.file_size_bytes(path)
    record = {
        "path": str(path.relative_to(cfg.REPO_ROOT)).replace("\\", "/"),
        "size_bytes": size,
        "size_human": cfg.human_size(size),
    }
    if checksum and path.exists():
        record["sha256"] = cfg.sha256_file(path)
    return record
