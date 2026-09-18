"""Run a reproducible sanity check of the historical conjunction reconstruction."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.conjunctions import historical_conjunction_source_record, reconstruct_historical_conjunctions
from app.domain import Window, aware


def parse_time(value: str) -> datetime:
    return aware(datetime.fromisoformat(value.replace("Z", "+00:00")))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-05-10T06:00:00Z")
    parser.add_argument("--end", default="2024-05-10T08:00:00Z")
    args = parser.parse_args()
    window = Window(start=parse_time(args.start), end=parse_time(args.end))
    record = historical_conjunction_source_record()

    started = time.perf_counter()
    events, metadata = reconstruct_historical_conjunctions(window, record.id)
    elapsed = time.perf_counter() - started

    print(json.dumps({
        "elapsed_seconds": round(elapsed, 3),
        "event_count": len(events),
        "metadata": metadata,
        "events": [event.model_dump(mode="json") for event in events],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
