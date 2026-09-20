"""Deterministic helpers for Phase 2B temporal metro accessibility.

This module contains only small, testable transformations. Network loading,
edge-aware snapping and shortest paths remain authoritative in
``accessibility_utils.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import hashlib
import json

import numpy as np
import pandas as pd

import accessibility_utils as au


@dataclass(frozen=True)
class MetroState:
    """One distinct active-station source set within the analytical period."""

    state_id: str
    years: tuple[int, ...]
    active_station_ids: tuple[str, ...]

    @property
    def first_year(self) -> int:
        return self.years[0]

    @property
    def last_year(self) -> int:
        return self.years[-1]

    @property
    def open_station_count(self) -> int:
        return len(self.active_station_ids)


def derive_metro_states(
    stations: pd.DataFrame, years: tuple[int, ...]
) -> tuple[list[MetroState], dict[int, str]]:
    """Derive distinct nested source sets from station ``opening_year`` values."""
    required = {"station_id", "opening_year"}
    missing = sorted(required - set(stations.columns))
    if missing:
        raise ValueError(f"station history missing columns: {missing}")
    if stations.station_id.astype(str).duplicated().any():
        raise ValueError("station history contains duplicate station_id values")

    ordered = stations.assign(
        station_id=stations.station_id.astype(str),
        opening_year=pd.to_numeric(stations.opening_year, errors="raise").astype(int),
    ).sort_values("station_id", kind="stable")

    grouped: dict[tuple[str, ...], list[int]] = {}
    source_sets: list[tuple[str, ...]] = []
    for year in years:
        active = tuple(
            ordered.loc[ordered.opening_year <= year, "station_id"].tolist()
        )
        grouped.setdefault(active, []).append(int(year))
        source_sets.append(active)

    for previous, current in zip(source_sets, source_sets[1:]):
        if not set(previous).issubset(current):
            raise ValueError("metro source sets are not nested; a station disappears")

    states: list[MetroState] = []
    seen_ids: set[str] = set()
    for active, state_years in grouped.items():
        state_id = f"metro_state_{len(active)}"
        if state_id in seen_ids:
            raise ValueError(
                "different station source sets have the same count; count-based state "
                "IDs would not be unique"
            )
        seen_ids.add(state_id)
        states.append(MetroState(state_id, tuple(state_years), active))
    states.sort(key=lambda state: state.first_year)
    year_to_state = {
        year: state.state_id for state in states for year in state.years
    }
    return states, year_to_state


def subset_edge_snap(snap: au.EdgeSnap, indices: np.ndarray) -> au.EdgeSnap:
    """Return an ``EdgeSnap`` subset without recomputing any placement."""
    indices = np.asarray(indices, dtype=np.int64)
    return au.EdgeSnap(
        edge_index=snap.edge_index[indices],
        connector_m=snap.connector_m[indices],
        fraction=snap.fraction[indices],
        cost_to_u=snap.cost_to_u[indices],
        cost_to_v=snap.cost_to_v[indices],
        snapped_xy=snap.snapped_xy[indices],
    )


def weighted_access(
    population: np.ndarray, accessible: np.ndarray
) -> tuple[float, float, float]:
    """Return denominator, numerator and percent with annual missing excluded."""
    population = np.asarray(population, dtype=np.float64)
    accessible = np.asarray(accessible, dtype=bool)
    if population.shape != accessible.shape:
        raise ValueError("population and accessibility arrays must have the same shape")
    finite = np.isfinite(population)
    if np.any(population[finite] < 0):
        raise ValueError("finite population weights must be non-negative")
    denominator = float(population[finite].sum(dtype=np.float64))
    numerator = float(population[finite & accessible].sum(dtype=np.float64))
    percentage = float(100.0 * numerator / denominator) if denominator > 0 else float("nan")
    return denominator, numerator, percentage


def active_station_ids_sha256(station_ids: tuple[str, ...]) -> str:
    """Stable digest of an ordered source set."""
    payload = ("\n".join(station_ids) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def write_json_lf(path: Path, payload: object) -> None:
    """Write JSON as canonical UTF-8 bytes with LF newlines on every platform.

    ``Path.write_text`` opens the file in text mode, so on Windows every
    newline is translated to CRLF. Git stores these committed outputs with LF,
    so a manifest hashed from a text-mode write records a representation that
    no LF checkout can reproduce. Writing bytes keeps the hashed file
    byte-identical on Windows, macOS and Linux.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    path.write_bytes(text.encode("utf-8"))


def write_deterministic_npz(path: Path, arrays: list[tuple[str, np.ndarray]]) -> None:
    """Write an NPZ with stable member order, metadata and bytes.

    ``numpy.savez`` uses current ZIP timestamps. That is harmless for a cache,
    but its changing SHA would make the committed analysis manifest unstable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as archive:
        for name, value in arrays:
            buffer = BytesIO()
            np.save(buffer, np.asarray(value), allow_pickle=False)
            info = ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, buffer.getvalue())
