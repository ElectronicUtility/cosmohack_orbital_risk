"""Audit the age of historical TLEs selected at a reconstruction instant."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.conjunctions import HISTORY
from app.domain import aware


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--at", action="append", required=True, help="UTC ISO timestamp; may be repeated")
    args = parser.parse_args()

    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    results = []
    try:
        for raw_at in args.at:
            at = aware(datetime.fromisoformat(raw_at.replace("Z", "+00:00")))
            ages = [
                float(row[0])
                for row in con.execute(
                    """
                    WITH latest AS (
                        SELECT
                            norad_id,
                            epoch,
                            row_number() OVER (PARTITION BY norad_id ORDER BY epoch DESC) AS rn
                        FROM read_parquet(?)
                        WHERE epoch <= ?
                    )
                    SELECT date_diff('second', epoch, ?), epoch
                    FROM latest
                    WHERE rn = 1 AND norad_id <> 25544
                    """,
                    [str(HISTORY), at, at],
                ).fetchall()
            ]
            ages.sort()

            def percentile(fraction: float) -> float | None:
                if not ages:
                    return None
                index = round((len(ages) - 1) * fraction)
                return ages[index]

            results.append({
                "at": at.isoformat(),
                "candidate_objects": len(ages),
                "age_seconds": {
                    "min": ages[0] if ages else None,
                    "p50": percentile(0.50),
                    "p90": percentile(0.90),
                    "p99": percentile(0.99),
                    "max": ages[-1] if ages else None,
                },
            })
    finally:
        con.close()

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
