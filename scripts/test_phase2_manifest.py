"""Fast synthetic regression tests for Phase 2A provenance hashing.

    python scripts/test_phase2_manifest.py
    pytest scripts/test_phase2_manifest.py

No repository data and no network download is used.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase2_manifest as pm  # noqa: E402


def test_canonical_hash_ignores_checkout_newlines():
    body = '{\n  "cells": 67824,\n  "method": "union_valid_with_annual_missing"\n}\n'
    with tempfile.TemporaryDirectory() as directory:
        lf_path = Path(directory) / "lf.json"
        crlf_path = Path(directory) / "crlf.json"
        lf_path.write_bytes(body.encode("utf-8"))
        crlf_path.write_bytes(body.replace("\n", "\r\n").encode("utf-8"))

        lf = pm.canonical_provenance(lf_path)
        crlf = pm.canonical_provenance(crlf_path)

        assert crlf_path.read_bytes().count(b"\r\n") == 4, "fixture must really be CRLF"
        assert lf["sha256"] == crlf["sha256"], "canonical hash must ignore CRLF"
        assert lf["size_bytes"] == crlf["size_bytes"] == len(body)
        assert lf["hash_basis"] == pm.HASH_BASIS_CANONICAL_TEXT
    return f"CRLF and LF share canonical {lf['sha256'][:12]} and size {lf['size_bytes']}"


def test_content_change_still_changes_the_hash():
    with tempfile.TemporaryDirectory() as directory:
        original = Path(directory) / "original.json"
        changed = Path(directory) / "changed.json"
        original.write_bytes(b'{\n  "valid_in_all_years_cells": 64756\n}\n')
        changed.write_bytes(b'{\n  "valid_in_all_years_cells": 64757\n}\n')
        first = pm.canonical_utf8_lf_sha256(original)
        second = pm.canonical_utf8_lf_sha256(changed)
    assert first != second, "canonical hashing must react to a real content change"
    return "a one-digit cell-count change produces a different canonical hash"


def test_bare_cr_is_rejected_not_normalized():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "bare_cr.json"
        path.write_bytes(b'{\r  "cells": 1\n}\n')
        try:
            pm.canonical_utf8_lf_sha256(path)
        except ValueError as error:
            message = str(error)
        else:
            raise AssertionError("a bare CR must not be silently normalized")
    assert "bare CR" in message
    return "a lone CR raises instead of being folded into LF"


def test_writer_emits_canonical_lf_bytes():
    payload = {"production_treatment": {"method": "union_valid_with_annual_missing"}}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "diagnostic.json"
        pm.write_json_lf(path, payload)
        first = path.read_bytes()
        pm.write_json_lf(path, payload)
        second = path.read_bytes()

    first.decode("utf-8")
    assert b"\r\n" not in first, "canonical JSON must not contain CRLF"
    assert b"\r" not in first, "canonical JSON must not contain a bare CR"
    assert first.endswith(b"}\n"), "canonical JSON must end with exactly one LF"
    assert not first.endswith(b"\n\n"), "canonical JSON must not end with a blank line"
    assert json.loads(first.decode("utf-8")) == payload
    assert first == second, "repeated writes must be byte-identical"
    lf_count = first.count(b"\n")
    return f"{len(first)} bytes, {lf_count} LF, 0 CRLF, byte-stable on rewrite"


def test_writer_keeps_sorted_keys_and_rejects_nan():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "sorted.json"
        pm.write_json_lf(path, {"zebra": 1, "alpha": 2})
        text = path.read_bytes().decode("utf-8")
        assert text.index('"alpha"') < text.index('"zebra"'), "keys must stay sorted"
        try:
            pm.write_json_lf(path, {"value": float("nan")})
        except ValueError:
            rejected = True
        else:
            rejected = False
    assert rejected, "NaN must not be written into a provenance artifact"
    return "keys stay sorted and NaN is refused"


TESTS = [
    ("canonical hashing ignores checkout newlines", test_canonical_hash_ignores_checkout_newlines),
    ("a real content change changes the hash", test_content_change_still_changes_the_hash),
    ("a bare CR is rejected rather than normalized", test_bare_cr_is_rejected_not_normalized),
    ("Phase 2A JSON is written as canonical LF bytes", test_writer_emits_canonical_lf_bytes),
    ("writer keeps sorted keys and refuses NaN", test_writer_keeps_sorted_keys_and_rejects_nan),
]


def main() -> int:
    print("=" * 74)
    print("Phase 2A provenance - synthetic regression tests")
    print("=" * 74)
    failures = 0
    for title, function in TESTS:
        try:
            detail = function()
        except Exception as error:  # noqa: BLE001 - standalone test runner
            failures += 1
            print(f"  FAIL  {title}\n        {type(error).__name__}: {error}")
        else:
            print(f"  PASS  {title}\n        {detail}")
    print("-" * 74)
    print(f"  {len(TESTS) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
