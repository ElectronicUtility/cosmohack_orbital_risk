"""Reproduce event/control and a window-specific comparison from saved source records."""
from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ALGORITHM_VERSION
from app.analysis import run
from app.domain import AnalysisRequest, SavedAnalysis
from app.providers import ARCHIVE
from app.storage import store_analysis
from app.api import export_html

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
                              duration_hours=case["hours"], search_hours=12, requires_sunlight=True)
    windows, comparison, records = run(request)
    saved = SavedAnalysis(id=uuid.uuid4().hex, request=request, windows=windows,
                          comparison=comparison, created_at=datetime.now(timezone.utc),
                          algorithm_version=ALGORITHM_VERSION, source_records=records)
    (OUT / f"{name}.json").write_text(saved.model_dump_json(indent=2),encoding="utf-8")
    store_analysis(saved)
    (OUT / f"{name}.html").write_text(export_html(saved.id).body.decode("utf-8"),encoding="utf-8")
    factors_by_window = [
        {factor.mechanism: factor for factor in window.factors}
        for window in windows
    ]
    first_weather = factors_by_window[0]["space_weather"]
    first_probability = first_weather.evidence[0]["event"]["value"] if first_weather.evidence else None
    observed_onset = validate(request.start.date().isoformat()) if name != "window_demo" else None
    summary[name] = {
        "cutoff": request.cutoff.isoformat(),
        "baseline": {"method": "Latest issued daily proton probability applied uniformly to every window; no orbit",
                     "probability_percent": first_probability},
        "full": {"outcome": comparison.outcome,
                 "decision_mechanisms": comparison.decision_mechanisms,
                 "excluded_mechanisms": comparison.excluded_mechanisms,
                 "factor_states": [
                     {name: factor.state for name, factor in factor_map.items()}
                     for factor_map in factors_by_window
                 ],
                 "weather_probability_percent": [
                     factor_map["space_weather"].comparison_value for factor_map in factors_by_window
                 ],
                 "conjunction_min_separation_km": [
                     factor_map["conjunctions"].comparison_value for factor_map in factors_by_window
                 ],
                 "conjunction_decision_eligible": [
                     factor_map["conjunctions"].decision_eligible for factor_map in factors_by_window
                 ],
                 "lighting_overlap_minutes": [
                     factor_map["lighting"].overlap_minutes for factor_map in factors_by_window
                 ],
                 "lighting_decision_eligible": [
                     factor_map["lighting"].decision_eligible for factor_map in factors_by_window
                 ]},
        "validation_after_replay": {"observed_S1_onset_on_start_day": observed_onset,
                                    "note": "Onset catalog does not establish every day above the S1 threshold; no probability score is calculated."},
        "source_ids": [r.id for r in records],
    }
(OUT / "summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(summary,ensure_ascii=False,indent=2))
