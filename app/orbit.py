from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sgp4.api import Satrec, WGS72, jday

from .domain import OrbitState, Window, aware
from .providers import historical_elements, ISS_ARCHIVE
import hashlib

UTC = timezone.utc


def julian(t: datetime):
    t = aware(t)
    return jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)


def historical_satrec(row: dict):
    epoch = aware(datetime.fromisoformat(row["epoch"]))
    jd, fr = julian(epoch)
    sat = Satrec()
    sat.sgp4init(WGS72, "i", 25544, jd + fr - 2433281.5, float(row["bstar"]), 0.0, 0.0,
                 float(row["eccentricity"]), math.radians(float(row["arg_perigee"])),
                 math.radians(float(row["inclination"])), math.radians(float(row["mean_anomaly"])),
                 float(row["mean_motion"]) * 2 * math.pi / 1440,
                 math.radians(float(row["raan"])))
    return sat, epoch


def state_at(at: datetime, mode: str, current=None):
    at = aware(at)
    if mode == "current":
        if current is None:
            return None
        line1, line2, raw = current
        sat = Satrec.twoline2rv(line1, line2)
        epoch = datetime.fromtimestamp((sat.jdsatepoch + sat.jdsatepochF - 2440587.5) * 86400, UTC)
        url, raw_id, classification = raw.url, raw.id, "current"
    else:
        rows = historical_elements()
        prior = [r for r in rows if aware(datetime.fromisoformat(r["epoch"])) <= at]
        if not prior:
            return None
        row = max(prior, key=lambda r: aware(datetime.fromisoformat(r["epoch"])))
        sat, epoch = historical_satrec(row)
        url = "https://huggingface.co/datasets/juliensimon/space-track-tle-history"
        raw_id = "iss_history_extract:" + hashlib.sha256(ISS_ARCHIVE.read_bytes()).hexdigest()
        classification = "historical_reconstruction_publication_unknown"
    if abs((at - epoch).total_seconds()) > 2 * 86400:
        return None
    jd, fr = julian(at)
    error, position, _ = sat.sgp4(jd, fr)
    if error:
        return None
    return OrbitState(at=at, position_teme_km=position, epoch=epoch, source_url=url,
                      raw_record_id=raw_id, classification=classification)


def trajectory(window: Window, mode: str, current=None, step_minutes=5):
    times = []
    at = window.start
    while at < window.end:
        times.append(at)
        at += timedelta(minutes=step_minutes)
    times.append(window.end)
    return [state for t in times if (state := state_at(t, mode, current)) is not None]


def sun_vector(t: datetime):
    """Low-precision Sun direction in a mean equatorial frame; illustrative geometry only."""
    jd, fr = julian(t)
    n = jd + fr - 2451545.0
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians((280.460 + 0.9856474 * n + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)) % 360)
    eps = math.radians(23.439 - 0.0000004 * n)
    return (math.cos(lam), math.cos(eps) * math.sin(lam), math.sin(eps) * math.sin(lam))


def in_earth_shadow(state: OrbitState):
    p = state.position_teme_km
    s = sun_vector(state.at)
    dot = sum(a * b for a, b in zip(p, s))
    perpendicular2 = sum(a*a for a in p) - dot*dot
    return dot < 0 and perpendicular2 < 6378.137**2
