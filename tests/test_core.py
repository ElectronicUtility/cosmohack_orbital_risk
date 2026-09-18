from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analysis import compare, evaluate, run, weather_assessment
from app.api import app
from app.domain import AnalysisRequest, ExternalEvent, FactorAssessment, Window, WindowAssessment
from app.orbit import state_at
from app.providers import archived_weather, forecast_events, published
from app.storage import store_raw
from app.domain import RawRecord

UTC = timezone.utc


def dt(day, hour=0):
    return datetime(2024, 5, day, hour, tzinfo=UTC)


def test_naive_time_rejected():
    with pytest.raises(ValueError):
        AnalysisRequest(mode="replay", start="2024-05-10T06:00:00", duration_hours=6,
                        search_hours=12, cutoff="2024-05-10T00:00:00Z")


def test_archived_release_respects_cutoff(tmp_path, monkeypatch):
    monkeypatch.setenv("COSMO_DB", str(tmp_path / "db.sqlite"))
    events, records, _ = archived_weather(dt(10, 0), dt(10, 6), dt(11, 0))
    assert events
    assert all(e.published_at <= dt(10, 0) for e in events)
    assert records[0].published_at == dt(9, 22)
    assert all("202405100030" not in e.source_url for e in events)


def test_future_event_and_revision_excluded_by_pipeline():
    w = Window(start=dt(10, 6), end=dt(10, 12))
    def event(issue, value, suffix):
        return ExternalEvent(id=suffix, mechanism="space_weather", kind="external_forecast",
            quantity="S1 probability", value=value, unit="%", valid_start=w.start,
            valid_end=w.end, published_at=issue, raw_record_id=suffix, source_url="https://example.org/"+suffix)
    earlier = event(dt(9, 22), 10, "original")
    later = event(dt(10, 1), 90, "revision")
    result = weather_assessment(w, [earlier, later], "archive", dt(10, 0))
    assert result.state == "forecast_below_experimental_threshold"
    assert len(result.evidence) == 1
    assert result.evidence[0]["event"]["id"] == "original"


def test_missing_data_not_favorable():
    w = Window(start=dt(10, 6), end=dt(10, 12))
    result = weather_assessment(w, [], "missing")
    assert result.state == "insufficient"
    assert result.overlap_minutes is None


def test_historical_orbit_never_uses_current_epoch():
    state = state_at(dt(10, 6), "replay")
    assert state is not None
    assert state.epoch.year == 2024
    assert state.classification == "historical_reconstruction_publication_unknown"
    assert 6300 < sum(v*v for v in state.position_teme_km)**0.5 < 7200


def result(start, weather, lighting, bad=False):
    w = Window(start=start, end=start + timedelta(hours=6))
    vals = []
    for mechanism, value in [("space_weather", weather), ("lighting", lighting)]:
        vals.append(FactorAssessment(mechanism=mechanism, state="insufficient" if bad else "attention",
            covered_minutes=0 if bad else 360, overlap_minutes=None if bad else value,
            completeness="partial_or_absent" if bad else "complete", freshness="missing" if bad else "archive",
            algorithm_version="test"))
    return WindowAssessment(window=w, factors=vals, orbit=[])


@pytest.mark.parametrize("values,outcome,index", [
    ([(120,100),(40,80)],"preferred",1),
    ([(40,80),(120,100)],"preferred",0),
    ([(40,80),(40,80)],"equivalent",None),
    ([(40,100),(100,40)],"tradeoff",None),
])
def test_comparison(values,outcome,index):
    wins=[result(dt(10,i),*v) for i,v in enumerate(values)]
    c=compare(wins)
    assert (c.outcome,c.preferred_index)==(outcome,index)


def test_comparison_missing_source():
    assert compare([result(dt(10),0,0),result(dt(10,1),0,0,bad=True)]).outcome=="insufficient"


def test_api_historical_e2e(tmp_path,monkeypatch):
    monkeypatch.setenv("COSMO_DB",str(tmp_path / "api.db"))
    client=TestClient(app)
    request={"mode":"replay","start":"2024-05-10T06:00:00Z","duration_hours":6,
             "search_hours":12,"cutoff":"2024-05-10T00:00:00Z"}
    response=client.post("/api/analyze",json=request)
    assert response.status_code==200,response.text
    doc=response.json()
    assert len(doc["windows"])==3
    assert doc["windows"][0]["orbit"][0]["classification"].startswith("historical_reconstruction")
    assert doc["source_records"][0]["published_at"]<request["cutoff"]
    assert client.get(f"/api/analyses/{doc['id']}").json()==doc
    assert client.get(f"/api/analyses/{doc['id']}/export.json").status_code==200
    assert "<h1>Анализ ВКД</h1>" in client.get(f"/api/analyses/{doc['id']}/export.html").text


def test_provider_disabled_and_stale_cache(tmp_path,monkeypatch):
    from app.providers import fetch_current
    monkeypatch.setenv("COSMO_DB",str(tmp_path / "cache.db"))
    monkeypatch.setenv("DISABLE_PROVIDERS","probe")
    assert fetch_current("probe","https://example.org/")[2]=="disabled"
    raw=store_raw("probe","https://example.org/",b"sample")
    payload, record, status=fetch_current("probe","https://example.org/")
    assert payload==b"sample" and status=="disabled"
    assert record.cache_state=="provider_disabled"


def test_provider_http_failure_never_becomes_good(tmp_path,monkeypatch):
    import httpx
    from app import providers
    class FailedClient:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,*args,**kwargs):raise httpx.TimeoutException("timeout")
    monkeypatch.setenv("COSMO_DB",str(tmp_path / "failure.db"))
    monkeypatch.delenv("DISABLE_PROVIDERS",raising=False)
    monkeypatch.setattr(providers.httpx,"Client",FailedClient)
    assert providers.fetch_current("missing","https://example.org/")[2]=="missing"
    store_raw("old","https://example.org/",b"old")
    assert providers.fetch_current("old","https://example.org/",max_age_minutes=0)[2]=="stale"


def test_invalid_forecast_rejected(tmp_path,monkeypatch):
    monkeypatch.setenv("COSMO_DB",str(tmp_path / "raw.db"))
    raw=store_raw("noaa_archive","https://example.org/three_day_forecast.txt",b":Issued: 2024 May 10 0030 UTC",
                  published_at=dt(10))
    with pytest.raises(ValueError):
        forecast_events(":Issued: 2024 May 10 0030 UTC",raw)


@pytest.mark.parametrize("day",["2024-05-01","2024-06-01","2024-06-30"])
def test_historical_archive_boundaries(day,tmp_path,monkeypatch):
    monkeypatch.setenv("COSMO_DB",str(tmp_path / "boundary.db"))
    start=datetime.fromisoformat(day+"T06:00:00+00:00")
    events,records,status=archived_weather(start-timedelta(hours=6),start,start+timedelta(hours=2))
    assert records and any(e.valid_start<=start and e.valid_end>=start+timedelta(hours=2) for e in events)


def test_current_api_offline_fixture(tmp_path,monkeypatch):
    from app import analysis
    root=Path(__file__).parent/"fixtures"
    raw=RawRecord(id="fixture",source="noaa_current",url="https://services.swpc.noaa.gov/text/3-day-forecast.txt",
        content_sha256="fixture",retrieved_at=datetime(2026,9,18,13,tzinfo=UTC),
        published_at=datetime(2026,9,18,12,30,tzinfo=UTC))
    text=(root/"noaa_3day_20260918.txt").read_text()
    events=forecast_events(text,raw)
    tle=(root/"iss_20260918.tle").read_text().splitlines()
    monkeypatch.setattr(analysis,"current_weather",lambda refresh=False:(events,[raw],"fresh"))
    monkeypatch.setattr(analysis,"current_tle",lambda refresh=False:((tle[1],tle[2],raw),[raw],"fresh"))
    monkeypatch.setenv("COSMO_DB",str(tmp_path/"current.db"))
    response=TestClient(app).post("/api/analyze",json={"mode":"current","start":"2026-09-18T18:00:00Z",
        "duration_hours":2,"search_hours":2})
    assert response.status_code==200,response.text
    doc=response.json()
    assert len(doc["windows"])==3
    assert all(w["orbit"] and w["factors"][0]["state"]!="insufficient" for w in doc["windows"])


def test_every_historical_day_has_a_dated_weather_release(tmp_path,monkeypatch):
    monkeypatch.setenv("COSMO_DB",str(tmp_path/"all_days.db"))
    first=datetime(2024,5,1,tzinfo=UTC)
    for offset in range(61):
        start=first+timedelta(days=offset,hours=6)
        events,records,_=archived_weather(start-timedelta(hours=6),start,start+timedelta(hours=2))
        assert records, start.date()
        assert all(e.published_at<=start-timedelta(hours=6) for e in events)
        assert any(e.valid_start<=start and e.valid_end>=start+timedelta(hours=2) for e in events)


def test_stale_orbit_blocks_favorable_comparison(tmp_path,monkeypatch):
    from app import analysis
    root=Path(__file__).parent/"fixtures"
    raw=RawRecord(id="fixture",source="noaa_current",url="https://services.swpc.noaa.gov/text/3-day-forecast.txt",
        content_sha256="fixture",retrieved_at=datetime(2026,9,18,13,tzinfo=UTC),
        published_at=datetime(2026,9,18,12,30,tzinfo=UTC))
    events=forecast_events((root/"noaa_3day_20260918.txt").read_text(),raw)
    tle=(root/"iss_20260918.tle").read_text().splitlines()
    monkeypatch.setattr(analysis,"current_weather",lambda refresh=False:(events,[raw],"fresh"))
    monkeypatch.setattr(analysis,"current_tle",lambda refresh=False:((tle[1],tle[2],raw),[raw],"stale"))
    windows,comparison,_=run(AnalysisRequest(mode="current",start="2026-09-18T18:00:00Z",
        duration_hours=2,search_hours=2))
    assert comparison.outcome=="insufficient"
    assert all(w.factors[1].state=="insufficient" and w.factors[1].freshness=="stale" for w in windows)
