from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sgp4.api import Satrec, WGS72, jday

from .domain import OrbitState, Window, aware
from .providers import historical_elements, ISS_ARCHIVE, CURRENT_TLE_MAX_PROPAGATION_AGE_MINUTES
import hashlib

UTC = timezone.utc


def julian(t: datetime):
    t = aware(t)
    return jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)


def historical_satrec(row: dict):
    raw_epoch = row["epoch"]
    epoch = aware(raw_epoch if isinstance(raw_epoch, datetime) else datetime.fromisoformat(raw_epoch))
    jd, fr = julian(epoch)
    sat = Satrec()
    satnum = int(row.get("norad_id", 25544))
    sat.sgp4init(WGS72, "i", satnum, jd + fr - 2433281.5, float(row["bstar"]), 0.0, 0.0,
                 float(row["eccentricity"]), math.radians(float(row["arg_perigee"])),
                 math.radians(float(row["inclination"])), math.radians(float(row["mean_anomaly"])),
                 float(row["mean_motion"]) * 2 * math.pi / 1440,
                 math.radians(float(row["raan"])))
    return sat, epoch


def historical_row_at(at: datetime):
    """Return the newest ISS element epoch at or before ``at``.

    Element epoch is not treated as a publication timestamp.  This helper is
    therefore suitable only for the explicitly labelled historical
    reconstruction path.
    """
    at = aware(at)
    prior = []
    for row in historical_elements():
        epoch = aware(datetime.fromisoformat(row["epoch"]))
        if epoch <= at:
            prior.append((epoch, row))
    if not prior:
        return None
    return max(prior, key=lambda item: item[0])[1]


def state_at(at: datetime, mode: str, current=None, historical_row=None):
    at = aware(at)
    if mode == "current":
        if current is None:
            return None
        line1, line2, raw = current
        sat = Satrec.twoline2rv(line1, line2)
        epoch = datetime.fromtimestamp((sat.jdsatepoch + sat.jdsatepochF - 2440587.5) * 86400, UTC)
        url, raw_id, classification = raw.url, raw.id, "current"
    else:
        row = historical_row if historical_row is not None else historical_row_at(at)
        if row is None:
            return None
        sat, epoch = historical_satrec(row)
        url = "https://huggingface.co/datasets/juliensimon/space-track-tle-history"
        raw_id = "iss_history_extract:" + hashlib.sha256(ISS_ARCHIVE.read_bytes()).hexdigest()
        classification = "historical_reconstruction_publication_unknown"
    if abs((at - epoch).total_seconds()) > CURRENT_TLE_MAX_PROPAGATION_AGE_MINUTES * 60:
        return None
    jd, fr = julian(at)
    error, position, _ = sat.sgp4(jd, fr)
    if error:
        return None
    return OrbitState(at=at, position_teme_km=position, epoch=epoch, source_url=url,
                      raw_record_id=raw_id, classification=classification)


def trajectory(window: Window, mode: str, current=None, step_minutes=5):
    # Historical reconstruction uses one explicit window-start orbital snapshot.
    # Switching element sets mid-window would silently give this trajectory a
    # different temporal meaning from the historical conjunction reconstruction.
    # Publication time is unknown, so this remains reconstruction rather than
    # point-in-time replay.
    historical_row = None if mode == "current" else historical_row_at(window.start)
    times = []
    at = window.start
    while at < window.end:
        times.append(at)
        at += timedelta(minutes=step_minutes)
    times.append(window.end)
    return [
        state for t in times
        if (state := state_at(t, mode, current, historical_row=historical_row)) is not None
    ]


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


def interpolate_orbit(a: OrbitState, b: OrbitState, fraction: float):
    """Short-arc spherical interpolation; a chord falsely lowers orbital altitude."""
    ra = math.sqrt(sum(x*x for x in a.position_teme_km))
    rb = math.sqrt(sum(x*x for x in b.position_teme_km))
    u = [x/ra for x in a.position_teme_km]
    v = [x/rb for x in b.position_teme_km]
    angle = math.acos(max(-1.0, min(1.0, sum(x*y for x,y in zip(u,v)))))
    if angle < 1e-8:
        direction = u
    else:
        direction = [(math.sin((1-fraction)*angle)*x + math.sin(fraction*angle)*y)/math.sin(angle)
                     for x,y in zip(u,v)]
    radius = ra + (rb-ra)*fraction
    return a.model_copy(update={'at': a.at+(b.at-a.at)*fraction,
                                'position_teme_km': tuple(radius*x for x in direction)})


def shadow_intervals(states):
    """30-second probes and <=1-second boundary bisection on short orbital arcs.

    Sub-30-second grazing transits may remain unresolved. This improves numerical
    integration, not the physical accuracy of the cylindrical shadow model.
    """
    segments=[]
    for a,b in zip(states,states[1:]):
        seconds=(b.at-a.at).total_seconds()
        count=max(1,math.ceil(seconds/30))
        for j in range(count):
            left,right=j/count,(j+1)/count
            dark_left=in_earth_shadow(interpolate_orbit(a,b,left))
            dark_right=in_earth_shadow(interpolate_orbit(a,b,right))
            if dark_left != dark_right:
                lo,hi=left,right
                while (hi-lo)*seconds>1:
                    mid=(lo+hi)/2
                    if in_earth_shadow(interpolate_orbit(a,b,mid))==dark_left: lo=mid
                    else: hi=mid
                boundary=(lo+hi)/2
                if dark_left: right=boundary
                else: left=boundary
            elif not dark_left:
                continue
            start=a.at+(b.at-a.at)*left; end=a.at+(b.at-a.at)*right
            if segments and segments[-1][1]==start: segments[-1]=(segments[-1][0],end)
            else: segments.append((start,end))
    return [{'start':a.isoformat(),'end':b.isoformat(),'minutes':(b-a).total_seconds()/60} for a,b in segments]
