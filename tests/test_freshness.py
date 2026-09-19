from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import providers
from app.analysis import conjunction_assessment
from app.domain import RawRecord, Window

UTC = timezone.utc
FIXTURES = Path(__file__).parent / "fixtures"


def test_cached_socrates_ages_since_publication_not_download(monkeypatch):
    payload = (Path(__file__).parents[1] / "data/conjunctions/socrates_iss_probe.html").read_bytes()
    issued, _, _ = providers.socrates_metadata(payload.decode())
    fetched = issued + timedelta(hours=11, minutes=59)
    record = RawRecord(id="cached", source="socrates_current", url=providers.SOCRATES_CURRENT,
                       content_sha256="fixture", published_at=issued, retrieved_at=fetched)
    monkeypatch.setattr(providers, "fetch_current", lambda *a, **kw: (payload, record, "cached"))
    monkeypatch.setattr(providers, "latest_raw", lambda name: (payload, record) if name == record.source else None)
    monkeypatch.setattr(providers, "utc_now", lambda: fetched)
    assert providers.current_conjunctions()[2] == "cached"
    monkeypatch.setattr(providers, "utc_now", lambda: fetched + timedelta(hours=2))
    assert providers.current_conjunctions()[2] == "stale"
    health = providers.current_provider_health()[record.source]
    assert health["state"] == "source_stale"
    assert health["source_data_age_minutes"] == 839
    assert health["source_data_age_at_retrieval_minutes"] == 719


def test_six_hour_coverage_is_relative_to_assessment_time():
    issued = datetime(2026, 9, 18, 22, 16, tzinfo=UTC)
    start = issued.replace(hour=23, minute=0)
    end = start + timedelta(days=7)
    window = Window(start=start + timedelta(hours=1), end=start + timedelta(hours=2))
    factor = conjunction_assessment(window, [], "fresh", (start, end), source_as_of=issued,
                                    assessed_at=start)
    assert factor.supports_next_6h_horizon is True
    near_end = conjunction_assessment(window, [], "cached", (start, end), source_as_of=issued,
                                      assessed_at=end - timedelta(hours=5))
    assert near_end.supports_next_6h_horizon is False
    before_coverage = conjunction_assessment(window, [], "fresh", (start, end), source_as_of=issued,
                                             assessed_at=issued)
    assert before_coverage.supports_next_6h_horizon is False


def test_repeated_download_does_not_refresh_old_noaa_issue(monkeypatch):
    payload = (FIXTURES / "noaa_3day_20260918.txt").read_bytes()
    issued = providers.published(payload.decode())
    now = issued + timedelta(hours=25)
    record = RawRecord(id="noaa", source="noaa_current", url=providers.NOAA_CURRENT,
                       content_sha256="fixture", published_at=issued, retrieved_at=now)
    monkeypatch.setattr(providers, "utc_now", lambda: now)
    monkeypatch.setattr(providers, "fetch_current", lambda *a, **kw: (payload, record, "fresh"))
    assert providers.current_weather()[2] == "stale"
