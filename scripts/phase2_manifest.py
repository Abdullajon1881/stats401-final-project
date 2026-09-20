"""Deterministic helpers for the additive Phase 2 source manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import config as cfg

HASH_BASIS_CANONICAL_TEXT = "canonical_utf8_lf"


def dump_json_text(payload: Any) -> str:
    """Serialize Phase 2 JSON with this project's fixed formatting."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def write_json_lf(path: Path, payload: Any) -> None:
    """Write Phase 2A JSON as canonical UTF-8 bytes with LF newlines.

    ``Path.write_text`` opens the file in text mode, so on Windows every
    newline is translated to CRLF while Git stores the file with LF. Hashing a
    text-mode write therefore records a representation that no LF checkout can
    reproduce. Writing bytes keeps the file identical on every platform.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dump_json_text(payload).encode("utf-8"))


def canonical_utf8_lf_bytes(path: Path) -> bytes:
    """Return a checkout-independent byte image of a tracked UTF-8 text file.

    Git may store a tracked text file with LF and hand Windows a CRLF working
    copy, so raw filesystem bytes are not a stable identity for it. Collapsing
    CRLF to LF makes both representations hash alike while still reacting to
    any real content change.
    """
    raw = path.read_bytes()
    normalized = raw.decode("utf-8").replace("\r\n", "\n")
    if "\r" in normalized:
        raise ValueError(
            f"{path.name} contains a bare CR; refusing to normalize it silently "
            "because that byte is content, not a line ending"
        )
    return normalized.encode("utf-8")


def canonical_utf8_lf_sha256(path: Path) -> str:
    """SHA-256 of the canonical UTF-8 LF image of a tracked text file."""
    return hashlib.sha256(canonical_utf8_lf_bytes(path)).hexdigest()


def canonical_provenance(path: Path) -> dict[str, Any]:
    """Describe a tracked text file by its canonical UTF-8 LF bytes.

    ``sha256`` and ``size_bytes`` always describe the same bytes, so a record
    can never pair a canonical digest with a raw CRLF size.
    """
    payload = canonical_utf8_lf_bytes(path)
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "hash_basis": HASH_BASIS_CANONICAL_TEXT,
    }


def load_manifest() -> dict[str, Any]:
    if not cfg.PHASE2_SOURCE_MANIFEST_PATH.exists():
        return {
            "schema_version": 1,
            "phase": "Phase 2A temporal data foundation",
        }
    return json.loads(cfg.PHASE2_SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))


def update_manifest(section: str, value: Any) -> None:
    """Replace one manifest section and write byte-stable formatted JSON."""
    manifest = load_manifest()
    manifest[section] = value
    write_json_lf(cfg.PHASE2_SOURCE_MANIFEST_PATH, manifest)
