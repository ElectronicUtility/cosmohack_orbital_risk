from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb

from . import ALGORITHM_VERSION
from .domain import ConjunctionEvent, RawRecord, Window, aware
from .orbit import historical_satrec, julian
from .providers import ISS_ARCHIVE, historical_elements
from .storage import ROOT


HISTORY = ROOT / "data" / "conjunctions" / "tle_candidates_2024_may_june.parquet"
PROVENANCE = ROOT / "data" / "conjunctions" / "provenance.json"
KNOWN_ASSOCIATIONS = ROOT / "data" / "conjunctions" / "known_iss_associations.json"
REPORT_THRESHOLD_KM = 5.0
COARSE_STEP_SECONDS = 60
EARTH_MU_KM3_S2 = 398600.4418
EARTH_RADIUS_KM = 6378.137


def _orbit_signature(row: dict) -> tuple:
    """Fields that define the propagated state in this archive."""
    return tuple(row[key] for key in (
        "epoch", "inclination", "raan", "eccentricity", "arg_perigee",
        "mean_anomaly", "mean_motion", "bstar",
    ))


def _remove_duplicate_states(rows: list[dict]) -> tuple[list[dict], list[list[int]]]:
    """Exclude catalog rows that share one exact propagated state.

    The source contains exact duplicate element sets for some co-located/docked
    spacecraft. Propagating those rows independently produces false debris-style
    close approaches, so they are retained only as an explicit data limitation.
    """
    grouped: dict[tuple, list[dict]] = {}
    for row in rows:
        grouped.setdefault(_orbit_signature(row), []).append(row)
    duplicate_groups = [
        sorted(int(row["norad_id"]) for row in group)
        for group in grouped.values() if len(group) > 1
    ]
    duplicate_ids = {item for group in duplicate_groups for item in group}
    return [row for row in rows if int(row["norad_id"]) not in duplicate_ids], duplicate_groups


def _known_association(norad_id: int, at: datetime) -> dict | None:
    """Return a source-backed ISS association that is active at ``at``.

    This list is intentionally small and explicit. It is used only to stop a
    known visiting/docked vehicle from being mislabeled as an independent
    debris conjunction. Absence from the list never means that an object is
    debris.
    """
    if not KNOWN_ASSOCIATIONS.exists():
        return None
    at = aware(at)
    for item in json.loads(KNOWN_ASSOCIATIONS.read_text(encoding="utf-8")):
        if int(item["norad_id"]) != norad_id:
            continue
        start = aware(datetime.fromisoformat(item["valid_start"].replace("Z", "+00:00")))
        end = aware(datetime.fromisoformat(item["valid_end"].replace("Z", "+00:00")))
        if start <= at <= end:
            return item
    return None


def _persistent_proximity(iss_sat, object_sat, window: Window) -> dict | None:
    """Detect geometry that stays inside the reporting screen across a window.

    Such geometry cannot honestly be interpreted as a transient conjunction
    without additional identity/context. This is a classification guard, not
    an operational threshold: it uses the same published 5 km reporting screen
    already used by the reconstruction.
    """
    fractions = (0.0, 0.25, 0.5, 0.75, 1.0)
    samples = []
    for fraction in fractions:
        at = window.start + window.duration * fraction
        state = _relative_state(iss_sat, object_sat, at)
        if state is None:
            return None
        distance, speed = state
        samples.append((at, distance, speed))
    if all(distance <= REPORT_THRESHOLD_KM for _, distance, _ in samples):
        return {
            "sample_count": len(samples),
            "min_sampled_separation_km": min(distance for _, distance, _ in samples),
            "max_sampled_separation_km": max(distance for _, distance, _ in samples),
            "min_sampled_relative_speed_km_s": min(speed for _, _, speed in samples),
            "max_sampled_relative_speed_km_s": max(speed for _, _, speed in samples),
        }
    return None


def historical_conjunction_source_record() -> RawRecord:
    metadata = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    payload_hash = hashlib.sha256(HISTORY.read_bytes()).hexdigest()
    if payload_hash != metadata["local_sha256"]:
        raise ValueError("Historical conjunction extract hash does not match provenance")
    return RawRecord(
        id=f"conjunction_tle_history:{payload_hash}",
        source="conjunction_tle_history",
        url=metadata["source"],
        content_sha256=payload_hash,
        retrieved_at=datetime.fromtimestamp(HISTORY.stat().st_mtime, timezone.utc),
        published_at=None,
        publication_basis="Individual element publication timestamps are unavailable; historical reconstruction only",
        cache_state="archived_local_extract",
        artifact_path=metadata["local_file"],
        source_revision=metadata["source_revision"],
    )


def iss_history_record_id() -> str:
    return "iss_history_extract:" + hashlib.sha256(ISS_ARCHIVE.read_bytes()).hexdigest()


def _latest_candidate_rows(at: datetime) -> list[dict]:
    at = aware(at)
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        cursor = con.execute(
            """
            SELECT * EXCLUDE (rn)
            FROM (
                SELECT *, row_number() OVER (PARTITION BY norad_id ORDER BY epoch DESC) AS rn
                FROM read_parquet(?)
                WHERE epoch <= ?
            )
            WHERE rn = 1 AND norad_id <> 25544
            """,
            [str(HISTORY), at],
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        con.close()


def _candidate_updates_in_window(window: Window) -> dict[int, dict]:
    """Describe element epochs that occur after the window-start snapshot.

    These are sensitivity diagnostics only.  The source does not provide the
    publication time of an individual element set, so a later element epoch is
    never interpreted as proof that the element was available at that time.
    """
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC'")
        cursor = con.execute(
            """
            SELECT norad_id, min(epoch) AS first_epoch, max(epoch) AS last_epoch, count(*) AS element_count
            FROM read_parquet(?)
            WHERE epoch > ? AND epoch <= ? AND norad_id <> 25544
            GROUP BY norad_id
            """,
            [str(HISTORY), window.start, window.end],
        )
        return {
            int(norad_id): {
                "first_epoch": aware(first_epoch),
                "last_epoch": aware(last_epoch),
                "element_count": int(element_count),
            }
            for norad_id, first_epoch, last_epoch, element_count in cursor.fetchall()
        }
    finally:
        con.close()


def _iss_updates_in_window(window: Window) -> list[datetime]:
    updates = []
    for row in historical_elements():
        raw = row["epoch"]
        epoch = aware(raw if isinstance(raw, datetime) else datetime.fromisoformat(raw))
        if window.start < epoch <= window.end:
            updates.append(epoch)
    return sorted(updates)


def _iss_satrec(at: datetime):
    prior = []
    for row in historical_elements():
        epoch_raw = row["epoch"]
        epoch = aware(epoch_raw if isinstance(epoch_raw, datetime) else datetime.fromisoformat(epoch_raw))
        if epoch <= at:
            prior.append((epoch, row))
    if not prior:
        return None
    _, row = max(prior, key=lambda item: item[0])
    return historical_satrec(row)


def _relative_state(iss_sat, object_sat, at: datetime):
    jd, fr = julian(at)
    err_iss, p_iss, v_iss = iss_sat.sgp4(jd, fr)
    err_obj, p_obj, v_obj = object_sat.sgp4(jd, fr)
    if err_iss or err_obj:
        return None
    rel_p = tuple(a - b for a, b in zip(p_obj, p_iss))
    rel_v = tuple(a - b for a, b in zip(v_obj, v_iss))
    distance = math.sqrt(sum(x * x for x in rel_p))
    speed = math.sqrt(sum(x * x for x in rel_v))
    return distance, speed


def _refine_tca(iss_sat, object_sat, left: datetime, right: datetime):
    """Golden-section minimum of modeled separation inside one coarse bracket."""
    span = (right - left).total_seconds()
    if span <= 0:
        state = _relative_state(iss_sat, object_sat, left)
        return (left, *state) if state else None

    phi = (1 + math.sqrt(5)) / 2
    lo, hi = 0.0, span
    c = hi - (hi - lo) / phi
    d = lo + (hi - lo) / phi

    def value(seconds: float):
        state = _relative_state(iss_sat, object_sat, left + timedelta(seconds=seconds))
        return math.inf if state is None else state[0] ** 2

    fc, fd = value(c), value(d)
    for _ in range(36):
        if fc < fd:
            hi, d, fd = d, c, fc
            c = hi - (hi - lo) / phi
            fc = value(c)
        else:
            lo, c, fc = c, d, fd
            d = lo + (hi - lo) / phi
            fd = value(d)
    seconds = (lo + hi) / 2
    probes = [left, left + timedelta(seconds=seconds), right]
    states = []
    for at in probes:
        state = _relative_state(iss_sat, object_sat, at)
        if state is not None:
            states.append((at, *state))
    return min(states, key=lambda item: item[1]) if states else None


def reconstruct_historical_conjunctions(
    window: Window,
    conjunction_record_id: str,
) -> tuple[list[ConjunctionEvent], dict]:
    iss_info = _iss_satrec(window.start)
    rows = _latest_candidate_rows(window.start)
    if iss_info is None or not rows:
        return [], {
            "status": "missing",
            "candidate_objects": len(rows),
            "screening_threshold_km": REPORT_THRESHOLD_KM,
        }

    rows, duplicate_groups = _remove_duplicate_states(rows)
    iss_sat, iss_epoch = iss_info
    candidates = []
    for row in rows:
        try:
            sat, epoch = historical_satrec(row)
        except (TypeError, ValueError):
            continue
        candidates.append((int(row["norad_id"]), row.get("intl_designator"), sat, epoch))

    candidate_ids = {norad_id for norad_id, _, _, _ in candidates}
    all_candidate_updates = _candidate_updates_in_window(window)
    candidate_updates = {
        norad_id: info for norad_id, info in all_candidate_updates.items()
        if norad_id in candidate_ids
    }
    iss_updates = _iss_updates_in_window(window)

    half_step = COARSE_STEP_SECONDS / 2
    # Conservative curvature allowance over half a coarse step. This is a numerical
    # search bound, not an EVA or conjunction-risk threshold.
    relative_acceleration_bound = 2 * EARTH_MU_KM3_S2 / (EARTH_RADIUS_KM ** 2)
    curvature_margin = 0.5 * relative_acceleration_bound * half_step ** 2

    admitted: dict[int, dict] = {}
    sample_times = []
    at = window.start
    while at < window.end:
        sample_times.append(at)
        at += timedelta(seconds=COARSE_STEP_SECONDS)
    sample_times.append(window.end)
    for at in sample_times:
        jd, fr = julian(at)
        err_iss, p_iss, v_iss = iss_sat.sgp4(jd, fr)
        if not err_iss:
            for norad_id, designator, sat, epoch in candidates:
                err, p_obj, v_obj = sat.sgp4(jd, fr)
                if err:
                    continue
                rel_p = tuple(a - b for a, b in zip(p_obj, p_iss))
                rel_v = tuple(a - b for a, b in zip(v_obj, v_iss))
                distance = math.sqrt(sum(x * x for x in rel_p))
                speed = math.sqrt(sum(x * x for x in rel_v))
                lower_bound = distance - speed * half_step - curvature_margin
                if lower_bound <= REPORT_THRESHOLD_KM:
                    item = admitted.setdefault(norad_id, {
                        "sat": sat,
                        "epoch": epoch,
                        "designator": designator,
                        "sample_times": set(),
                    })
                    item["sample_times"].add(at)
    events: list[ConjunctionEvent] = []
    excluded_associations = []
    ambiguous_persistent = []
    sample_index = {at: index for index, at in enumerate(sample_times)}
    refined_brackets = 0
    for norad_id, item in admitted.items():
        sat = item["sat"]
        epoch = item["epoch"]
        designator = item["designator"]
        interval_indexes = set()
        for coarse_at in item["sample_times"]:
            index = sample_index[coarse_at]
            if index > 0:
                interval_indexes.add((index - 1, index))
            if index + 1 < len(sample_times):
                interval_indexes.add((index, index + 1))
        refinements = []
        for left_index, right_index in sorted(interval_indexes):
            refined_brackets += 1
            refined = _refine_tca(iss_sat, sat, sample_times[left_index], sample_times[right_index])
            if refined is not None:
                refinements.append(refined)
        if not refinements:
            continue
        tca, separation, relative_speed = min(refinements, key=lambda result: result[1])
        if separation > REPORT_THRESHOLD_KM:
            continue
        association = _known_association(norad_id, tca)
        if association is not None:
            excluded_associations.append({
                "norad_id": norad_id,
                "international_designator": designator,
                "tca": tca.isoformat(),
                "min_separation_km": separation,
                "relative_speed_km_s": relative_speed,
                "association": association,
                "reason": "Source-backed ISS visiting/docked vehicle; excluded from independent debris-conjunction interpretation.",
            })
            continue
        persistent = _persistent_proximity(iss_sat, sat, window)
        classification = "historical_tle_geometry_reconstruction"
        extra_limitations = []
        if persistent is not None:
            classification = "historical_persistent_proximity_ambiguous"
            ambiguous_persistent.append({
                "norad_id": norad_id,
                "international_designator": designator,
                "tca": tca.isoformat(),
                **persistent,
            })
            extra_limitations = [
                "The object remains inside the 5 km reconstruction screen across the sampled window; without identity/context it cannot be treated as a transient independent debris conjunction.",
            ]
        update_info = candidate_updates.get(norad_id)
        if update_info is not None:
            extra_limitations.append(
                "The archive contains a newer element epoch for this object inside the analyzed window; geometry therefore depends on the explicit window-start snapshot policy."
            )
        if iss_updates:
            extra_limitations.append(
                "The archive contains a newer ISS element epoch inside the analyzed window; conjunction geometry intentionally keeps the ISS window-start snapshot fixed for consistency."
            )
        events.append(ConjunctionEvent(
            id=f"historical-reconstruction:{norad_id}:{tca.isoformat()}",
            tca=tca,
            min_separation_km=separation,
            relative_speed_km_s=relative_speed,
            object_norad_id=norad_id,
            object_name=designator,
            object_element_epoch=epoch,
            iss_element_epoch=iss_epoch,
            max_probability=None,
            published_at=None,
            source_record_ids=[conjunction_record_id, iss_history_record_id()],
            source_url="https://huggingface.co/datasets/juliensimon/space-track-tle-history",
            classification=classification,
            limitations=[
                "This is reconstructed TLE geometry, not an archived SOCRATES report.",
                "No covariance is available, so collision probability is not calculated.",
                "Individual historical element publication timestamps are unavailable; this factor is not strict point-in-time replay.",
                "Each object's latest element at the window start is held fixed across the window; element age is preserved in evidence.",
                "Catalog rows sharing an identical orbital state are excluded because they cannot be interpreted as independent debris encounters.",
            ] + extra_limitations,
            algorithm_version=ALGORITHM_VERSION,
        ))

    events.sort(key=lambda event: (event.tca, event.min_separation_km))
    epochs = [epoch for _, _, _, epoch in candidates]
    candidate_ages = sorted((window.start - epoch).total_seconds() / 3600 for epoch in epochs)

    def age_percentile(fraction: float) -> float | None:
        if not candidate_ages:
            return None
        return candidate_ages[round((len(candidate_ages) - 1) * fraction)]

    reported_event_sensitivity = []
    for event in events:
        update_info = candidate_updates.get(event.object_norad_id)
        reported_event_sensitivity.append({
            "norad_id": event.object_norad_id,
            "tca": event.tca.isoformat(),
            "object_snapshot_epoch": event.object_element_epoch.isoformat() if event.object_element_epoch else None,
            "object_element_age_hours_at_tca": (
                (event.tca - event.object_element_epoch).total_seconds() / 3600
                if event.object_element_epoch else None
            ),
            "first_later_object_element_epoch_inside_window": (
                update_info["first_epoch"].isoformat() if update_info else None
            ),
            "later_object_element_epoch_precedes_tca": bool(
                update_info and update_info["first_epoch"] <= event.tca
            ),
        })
    updated_fraction = len(candidate_updates) / len(candidates) if candidates else None
    return events, {
        "status": "historical_reconstruction",
        "candidate_objects": len(candidates),
        "screened_candidates": len(admitted),
        "refined_coarse_intervals": refined_brackets,
        "reported_events": len(events),
        "screening_threshold_km": REPORT_THRESHOLD_KM,
        "coarse_step_seconds": COARSE_STEP_SECONDS,
        "curvature_margin_km": curvature_margin,
        "iss_element_epoch": iss_epoch.isoformat(),
        "iss_element_age_hours_at_window_start": (window.start - iss_epoch).total_seconds() / 3600,
        "element_snapshot_policy": "latest element epoch at or before window start, held fixed through the full window",
        "snapshot_sensitivity": {
            "interpretation": "Diagnostic of element-set turnover only; not a probability or calibrated position uncertainty.",
            "publication_time_known": False,
            "candidate_objects_with_later_element_epoch_inside_window": len(candidate_updates),
            "candidate_object_fraction_with_later_element_epoch_inside_window": updated_fraction,
            "iss_later_element_epoch_count_inside_window": len(iss_updates),
            "iss_first_later_element_epoch_inside_window": iss_updates[0].isoformat() if iss_updates else None,
            "iss_last_later_element_epoch_inside_window": iss_updates[-1].isoformat() if iss_updates else None,
            "reported_events": reported_event_sensitivity,
        },
        "oldest_candidate_epoch": min(epochs).isoformat() if epochs else None,
        "newest_candidate_epoch": max(epochs).isoformat() if epochs else None,
        "oldest_candidate_element_age_hours_at_window_start": (
            (window.start - min(epochs)).total_seconds() / 3600 if epochs else None
        ),
        "newest_candidate_element_age_hours_at_window_start": (
            (window.start - max(epochs)).total_seconds() / 3600 if epochs else None
        ),
        "candidate_element_age_hours_at_window_start": {
            "p50": age_percentile(0.50),
            "p90": age_percentile(0.90),
            "p99": age_percentile(0.99),
        },
        "publication_time_known": False,
        "excluded_duplicate_state_objects": sum(len(group) for group in duplicate_groups),
        "duplicate_state_groups": duplicate_groups,
        "excluded_known_iss_associations": excluded_associations,
        "ambiguous_persistent_proximity_events": ambiguous_persistent,
    }
