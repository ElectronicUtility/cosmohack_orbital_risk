"""Probe the public 2024 TLE history for objects near the ISS orbital regime.

This is a research/data-availability probe, not runtime business logic.  The
selection is deliberately broad and is used only to estimate whether a local
historical conjunction reconstruction dataset is practical.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb


SOURCE = (
    "https://huggingface.co/datasets/juliensimon/space-track-tle-history/resolve/"
    "8adc73511d84b3a1cd90ba15b2b774eda282ec89/data/tle_2024.parquet"
)
REVISION = "8adc73511d84b3a1cd90ba15b2b774eda282ec89"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "conjunctions" / "tle_candidates_2024_may_june.parquet"
PROVENANCE = ROOT / "data" / "conjunctions" / "provenance.json"
RADIAL_PREDICATE = (
    "((6378.137 + altitude_km) * (1 - eccentricity) - 6378.137) <= 460 "
    "AND ((6378.137 + altitude_km) * (1 + eccentricity) - 6378.137) >= 380"
)


def export(con: duckdb.DuckDBPyConnection) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    target = OUT.as_posix().replace("'", "''")
    query = f"""
        COPY (
            WITH period AS (
                SELECT * FROM read_parquet('{SOURCE}')
                WHERE epoch >= TIMESTAMP '2024-04-29'
                  AND epoch < TIMESTAMP '2024-07-02'
            ), candidate_ids AS (
                SELECT DISTINCT norad_id FROM period WHERE {RADIAL_PREDICATE}
            )
            SELECT p.norad_id, p.epoch, p.inclination, p.raan, p.eccentricity,
                   p.arg_perigee, p.mean_anomaly, p.mean_motion,
                   p.mean_motion_dot, p.bstar, p.intl_designator, p.altitude_km
            FROM period p JOIN candidate_ids c USING (norad_id)
            ORDER BY p.norad_id, p.epoch
        ) TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """
    con.execute(query)
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    rows, objects = con.execute(
        "SELECT count(*), count(DISTINCT norad_id) FROM read_parquet(?)", [str(OUT)]
    ).fetchone()
    PROVENANCE.write_text(json.dumps({
        "source": "https://huggingface.co/datasets/juliensimon/space-track-tle-history",
        "source_file": "data/tle_2024.parquet",
        "source_revision": REVISION,
        "local_file": OUT.relative_to(ROOT).as_posix(),
        "local_sha256": digest,
        "rows": rows,
        "objects": objects,
        "period": "2024-04-29T00:00:00Z/2024-07-02T00:00:00Z",
        "selection": "objects with at least one element whose orbital radial range intersects 380-460 km; all period elements retained for each selected object",
        "publication_time": None,
        "classification": "historical reconstruction only",
        "limitation": "Individual element publication times and covariance are unavailable; this extract cannot support strict point-in-time collision probability replay."
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("exported", rows, "rows", objects, "objects", OUT.stat().st_size, "bytes", digest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()
    con = duckdb.connect()
    predicates = {
        "iss_like_inclination_300_550": "altitude_km BETWEEN 300 AND 550 AND inclination BETWEEN 45 AND 60",
        "all_inclinations_300_550": "altitude_km BETWEEN 300 AND 550",
        "all_inclinations_350_500": "altitude_km BETWEEN 350 AND 500",
        "radial_band_crosses_300_550": (
            "((6378.137 + altitude_km) * (1 - eccentricity) - 6378.137) <= 550 "
            "AND ((6378.137 + altitude_km) * (1 + eccentricity) - 6378.137) >= 300"
        ),
        "radial_band_crosses_350_500": (
            "((6378.137 + altitude_km) * (1 - eccentricity) - 6378.137) <= 500 "
            "AND ((6378.137 + altitude_km) * (1 + eccentricity) - 6378.137) >= 350"
        ),
        "radial_band_crosses_380_460": (
            "((6378.137 + altitude_km) * (1 - eccentricity) - 6378.137) <= 460 "
            "AND ((6378.137 + altitude_km) * (1 + eccentricity) - 6378.137) >= 380"
        ),
    }
    for name, predicate in predicates.items():
        query = f"""
            SELECT count(*) AS rows, count(DISTINCT norad_id) AS objects
            FROM read_parquet(?)
            WHERE epoch >= TIMESTAMP '2024-04-29'
              AND epoch < TIMESTAMP '2024-07-02'
              AND {predicate}
        """
        print(name, con.execute(query, [SOURCE]).fetchall()[0])
    if args.export:
        export(con)


if __name__ == "__main__":
    main()
