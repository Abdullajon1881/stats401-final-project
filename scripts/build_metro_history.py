"""Build the source-backed station-level history for all 50 current stations."""

from __future__ import annotations

import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg
from phase2_manifest import update_manifest
from pipeline_utils import enable_utf8_stdout, log, step

LEGACY_SOURCE = "https://www.dkm.gov.uz/uz/toskent-metropoliteni"
YUNUSOBOD_2020_SOURCE = (
    "https://railway.uz/uz/informatsionnaya_sluzhba/novosti/19844/"
)
CIRCLE_2020_SOURCE = "https://www.president.uz/oz/lists/view/3816"
SERGELI_2020_SOURCE = "https://president.uz/oz/4044"
CIRCLE_2023_SOURCE = (
    "https://railway.uz/uz/informatsionnaya_sluzhba/novosti/33727/"
)
CIRCLE_2024_SOURCE = (
    "https://www.dkm.gov.uz/uz/11-martdan-toskent-metrosining-angi-2-ta-"
    "bekati-julovcilar-ucun-ocildi"
)


def _key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.replace("ʻ", "'").replace("‘", "'").replace("’", "'")
    value = value.replace("ʼ", "'").replace("`", "'")
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _record(
    station_id: str,
    name: str,
    line: str,
    opening_date: str,
    precision: str,
    batch: str,
    source_url: str,
    provider: str,
    historical_name: str = "",
    notes: str = "",
) -> dict[str, Any]:
    return {
        "station_id": station_id,
        "station_name_current": name,
        "station_name_historical": historical_name,
        "line": line,
        "opening_date": opening_date,
        "opening_year": int(opening_date[:4]),
        "date_precision": precision,
        "opening_batch_id": batch,
        "source_url": source_url,
        "source_provider": provider,
        "source_quality": "primary",
        "notes": notes,
    }


def station_records() -> list[dict[str, Any]]:
    """Curated batch membership; every opening date is tied to an official source."""
    records: list[dict[str, Any]] = []

    def add_batch(
        line: str,
        date: str,
        precision: str,
        batch: str,
        source: str,
        provider: str,
        stations: list[tuple[str, str, str]],
        note: str,
    ) -> None:
        for station_id, name, historical in stations:
            records.append(
                _record(
                    station_id,
                    name,
                    line,
                    date,
                    precision,
                    batch,
                    source,
                    provider,
                    historical,
                    note,
                )
            )

    government = "Government of Uzbekistan metro-construction directorate"
    railway = "Toshkent metropoliteni / O‘zbekiston temir yo‘llari"
    president = "President of the Republic of Uzbekistan"

    add_batch(
        "Chilonzor line", "1977-11-06", "day", "chilonzor_1977_11_06",
        LEGACY_SOURCE, government,
        [
            ("tm_chilonzor_01", "Olmazor", "Sobir Rahimov"),
            ("tm_chilonzor_02", "Chilonzor", ""),
            ("tm_chilonzor_03", "Mirzo Ulugʻbek", ""),
            ("tm_chilonzor_04", "Novza", "Hamza"),
            ("tm_chilonzor_05", "Milliy bogʻ", "Yoshlik"),
            ("tm_chilonzor_06", "Xalqlar doʻstligi", ""),
            ("tm_chilonzor_07", "Paxtakor", ""),
            ("tm_chilonzor_08", "Mustaqillik maydoni", ""),
            ("tm_chilonzor_09", "Amir Temur xiyoboni", "Markaziy xiyobon"),
        ],
        "Official history identifies the nine-station first-stage opening.",
    )
    add_batch(
        "Chilonzor line", "1980-08-18", "day", "chilonzor_1980_08_18",
        LEGACY_SOURCE, government,
        [
            ("tm_chilonzor_10", "Hamid Olimjon", ""),
            ("tm_chilonzor_11", "Pushkin", ""),
            ("tm_chilonzor_12", "Buyuk Ipak Yoʻli", ""),
        ],
        "Official history identifies the three-station second-stage opening.",
    )
    add_batch(
        "Oʻzbekiston line", "1984-11", "month", "ozbekiston_1984_11",
        LEGACY_SOURCE, government,
        [
            ("tm_ozbekiston_03", "Toshkent", ""),
            ("tm_ozbekiston_04", "Oybek", ""),
            ("tm_ozbekiston_05", "Kosmonavtlar", ""),
            ("tm_ozbekiston_06", "Oʻzbekiston", ""),
            ("tm_ozbekiston_07", "Alisher Navoiy", ""),
        ],
        "The official source states November 1984 but not a day.",
    )
    add_batch(
        "Oʻzbekiston line", "1987-11", "month", "ozbekiston_1987_11",
        LEGACY_SOURCE, government,
        [
            ("tm_ozbekiston_02", "Mashinasozlar", ""),
            ("tm_ozbekiston_01", "Do'stlik", ""),
        ],
        "The official source states November 1987 but not a day.",
    )
    add_batch(
        "Oʻzbekiston line", "1989-11", "month", "ozbekiston_1989_11",
        LEGACY_SOURCE, government,
        [
            ("tm_ozbekiston_08", "G'afur G'ulom", ""),
            ("tm_ozbekiston_09", "Chorsu", ""),
        ],
        "The official source states November 1989 but not a day.",
    )
    add_batch(
        "Oʻzbekiston line", "1991-04-30", "day", "ozbekiston_1991_04_30",
        LEGACY_SOURCE, government,
        [
            ("tm_ozbekiston_10", "Tinchlik", ""),
            ("tm_ozbekiston_11", "Beruniy", ""),
        ],
        "Official history identifies the two-station fourth-stage opening.",
    )
    add_batch(
        "Yunusobod line", "2001-10-26", "day", "yunusobod_2001_10_26",
        LEGACY_SOURCE, government,
        [
            ("tm_yunusobod_01", "Mingoʻrik", ""),
            ("tm_yunusobod_02", "Yunus Rajabiy", ""),
            ("tm_yunusobod_03", "Abdulla Qodiriy", ""),
            ("tm_yunusobod_04", "Minor", ""),
            ("tm_yunusobod_05", "Bodomzor", ""),
            ("tm_yunusobod_06", "Shahriston", "Habib Abdullayev"),
        ],
        "Official history identifies the six-station first-stage opening.",
    )
    add_batch(
        "Yunusobod line", "2020-08-29", "day", "yunusobod_2020_08_29",
        YUNUSOBOD_2020_SOURCE, railway,
        [
            ("tm_yunusobod_07", "Yunusobod", ""),
            ("tm_yunusobod_08", "Turkiston", ""),
        ],
        "Official passenger notice states service began at 16:30.",
    )
    add_batch(
        "Circle line", "2020-08-29", "day", "circle_2020_08_29",
        CIRCLE_2020_SOURCE, president,
        [
            ("tm_circle_01", "Texnopark", "Doʻstlik-2"),
            ("tm_circle_02", "Yashnobod", ""),
            ("tm_circle_03", "Tuzel", ""),
            ("tm_circle_04", "Olmos", ""),
            ("tm_circle_05", "Rohat", ""),
            ("tm_circle_06", "Yangiobod", ""),
            ("tm_circle_07", "Qo‘yliq", ""),
        ],
        "Official launch record gives the seven-station Doʻstlik-2–Qoʻyliq stage.",
    )
    add_batch(
        "Sergeli line", "2020-12-26", "day", "sergeli_2020_12_26",
        SERGELI_2020_SOURCE, president,
        [
            ("tm_sergeli_01", "Choshtepa", ""),
            ("tm_sergeli_02", "O‘zgarish", ""),
            ("tm_sergeli_03", "Sergeli", ""),
            ("tm_sergeli_04", "Yangihayot", ""),
            ("tm_sergeli_05", "Chinor", ""),
        ],
        "Official launch record covers the five-station Sergeli line.",
    )
    add_batch(
        "Circle line", "2023-04-25", "day", "circle_2023_04_25",
        CIRCLE_2023_SOURCE, railway,
        [
            ("tm_circle_08", "Matonat", ""),
            ("tm_circle_09", "Qiyot", ""),
            ("tm_circle_10", "Tolarik", ""),
            ("tm_circle_11", "Xonobod", ""),
            ("tm_circle_12", "Quruvchilar", ""),
        ],
        "Official record states the five-station Qoʻyliq–Quruvchilar opening.",
    )
    add_batch(
        "Circle line", "2024-03-11", "day", "circle_2024_03_11",
        CIRCLE_2024_SOURCE, government,
        [
            ("tm_circle_13", "Turon", ""),
            ("tm_circle_14", "Qipchok", ""),
        ],
        "Official notice distinguishes passenger opening from earlier test running.",
    )
    return records


def build_station_history() -> pd.DataFrame:
    step("METRO  Build source-backed current-station history")
    current = gpd.read_file(cfg.METRO_STATIONS_FILE).to_crs(cfg.GEOGRAPHIC_CRS)
    if len(current) != 50:
        raise RuntimeError(f"expected 50 current metro stations, got {len(current)}")
    current["match_key"] = current["name"].map(_key)
    if current["match_key"].duplicated().any():
        duplicates = current.loc[current["match_key"].duplicated(False), "name"].tolist()
        raise RuntimeError(f"current station names are not unique after normalization: {duplicates}")

    history = pd.DataFrame(station_records())
    history["match_key"] = history["station_name_current"].map(_key)
    missing = sorted(set(current.match_key) - set(history.match_key))
    unexpected = sorted(set(history.match_key) - set(current.match_key))
    if missing or unexpected:
        raise RuntimeError(
            f"metro history/current mismatch; missing={missing}, unexpected={unexpected}"
        )
    if len(history) != 50 or history.station_id.duplicated().any():
        raise RuntimeError("metro history must contain exactly 50 unique station IDs")

    station_points = current[[
        "match_key", "osm_id", "district_name", "geometry"
    ]].copy()
    station_points["longitude"] = station_points.geometry.x
    station_points["latitude"] = station_points.geometry.y
    station_points = station_points.drop(columns="geometry").rename(
        columns={"osm_id": "current_osm_id"}
    )
    history = history.merge(station_points, on="match_key", validate="one_to_one")
    history = history.drop(columns="match_key").sort_values("station_id").reset_index(drop=True)
    columns = [
        "station_id", "station_name_current", "station_name_historical", "line",
        "opening_date", "opening_year", "date_precision", "opening_batch_id",
        "source_url", "source_provider", "source_quality", "notes",
        "current_osm_id", "district_name", "longitude", "latitude",
    ]
    history[columns].to_csv(
        cfg.METRO_STATION_HISTORY_FILE,
        index=False,
        lineterminator="\n",
        float_format="%.8f",
    )
    log(f"  wrote {len(history)} station rows")
    return history[columns]


def build_timeline(history: pd.DataFrame) -> pd.DataFrame:
    annual = (
        history.groupby("opening_year", as_index=False)
        .agg(
            stations_opened=("station_id", "size"),
            station_names_opened=(
                "station_name_current",
                lambda values: " | ".join(sorted(values)),
            ),
        )
        .sort_values("opening_year")
        .rename(columns={"opening_year": "year"})
    )
    annual["cumulative_station_count"] = annual["stations_opened"].cumsum()
    annual = annual[
        ["year", "stations_opened", "cumulative_station_count", "station_names_opened"]
    ]
    annual.to_csv(cfg.METRO_OPENING_TIMELINE_FILE, index=False, lineterminator="\n")
    log(f"  wrote {len(annual)} opening-year events; final cumulative count 50")
    return annual


def main() -> int:
    cfg.ensure_directories()
    history = build_station_history()
    timeline = build_timeline(history)
    sources = (
        history[["source_url", "source_provider", "source_quality"]]
        .drop_duplicates()
        .sort_values("source_url")
        .to_dict(orient="records")
    )
    update_manifest(
        "metro",
        {
            "role": "primary source-backed station opening history",
            "current_station_source": cfg.METRO_STATIONS_FILE.name,
            "station_count": len(history),
            "opening_year_range": [
                int(history.opening_year.min()), int(history.opening_year.max())
            ],
            "date_precision_counts": dict(sorted(Counter(history.date_precision).items())),
            "source_urls": sources,
            "stations_without_primary_source": int(
                (history.source_quality != "primary").sum()
            ),
            "timeline_final_cumulative_count": int(
                timeline.cumulative_station_count.iloc[-1]
            ),
            "segment_history_implemented": False,
            "historical_name_rule": (
                "Historical aliases are populated only when stated in the cited official "
                "source; blank does not assert that a station never had another name."
            ),
        },
    )
    update_manifest(
        "standardized_temporal_metro_access_specification",
        {
            "metric": "metro_access_pct_standardized",
            "status": "specified_not_computed_in_phase2a",
            "source_placement_rule": (
                "Use the current station-centre point recorded in metro_station_history.csv "
                "for every station and every year; filter stations by opening_year."
            ),
            "pedestrian_network_rule": (
                "Hold the current pedestrian graph fixed in EPSG:32642 for every year."
            ),
            "walking_speed_kmh": cfg.MAIN_WALK_SPEED_KMH,
            "walking_time_minutes": cfg.WALK_TIME_LIMIT_MINUTES,
            "walking_budget_m": cfg.walk_budget_m(cfg.MAIN_WALK_SPEED_KMH),
            "population_weight_rule": (
                "Use uncalibrated annual WorldPop Global 2 R2025A v1 model weights."
            ),
            "geography_version": cfg.TEMPORAL_GEOGRAPHY_VERSION,
            "held_constant": [
                "current pedestrian network",
                "walking speed and threshold",
                "station-centre source placement",
                "routing and cell assignment method",
                "current 12-district fixed geography",
            ],
            "changes_by_year": [
                "stations open by opening_year",
                "annual WorldPop model weights",
            ],
            "current_headline_method": (
                "Entrance-aware current access sources, current calibrated population, "
                "and current pedestrian network; frozen existing outputs."
            ),
            "temporal_method": (
                "Standardized station-centre proxy with the current pedestrian network "
                "held fixed and raw annual WorldPop weights."
            ),
            "historical_reconstruction_claim": False,
            "bus_history_used": False,
        },
    )
    log("\nMetro opening history complete.")
    return 0


if __name__ == "__main__":
    enable_utf8_stdout()
    raise SystemExit(main())
