from __future__ import annotations

import json
import hashlib
import os
import re
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import httpx
from sgp4.api import Satrec

from . import ALGORITHM_VERSION
from .domain import ConjunctionEvent, ExternalEvent, RawRecord, aware
from .storage import ROOT, latest_raw, store_raw

NOAA_CURRENT = "https://services.swpc.noaa.gov/text/3-day-forecast.txt"
ISS_CURRENT = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=TLE"
SOCRATES_CURRENT = "https://celestrak.org/SOCRATES/table-socrates.php?CATNR=25544,&ORDER=MINRANGE&MAX=100"
CURRENT_PROVIDER_MAX_AGE_MINUTES = {
    "noaa_current": 60,
    "iss_current": 120,
    "socrates_current": 360,
}
NOAA_BASE = "https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports/"
ARCHIVE = ROOT / "data" / "noaa"
ISS_ARCHIVE = ROOT / "data" / "iss_2024_may_june.json"
AVAILABILITY_MANIFEST = ARCHIVE / "availability_manifest.json"
PARSER_VERSION = "1"
CURRENT_TLE_MAX_PROPAGATION_AGE_MINUTES = 2 * 24 * 60


def socrates_source_max_age_minutes() -> int:
    """Maximum accepted age of SOCRATES' own `Data current as of` timestamp.

    CelesTrak documents that SOCRATES is run three times per day.  The default
    therefore allows twelve hours (one nominal 8 h cycle plus 4 h grace).  This
    is a configurable provider-health rule, not an EVA operating threshold.
    """
    return int(os.getenv("SOCRATES_SOURCE_MAX_AGE_MINUTES", "720"))


class _CellTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def socrates_metadata(text: str) -> tuple[datetime, datetime, datetime]:
    as_of = re.search(r"Data current as of\s+(\d{4} \w{3} \d{1,2} \d{2}:\d{2}:\d{2}) UTC", text)
    interval = re.search(
        r"Computation Interval:\s*Start =\s*(\d{4} \w{3} \d{1,2} \d{2}:\d{2}:\d{2}) UTC,\s*Stop =\s*(\d{4} \w{3} \d{1,2} \d{2}:\d{2}:\d{2}) UTC",
        text,
    )
    if not as_of or not interval:
        raise ValueError("SOCRATES metadata absent")
    parse = lambda value: datetime.strptime(value, "%Y %b %d %H:%M:%S").replace(tzinfo=timezone.utc)
    return parse(as_of.group(1)), parse(interval.group(1)), parse(interval.group(2))


def socrates_threshold_km(text: str) -> float:
    match = re.search(r"Computation Threshold:\s*([0-9.]+) km", text)
    if not match:
        raise ValueError("SOCRATES computation threshold absent")
    return float(match.group(1))


def socrates_result_limits(text: str) -> tuple[int, int]:
    """Return the server-declared result limit and rendered record count.

    SOCRATES may clamp the MAX query parameter. The rendered page is therefore
    authoritative for the effective limit; assuming the requested value can
    silently turn a truncated table into an apparently complete one.
    """
    limit_match = re.search(r"Return first\s+([0-9,]+)\s+items", text, re.I)
    count_match = re.search(r"([0-9,]+)\s+records found", text, re.I)
    if not limit_match or not count_match:
        raise ValueError("SOCRATES result-limit metadata absent")
    parse = lambda value: int(value.replace(",", ""))
    return parse(limit_match.group(1)), parse(count_match.group(1))


def socrates_results_truncated(text: str) -> bool:
    """Return true only when SOCRATES reports more matches than its page limit."""
    effective_limit, records_found = socrates_result_limits(text)
    return records_found > effective_limit


def socrates_source_age_minutes(text: str, reference_time: datetime) -> float:
    """Age of the source computation at a known retrieval/reference instant."""
    as_of, _, _ = socrates_metadata(text)
    return (aware(reference_time) - as_of).total_seconds() / 60.0


def tle_epoch(line1: str, line2: str) -> datetime:
    """Return the orbital-element epoch encoded by a TLE.

    This is an element epoch, not a publication timestamp.  It is exposed as
    source-data age so a freshly downloaded but old element set cannot look
    current merely because the HTTP/cache retrieval is recent.
    """
    sat = Satrec.twoline2rv(line1, line2)
    return datetime.fromtimestamp(
        (sat.jdsatepoch + sat.jdsatepochF - 2440587.5) * 86400,
        timezone.utc,
    )


def tle_source_age_minutes(line1: str, line2: str, reference_time: datetime) -> float:
    return (aware(reference_time) - tle_epoch(line1, line2)).total_seconds() / 60.0


def socrates_events(text: str, raw: RawRecord) -> tuple[list[ConjunctionEvent], tuple[datetime, datetime]]:
    as_of, interval_start, interval_end = socrates_metadata(text)
    parser = _CellTableParser()
    parser.feed(text)
    rows = parser.rows
    events: list[ConjunctionEvent] = []
    i = 0
    while i + 1 < len(rows):
        first, second = rows[i], rows[i + 1]
        if len(first) >= 7 and len(second) >= 6 and first[1].isdigit() and second[1].isdigit():
            try:
                first_id, second_id = int(first[1]), int(second[1])
                if 25544 not in {first_id, second_id}:
                    i += 1
                    continue
                tca = datetime.strptime(first[4], "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
                separation = float(first[5])
                relative_speed = float(first[6])
                max_probability = float(second[4])
                other_id = second_id if first_id == 25544 else first_id
                other_name = second[2] if first_id == 25544 else first[2]
            except (ValueError, IndexError):
                i += 1
                continue
            events.append(ConjunctionEvent(
                id=f"{raw.id}:{other_id}:{tca.isoformat()}",
                tca=tca,
                min_separation_km=separation,
                relative_speed_km_s=relative_speed,
                object_norad_id=other_id,
                object_name=other_name,
                max_probability=max_probability,
                published_at=as_of,
                source_record_ids=[raw.id],
                source_url=raw.url,
                classification="current_socrates_report",
                limitations=[
                    "SOCRATES maximum probability is an orbital conjunction metric, not the probability of striking an EVA crewmember.",
                    "SOCRATES screens conjunctions inside its published 5 km computation threshold; absence of a row is not a claim of zero debris risk.",
                ],
                algorithm_version=ALGORITHM_VERSION,
            ))
            i += 2
            continue
        i += 1
    effective_limit, records_found = socrates_result_limits(text)
    expected_rows = min(records_found, effective_limit)
    if expected_rows != len(events):
        raise ValueError(
            f"SOCRATES should render {expected_rows} of {records_found} records "
            f"under page limit {effective_limit}, but parser recovered {len(events)}"
        )
    return events, (interval_start, interval_end)


def published(text: str) -> datetime:
    m = re.search(r"^:Issued:\s*(\d{4} \w{3} \d{1,2} \d{4}) UTC", text, re.M)
    if not m:
        raise ValueError("NOAA issue time absent")
    return datetime.strptime(m.group(1), "%Y %b %d %H%M").replace(tzinfo=timezone.utc)


def forecast_events(text: str, raw: RawRecord) -> list[ExternalEvent]:
    issue = published(text)
    if raw.published_at and issue != raw.published_at:
        raise ValueError("Archive issue metadata mismatch")
    kp_events: list[ExternalEvent] = []
    if "three_day_forecast" in raw.url or raw.source == "noaa_current":
        match = re.search(r"^S1 or greater\s+(\d+)%\s+(\d+)%\s+(\d+)%", text, re.M)
        day0 = issue.date()
        quantity = "NOAA S1-or-greater forecast probability"
        kp_rows = re.findall(
            r"^(00-03|03-06|06-09|09-12|12-15|15-18|18-21|21-00)UT\s+(.+)$",
            text,
            re.M,
        )
        if len(kp_rows) != 8:
            raise ValueError("Expected NOAA 3-hour Kp forecast rows absent")
        for row_index, (hours, row) in enumerate(kp_rows):
            values = [float(value) for value in re.findall(r"\d+\.\d+", row)]
            if len(values) != 3:
                raise ValueError("Malformed NOAA 3-hour Kp forecast row")
            start_hour = int(hours[:2])
            for day_index, value in enumerate(values):
                start = datetime.combine(
                    day0 + timedelta(days=day_index), datetime.min.time(), timezone.utc
                ) + timedelta(hours=start_hour)
                kp_events.append(ExternalEvent(
                    id=f"{raw.id}:kp:{row_index}:{day_index}",
                    mechanism="space_weather",
                    kind="external_forecast_context",
                    quantity="NOAA expected 3-hour planetary Kp",
                    value=value,
                    unit="Kp index",
                    valid_start=start,
                    valid_end=start + timedelta(hours=3),
                    published_at=issue,
                    raw_record_id=raw.id,
                    source_url=raw.url,
                    limitations=[
                        "Planetary Kp is geomagnetic forecast context, not an EVA dose or a direct astronaut-risk probability.",
                        "Kp context is not counted as an additional independent risk factor or combined with S1 probability."
                    ],
                ))
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
    return events + kp_events


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
    """Select a release whose archived bytes have retrospective availability metadata."""
    manifest = {r["path"]: r for r in json.loads(AVAILABILITY_MANIFEST.read_text(encoding="utf-8"))}
    candidates = []
    for issue, sub, url, path, text in archive_products():
        metadata = manifest.get(path.relative_to(ROOT).as_posix())
        if not metadata or not metadata["http_last_modified"]:
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["sha256"]:
            continue
        modified = aware(datetime.fromisoformat(metadata["http_last_modified"]))
        if max(issue, modified) > cutoff:
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
                    candidates.append((issue, sub == "3day_forecast", url, path, text, modified))
            except ValueError:
                continue
    if not candidates:
        return [], [], "missing"
    issue, _, url, path, text, modified = max(candidates, key=lambda x: (x[0], x[1]))
    raw = store_raw("noaa_archive", url, path.read_bytes(), published_at=issue, cache_state="archived",
                    archive_last_modified_at=modified,
                    publication_basis="Issued plus retrospective matching HTTP Last-Modified; no signed historical snapshot")
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
            elif source == "iss_current":
                pub = None
                lines = [line for line in payload.decode("utf-8", "replace").splitlines()
                         if line.startswith(("1 ", "2 "))]
                if len(lines) < 2 or "25544" not in lines[0] or "25544" not in lines[1]:
                    raise ValueError("Invalid ISS TLE response")
            elif source == "socrates_current":
                content = payload.decode("utf-8", "replace")
                pub, _, _ = socrates_metadata(content)
                if socrates_threshold_km(content) != 5.0:
                    raise ValueError("Unexpected SOCRATES computation threshold")
                probe = RawRecord(id="probe", source=source, url=url, content_sha256="probe",
                                  retrieved_at=datetime.now(timezone.utc), published_at=pub)
                socrates_events(content, probe)
            else:
                pub = None
            raw = store_raw(
                source,
                url,
                payload,
                published_at=pub,
                publication_basis=(
                    "SOCRATES 'Data current as of' timestamp; current-feed provenance, not strict historical publication proof"
                    if source == "socrates_current" else "unknown"
                ),
            )
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
    try:
        source_age_minutes = tle_source_age_minutes(lines[0], lines[1], raw.retrieved_at)
    except (ValueError, OverflowError):
        return None, [raw], "invalid"
    if status in {"fresh", "cached"} and abs(source_age_minutes) > CURRENT_TLE_MAX_PROPAGATION_AGE_MINUTES:
        status = "stale"
    return (lines[0], lines[1], raw), [raw], status


def current_conjunctions(refresh=False):
    payload, raw, status = fetch_current("socrates_current", SOCRATES_CURRENT, 0 if refresh else 360)
    if payload is None:
        return [], [], status, None
    try:
        text = payload.decode("utf-8", "replace")
        events, coverage = socrates_events(text, raw)
        truncated = socrates_results_truncated(text)
        source_age_minutes = socrates_source_age_minutes(text, raw.retrieved_at)
    except ValueError:
        return [], [raw], "invalid", None
    if truncated:
        return events, [raw], "truncated", coverage
    if status in {"fresh", "cached"} and source_age_minutes > socrates_source_max_age_minutes():
        return events, [raw], "stale", coverage
    return events, [raw], status, coverage


def current_provider_health() -> dict:
    """Read-only provider/cache health without performing external requests."""
    disabled = {s.strip() for s in os.getenv("DISABLE_PROVIDERS", "").split(",") if s.strip()}
    now = datetime.now(timezone.utc)
    result = {}
    for name, max_age_minutes in CURRENT_PROVIDER_MAX_AGE_MINUTES.items():
        cached = latest_raw(name)
        payload = cached[0] if cached else None
        record = cached[1] if cached else None
        age_minutes = ((now - record.retrieved_at).total_seconds() / 60) if record else None
        validation_state = "unknown"
        source_data_at = None
        source_age_minutes = None
        if payload is not None and record is not None:
            try:
                if name == "noaa_current":
                    text = payload.decode("utf-8", "replace")
                    forecast_events(text, record)
                    validation_state = "valid"
                elif name == "iss_current":
                    lines = [line for line in payload.decode("utf-8", "replace").splitlines()
                             if line.startswith(("1 ", "2 "))]
                    if len(lines) < 2 or "25544" not in lines[0] or "25544" not in lines[1]:
                        raise ValueError("Invalid ISS TLE response")
                    source_data_at = tle_epoch(lines[0], lines[1])
                    source_age_minutes = tle_source_age_minutes(lines[0], lines[1], record.retrieved_at)
                    validation_state = "valid"
                elif name == "socrates_current":
                    text = payload.decode("utf-8", "replace")
                    source_data_at, _, _ = socrates_metadata(text)
                    socrates_events(text, record)
                    validation_state = "truncated" if socrates_results_truncated(text) else "valid"
                    source_age_minutes = socrates_source_age_minutes(text, record.retrieved_at)
            except (ValueError, UnicodeError):
                validation_state = "invalid"
        if name in disabled:
            state = "disabled"
        elif record is None:
            state = "missing"
        elif validation_state == "invalid":
            state = "invalid"
        elif validation_state == "truncated":
            state = "truncated"
        elif (name == "iss_current" and source_age_minutes is not None
              and abs(source_age_minutes) > CURRENT_TLE_MAX_PROPAGATION_AGE_MINUTES):
            state = "source_stale"
        elif (name == "socrates_current" and source_age_minutes is not None
              and source_age_minutes > socrates_source_max_age_minutes()):
            state = "source_stale"
        elif age_minutes > max_age_minutes:
            state = "cache_stale"
        else:
            state = "cache_fresh"
        result[name] = {
            "enabled": name not in disabled,
            "state": state,
            "cache_age_minutes": age_minutes,
            "expected_max_age_minutes": max_age_minutes,
            "validation_state": validation_state,
            "source_data_at": source_data_at.isoformat() if source_data_at else None,
            "source_data_age_at_retrieval_minutes": source_age_minutes,
            "source_expected_max_age_minutes": (
                socrates_source_max_age_minutes() if name == "socrates_current" else
                CURRENT_TLE_MAX_PROPAGATION_AGE_MINUTES if name == "iss_current" else None
            ),
            "last_successful_record": record.model_dump(mode="json") if record else None,
        }
    return result


def historical_elements():
    return json.loads(ISS_ARCHIVE.read_text(encoding="utf-8"))
