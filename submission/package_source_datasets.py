#!/usr/bin/env python3
"""Package the ORIGINAL / source datasets for the STATS 401 final submission.

The rubric requires the original source datasets, but two of them are large binaries
that are intentionally gitignored (`data/external/`) and therefore not committed:

    1. data/external/uzb_pop_2026_CN_100m_R2025A_v1.tif   (WorldPop 2026 raster)
    2. data/external/tashkent_walk_network.graphml        (OSM pedestrian network)

This tool builds a verifiable ZIP of those originals (plus an inventory) for delivery
through a separate, instructor-approved channel. It is fail-closed and provenance-driven:

  * It reads the committed `data/source_manifest.json` for the authoritative paths,
    sizes, provider attribution and (for WorldPop) the committed SHA-256.
  * It validates each file's exact size, validates WorldPop's committed SHA-256, and
    computes the GraphML SHA-256 — stating clearly that the committed manifest records
    NO SHA-256 for the network, so its historical cryptographic identity cannot be
    proven from a freshly computed hash alone.
  * It NEVER downloads or substitutes a dataset, and it writes the ZIP OUTSIDE the
    repository by default so large binaries are never committed to Git.
  * It verifies the ZIP's integrity after creation.
  * The archive contains ONLY the two validated originals plus the generated inventory
    and README — no credentials, secrets, or unrelated caches.

Usage
  python3 -I submission/package_source_datasets.py            # build the real archive
  python3 -I submission/package_source_datasets.py --self-test  # exercise the logic with safe fixtures
  python3 -I submission/package_source_datasets.py --external-dir /path/to/data/external --output /path/out.zip

Run with `python3 -I` (isolated) so it never imports anything from the working directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent          # submission/ -> repo root
DEFAULT_MANIFEST = REPO_ROOT / "data" / "source_manifest.json"
DEFAULT_EXTERNAL_DIR = REPO_ROOT / "data" / "external"

# The original source binaries this archive must carry, keyed by their manifest source.
SOURCE_KEYS = ("worldpop", "osm_walk_network")

# Provenance fields copied verbatim into the inventory when present on a manifest source.
PROVENANCE_FIELDS = ("url", "landing_page", "doi", "release", "licence",
                     "licence_url", "acquired_at_utc", "method")


class PackagingError(Exception):
    """Any fail-closed condition: missing, modified, or inconsistent input."""


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def load_specs(manifest_path: Path):
    """Return (manifest, [spec,...]) from the committed source manifest."""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    sources = manifest.get("sources", {})
    specs = []
    for key in SOURCE_KEYS:
        src = sources.get(key)
        if not isinstance(src, dict):
            raise PackagingError(f"manifest has no source entry for '{key}'")
        out = src.get("outputs")
        if isinstance(out, list):
            out = out[0] if out else None
        if not isinstance(out, dict) or "path" not in out:
            raise PackagingError(f"manifest source '{key}' has no output path")
        specs.append({
            "key": key,
            "repo_relative_path": out["path"],
            "filename": Path(out["path"]).name,
            "expected_size": out.get("size_bytes"),
            "expected_sha256": out.get("sha256"),            # None for the GraphML
            "provider": src.get("source"),
            "provenance": {k: src.get(k) for k in PROVENANCE_FIELDS if src.get(k) is not None},
        })
    return manifest, specs


def validate_source(spec: dict, external_dir: Path) -> dict:
    """Validate one original binary, fail-closed. Returns an inventory record."""
    path = Path(external_dir) / spec["filename"]
    if not path.exists():
        raise PackagingError(
            f"original source file is not present: {path}\n"
            f"  This tool never downloads or substitutes a dataset. Provide the real file "
            f"(re-run the project's acquire step in a cache-equipped checkout) and try again.")
    size = path.stat().st_size
    expected_size = spec["expected_size"]
    if expected_size is not None and size != expected_size:
        raise PackagingError(
            f"{spec['filename']}: size {size} bytes != expected {expected_size} bytes "
            f"(file is modified, truncated, or the wrong release)")
    digest = sha256_file(path)
    expected_sha = spec["expected_sha256"]
    if expected_sha:
        if digest != expected_sha:
            raise PackagingError(
                f"{spec['filename']}: SHA-256 mismatch\n"
                f"  computed : {digest}\n  committed: {expected_sha}\n  (file does not match the audited original)")
        sha_verified = True
        sha_note = "matches the committed manifest SHA-256 (cryptographically verified)"
    else:
        sha_verified = False
        sha_note = ("computed at packaging time; the committed manifest records NO SHA-256 for this "
                    "file, so its historical cryptographic identity cannot be proven from this hash "
                    "alone — it is recorded here only as a freshly computed integrity reference")
    return {
        "key": spec["key"],
        "filename": spec["filename"],
        "repo_relative_path": spec["repo_relative_path"],
        "size_bytes": size,
        "sha256": digest,
        "sha256_verified_against_manifest": sha_verified,
        "sha256_note": sha_note,
        "provider": spec["provider"],
        "provenance": spec["provenance"],
    }


def build_inventory(manifest: dict, records: list, manifest_path: Path) -> dict:
    return {
        "archive": "STATS 401 — Tashkent Transit & Walkability: original source datasets",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_manifest": str(Path(manifest_path).name),
        "source_manifest_sha256": sha256_file(Path(manifest_path)),
        "analysis_release_note": manifest.get("analysis_version") or manifest.get("project_stage"),
        "files": records,
        "attribution": [
            "WorldPop, University of Southampton — CC BY 4.0 (R2025A, alpha release).",
            "OpenStreetMap contributors — Open Database License (ODbL) v1.0.",
        ],
        "notes": [
            "These are the ORIGINAL source binaries, excluded from Git for size (data/external/ is gitignored).",
            "The cleaned/processed datasets and full provenance manifests are committed in the repository.",
            "The OSM pedestrian-network GraphML has no committed SHA-256; the value above is a freshly "
            "computed integrity reference, not a proof of historical identity.",
            "Packaged by submission/package_source_datasets.py; no dataset was downloaded or substituted.",
        ],
    }


def write_archive(records_paths: list, inventory: dict, output_zip: Path) -> None:
    """Write the ZIP with exactly the validated files + inventory.json + README.txt."""
    output_zip = Path(output_zip)
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    readme = _readme_text(inventory)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rec, src_path in records_paths:
            zf.write(src_path, arcname=rec["filename"])
        zf.writestr("inventory.json", json.dumps(inventory, indent=2, ensure_ascii=False))
        zf.writestr("README.txt", readme)


def _readme_text(inventory: dict) -> str:
    lines = [inventory["archive"], "=" * len(inventory["archive"]), "",
             f"Generated: {inventory['generated_at_utc']}", "",
             "Contents:"]
    for rec in inventory["files"]:
        lines += [
            f"  - {rec['filename']}  ({rec['size_bytes']} bytes)",
            f"      provider : {rec['provider']}",
            f"      sha256   : {rec['sha256']}",
            f"      verified : {rec['sha256_verified_against_manifest']} — {rec['sha256_note']}",
        ]
    lines += ["", "Attribution:"]
    lines += [f"  - {a}" for a in inventory["attribution"]]
    lines += ["", "Notes:"]
    lines += [f"  - {n}" for n in inventory["notes"]]
    return "\n".join(lines) + "\n"


def verify_archive(output_zip: Path, records: list) -> None:
    """Re-open the ZIP, run CRC check, and re-hash each source member against its record."""
    with zipfile.ZipFile(output_zip, "r") as zf:
        bad = zf.testzip()
        if bad is not None:
            raise PackagingError(f"ZIP integrity check failed on member: {bad}")
        names = set(zf.namelist())
        required = {r["filename"] for r in records} | {"inventory.json", "README.txt"}
        missing = required - names
        if missing:
            raise PackagingError(f"archive is missing expected members: {sorted(missing)}")
        extra = names - required
        if extra:
            raise PackagingError(f"archive contains unexpected members (refusing): {sorted(extra)}")
        for rec in records:
            h = hashlib.sha256()
            with zf.open(rec["filename"]) as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    h.update(block)
            if h.hexdigest() != rec["sha256"]:
                raise PackagingError(f"archived {rec['filename']} does not match its recorded SHA-256")


def run_packaging(manifest_path: Path, external_dir: Path, output_zip: Path) -> dict:
    output_zip = Path(output_zip).resolve()
    if REPO_ROOT in output_zip.parents or output_zip.parent == REPO_ROOT:
        raise PackagingError(
            f"refusing to write the archive inside the repository ({output_zip}); "
            f"choose a path outside it so large binaries are never committed to Git")
    manifest, specs = load_specs(manifest_path)
    records, records_paths = [], []
    for spec in specs:
        rec = validate_source(spec, external_dir)
        records.append(rec)
        records_paths.append((rec, Path(external_dir) / rec["filename"]))
    inventory = build_inventory(manifest, records, manifest_path)
    write_archive(records_paths, inventory, output_zip)
    verify_archive(output_zip, records)
    return {"output_zip": str(output_zip), "inventory": inventory}


# --------------------------------------------------------------------------- #
# Self-test with safe synthetic fixtures (used when the real binaries are absent)
# --------------------------------------------------------------------------- #
def _self_test() -> int:
    print("SELF-TEST: exercising the packaging logic with small synthetic fixtures")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ext = tmp / "external"
        ext.mkdir()
        # Deterministic synthetic 'originals' (tiny, safe — NOT the real datasets).
        raster = ext / "uzb_pop_2026_CN_100m_R2025A_v1.tif"
        graph = ext / "tashkent_walk_network.graphml"
        raster.write_bytes(b"SYNTHETIC-RASTER-FIXTURE\n" * 64)
        graph.write_bytes(b"<graphml>SYNTHETIC-NETWORK-FIXTURE</graphml>\n" * 64)
        raster_sha = sha256_file(raster)
        # Synthetic manifest mirroring the real schema: WorldPop has a committed sha, network does not.
        manifest = {
            "analysis_version": "self-test",
            "sources": {
                "worldpop": {"source": "WorldPop (fixture)", "licence": "CC BY 4.0",
                             "url": "https://example.invalid/worldpop",
                             "outputs": {"path": "data/external/uzb_pop_2026_CN_100m_R2025A_v1.tif",
                                         "size_bytes": raster.stat().st_size, "sha256": raster_sha}},
                "osm_walk_network": {"source": "OpenStreetMap (fixture)", "licence": "ODbL v1.0",
                                     "url": "https://example.invalid/osm",
                                     "outputs": {"path": "data/external/tashkent_walk_network.graphml",
                                                 "size_bytes": graph.stat().st_size}},
            },
        }
        man_path = tmp / "source_manifest.json"
        man_path.write_text(json.dumps(manifest), encoding="utf-8")
        out = tmp / "out" / "archive.zip"

        checks = []

        # 1. Happy path: validate + package + verify.
        _, specs = load_specs(man_path)
        records, records_paths = [], []
        for spec in specs:
            rec = validate_source(spec, ext)
            records.append(rec); records_paths.append((rec, ext / rec["filename"]))
        inv = build_inventory(manifest, records, man_path)
        write_archive(records_paths, inv, out)
        verify_archive(out, records)
        checks.append(("valid fixtures package and verify", out.exists()))
        checks.append(("worldpop sha verified against manifest", records[0]["sha256_verified_against_manifest"] is True))
        checks.append(("network sha recorded but NOT claimed verified", records[1]["sha256_verified_against_manifest"] is False))
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
        checks.append(("archive holds exactly the 2 originals + inventory + README",
                       names == {"uzb_pop_2026_CN_100m_R2025A_v1.tif", "tashkent_walk_network.graphml",
                                 "inventory.json", "README.txt"}))

        # 2. Fail-closed: missing file.
        try:
            validate_source(specs[0], tmp / "nonexistent")
            checks.append(("missing file fails closed", False))
        except PackagingError:
            checks.append(("missing file fails closed", True))

        # 3. Fail-closed: wrong size.
        bad_size_manifest = json.loads(json.dumps(manifest))
        bad_size_manifest["sources"]["worldpop"]["outputs"]["size_bytes"] += 1
        bsp = man_path.with_name("bad_size.json"); bsp.write_text(json.dumps(bad_size_manifest))
        _, bad_specs = load_specs(bsp)
        try:
            validate_source(bad_specs[0], ext); checks.append(("wrong size fails closed", False))
        except PackagingError:
            checks.append(("wrong size fails closed", True))

        # 4. Fail-closed: tampered content (size preserved, sha changes).
        tampered = ext / "tampered.tif"
        data = bytearray(raster.read_bytes()); data[0] ^= 0xFF; tampered.write_bytes(bytes(data))
        tamper_spec = dict(specs[0]); tamper_spec["filename"] = "tampered.tif"
        try:
            validate_source(tamper_spec, ext); checks.append(("tampered worldpop fails sha check", False))
        except PackagingError:
            checks.append(("tampered worldpop fails sha check", True))

        # 5. Guard: refuse output inside the repository.
        try:
            run_packaging(DEFAULT_MANIFEST, DEFAULT_EXTERNAL_DIR, REPO_ROOT / "submission" / "x.zip")
            checks.append(("refuses in-repo output path", False))
        except PackagingError:
            checks.append(("refuses in-repo output path", True))

        ok = all(p for _, p in checks)
        for name, passed in checks:
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        print("SELF-TEST:", "PASS" if ok else "FAIL")
        print("NOTE: the real archive is NOT created by --self-test; run without it in a cache-equipped "
              "checkout (with data/external/ present) to build the deliverable.")
        return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Package the original source datasets into a verifiable ZIP.")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--external-dir", type=Path, default=DEFAULT_EXTERNAL_DIR,
                    help="directory holding the original binaries (default: data/external/)")
    ap.add_argument("--output", type=Path, default=None,
                    help="ZIP path (default: a path OUTSIDE the repository)")
    ap.add_argument("--self-test", action="store_true", help="run the fixture-based self-test and exit")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()

    default_out = REPO_ROOT.parent / f"stats401_source_datasets_{datetime.now().strftime('%Y%m%d')}.zip"
    output = args.output or default_out
    try:
        result = run_packaging(args.manifest, args.external_dir, output)
    except PackagingError as exc:
        print(f"PACKAGING FAILED (fail-closed): {exc}", file=sys.stderr)
        print("No archive was written. Nothing was downloaded or substituted.", file=sys.stderr)
        return 2

    inv = result["inventory"]
    print("SOURCE-DATASET ARCHIVE CREATED")
    print(f"  output   : {result['output_zip']}  (outside the repository)")
    for rec in inv["files"]:
        print(f"  file     : {rec['filename']}  {rec['size_bytes']} bytes")
        print(f"             sha256={rec['sha256']} verified={rec['sha256_verified_against_manifest']}")
    print("  integrity: ZIP re-opened, CRC-checked, and every member re-hashed to match — OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
