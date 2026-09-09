"""Acquire the Tashkent metro route geometry as a DISPLAY-ONLY snapshot.

    python scripts/acquire_metro_lines.py

Why this is a separate script, and separate data.

The Week 4 accessibility result is audited and frozen. It is built from metro
ENTRANCES and station points, not from route lines, and nothing here may touch
it. This script therefore writes only to `data/display/`, a directory that
exists to make the analytical/display boundary structural rather than a matter
of remembering. It never reads or writes `data/processed/`, `data/raw/` or
`data/analysis_manifest.json`, and it does not change any station or entrance
count.

The metro lines exist so the map can show the network people actually recognise.
They are drawn; they are never measured.

Provenance is recorded in full - the exact Overpass query, the endpoint that
answered, the relations returned and their tags - so the snapshot can be audited
or refreshed deliberately. The snapshot is committed so that
`scripts/build_web_data.py` stays offline and deterministic: the network is
touched here, once, on purpose.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, mapping, shape
from shapely.ops import linemerge

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg  # noqa: E402
from pipeline_utils import log, overpass_post, step  # noqa: E402

DISPLAY_DIR = cfg.DATA_DIR / "display"
METRO_LINES_FILE = DISPLAY_DIR / "metro_lines_osm.geojson"
METRO_LINES_PROVENANCE = DISPLAY_DIR / "metro_lines_provenance.json"

# Generous enough to hold every branch of the network, including the parts of
# the ring line that run outside the city administrative boundary.
BBOX = (41.15, 69.10, 41.45, 69.55)  # south, west, north, east

QUERY = f"""[out:json][timeout:{cfg.OVERPASS_TIMEOUT}];
relation["route"="subway"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
out geom;"""

COORD_PRECISION = 5


def _round(value, precision: int = COORD_PRECISION):
    if isinstance(value, (list, tuple)):
        if value and isinstance(value[0], (int, float)):
            return [round(float(v), precision) for v in value]
        return [_round(v, precision) for v in value]
    return value


def main() -> int:
    DISPLAY_DIR.mkdir(parents=True, exist_ok=True)

    step("STEP 1  Query OSM for subway route relations")
    log("  This is the only step that touches the network. It writes to")
    log("  data/display/ only and cannot alter any audited Week 4 output.")
    log(f"  bbox (S,W,N,E): {BBOX}")
    payload = overpass_post(QUERY, "Tashkent subway route relations")
    relations = [e for e in payload.get("elements", []) if e.get("type") == "relation"]
    log(f"  relations returned: {len(relations)}")
    if not relations:
        raise SystemExit("no subway route relations returned; refusing to write an empty layer")

    step("STEP 2  Group directional variants into lines")
    # OSM stores each line twice, once per direction, over the same physical
    # alignment. Ways are therefore deduplicated by OSM way id so a line is not
    # drawn on top of itself.
    lines: dict[str, dict] = defaultdict(
        lambda: {"ways": {}, "relations": [], "names": set(), "names_en": set(), "colours": set()}
    )
    total_members = 0
    for relation in relations:
        tags = relation.get("tags", {})
        ref = str(tags.get("ref") or tags.get("name") or relation["id"])
        entry = lines[ref]
        entry["relations"].append(int(relation["id"]))
        if tags.get("name"):
            entry["names"].add(tags["name"])
        if tags.get("name:en"):
            entry["names_en"].add(tags["name:en"])
        colour = tags.get("colour") or tags.get("color")
        if colour:
            entry["colours"].add(colour.strip())
        for member in relation.get("members", []):
            if member.get("type") != "way" or not member.get("geometry"):
                continue
            total_members += 1
            coords = [(p["lon"], p["lat"]) for p in member["geometry"]]
            if len(coords) >= 2:
                entry["ways"][int(member["ref"])] = coords

    log(f"  member ways with geometry: {total_members}")
    for ref, entry in sorted(lines.items()):
        log(f"    ref {ref:<4} relations={entry['relations']}  distinct ways={len(entry['ways'])}  "
            f"colour={sorted(entry['colours'])}")

    step("STEP 3  Build one feature per line")
    features = []
    summary = []
    for ref in sorted(lines, key=lambda r: (len(r), r)):
        entry = lines[ref]
        segments = [LineString(c) for c in entry["ways"].values()]
        if not segments:
            continue
        merged = linemerge(segments)
        if merged.geom_type == "LineString":
            merged = LineString(merged)

        colours = sorted(entry["colours"])
        if len(colours) != 1:
            # Never guess a line colour. Without exactly one tagged value the
            # map falls back to a single network colour for this line.
            log(f"    ! ref {ref}: {len(colours)} distinct colour tags {colours}; "
                f"colour left null so the map does not invent one")
        colour = colours[0] if len(colours) == 1 else None

        name_en = sorted(entry["names_en"])
        name = sorted(entry["names"])
        # The relation name carries the direction ("A => B"); the line name is
        # the part before it.
        label = None
        if name_en:
            label = name_en[0].split(":")[0].strip()
        elif name:
            label = name[0].split(":")[0].strip()

        geom = mapping(merged)
        features.append({
            "type": "Feature",
            "properties": {
                "ref": ref,
                "line_name": label,
                "name_en": name_en[0] if name_en else None,
                "colour": colour,
                "osm_relations": sorted(entry["relations"]),
                "way_count": len(entry["ways"]),
                "role": "display_only",
            },
            "geometry": {"type": geom["type"], "coordinates": _round(geom["coordinates"])},
        })
        summary.append({
            "ref": ref, "line_name": label, "colour": colour,
            "osm_relations": sorted(entry["relations"]), "way_count": len(entry["ways"]),
        })
        log(f"    ref {ref:<4} {str(label)[:34]:34s} colour={str(colour):9s} "
            f"ways={len(entry['ways']):<4} geometry={geom['type']}")

    # Deterministic ordering by line reference.
    features.sort(key=lambda f: (len(f["properties"]["ref"]), f["properties"]["ref"]))

    # Measured in the project's metric CRS rather than in degrees, and named for
    # what it actually is. OSM maps part of each line as one shared way and part
    # as separate per-direction tracks, so the merged geometry is total mapped
    # TRACK length - close to twice the route length on the split sections. It is
    # recorded for provenance and is deliberately not shown as a line length.
    projected = gpd.GeoSeries(
        [shape(f["geometry"]) for f in features], crs=cfg.GEOGRAPHIC_CRS
    ).to_crs(cfg.METRIC_CRS)
    for feature, length_m in zip(features, projected.length):
        feature["properties"]["mapped_track_length_km"] = round(float(length_m) / 1000.0, 3)
        summary_entry = next(s for s in summary if s["ref"] == feature["properties"]["ref"])
        summary_entry["mapped_track_length_km"] = feature["properties"]["mapped_track_length_km"]

    step("STEP 4  Write the display snapshot")
    collection = {"type": "FeatureCollection", "features": features}
    METRO_LINES_FILE.write_text(
        json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8", newline="\n",
    )
    log(f"  wrote {METRO_LINES_FILE.relative_to(cfg.REPO_ROOT)} "
        f"({cfg.human_size(cfg.file_size_bytes(METRO_LINES_FILE))}, {len(features)} lines)")

    provenance = {
        "layer": "Tashkent metro route lines",
        "role": "display_only",
        "purpose": (
            "Draw the metro network on the map so its structure is legible. This layer "
            "is never measured: the audited Week 4 accessibility result is computed from "
            "metro entrances and station points, and is unaffected by these lines."
        ),
        "does_not_affect": [
            "data/processed/city_access_summary.json",
            "data/processed/district_access_metrics.csv",
            "data/processed/metro_access_points.csv",
            "data/processed/metro_stations.geojson",
            "data/analysis_manifest.json",
        ],
        "source": "OpenStreetMap via the Overpass API",
        "licence": "Open Database License (ODbL) v1.0",
        "licence_url": "https://www.openstreetmap.org/copyright",
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bbox_south_west_north_east": list(BBOX),
        "query": QUERY,
        "relations_returned": len(relations),
        "member_ways_with_geometry": total_members,
        "lines": summary,
        "colour_rule": (
            "A line's colour is used only when every one of its route relations carries "
            "the same OSM colour tag. Otherwise the colour is null and the map draws that "
            "line in a single neutral network colour rather than guessing."
        ),
        "geometry_rule": (
            "The two directional relations of a line overlap only partly: some sections "
            "are mapped as one shared way, others as separate per-direction tracks. Ways "
            "are therefore deduplicated by OSM way id and then merged, and no geometry is "
            "synthesised. The consequence is that mapped_track_length_km is total mapped "
            "TRACK length, not route length - close to twice the route length wherever the "
            "two tracks are mapped separately. It is recorded for provenance only and is "
            "never presented in the interface as a line length."
        ),
        "outputs": [str(METRO_LINES_FILE.relative_to(cfg.REPO_ROOT)).replace("\\", "/")],
    }
    METRO_LINES_PROVENANCE.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    log(f"  wrote {METRO_LINES_PROVENANCE.relative_to(cfg.REPO_ROOT)}")

    step("Done - display snapshot only; no audited output was touched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
