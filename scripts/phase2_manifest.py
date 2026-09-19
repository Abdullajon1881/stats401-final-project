"""Deterministic helpers for the additive Phase 2 source manifest."""

from __future__ import annotations

import json
from typing import Any

import config as cfg


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
    cfg.PHASE2_SOURCE_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    cfg.PHASE2_SOURCE_MANIFEST_PATH.write_text(payload, encoding="utf-8")
