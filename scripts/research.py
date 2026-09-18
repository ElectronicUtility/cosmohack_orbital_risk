"""Reproduce event/control and a window-specific comparison from saved source records."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app import ALGORITHM_VERSION
from app.analysis import run
from app.domain import AnalysisRequest, SavedAnalysis
from app.providers import ARCHIVE

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research_results"
OUT.mkdir(exist_ok=True)


def validate(day: str) -> bool:
    """Observed day-level S1 onset, read only after the replay calculation."""
    catalog = (ARCHIVE / "sep_catalog_20241115.html").read_text(encoding="utf-8", errors="replace")
    year, month, date = day.split("-")
    return re.search(rf"{year}\s+{month}/{date}\s+\d{{4}}", catalog) is not None


cases = {
    "event": {"start": "2024-05-10T06:00:00Z", "cutoff": "2024-05-10T00:00:00Z", "hours": 6},
    "control": {"start": "2024-05-02T06:00:00Z", "cutoff": "2024-05-02T00:00:00Z", "hours": 6},
    "window_demo": {"start": "2024-05-05T01:00:00Z", "cutoff": "2024-05-04T23:00:00Z", "hours": 1},
}
summary = {}
for name, case in cases.items():
    request = AnalysisRequest(mode="replay", start=case["start"], cutoff=case["cutoff"],
                              duration_hours=case["hours"], search_hours=12)
    windows, comparison, records = run(request)
    saved = SavedAnalysis(id=uuid.uuid4().hex, request=request, windows=windows,
                          comparison=comparison, created_at=datetime.now(timezone.utc),
                          algorithm_version=ALGORITHM_VERSION, source_records=records)
    (OUT / f"{name}.json").write_text(saved.model_dump_json(indent=2),encoding="utf-8")
    first_weather = windows[0].factors[0]
    first_probability = first_weather.evidence[0]["event"]["value"] if first_weather.evidence else None
    observed = validate(request.start.date().isoformat()) if name != "window_demo" else None
    summary[name] = {
        "cutoff": request.cutoff.isoformat(),
        "baseline": {"method": "Latest issued daily proton probability applied uniformly to every window; no orbit",
                     "probability_percent": first_probability,
                     "attention_each_window": first_probability is not None and first_probability >= 30},
        "full": {"outcome": comparison.outcome,
                 "weather_states": [w.factors[0].state for w in windows],
                 "lighting_overlap_minutes": [w.factors[1].overlap_minutes for w in windows]},
        "validation_after_replay": {"observed_S1_onset_on_start_day": observed,
                                    "brier_baseline": (first_probability/100-int(observed))**2 if observed is not None and first_probability is not None else None,
                                    "brier_full_weather": (first_probability/100-int(observed))**2 if observed is not None and first_probability is not None else None},
        "source_ids": [r.id for r in records],
    }
(OUT / "summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(summary,ensure_ascii=False,indent=2))
