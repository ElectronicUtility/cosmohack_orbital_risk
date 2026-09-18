from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from . import ALGORITHM_VERSION
from .domain import AnalysisRequest, Comparison, FactorAssessment, Window, WindowAssessment
from .orbit import in_earth_shadow, trajectory
from .providers import archived_weather, current_tle, current_weather, ISS_ARCHIVE
from .storage import store_raw


def intersection_minutes(a: Window, start: datetime, end: datetime) -> float:
    return max(0.0, (min(a.end, end) - max(a.start, start)).total_seconds() / 60)


def weather_assessment(window: Window, events, status, cutoff=None):
    if cutoff is not None:
        events = [e for e in events if e.published_at <= cutoff]
    covered = 0.0
    weighted = 0.0
    evidence = []
    for e in events:
        overlap = intersection_minutes(window, e.valid_start, e.valid_end)
        if overlap <= 0:
            continue
        covered += overlap
        weighted += overlap * e.value
        evidence.append({"event": e.model_dump(mode="json"), "overlap_minutes": overlap,
                         "rule": "Experimental attention threshold on a daily external probability; not EVA risk."})
    minutes = window.duration.total_seconds() / 60
    complete = covered >= minutes - 0.01
    threshold = float(os.getenv("EXPERIMENTAL_S1_ATTENTION_PERCENT", "30"))
    mean = weighted / covered if covered else None
    stale = status in {"stale", "disabled", "missing", "invalid"}
    return FactorAssessment(
        mechanism="space_weather", state="insufficient" if not complete or stale else (
            "attention" if mean is not None and mean >= threshold else "forecast_below_experimental_threshold"),
        covered_minutes=min(minutes, covered), overlap_minutes=covered if complete and mean is not None and mean >= threshold else 0 if complete else None,
        completeness="complete" if complete else "partial_or_absent", freshness=status,
        evidence=evidence, algorithm_version=ALGORITHM_VERSION,
        limitations=["Forecast probability is not observed astronaut radiation dose.",
                     f"Attention threshold {threshold:g}% is experimental, configurable, and not an EVA operating limit."]
        + (["Provider is unavailable or cache is stale; no favorable conclusion."] if stale else [])
    )


def lighting_assessment(window: Window, states, requires_sunlight):
    total = window.duration.total_seconds() / 60
    if not states or states[0].at != window.start or states[-1].at != window.end:
        return FactorAssessment(mechanism="lighting", state="insufficient", covered_minutes=0,
            overlap_minutes=None, completeness="partial_or_absent", freshness="orbit_missing",
            algorithm_version=ALGORITHM_VERSION, limitations=["No suitable ISS elements for the full window."])
    dark = 0.0
    intervals = []
    for a, b in zip(states, states[1:]):
        # Interval classification at midpoint avoids interpreting an endpoint as a whole segment.
        if in_earth_shadow(a):
            minutes = (b.at - a.at).total_seconds() / 60
            dark += minutes
            intervals.append({"start": a.at.isoformat(), "end": b.at.isoformat(), "minutes": minutes})
    return FactorAssessment(mechanism="lighting",
        state="attention" if requires_sunlight and dark > 0 else "no_restriction_detected",
        covered_minutes=total, overlap_minutes=dark if requires_sunlight else 0,
        completeness="complete", freshness="historical_reconstruction" if states[0].classification.startswith("historical") else "current",
        evidence=[{"quantity": "Earth-shadow interval", "unit": "minutes", "value": dark,
                   "intervals": intervals, "orbit_record": states[0].raw_record_id,
                   "orbit_epoch": states[0].epoch.isoformat(), "source": states[0].source_url,
                   "rule": "Earth-shadow geometry; relevant only when the plan requires direct sunlight."}],
        limitations=["Solar vector and cylindrical Earth shadow are approximate.",
                     "Illumination is an operational constraint, not a standalone claim of danger.",
                     "Historical orbital elements have no verified publication time; geometry is reconstruction."] if states[0].classification.startswith("historical") else
                    ["Solar vector and cylindrical Earth shadow are approximate.",
                     "Illumination is an operational constraint, not a standalone claim of danger."],
        algorithm_version=ALGORITHM_VERSION)


def evaluate(window: Window, events, weather_status, orbit_mode, current_orbit=None, cutoff=None, requires_sunlight=True):
    states = trajectory(window, orbit_mode, current_orbit)
    factors = [weather_assessment(window, events, weather_status, cutoff),
               lighting_assessment(window, states, requires_sunlight)]
    return WindowAssessment(window=window, factors=factors, orbit=states,
                            limitations=["Историческая геометрия — реконструкция; её доступность на момент cutoff не подтверждена."] if orbit_mode != "current" else [])


def compare(windows: list[WindowAssessment]) -> Comparison:
    if len(windows) < 2 or len({w.window.duration for w in windows}) != 1:
        raise ValueError("Comparison requires at least two equal-duration windows")
    if any(any(f.state == "insufficient" for f in w.factors) for w in windows):
        return Comparison(outcome="insufficient", reasons=["Хотя бы для одного фактора нет полного и актуального покрытия сравниваемого окна."],
                          algorithm_version=ALGORITHM_VERSION)
    # Pareto dominance. No scalar score or cross-mechanism compensation.
    values = [[f.overlap_minutes or 0 for f in w.factors] for w in windows]
    epsilon = float(os.getenv("EXPERIMENTAL_COMPARISON_EPSILON_MINUTES", "10"))
    frontier = [i for i, a in enumerate(values) if not any(j != i and
                all(y <= x + epsilon for x, y in zip(a, b)) and any(y < x - epsilon for x, y in zip(a, b))
                for j, b in enumerate(values))]
    if len(frontier) == 1:
        i = frontier[0]
        return Comparison(outcome="preferred", preferred_index=i,
                          reasons=[f"В окне {i+1} пересечение ни с одним фактором не длиннее, а хотя бы с одним короче (экспериментальный допуск {epsilon:g} мин)."],
                          algorithm_version=ALGORITHM_VERSION)
    if all(all(abs(x-y) <= epsilon for x,y in zip(values[frontier[0]],values[i])) for i in frontier):
        return Comparison(outcome="equivalent", reasons=[f"Лучшие окна различаются не более чем на экспериментальный допуск {epsilon:g} мин."],
                          algorithm_version=ALGORITHM_VERSION)
    return Comparison(outcome="tradeoff", reasons=["Факторы указывают на разные окна; веса для их произвольного сложения не вводились."],
                      algorithm_version=ALGORITHM_VERSION)


def run(request: AnalysisRequest):
    starts = [request.start]
    starts += [request.start + timedelta(hours=request.search_hours / 2),
               request.start + timedelta(hours=request.search_hours)]
    windows = [Window(start=s, end=s + timedelta(hours=request.duration_hours)) for s in starts]
    if request.mode == "current":
        events, weather_records, weather_status = current_weather(request.refresh)
        orbit_input, orbit_records, _ = current_tle(request.refresh)
        cutoff = None
    else:
        cutoff = request.cutoff if request.mode == "replay" else max(w.end for w in windows)
        events, weather_records, weather_status = archived_weather(cutoff, min(w.start for w in windows), max(w.end for w in windows))
        orbit_input = None
        orbit_records = [store_raw("iss_history_extract",
                          "https://huggingface.co/datasets/juliensimon/space-track-tle-history",
                          ISS_ARCHIVE.read_bytes(), cache_state="archived")]
    results = [evaluate(w, events, weather_status, request.mode.value, orbit_input,
                        cutoff if request.mode == "replay" else None, request.requires_sunlight) for w in windows]
    return results, compare(results), weather_records + orbit_records
