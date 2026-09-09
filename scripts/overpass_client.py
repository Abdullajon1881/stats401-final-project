"""A small, explicit Overpass client.

OSMnx is used for the administrative boundaries and the walk graph, but the
point layers are fetched with hand-written Overpass QL instead. Two reasons:

* the query is visible in the source, so the tag rules can be audited directly;
* OSMnx's slot-polling against the busy public instance repeatedly stalled,
  while a small explicit query with mirror failover completes in seconds.

`out center` returns one coordinate per element, which is exactly what a
catchment analysis needs: a way or relation is reduced to the centre of its
bounding box rather than kept as a polygon. For stop platforms and market
areas that displacement is a few tens of metres at most.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

import config as cfg
from pipeline_utils import log, overpass_post

# (key, value) pairs; a value of None matches any value for that key.
TagSelector = tuple[str, str | None]


def build_query(bbox: tuple[float, float, float, float], selectors: list[TagSelector]) -> str:
    """Build an Overpass QL union query over node/way/relation for each selector."""
    west, south, east, north = bbox
    area = f"({south},{west},{north},{east})"
    clauses = []
    for key, value in selectors:
        filt = f'["{key}"]' if value is None else f'["{key}"="{value}"]'
        for element in ("node", "way", "relation"):
            clauses.append(f"  {element}{filt}{area};")
    body = "\n".join(clauses)
    return f"[out:json][timeout:{cfg.OVERPASS_TIMEOUT}];\n(\n{body}\n);\nout center tags;"


def fetch(
    bbox: tuple[float, float, float, float],
    selectors: list[TagSelector],
    description: str,
) -> gpd.GeoDataFrame:
    """Run a tag query and return one point per OSM element, with all its tags."""
    query = build_query(bbox, selectors)
    payload = overpass_post(query, description)
    elements = payload.get("elements", [])
    log(f"    Overpass returned {len(elements)} elements for {description}")

    records, geometries = [], []
    seen: set[tuple[str, int]] = set()
    for element in elements:
        element_type = element.get("type")
        element_id = element.get("id")
        key = (element_type, element_id)
        if key in seen:
            continue  # the same object can match several selectors in the union
        seen.add(key)

        if element_type == "node":
            lon, lat = element.get("lon"), element.get("lat")
        else:
            centre = element.get("center") or {}
            lon, lat = centre.get("lon"), centre.get("lat")
        if lon is None or lat is None:
            continue  # element without geometry (rare, e.g. an empty relation)

        row = dict(element.get("tags", {}))
        row["osm_element"] = element_type
        row["osm_id"] = element_id
        records.append(row)
        geometries.append(Point(float(lon), float(lat)))

    if not records:
        return gpd.GeoDataFrame(
            pd.DataFrame(columns=["osm_element", "osm_id"]),
            geometry=[],
            crs=cfg.GEOGRAPHIC_CRS,
        )

    frame = pd.DataFrame.from_records(records)
    return gpd.GeoDataFrame(frame, geometry=geometries, crs=cfg.GEOGRAPHIC_CRS)
