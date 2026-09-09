"""Small helpers shared by the acquisition and validation scripts."""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

import config as cfg

# Data-quality notes, scoped to the source that produced them and keyed by a
# stable id.
#
# An earlier design appended free text to one global list and de-duplicated by
# string equality. Because these notes embed live counts ("231 of 2163 bus
# stops..."), a changed count produced a *different* string, so a partial rerun
# left the stale note sitting next to the new one and the manifest contradicted
# itself. Keying by (source, note_id) means a rerun of a source replaces its
# notes outright, while sources that were genuinely skipped keep theirs.
SOURCE_NOTES: dict[str, dict[str, str]] = {}


def add_note(source_key: str, note_id: str, text: str) -> None:
    """Record a data-quality note for `source_key` under a stable `note_id`."""
    SOURCE_NOTES.setdefault(source_key, {})[note_id] = text


def notes_for(source_key: str) -> list[dict[str, str]]:
    """Return this run's notes for one source, ordered by note id."""
    notes = SOURCE_NOTES.get(source_key, {})
    return [{"id": nid, "text": notes[nid]} for nid in sorted(notes)]


def reset_notes(source_key: str) -> None:
    """Drop any notes already collected for a source before it re-extracts."""
    SOURCE_NOTES.pop(source_key, None)


def enable_utf8_stdout() -> None:
    """Make this process's console able to print the names in the data.

    Uzbek place names ("Gʻafur Gʻulom") and units ("km²") sit outside the
    legacy Windows code pages, so a script that prints them dies with
    UnicodeEncodeError on a default `cmd` console even though everything it
    writes to disk is correct UTF-8. Reconfiguring the streams stops a run
    from failing over a progress line. Call it from a script's entry point
    only - importing a module should not reach into another program's stdout.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (ValueError, OSError):
            # A redirected or detached stream; log() still degrades on its own.
            pass


def log(message: str) -> None:
    """Print a progress line without letting the console's encoding abort a run.

    Uzbek place names carry characters (Gʻafur Gʻulom, Oʻzbekiston) that a
    Windows console running a legacy code page cannot encode, and an
    unhandled UnicodeEncodeError there would kill the pipeline over a progress
    message. Fall back to an escaped form so the run continues and the name is
    still legible; the data written to disk is always UTF-8 regardless.
    """
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(message.encode(encoding, "backslashreplace").decode(encoding),
              flush=True)


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


# Which mirror answered each Overpass query. Mirrors replicate OSM at slightly
# different lags, so two runs minutes apart can legitimately return different
# counts depending on who served them. Recording the endpoint makes a count
# difference between runs explainable instead of mysterious.
OVERPASS_LOG: list[dict[str, str]] = []


def last_overpass_endpoint() -> str | None:
    """The endpoint that served the most recent Overpass query."""
    return OVERPASS_LOG[-1]["endpoint"] if OVERPASS_LOG else None


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
                result = operation(endpoint)
                OVERPASS_LOG.append(
                    {"description": description, "endpoint": endpoint, "at_utc": utc_now()}
                )
                return result
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
