from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from . import ALGORITHM_VERSION
from .conjunctions import historical_conjunction_source_record, reconstruct_historical_conjunctions
from .domain import AnalysisRequest, Comparison, FactorAssessment, Window, WindowAssessment
from .orbit import in_earth_shadow, trajectory
from .providers import archived_weather, current_conjunctions, current_tle, current_weather, ISS_ARCHIVE
from .storage import store_raw


def intersection_minutes(a: Window, start: datetime, end: datetime) -> float:
    return max(0.0, (min(a.end, end) - max(a.start, start)).total_seconds() / 60)


def weather_assessment(window: Window, events, status, cutoff=None):
    if cutoff is not None:
        events = [e for e in events if e.published_at <= cutoff]
    decision_events = [e for e in events if e.kind == "external_forecast" and e.unit == "%"]
    context_events = [e for e in events if e.kind == "external_forecast_context"]
    covered = 0.0
    probabilities = []
    quantities = []
    evidence = []
    for e in decision_events:
        overlap = intersection_minutes(window, e.valid_start, e.valid_end)
        if overlap <= 0:
            continue
        covered += overlap
        probabilities.append(e.value)
        quantities.append(e.quantity)
        evidence.append({"event": e.model_dump(mode="json"), "forecast_validity_overlap_minutes": overlap,
                         "rule": "Daily event probability applies to the UTC day, not to an EVA interval or its duration."})
    for e in context_events:
        overlap = intersection_minutes(window, e.valid_start, e.valid_end)
        if overlap <= 0:
            continue
        evidence.append({
            "event": e.model_dump(mode="json"),
            "forecast_validity_overlap_minutes": overlap,
            "role": "forecast_context_only",
            "rule": (
                "Three-hour Kp expresses expected geomagnetic evolution. It is shown as forecast context and is not "
                "converted into EVA dose, treated as an independent factor, or added to the S1 probability."
            ),
        })
    minutes = window.duration.total_seconds() / 60
    complete = covered >= minutes - 0.01
    threshold = float(os.getenv("EXPERIMENTAL_S1_ATTENTION_PERCENT", "30"))
    uniform_probability = probabilities[0] if probabilities and len(set(probabilities)) == 1 else None
    uniform_quantity = quantities[0] if quantities and len(set(quantities)) == 1 else None
    stale = status in {"stale", "disabled", "missing", "invalid"}
    forecast_horizon_hours = None
    if events:
        forecast_horizon_hours = max(
            max(0.0, (e.valid_end - e.published_at).total_seconds() / 3600)
            for e in events
        )
    return FactorAssessment(
        mechanism="space_weather", role="risk_mechanism", state="insufficient" if not complete or stale else (
            "attention" if probabilities and max(probabilities) >= threshold else "forecast_below_experimental_threshold"),
        covered_minutes=min(minutes, covered), overlap_minutes=None,
        forecast_probability_percent=uniform_probability if complete and uniform_quantity else None,
        forecast_horizon_hours=forecast_horizon_hours,
        forecast_temporal_resolution=(
            "3 hours for planetary Kp context; 1 UTC day for solar-radiation probability"
            if context_events else "1 UTC day"
        ),
        forecast_basis=(
            "NOAA/USAF published solar-radiation probability; NOAA 3-hour planetary Kp is context-only"
            if context_events else "NOAA/USAF published daily solar-radiation event probability"
        ),
        comparison_value=uniform_probability if complete and uniform_quantity else None,
        comparison_unit="daily_probability_percent", comparison_quantity=uniform_quantity,
        comparison_direction="lower_is_better", comparison_tolerance=0,
        completeness="complete" if complete else "partial_or_absent", freshness=status,
        evidence=evidence, algorithm_version=ALGORITHM_VERSION,
        limitations=["Forecast validity coverage is not duration of adverse conditions; that duration is unknown.",
                     "Daily probability is not the probability of exposure in this particular EVA window or an observed astronaut dose.",
                     "Three-hour planetary Kp, when present, is forecast context only and is not mapped to EVA dose or double-counted as a second risk factor.",
                     "When a window spans different daily probabilities, the prototype does not invent a rule to collapse them into one value.",
                     "S1+ and RSGA Proton are distinct forecast quantities and cannot be compared as identical percentages.",
                     f"Attention threshold {threshold:g}% is experimental, configurable, and not an EVA operating limit."]
        + (["Provider is unavailable or cache is stale; no favorable conclusion."] if stale else [])
    )


def conjunction_assessment(window: Window, events, status, coverage=None, reconstruction_meta=None,
                           strict_replay=False, source_as_of: datetime | None = None):
    total = window.duration.total_seconds() / 60
    unavailable = status in {"stale", "disabled", "missing", "invalid", "truncated"}
    historical = reconstruction_meta is not None
    decision_eligible = not historical
    forecast_horizon_hours = None
    supports_next_6h_horizon = None
    forecast_semantics = None
    if not historical and coverage and source_as_of is not None:
        forecast_horizon_hours = max(0.0, (coverage[1] - source_as_of).total_seconds() / 3600)
        supports_next_6h_horizon = (
            status in {"fresh", "cached"}
            and coverage[0] <= source_as_of
            and coverage[1] >= source_as_of + timedelta(hours=6)
        )
        forecast_semantics = {
            "source_as_of": source_as_of.isoformat(),
            "forecast_interval_start": coverage[0].isoformat(),
            "forecast_interval_end": coverage[1].isoformat(),
            "forecast_horizon_hours": forecast_horizon_hours,
            "supports_next_6h_horizon": supports_next_6h_horizon,
            "interpretation": (
                "SOCRATES predicts conjunction geometry over its computation interval. "
                "This horizon is distinct from the temporal resolution of NOAA daily probabilities."
            ),
        }
    eligibility_reason = (
        "Historical conjunction geometry is reconstruction/validation only: per-element publication time and catalog completeness at the historical instant are unproven."
        if historical else None
    )
    if historical:
        complete = reconstruction_meta.get("status") == "historical_reconstruction"
    else:
        complete = bool(coverage and coverage[0] <= window.start and coverage[1] >= window.end)
    if unavailable or not complete:
        return FactorAssessment(
            mechanism="conjunctions", role="risk_mechanism", state="insufficient",
            decision_eligible=decision_eligible,
            eligibility_reason=eligibility_reason,
            covered_minutes=0 if not complete else total, overlap_minutes=None,
            forecast_horizon_hours=forecast_horizon_hours,
            supports_next_6h_horizon=supports_next_6h_horizon,
            forecast_temporal_resolution=(
                "propagated conjunction geometry with reported TCA timestamps" if not historical else None
            ),
            forecast_basis=(
                "CelesTrak SOCRATES next-seven-day conjunction screen" if not historical else None
            ),
            comparison_value=None, comparison_unit="minimum_modeled_separation_km",
            comparison_quantity="ISS-object minimum modeled separation",
            comparison_direction="higher_is_better", comparison_tolerance=0,
            completeness="partial_or_absent", freshness=status,
            evidence=([{"coverage": [t.isoformat() for t in coverage],
                        "forecast_semantics": forecast_semantics}] if coverage else []),
            limitations=["Conjunction source does not fully cover the requested window; no favorable conclusion."],
            algorithm_version=ALGORITHM_VERSION,
        )

    relevant = [event for event in events if window.start <= event.tca <= window.end]
    threshold = 5.0
    ambiguous = [event for event in relevant if event.classification == "historical_persistent_proximity_ambiguous"]
    if ambiguous:
        minimum = None
        state = "ambiguous_persistent_proximity"
    elif relevant:
        minimum = min(event.min_separation_km for event in relevant)
        state = "reconstructed_close_approach" if historical else "reported_close_approach"
    else:
        # Current SOCRATES explicitly screens its computation interval at 5 km.
        # Historical public-TLE reconstruction cannot prove catalog completeness,
        # so absence of an event must not become a favorable lower bound.
        minimum = None if historical else threshold
        state = "no_reconstructed_close_approach_within_screen" if historical else "no_reported_close_approach_within_screen"

    evidence = [{"event": event.model_dump(mode="json")} for event in relevant]
    evidence.append({
        "screening_threshold_km": threshold,
        "coverage": ([coverage[0].isoformat(), coverage[1].isoformat()] if coverage else
                     [window.start.isoformat(), window.end.isoformat()]),
        "reconstruction": reconstruction_meta,
        "forecast_semantics": forecast_semantics,
        "rule": "Compare the minimum modeled/reported separation directly; no cross-factor scalar risk score is created.",
    })
    limitations = [
        "The 5 km value is a conjunction screening threshold, not an EVA safety or operating limit.",
        "No reported/reconstructed approach inside 5 km does not imply zero debris risk.",
        "Orbital conjunction probability is not the probability of a fragment striking an EVA crewmember.",
    ]
    if historical:
        limitations += [
            "Historical result is a TLE geometry reconstruction, not an archived SOCRATES report.",
            "No covariance is available, so collision probability is not calculated.",
            "Individual historical TLE publication times are unavailable; this mechanism is excluded from strict point-in-time replay claims.",
            "Candidate catalog completeness at the historical instant cannot be proven from this public mirror.",
            "ISS and object elements are selected at the window start and held fixed through the window; element turnover inside the window is exposed as a sensitivity diagnostic, not converted into a probability.",
            "If no historical encounter is reconstructed inside the screen, no favorable comparison value is assigned.",
        ]
    if ambiguous:
        limitations.append(
            "At least one object remains persistently close in the reconstructed geometry and lacks enough identity/context to classify it as an independent debris encounter; no comparison value is assigned."
        )
    return FactorAssessment(
        mechanism="conjunctions", role="risk_mechanism", state=state,
        decision_eligible=decision_eligible,
        eligibility_reason=eligibility_reason,
        covered_minutes=total, overlap_minutes=None,
        forecast_horizon_hours=forecast_horizon_hours,
        supports_next_6h_horizon=supports_next_6h_horizon,
        forecast_temporal_resolution=(
            "propagated conjunction geometry with reported TCA timestamps" if not historical else None
        ),
        forecast_basis=(
            "CelesTrak SOCRATES next-seven-day conjunction screen" if not historical else None
        ),
        comparison_value=minimum, comparison_unit="minimum_modeled_separation_km",
        comparison_quantity="ISS-object minimum modeled separation",
        comparison_direction="higher_is_better", comparison_tolerance=0,
        completeness="reconstruction_unverified_catalog_completeness" if historical else "complete",
        freshness="historical_reconstruction_publication_unknown" if historical else status,
        evidence=evidence, limitations=limitations, algorithm_version=ALGORITHM_VERSION,
    )


def lighting_assessment(window: Window, states, requires_sunlight, provider_status="current", strict_replay=False):
    total = window.duration.total_seconds() / 60
    historical = bool(states and states[0].classification.startswith("historical"))
    eligible = requires_sunlight and not (historical and strict_replay)
    if not requires_sunlight:
        eligibility_reason = "Direct sunlight was not declared by the analyst as a planning constraint."
    elif historical and strict_replay:
        eligibility_reason = "Historical orbital-element publication times are unavailable, so lighting geometry is validation-only in strict replay."
    else:
        eligibility_reason = None
    if not states or states[0].at != window.start or states[-1].at != window.end:
        return FactorAssessment(mechanism="lighting", role="plan_constraint", state="insufficient", covered_minutes=0,
            decision_eligible=eligible, eligibility_reason=eligibility_reason,
            overlap_minutes=None, completeness="partial_or_absent", freshness="orbit_missing",
            algorithm_version=ALGORITHM_VERSION, limitations=["No suitable ISS elements for the full window."])
    dark = 0.0
    intervals = []
    for a, b in zip(states, states[1:]):
        midpoint = a.model_copy(update={
            "at": a.at + (b.at - a.at) / 2,
            "position_teme_km": tuple((x + y) / 2 for x, y in zip(a.position_teme_km, b.position_teme_km)),
        })
        if in_earth_shadow(midpoint):
            minutes = (b.at - a.at).total_seconds() / 60
            dark += minutes
            intervals.append({"start": a.at.isoformat(), "end": b.at.isoformat(), "minutes": minutes})
    unavailable = provider_status in {"stale", "disabled", "missing", "invalid"}
    return FactorAssessment(mechanism="lighting", role="plan_constraint",
        decision_eligible=eligible, eligibility_reason=eligibility_reason,
        state=("not_requested" if not requires_sunlight else
               "insufficient" if unavailable else
               "attention" if dark > 0 else "no_restriction_detected"),
        covered_minutes=total, overlap_minutes=dark if requires_sunlight else None,
        comparison_value=dark if requires_sunlight else None, comparison_unit="minutes_of_plan_constraint",
        comparison_quantity="Earth-shadow minutes requiring direct sunlight",
        comparison_direction="lower_is_better",
        comparison_tolerance=float(os.getenv("EXPERIMENTAL_LIGHTING_EQUIVALENCE_MINUTES", "0")),
        completeness="complete" if not unavailable else "stale_or_unavailable",
        freshness="historical_reconstruction" if states[0].classification.startswith("historical") else provider_status,
        evidence=[{"quantity": "Earth-shadow interval", "unit": "minutes", "value": dark,
                   "intervals": intervals, "orbit_records": sorted({s.raw_record_id for s in states}),
                   "orbit_epochs": sorted({s.epoch.isoformat() for s in states}), "source": states[0].source_url,
                   "rule": "Earth-shadow geometry; relevant only when the plan requires direct sunlight."}],
        limitations=(["Orbit provider is unavailable or stale; no favorable conclusion."] if unavailable else []) + (["Solar vector and cylindrical Earth shadow are approximate.",
                     "Illumination is an operational constraint, not a standalone claim of danger.",
                     "Historical orbital elements have no verified publication time; geometry is reconstruction."] if states[0].classification.startswith("historical") else
                    ["Solar vector and cylindrical Earth shadow are approximate.",
                     "Illumination is an operational constraint, not a standalone claim of danger."]),
        algorithm_version=ALGORITHM_VERSION)


def evaluate(window: Window, events, weather_status, orbit_mode, current_orbit=None, cutoff=None,
             requires_sunlight=False, orbit_status="current", conjunction_events=None,
             conjunction_status="missing", conjunction_coverage=None, conjunction_meta=None,
             strict_replay=False, conjunction_source_as_of: datetime | None = None):
    states = trajectory(window, orbit_mode, current_orbit)
    factors = [weather_assessment(window, events, weather_status, cutoff),
               conjunction_assessment(window, conjunction_events or [], conjunction_status,
                                      conjunction_coverage, conjunction_meta, strict_replay,
                                      conjunction_source_as_of),
               lighting_assessment(window, states, requires_sunlight, orbit_status, strict_replay)]
    limitation = (
        "Историческая орбита и сближения — реконструкция; их доступность на момент cutoff не подтверждена. "
        "Для геометрии используется единый снимок элементов на начало каждого окна, без скрытого переключения TLE внутри окна. "
        "В strict replay они показываются как validation/reconstruction и не участвуют в решении, пока их доступность к cutoff не доказана."
    )
    return WindowAssessment(window=window, factors=factors, orbit=states,
                            limitations=[limitation] if orbit_mode != "current" else [])


def compare(windows: list[WindowAssessment]) -> Comparison:
    if len(windows) < 2 or len({w.window.duration for w in windows}) != 1:
        raise ValueError("Comparison requires at least two equal-duration windows")
    excluded = []
    seen_excluded = set()
    for window in windows:
        for factor in window.factors:
            if not factor.decision_eligible:
                key = (factor.mechanism, factor.eligibility_reason)
                if key not in seen_excluded:
                    excluded.append({"mechanism": factor.mechanism, "reason": factor.eligibility_reason})
                    seen_excluded.add(key)
    if any(any(f.decision_eligible and f.state == "insufficient" for f in w.factors) for w in windows):
        mechanisms = sorted({f.mechanism for w in windows for f in w.factors if f.decision_eligible})
        return Comparison(outcome="insufficient", reasons=["Хотя бы для одного фактора нет полного и актуального покрытия сравниваемого окна."],
                          decision_mechanisms=mechanisms, excluded_mechanisms=excluded,
                          algorithm_version=ALGORITHM_VERSION)
    eligible_factors = [[factor for factor in window.factors if factor.decision_eligible] for window in windows]
    if any(len({factor.mechanism for factor in factors}) != len(factors) for factors in eligible_factors):
        return Comparison(outcome="insufficient", reasons=["В одном из окон один и тот же механизм представлен более одного раза; сравнение неоднозначно."],
                          decision_mechanisms=sorted({factor.mechanism for factors in eligible_factors for factor in factors}),
                          excluded_mechanisms=excluded, algorithm_version=ALGORITHM_VERSION)
    factor_maps = [{factor.mechanism: factor for factor in factors} for factors in eligible_factors]
    if any(not mapping for mapping in factor_maps):
        return Comparison(outcome="insufficient", reasons=["Нет ни одного фактора с доказанной пригодностью для принятия решения в этом режиме."],
                          decision_mechanisms=[], excluded_mechanisms=excluded, algorithm_version=ALGORITHM_VERSION)
    mechanisms = list(factor_maps[0])
    if any(set(mapping) != set(mechanisms) for mapping in factor_maps):
        return Comparison(outcome="insufficient", reasons=["Набор факторов различается между окнами."],
                          decision_mechanisms=mechanisms, excluded_mechanisms=excluded,
                          algorithm_version=ALGORITHM_VERSION)
    for name in mechanisms:
        signatures = {(mapping[name].comparison_unit, mapping[name].comparison_direction,
                       mapping[name].comparison_quantity) for mapping in factor_maps}
        if len(signatures) != 1:
            return Comparison(outcome="insufficient", reasons=[f"Механизм {name} имеет несовместимые величины, единицы или направление сравнения между окнами."],
                              decision_mechanisms=mechanisms, excluded_mechanisms=excluded,
                              algorithm_version=ALGORITHM_VERSION)
    if any(mapping[name].comparison_value is None for mapping in factor_maps for name in mechanisms):
        return Comparison(outcome="insufficient", reasons=["Хотя бы один фактор нельзя честно свести к сопоставимому значению для этого окна."],
                          decision_mechanisms=mechanisms, excluded_mechanisms=excluded,
                          algorithm_version=ALGORITHM_VERSION)

    def normalized(factor: FactorAssessment) -> float:
        value = float(factor.comparison_value)
        return value if factor.comparison_direction == "lower_is_better" else -value

    def dominates(a_index: int, b_index: int) -> bool:
        no_worse = True
        strictly_better = False
        for name in mechanisms:
            a = factor_maps[a_index][name]
            b = factor_maps[b_index][name]
            if a.comparison_unit != b.comparison_unit or a.comparison_direction != b.comparison_direction:
                return False
            tolerance = max(a.comparison_tolerance, b.comparison_tolerance)
            av, bv = normalized(a), normalized(b)
            if av > bv + tolerance:
                no_worse = False
                break
            if av < bv - tolerance:
                strictly_better = True
        return no_worse and strictly_better

    frontier = [i for i in range(len(windows)) if not any(j != i and dominates(j, i) for j in range(len(windows)))]
    if len(frontier) == 1:
        i = frontier[0]
        return Comparison(outcome="preferred", preferred_index=i, pareto_frontier_indices=frontier,
                          reasons=[f"Окно {i+1} Парето-доминирует: ни один сопоставимый фактор не хуже за пределами своего допуска, а хотя бы один лучше."],
                          decision_mechanisms=mechanisms, excluded_mechanisms=excluded,
                          algorithm_version=ALGORITHM_VERSION)
    def equivalent(a_index: int, b_index: int) -> bool:
        for name in mechanisms:
            a = factor_maps[a_index][name]
            b = factor_maps[b_index][name]
            tolerance = max(a.comparison_tolerance, b.comparison_tolerance)
            if abs(float(a.comparison_value) - float(b.comparison_value)) > tolerance:
                return False
        return True

    if all(equivalent(frontier[0], i) for i in frontier):
        dominated = [i for i in range(len(windows)) if i not in frontier]
        reason = (
            "Окна на Парето-фронте " + ", ".join(str(i + 1) for i in frontier)
            + " эквивалентны в пределах явно заданных допусков."
        )
        if dominated:
            reason += " Парето-доминируемые окна: " + ", ".join(str(i + 1) for i in dominated) + "."
        return Comparison(outcome="equivalent", pareto_frontier_indices=frontier, reasons=[reason],
                          decision_mechanisms=mechanisms, excluded_mechanisms=excluded,
                          algorithm_version=ALGORITHM_VERSION)
    return Comparison(outcome="tradeoff", pareto_frontier_indices=frontier,
                      reasons=["На Парето-фронте остаются окна " + ", ".join(str(i + 1) for i in frontier)
                               + "; факторы указывают на разные окна, поэтому веса для их произвольного сложения не вводились."],
                      decision_mechanisms=mechanisms, excluded_mechanisms=excluded,
                      algorithm_version=ALGORITHM_VERSION)


def run(request: AnalysisRequest):
    starts = [request.start]
    starts += [request.start + timedelta(hours=request.search_hours / 2),
               request.start + timedelta(hours=request.search_hours)]
    windows = [Window(start=s, end=s + timedelta(hours=request.duration_hours)) for s in starts]
    if request.mode == "current":
        events, weather_records, weather_status = current_weather(request.refresh)
        weather_by_window = [(events, weather_status, None) for _ in windows]
        orbit_input, orbit_records, orbit_status = current_tle(request.refresh)
        conjunction_events, conjunction_records, conjunction_status, conjunction_coverage = current_conjunctions(request.refresh)
        conjunction_source_as_of = conjunction_records[0].published_at if conjunction_records else None
        conjunction_by_window = [
            (conjunction_events, conjunction_status, conjunction_coverage, None, conjunction_source_as_of)
            for _ in windows
        ]
    elif request.mode == "replay":
        cutoff = request.cutoff
        events, weather_records, weather_status = archived_weather(
            cutoff, min(w.start for w in windows), max(w.end for w in windows)
        )
        weather_by_window = [(events, weather_status, cutoff) for _ in windows]
        orbit_input = None
        orbit_status = "historical_reconstruction"
        orbit_records = [store_raw("iss_history_extract",
                          "https://huggingface.co/datasets/juliensimon/space-track-tle-history",
                          ISS_ARCHIVE.read_bytes(), cache_state="archived")]
        conjunction_record = historical_conjunction_source_record()
        conjunction_records = [conjunction_record]
        conjunction_by_window = []
        for window in windows:
            reconstructed, meta = reconstruct_historical_conjunctions(window, conjunction_record.id)
            conjunction_by_window.append((reconstructed, "historical_reconstruction", None, meta, None))
    else:
        # Reconstruction uses the latest archived forecast that can be shown to
        # have existed by each candidate window's own start. Using one release
        # selected at the end of the search horizon can leak a later forecast
        # into an earlier historical window.
        weather_by_window = []
        weather_records = []
        for window in windows:
            events, records, status = archived_weather(window.start, window.start, window.end)
            weather_by_window.append((events, status, window.start))
            weather_records.extend(records)
        orbit_input = None
        orbit_status = "historical_reconstruction"
        orbit_records = [store_raw("iss_history_extract",
                          "https://huggingface.co/datasets/juliensimon/space-track-tle-history",
                          ISS_ARCHIVE.read_bytes(), cache_state="archived")]
        conjunction_record = historical_conjunction_source_record()
        conjunction_records = [conjunction_record]
        conjunction_by_window = []
        for window in windows:
            reconstructed, meta = reconstruct_historical_conjunctions(window, conjunction_record.id)
            conjunction_by_window.append((reconstructed, "historical_reconstruction", None, meta, None))
    results = [evaluate(
        w, weather[0], weather[1], request.mode.value, orbit_input,
        weather[2], request.requires_sunlight, orbit_status,
        conjunction_events=conj[0], conjunction_status=conj[1], conjunction_coverage=conj[2], conjunction_meta=conj[3],
        strict_replay=request.mode.value == "replay", conjunction_source_as_of=conj[4],
    ) for w, weather, conj in zip(windows, weather_by_window, conjunction_by_window)]
    records = weather_records + orbit_records + conjunction_records
    deduplicated_records = list({record.id: record for record in records}.values())
    return results, compare(results), deduplicated_records
