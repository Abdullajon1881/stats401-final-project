"""Validate the Phase 2C current urban-dimensions analysis.

    python scripts/validate_phase2_urban_dimensions.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import accessibility_utils as au  # noqa: E402
import config as cfg  # noqa: E402
import urban_dimensions as ud  # noqa: E402

STARTING_MAIN = "c92388adc8205546c152932d6ab70409882fa755"
BUDGET_M = cfg.PHASE2C_ACCESS_DISTANCE_BUDGET_M
DESTINATION_CLASSES = ("healthcare", "education", "bazaar")
ACCESS_LABELS = ("healthcare", "education", "bazaar", "healthcare_and_education")
PCT_TOL = 1e-6
POP_TOL = 1e-3
LENGTH_TOL_KM = 1e-6

FROZEN_CURRENT = (
    "data/analysis_manifest.json",
    "data/processed/city_access_summary.json",
    "data/processed/district_access_metrics.csv",
    "data/processed/metro_access_points.csv",
    "data/processed/metro_isochrone_10min.geojson",
    "data/processed/bus_isochrone_10min.geojson",
    "data/processed/walking_speed_sensitivity.csv",
    "data/processed/population_surface_sensitivity.csv",
)
FROZEN_PHASE2 = (
    "data/phase2_source_manifest.json",
    "data/phase2_analysis_manifest.json",
    "data/processed/metro_access_temporal_city.csv",
    "data/processed/metro_access_temporal_district.csv",
    "data/processed/metro_access_temporal_events.csv",
    "data/processed/metro_access_temporal_counterfactual.csv",
    "data/processed/metro_temporal_routing_states.json",
    "docs/phase2_temporal_methodology.md",
    "docs/phase2_temporal_accessibility.md",
)

passed = 0
failed = 0


def check(condition: bool, label: str, detail: str | None = None) -> bool:
    global passed, failed
    if bool(condition):
        passed += 1
        print(f"  [PASS] {label}")
        return True
    failed += 1
    suffix = f" ({detail})" if detail else ""
    print(f"  [FAIL] {label}{suffix}")
    return False


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def git_paths_unchanged(paths: tuple[str, ...]) -> tuple[bool, list[str]]:
    """Return whether every path is content-identical to the starting main."""
    result = subprocess.run(
        ["git", "diff", "--name-only", STARTING_MAIN, "--", *paths],
        capture_output=True, text=True, cwd=cfg.REPO_ROOT,
    )
    if result.returncode != 0:
        return False, ["git diff failed"]
    changed = [line for line in result.stdout.splitlines() if line.strip()]
    return not changed, changed


def main() -> int:  # noqa: PLR0915 - validator intentionally enumerates gates
    manifest = json.loads(
        ud.canonical_utf8_lf_bytes(cfg.PHASE2C_MANIFEST_PATH).decode("utf-8")
    )

    section("Sources")
    healthcare = gpd.read_file(cfg.HEALTHCARE_FACILITIES_FILE)
    education = gpd.read_file(cfg.EDUCATION_FACILITIES_FILE)
    bazaars = gpd.read_file(cfg.BAZAARS_FILE)
    check(len(healthcare) > 0, "healthcare facility layer exists and is populated")
    check(len(education) > 0, "education facility layer exists and is populated")
    check(len(bazaars) == 83, "existing bazaar layer still holds 83 marketplaces")

    for label, frame, column, categories in (
        ("healthcare", healthcare, "facility_category", cfg.PHASE2C_HEALTHCARE_CATEGORIES),
        ("education", education, "education_category", cfg.PHASE2C_EDUCATION_CATEGORIES),
    ):
        check(frame.facility_id.is_unique, f"{label} facility IDs are unique")
        check(not frame.duplicated(["osm_type", "osm_id"]).any(),
              f"{label} carries no duplicate OSM element")
        check(set(frame[column]) <= set(categories),
              f"{label} uses only the allowed categories",
              str(sorted(set(frame[column]) - set(categories))))
        finite = np.isfinite(frame.longitude.to_numpy()) & np.isfinite(
            frame.latitude.to_numpy()
        )
        check(bool(finite.all()), f"{label} representative coordinates are finite")
        check(bool(frame.geometry.is_valid.all()), f"{label} geometry is valid")
        check(bool(frame.geometry.notna().all()), f"{label} geometry is present")
        methods = set(frame.representative_point_method)
        check(methods <= {"osm_node", "polygon_representative_point", "line_midpoint",
                          "collection_representative_point"},
              f"{label} records a known representative-point rule", str(sorted(methods)))
        check(set(frame.district_name.dropna()) <= set(
                  gpd.read_file(cfg.DISTRICTS_FILE).district_name),
              f"{label} districts are analysis districts")

    city_geom = gpd.read_file(cfg.BOUNDARY_FILE).to_crs(cfg.METRIC_CRS).geometry.iloc[0]
    for label, frame in (("healthcare", healthcare), ("education", education)):
        points = gpd.GeoSeries(
            gpd.points_from_xy(frame.longitude, frame.latitude),
            crs=cfg.GEOGRAPHIC_CRS,
        ).to_crs(cfg.METRIC_CRS)
        check(bool(points.within(city_geom).all()),
              f"every retained {label} facility lies inside the city boundary")

    for label, key, frame, column, categories in (
        ("healthcare", "healthcare", healthcare, "facility_category",
         cfg.PHASE2C_HEALTHCARE_CATEGORIES),
        ("education", "education", education, "education_category",
         cfg.PHASE2C_EDUCATION_CATEGORIES),
    ):
        record = manifest["sources"][key]
        raw_total = record["raw_in_city"]["total"]
        clean_total = record["clean"]["total"]
        removed = record["duplicates_removed"]
        check(raw_total >= clean_total,
              f"{label} raw count is at least the cleaned count")
        check(raw_total - clean_total == removed,
              f"{label} dedupe count reconciles raw minus clean")
        check(clean_total == len(frame),
              f"{label} manifest clean total matches the committed layer")
        recount = record["recounted_clean"]["by_category"]
        check(all(int((frame[column] == c).sum()) == recount[c] for c in categories),
              f"{label} category counts reconcile with the committed layer")
        check(sum(recount.values()) == len(frame),
              f"{label} category subtotals sum to the layer total")
        check(isinstance(record.get("dedupe_rule"), str) and record["dedupe_rule"],
              f"{label} documents its dedupe semantics")
        check(record.get("osm_licence") == "ODbL 1.0", f"{label} records the OSM licence")
        check("out geom" in record.get("overpass_query", ""),
              f"{label} records the exact Overpass query")
        check(bool(record.get("acquired_at_utc")),
              f"{label} records its source acquisition timestamp")

    section("Current population")
    cells = pd.read_parquet(cfg.POPULATION_CELLS_CACHE)
    district_metrics = pd.read_csv(cfg.DISTRICT_ACCESS_METRICS_FILE)
    official_total = float(district_metrics.official_population.sum())
    check(len(district_metrics) == 12, "12 analysis districts carry official population")
    check(abs(float(cells.population.sum()) - official_total) < 1.0,
          "population cells reproduce the current official denominator")
    check(bool((cells.population.to_numpy() >= 0).all()),
          "no negative population in the current cell surface")
    check(abs(official_total - 3_212_200.0) < 1e-6,
          "current official denominator is 3,212,200")

    section("Routing")
    routing = manifest["routing"]
    check(sorted(routing["destination_classes"]) == sorted(DESTINATION_CLASSES),
          "exactly three destination classes are routed")
    check(routing["dijkstra_runs"] == 3, "exactly three Dijkstra runs")
    check(routing["distance_budget_m"] == BUDGET_M, "the budget is 800 m")
    check(routing["walking_speed_kmh"] == cfg.MAIN_WALK_SPEED_KMH,
          "the walking speed is 4.8 km/h")
    check(routing["walking_time_minutes"] == cfg.WALK_TIME_LIMIT_MINUTES,
          "the walking time is 10 minutes")
    check("unrounded" in routing["classification"],
          "classification is documented as unrounded network distance")
    check("not verified pedestrian entrances" in routing["source_representative_point_rule"],
          "the manifest states representative points are not verified entrances")
    for label in DESTINATION_CLASSES:
        diagnostics = routing["connector_diagnostics"][label]
        check(diagnostics["min_m"] >= 0.0, f"{label} source connectors are non-negative")
        check(all(np.isfinite(v) for k, v in diagnostics.items()
                  if isinstance(v, (int, float))),
              f"{label} connector diagnostics are finite")

    section("City access")
    city = pd.read_csv(cfg.URBAN_DIMENSIONS_CITY_FILE)
    check(len(city) == 1, "the city table holds exactly one row")
    row = city.iloc[0]
    denominator = float(row.population_total)
    for label in ACCESS_LABELS:
        numerator = float(row[f"{label}_10min_population"])
        percent = float(row[f"{label}_10min_pct"])
        check(0.0 <= percent <= 100.0, f"city {label} percentage lies in [0, 100]")
        check(numerator <= denominator + POP_TOL,
              f"city {label} numerator does not exceed the population")
        check(abs(percent - 100.0 * numerator / denominator) < PCT_TOL,
              f"city {label} percentage recomputes from the committed numbers")
    check(float(row.healthcare_and_education_10min_population)
          <= min(float(row.healthcare_10min_population),
                 float(row.education_10min_population)) + POP_TOL,
          "the healthcare-and-education population cannot exceed either class")

    section("Districts")
    district = pd.read_csv(cfg.URBAN_DIMENSIONS_DISTRICT_FILE)
    check(len(district) == 12, "the district table holds exactly 12 rows")
    check(district.district_name.is_unique, "district identities are unique")
    counts = ["hospitals", "clinics", "healthcare_total", "schools", "colleges",
              "universities", "kindergartens", "education_total", "bazaars",
              "metro_stations", "metro_access_points", "bus_stops"]
    check(all(district[c].dtype.kind in "iu" and bool((district[c] >= 0).all())
              for c in counts),
          "every facility and transit count is a non-negative integer")
    check(bool((district.hospitals + district.clinics == district.healthcare_total).all()),
          "healthcare subtotals reconcile")
    check(bool((district.schools + district.colleges + district.universities
                + district.kindergartens == district.education_total).all()),
          "education subtotals reconcile")
    check(int(district.healthcare_total.sum()) == len(healthcare),
          "district healthcare counts sum to the committed layer")
    check(int(district.education_total.sum()) == len(education),
          "district education counts sum to the committed layer")
    check(int(district.bazaars.sum()) == len(bazaars),
          "district bazaar counts sum to the existing bazaar layer")

    merged = district.merge(
        district_metrics[["district_name", "official_population",
                          "metro_stations_in_district",
                          "metro_access_points_in_district",
                          "bus_stops_in_district", "bazaars_in_district",
                          "metro_access_pct", "bus_only_pct", "underserved_pct"]],
        on="district_name", validate="1:1",
    )
    check(bool((merged.metro_stations == merged.metro_stations_in_district).all()),
          "metro station counts are reused unchanged")
    check(bool((merged.metro_access_points == merged.metro_access_points_in_district).all()),
          "metro access-point counts are reused unchanged")
    check(bool((merged.bus_stops == merged.bus_stops_in_district).all()),
          "bus stop counts are reused unchanged")
    check(bool((merged.bazaars == merged.bazaars_in_district).all()),
          "bazaar counts are reused unchanged")
    check(bool(np.allclose(merged.metro_access_pct_x, merged.metro_access_pct_y,
                           atol=PCT_TOL)),
          "metro access percentages are reused unchanged")
    check(abs(float(district.official_population.sum()) - official_total) < 1e-6,
          "district official populations sum to the current denominator")
    check(abs(float(district.population.sum()) - denominator) < POP_TOL,
          "district modelled populations sum to the city denominator")

    for label in ACCESS_LABELS:
        numerator = district[f"{label}_10min_population"].to_numpy(dtype=float)
        percent = district[f"{label}_10min_pct"].to_numpy(dtype=float)
        base = district.population.to_numpy(dtype=float)
        check(bool(((percent >= 0.0) & (percent <= 100.0)).all()),
              f"district {label} percentages lie in [0, 100]")
        check(bool((numerator <= base + POP_TOL).all()),
              f"district {label} numerators do not exceed district population")
        check(bool(np.allclose(percent, 100.0 * numerator / base, atol=PCT_TOL)),
              f"district {label} percentages recompute")
        check(abs(numerator.sum() - float(row[f"{label}_10min_population"])) < POP_TOL,
              f"district {label} populations sum to the city value")

    for column, count in (("healthcare_facilities_per_10k", "healthcare_total"),
                          ("education_facilities_per_10k", "education_total"),
                          ("bazaars_per_10k", "bazaars"),
                          ("bus_stops_per_10k", "bus_stops")):
        expected = district[count].to_numpy(float) * 10_000.0 / district.official_population.to_numpy(float)
        check(bool(np.allclose(district[column].to_numpy(float), expected, atol=1e-6)),
              f"{column} recomputes from count and population")
    check("metro_stations_per_10k" not in district.columns
          and "metro_stations_per_100k" not in district.columns,
          "metro supply stays a raw count, as documented")

    section("Walk network")
    network = au.load_walk_network(cfg.WALK_GRAPH_FILE)
    check(network.n_nodes == 111_386, "the fixed current network has 111,386 nodes")
    check(network.stats["stored_edge_records"] == 308_272,
          "the network carries 308,272 stored edge records")
    check(network.n_edges == 154_133, "the network has 154,133 canonical edges")
    edges = ud.canonical_edge_geometries(network)
    check(len(edges) == network.n_edges,
          "walk-network density reads canonical edges, not directional records")
    districts_gdf = gpd.read_file(cfg.DISTRICTS_FILE)
    districts_gdf = districts_gdf.loc[districts_gdf.in_siat].to_crs(cfg.METRIC_CRS)
    polygons = {r.district_name: r.geometry for r in districts_gdf.itertuples()}
    union_km = ud.union_clipped_length_km(edges, polygons)
    check(bool((district.walk_network_km.to_numpy(float) >= 0).all()),
          "every district walk-network length is non-negative")
    check(abs(float(district.walk_network_km.sum()) - union_km) < 1e-3,
          "district lengths reconcile with the district-union clip",
          f"{float(district.walk_network_km.sum()):.6f} vs {union_km:.6f}")
    expected_density = (
        district.walk_network_km.to_numpy(float) / district.area_km2.to_numpy(float)
    )
    check(bool(np.allclose(district.walk_network_density_km_per_km2.to_numpy(float),
                           expected_density, atol=1e-6)),
          "walk-network densities recompute from length and area")
    check("not a walkability score" in manifest["walk_network_density"]["label"],
          "the manifest labels this a network-density proxy")

    section("Provenance")
    basis_ok = True
    hashes_ok = True
    sizes_ok = True
    problems: list[str] = []
    for group in ("input_files", "output_files"):
        for relative_path, meta in manifest[group].items():
            path = cfg.REPO_ROOT / relative_path
            basis = meta.get("hash_basis")
            if basis not in (ud.HASH_BASIS_CANONICAL_TEXT, ud.HASH_BASIS_RAW_BYTES):
                basis_ok = False
                problems.append(f"{Path(relative_path).name}: basis {basis!r}")
                continue
            if not path.exists():
                hashes_ok = False
                problems.append(f"{Path(relative_path).name}: missing")
                continue
            record = ud.provenance_record(path, basis)
            if record["sha256"] != meta["sha256"]:
                hashes_ok = False
                problems.append(f"{Path(relative_path).name}: sha")
            if record["size_bytes"] != meta.get("size_bytes"):
                sizes_ok = False
                problems.append(f"{Path(relative_path).name}: size")
    check(basis_ok, "every manifest file declares a known hash basis",
          "; ".join(problems) if not basis_ok else None)
    check(hashes_ok, "all manifest input and output hashes match",
          "; ".join(problems) if not hashes_ok else None)
    check(sizes_ok, "all manifest sizes describe the same bytes as their hash",
          "; ".join(problems) if not sizes_ok else None)

    for path in (cfg.PHASE2C_MANIFEST_PATH, cfg.HEALTHCARE_FACILITIES_FILE,
                 cfg.EDUCATION_FACILITIES_FILE, cfg.URBAN_DIMENSIONS_CITY_FILE,
                 cfg.URBAN_DIMENSIONS_DISTRICT_FILE):
        raw = path.read_bytes()
        check(b"\r\n" not in raw and b"\r" not in raw,
              f"{path.name} is stored with LF newlines and no CR bytes",
              f"{raw.count(chr(13).encode() + chr(10).encode())} CRLF")
    check(manifest["historical_facility_claims"] is False,
          "the manifest records that no historical facility claim is made")
    check(manifest["composite_score_or_ranking"] is False,
          "the manifest records that no composite score or ranking is produced")
    check(len(manifest["limitations"]) >= 9,
          "the manifest enumerates the documented limitations")

    section("Freeze")
    for label, paths in (("current headline outputs", FROZEN_CURRENT),
                         ("Phase 2A and Phase 2B artifacts", FROZEN_PHASE2),
                         ("site/", ("site",))):
        unchanged, changed = git_paths_unchanged(paths)
        check(unchanged, f"{label} are unchanged against the starting main",
              ", ".join(changed) if changed else None)
    summary = json.loads(
        ud.canonical_utf8_lf_bytes(cfg.CITY_ACCESS_SUMMARY_FILE).decode("utf-8")
    )
    check(summary["metro_access_pct"] == 13.563595724255597,
          "the frozen current headline is unchanged")

    print("\nSummary\n-------")
    print(f"  passed: {passed}")
    print(f"  failed: {failed}")
    if failed:
        print("\nVALIDATION FAILED")
        return 1
    print("\nVALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
