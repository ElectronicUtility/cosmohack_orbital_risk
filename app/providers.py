from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .domain import ExternalEvent, RawRecord, aware
from .storage import ROOT, latest_raw, store_raw

NOAA_CURRENT = "https://services.swpc.noaa.gov/text/3-day-forecast.txt"
ISS_CURRENT = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"
NOAA_BASE = "https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports/"
ARCHIVE = ROOT / "data" / "noaa"
ISS_ARCHIVE = ROOT / "data" / "iss_2024_may_june.json"
PARSER_VERSION = "1"


def published(text: str) -> datetime:
    m = re.search(r"^:Issued:\s*(\d{4} \w{3} \d{1,2} \d{4}) UTC", text, re.M)
    if not m:
        raise ValueError("NOAA issue time absent")
    return datetime.strptime(m.group(1), "%Y %b %d %H%M").replace(tzinfo=timezone.utc)


def forecast_events(text: str, raw: RawRecord) -> list[ExternalEvent]:
    issue = published(text)
    if raw.published_at and issue != raw.published_at:
        raise ValueError("Archive issue metadata mismatch")
    if "three_day_forecast" in raw.url or raw.source == "noaa_current":
        match = re.search(r"^S1 or greater\s+(\d+)%\s+(\d+)%\s+(\d+)%", text, re.M)
        day0 = issue.date()
        quantity = "NOAA S1-or-greater forecast probability"
    else:
        match = re.search(r"^Proton\s+(\d+)/(\d+)/(\d+)\s*$", text, re.M)
        day0 = issue.date() + timedelta(days=1)
        quantity = "USAF/NOAA proton event probability (daily proxy)"
    if not match:
        raise ValueError("Expected solar-radiation forecast row absent")
    events = []
    for i, value in enumerate(match.groups()):
        start = datetime.combine(day0 + timedelta(days=i), datetime.min.time(), timezone.utc)
        events.append(ExternalEvent(
            id=f"{raw.id}:{i}", mechanism="space_weather", kind="external_forecast", quantity=quantity,
            value=float(value), unit="%", valid_start=start, valid_end=start + timedelta(days=1),
            published_at=issue, raw_record_id=raw.id, source_url=raw.url,
            limitations=["Daily probability is not an EVA dose or an event arrival time.",
                         "GOES/NOAA conditions do not directly measure astronaut exposure at ISS."]
        ))
    return events


def archive_products():
    result = []
    for sub in ("3day_forecast", "reports_solar_geophysical_activity"):
        for path in sorted((ARCHIVE / sub).glob("*.txt")):
            text = path.read_text(encoding="utf-8", errors="replace")
            try:
                issue = published(text)
            except ValueError:
                continue
            url = f"{NOAA_BASE}{sub}/2024/{issue:%m}/{path.name}"
            result.append((issue, sub, url, path, text))
    return result


def archived_weather(cutoff: datetime, target_start: datetime, target_end: datetime):
    """Select one dated release; no later revision enters replay."""
    candidates = []
    for issue, sub, url, path, text in archive_products():
        if issue > cutoff:
            continue
        # Forecast can cover a window only through the third forecast day.
        last = datetime.combine(issue.date() + timedelta(days=3 if sub == "3day_forecast" else 4),
                                datetime.min.time(), timezone.utc)
        if target_end <= last:
            try:
                provisional = RawRecord(id="probe", source="noaa_archive", url=url,
                    content_sha256="probe", retrieved_at=datetime.now(timezone.utc), published_at=issue)
                events = forecast_events(text, provisional)
                first = min(e.valid_start for e in events)
                if first <= target_start:
                    candidates.append((issue, sub == "3day_forecast", url, path, text))
            except ValueError:
                continue
    if not candidates:
        return [], [], "missing"
    issue, _, url, path, text = max(candidates, key=lambda x: (x[0], x[1]))
    raw = store_raw("noaa_archive", url, path.read_bytes(), published_at=issue, cache_state="archived")
    return forecast_events(text, raw), [raw], "archive"


def fetch_current(source: str, url: str, max_age_minutes: int = 60):
    disabled = {s.strip() for s in os.getenv("DISABLE_PROVIDERS", "").split(",")}
    previous = latest_raw(source)
    if source in disabled:
        return (previous[0], previous[1].model_copy(update={"cache_state": "provider_disabled"}), "disabled") if previous else (None, None, "disabled")
    if previous:
        age = datetime.now(timezone.utc) - previous[1].retrieved_at
        if age < timedelta(minutes=max_age_minutes):
            return previous[0], previous[1].model_copy(update={"cache_state": "cached"}), "cached"
    for attempt in range(2):
        try:
            with httpx.Client(timeout=12, follow_redirects=True) as client:
                response = client.get(url, headers={"User-Agent": "CosmoHackathonResearch/0.1"})
                response.raise_for_status()
            payload = response.content
            if not payload:
                raise ValueError("Empty response")
            if source == "noaa_current":
                content = payload.decode("utf-8", "replace")
                pub = published(content)
                probe = RawRecord(id="probe", source=source, url=url, content_sha256="probe",
                                  retrieved_at=datetime.now(timezone.utc), published_at=pub)
                forecast_events(content, probe)
            else:
                pub = None
                lines = [line for line in payload.decode("utf-8", "replace").splitlines()
                         if line.startswith(("1 ", "2 "))]
                if len(lines) < 2 or "25544" not in lines[0] or "25544" not in lines[1]:
                    raise ValueError("Invalid ISS TLE response")
            raw = store_raw(source, url, payload, published_at=pub)
            return payload, raw, "fresh"
        except (httpx.HTTPStatusError, ValueError, UnicodeError):
            break
        except httpx.RequestError:
            if attempt == 0:
                time.sleep(0.2)
    if previous:
        return previous[0], previous[1].model_copy(update={"cache_state": "stale"}), "stale"
    return None, None, "missing"


def current_weather(refresh=False):
    payload, raw, status = fetch_current("noaa_current", NOAA_CURRENT, 0 if refresh else 60)
    if payload is None:
        return [], [], status
    try:
        events = forecast_events(payload.decode("utf-8", "replace"), raw)
    except ValueError:
        return [], [raw], "invalid"
    return events, [raw], status


def current_tle(refresh=False):
    payload, raw, status = fetch_current("iss_current", ISS_CURRENT, 0 if refresh else 120)
    if payload is None:
        return None, [], status
    lines = [line for line in payload.decode("utf-8", "replace").splitlines() if line.startswith(("1 ", "2 "))]
    if len(lines) < 2 or "25544" not in lines[0] or "25544" not in lines[1]:
        return None, [raw], "invalid"
    return (lines[0], lines[1], raw), [raw], status


def historical_elements():
    return json.loads(ISS_ARCHIVE.read_text(encoding="utf-8"))
