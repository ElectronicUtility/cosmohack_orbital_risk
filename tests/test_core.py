from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.analysis import compare, conjunction_assessment, evaluate, run, weather_assessment
from app.conjunctions import historical_conjunction_source_record, reconstruct_historical_conjunctions
import app.conjunctions as conjunctions
from app.api import app
from app.domain import AnalysisRequest, ConjunctionEvent, ExternalEvent, FactorAssessment, Window, WindowAssessment
from app.orbit import state_at, trajectory
from app.providers import archived_weather, current_conjunctions, forecast_events, published, socrates_events, socrates_result_limits, socrates_results_truncated, socrates_threshold_km
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


def test_archive_last_modified_after_cutoff_excludes_issue(tmp_path, monkeypatch):
    monkeypatch.setenv("COSMO_DB", str(tmp_path / "issue.db"))
    events, records, status = archived_weather(dt(9, 22) + timedelta(minutes=5),
                                                 dt(10, 6), dt(10, 8))
    assert records and status == "archive"
    assert records[0].published_at < dt(9, 22)
    assert records[0].archive_last_modified_at <= dt(9, 22) + timedelta(minutes=5)
    assert all(e.published_at < dt(9, 22) for e in events)


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
    assert result.overlap_minutes is None
    assert result.forecast_probability_percent == 10


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


def test_historical_trajectory_holds_one_window_start_element_snapshot():
    window = Window(start=dt(10, 6), end=dt(10, 14))
    states = trajectory(window, "reconstruction")
    assert states
    assert states[0].at == window.start
    assert states[-1].at == window.end
    assert len({state.epoch for state in states}) == 1
    assert states[0].epoch <= window.start


def result(start, weather, lighting, bad=False):
    w = Window(start=start, end=start + timedelta(hours=6))
    vals = []
    for mechanism, value in [("measured_interval", weather), ("lighting", lighting)]:
        vals.append(FactorAssessment(mechanism=mechanism, state="insufficient" if bad else "attention",
            covered_minutes=0 if bad else 360, overlap_minutes=None if bad else value,
            comparison_value=None if bad else value, comparison_unit="minutes",
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


def test_comparison_reports_equivalent_pareto_frontier_without_calling_dominated_window_equivalent():
    first = result(dt(10), 10, 20)
    second = result(dt(10, 1), 10, 20)
    third = result(dt(10, 2), 30, 40)
    comparison = compare([first, second, third])
    assert comparison.outcome == "equivalent"
    assert comparison.preferred_index is None
    assert comparison.pareto_frontier_indices == [0, 1]
    assert "Парето-доминируемые окна: 3" in comparison.reasons[0]


def test_api_historical_e2e(tmp_path,monkeypatch):
    monkeypatch.setenv("COSMO_DB",str(tmp_path / "api.db"))
    client=TestClient(app)
    request={"mode":"replay","start":"2024-05-10T06:00:00Z","duration_hours":6,
             "search_hours":12,"cutoff":"2024-05-10T00:00:00Z","requires_sunlight":True}
    response=client.post("/api/analyze",json=request)
    assert response.status_code==200,response.text
    doc=response.json()
    assert len(doc["windows"])==3
    assert doc["windows"][0]["orbit"][0]["classification"].startswith("historical_reconstruction")
    factor_map={f["mechanism"]:f for f in doc["windows"][0]["factors"]}
    assert factor_map["space_weather"]["decision_eligible"] is True
    assert factor_map["conjunctions"]["decision_eligible"] is False
    assert factor_map["lighting"]["decision_eligible"] is False
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


def test_sources_api_reports_fresh_stale_missing_and_disabled(monkeypatch):
    from app import providers
    now = datetime.now(UTC)
    fixtures = Path(__file__).parent / "fixtures"

    def record(source, age_minutes):
        return RawRecord(
            id=source, source=source, url="https://example.org/" + source,
            content_sha256="a" * 64, retrieved_at=now - timedelta(minutes=age_minutes),
            cache_state="fresh",
        )

    records = {
        "noaa_current": record("noaa_current", 10),
        "iss_current": record("iss_current", 180),
    }
    payloads = {
        "noaa_current": (fixtures / "noaa_3day_20260918.txt").read_bytes(),
        "iss_current": (fixtures / "iss_20260918.tle").read_bytes(),
    }
    monkeypatch.setattr(
        providers, "latest_raw",
        lambda source: (payloads[source], records[source]) if source in records else None,
    )
    monkeypatch.setenv("DISABLE_PROVIDERS", "noaa_current")

    response = TestClient(app).get("/api/sources")
    assert response.status_code == 200
    sources = response.json()
    assert sources["noaa_current"]["state"] == "disabled"
    assert sources["noaa_current"]["enabled"] is False
    assert sources["iss_current"]["state"] == "cache_stale"
    assert sources["iss_current"]["enabled"] is True
    assert sources["socrates_current"]["state"] == "missing"
    assert sources["socrates_current"]["enabled"] is True

    monkeypatch.delenv("DISABLE_PROVIDERS", raising=False)
    response = TestClient(app).get("/api/sources")
    sources = response.json()
    assert sources["noaa_current"]["state"] == "cache_fresh"
    assert sources["noaa_current"]["last_successful_record"]["id"] == "noaa_current"


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
    monkeypatch.setattr(analysis,"current_conjunctions",lambda refresh=False:(
        [], [raw], "fresh", (datetime(2026,9,18,17,tzinfo=UTC), datetime(2026,9,25,17,tzinfo=UTC))))
    monkeypatch.setenv("COSMO_DB",str(tmp_path/"current.db"))
    response=TestClient(app).post("/api/analyze",json={"mode":"current","start":"2026-09-18T18:00:00Z",
        "duration_hours":2,"search_hours":2,"requires_sunlight":True})
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
    monkeypatch.setattr(analysis,"current_conjunctions",lambda refresh=False:(
        [], [raw], "fresh", (datetime(2026,9,18,17,tzinfo=UTC), datetime(2026,9,25,17,tzinfo=UTC))))
    windows,comparison,_=run(AnalysisRequest(mode="current",start="2026-09-18T18:00:00Z",
        duration_hours=2,search_hours=2,requires_sunlight=True))
    assert comparison.outcome=="insufficient"
    for window in windows:
        lighting = next(f for f in window.factors if f.mechanism == "lighting")
        assert lighting.state == "insufficient" and lighting.freshness == "stale"


def test_daily_forecast_is_not_adverse_duration():
    w = Window(start=dt(10, 6), end=dt(10, 12))
    e = ExternalEvent(id="forecast", mechanism="space_weather", kind="external_forecast",
        quantity="S1 probability", value=50, unit="%", valid_start=dt(10),
        valid_end=dt(11), published_at=dt(9, 22), raw_record_id="r", source_url="https://example.org/")
    f = weather_assessment(w, [e], "archive", dt(10))
    assert f.state == "attention"
    assert f.covered_minutes == 360
    assert f.overlap_minutes is None
    assert f.forecast_probability_percent == 50


def test_different_daily_probabilities_can_rank_distinct_windows():
    a = result(dt(10), 0, 20)
    b = result(dt(11), 0, 0)
    for w, p in [(a, 50), (b, 10)]:
        w.factors[0].mechanism = "space_weather"
        w.factors[0].comparison_value = p
        w.factors[0].comparison_unit = "daily_probability_percent"
    comparison = compare([a, b])
    assert comparison.outcome == "preferred" and comparison.preferred_index == 1


def test_cross_day_weather_is_not_collapsed_to_one_probability():
    w = Window(start=dt(10, 22), end=dt(11, 2))
    events = [
        ExternalEvent(id="d1", mechanism="space_weather", kind="external_forecast",
            quantity="S1 probability", value=50, unit="%", valid_start=dt(10), valid_end=dt(11),
            published_at=dt(9,22), raw_record_id="r", source_url="https://example.org/a"),
        ExternalEvent(id="d2", mechanism="space_weather", kind="external_forecast",
            quantity="S1 probability", value=10, unit="%", valid_start=dt(11), valid_end=dt(12),
            published_at=dt(9,22), raw_record_id="r", source_url="https://example.org/a"),
    ]
    factor = weather_assessment(w, events, "archive", dt(10))
    assert factor.completeness == "complete"
    assert factor.comparison_value is None


def test_noaa_kp_parser_preserves_three_hour_intervals_and_provenance():
    path = Path("data/noaa/3day_forecast/202405100030three_day_forecast.txt")
    issue = datetime(2024, 5, 10, 0, 30, tzinfo=UTC)
    raw = RawRecord(
        id="may10-forecast", source="noaa_archive",
        url="https://services.swpc.noaa.gov/products/3-day-forecast/2024/05/202405100030three_day_forecast.txt",
        content_sha256="fixture", retrieved_at=issue + timedelta(days=1), published_at=issue,
    )
    events = forecast_events(path.read_text(encoding="utf-8"), raw)
    kp = [event for event in events if event.kind == "external_forecast_context"]
    assert len(kp) == 24
    assert all(event.raw_record_id == raw.id for event in kp)
    assert all(event.published_at == issue for event in kp)
    assert all(event.valid_start.tzinfo is not None and event.valid_end.tzinfo is not None for event in kp)
    first = next(event for event in kp if event.valid_start == datetime(2024, 5, 10, 0, tzinfo=UTC))
    assert first.value == pytest.approx(3.33)
    assert first.valid_end - first.valid_start == timedelta(hours=3)
    g4 = next(event for event in kp if event.valid_start == datetime(2024, 5, 11, 6, tzinfo=UTC))
    assert g4.value == pytest.approx(8.33)
    assert g4.unit == "Kp index"


def test_kp_context_cannot_change_s1_decision_or_comparison_value():
    window = Window(start=dt(10, 6), end=dt(10, 9))
    s1 = ExternalEvent(
        id="s1", mechanism="space_weather", kind="external_forecast",
        quantity="S1 probability", value=50, unit="%", valid_start=dt(10), valid_end=dt(11),
        published_at=dt(9, 22), raw_record_id="s1", source_url="https://example.org/s1",
    )

    def kp(value: float) -> ExternalEvent:
        return ExternalEvent(
            id=f"kp-{value}", mechanism="space_weather", kind="external_forecast_context",
            quantity="NOAA expected 3-hour planetary Kp", value=value, unit="Kp index",
            valid_start=dt(10, 6), valid_end=dt(10, 9), published_at=dt(9, 22),
            raw_record_id="kp", source_url="https://example.org/kp",
        )

    low = weather_assessment(window, [s1, kp(1.0)], "archive", dt(10))
    high = weather_assessment(window, [s1, kp(9.0)], "archive", dt(10))
    assert (low.state, low.comparison_value, low.forecast_probability_percent) == (
        high.state, high.comparison_value, high.forecast_probability_percent
    )
    assert low.comparison_value == 50
    assert high.comparison_value == 50
    assert any(item.get("role") == "forecast_context_only" for item in high.evidence)


def test_socrates_six_hour_horizon_requires_fresh_source_and_full_horizon():
    source_as_of = datetime(2026, 9, 18, 12, tzinfo=UTC)
    window = Window(start=source_as_of + timedelta(hours=1), end=source_as_of + timedelta(hours=2))

    fresh = conjunction_assessment(
        window, [], "fresh",
        coverage=(source_as_of, source_as_of + timedelta(days=7)),
        source_as_of=source_as_of,
    )
    assert fresh.supports_next_6h_horizon is True
    assert fresh.forecast_horizon_hours == pytest.approx(168.0)

    partial = conjunction_assessment(
        window, [], "fresh",
        coverage=(source_as_of, source_as_of + timedelta(hours=5)),
        source_as_of=source_as_of,
    )
    assert partial.state != "insufficient"
    assert partial.supports_next_6h_horizon is False
    assert partial.forecast_horizon_hours == pytest.approx(5.0)

    stale = conjunction_assessment(
        window, [], "stale",
        coverage=(source_as_of, source_as_of + timedelta(days=7)),
        source_as_of=source_as_of,
    )
    assert stale.state == "insufficient"
    assert stale.supports_next_6h_horizon is False


def test_unrequested_lighting_constraint_is_excluded_from_decision():
    first = result(dt(10), 20, 0)
    second = result(dt(10, 1), 10, 999)
    for window, weather in ((first, 20), (second, 10)):
        window.factors[0].mechanism = "space_weather"
        window.factors[0].comparison_value = weather
        window.factors[0].comparison_unit = "daily_probability_percent"
        window.factors[1].mechanism = "lighting"
        window.factors[1].role = "plan_constraint"
        window.factors[1].decision_eligible = False
        window.factors[1].eligibility_reason = "Direct sunlight was not declared by the analyst as a planning constraint."
        window.factors[1].comparison_value = None
    comparison = compare([first, second])
    assert comparison.outcome == "preferred"
    assert comparison.preferred_index == 1
    assert comparison.decision_mechanisms == ["space_weather"]


def test_reconstruction_never_uses_a_forecast_published_after_window_start(tmp_path, monkeypatch):
    from app import analysis
    monkeypatch.setenv("COSMO_DB", str(tmp_path / "reconstruction.db"))
    monkeypatch.setattr(analysis, "reconstruct_historical_conjunctions", lambda window, record_id: (
        [], {"status": "historical_reconstruction", "candidate_objects": 1}
    ))
    windows, _, records = run(AnalysisRequest(
        mode="reconstruction", start=dt(10, 6), duration_hours=2,
        search_hours=12, requires_sunlight=False,
    ))
    weather_records = [record for record in records if record.source == "noaa_archive"]
    assert weather_records
    for window in windows:
        factor = next(item for item in window.factors if item.mechanism == "space_weather")
        assert factor.evidence
        assert all(
            datetime.fromisoformat(item["event"]["published_at"]) <= window.window.start
            for item in factor.evidence
        )
    assert all(record.published_at is None or any(
        record.published_at <= window.window.start for window in windows
    ) for record in weather_records)


def test_socrates_parser_preserves_orbital_metric_semantics():
    text = """
    <li>Return first 100 items</li>
    Data current as of 2026 Sep 17 22:14:23 UTC
    Computation Interval: Start = 2026 Sep 17 22:00:00 UTC, Stop = 2026 Sep 24 22:00:00 UTC
    Computation Threshold: 5.0 km
    <table>
      <tr><td>GP Data</td><td>25544</td><td>ISS (ZARYA) [+]</td><td>0.2</td><td>2026-09-21 21:20:21.992</td><td>1.732</td><td>15.319</td></tr>
      <tr><td>50 km All</td><td>39469</td><td>SMDC ONE 2.4 [+]</td><td>0.3</td><td>3.045E-05</td><td>0.937</td></tr>
    </table>
    <p>1 records found</p>
    """
    raw = RawRecord(id="s", source="socrates_current", url="https://celestrak.org/SOCRATES/",
        content_sha256="x", retrieved_at=datetime(2026,9,18,tzinfo=UTC),
        published_at=datetime(2026,9,17,22,14,23,tzinfo=UTC))
    events, coverage = socrates_events(text, raw)
    assert socrates_threshold_km(text) == 5.0
    assert socrates_result_limits(text) == (100, 1)
    assert coverage == (datetime(2026,9,17,22,tzinfo=UTC), datetime(2026,9,24,22,tzinfo=UTC))
    assert len(events) == 1
    event = events[0]
    assert event.object_norad_id == 39469
    assert event.min_separation_km == 1.732
    assert event.relative_speed_km_s == 15.319
    assert event.max_probability == pytest.approx(3.045e-5)
    assert any("not the probability of striking an EVA crewmember" in item for item in event.limitations)


def test_socrates_effective_limit_is_read_from_page():
    text = "<li>Return first 100 items</li><p>100 records found</p>"
    assert socrates_result_limits(text) == (100, 100)
    assert socrates_results_truncated(text) is False


def test_socrates_truncation_requires_more_matches_than_effective_limit():
    text = "<li>Return first 100 items</li><p>101 records found</p>"
    assert socrates_results_truncated(text) is True


def test_socrates_parser_accepts_a_clipped_page_and_leaves_it_for_truncation_handling():
    rows = []
    for index in range(100):
        other_id = 40000 + index
        rows.append(
            f"<tr><td>GP Data</td><td>25544</td><td>ISS (ZARYA) [+]</td><td>0.2</td>"
            f"<td>2026-09-21 21:{index % 60:02d}:21.992</td><td>1.732</td><td>15.319</td></tr>"
        )
        rows.append(
            f"<tr><td>50 km All</td><td>{other_id}</td><td>OBJECT {other_id} [+]</td><td>0.3</td>"
            f"<td>3.045E-05</td><td>0.937</td></tr>"
        )
    text = (
        "<li>Return first 100 items</li>"
        "Data current as of 2026 Sep 17 22:14:23 UTC "
        "Computation Interval: Start = 2026 Sep 17 22:00:00 UTC, "
        "Stop = 2026 Sep 24 22:00:00 UTC "
        "Computation Threshold: 5.0 km "
        "<table>" + "".join(rows) + "</table>"
        "<p>137 records found</p>"
    )
    raw = RawRecord(id="clipped", source="socrates_current", url="https://celestrak.org/SOCRATES/",
        content_sha256="x", retrieved_at=datetime(2026,9,18,tzinfo=UTC),
        published_at=datetime(2026,9,17,22,14,23,tzinfo=UTC))
    events, _ = socrates_events(text, raw)
    assert len(events) == 100
    assert socrates_result_limits(text) == (100, 137)


def test_socrates_old_upstream_computation_is_stale_even_after_fresh_download(monkeypatch):
    from app import providers
    text = """
    <li>Return first 100 items</li>
    Data current as of 2026 Sep 17 22:14:23 UTC
    Computation Interval: Start = 2026 Sep 17 22:00:00 UTC, Stop = 2026 Sep 24 22:00:00 UTC
    Computation Threshold: 5.0 km
    <p>0 records found</p>
    """
    raw = RawRecord(
        id="stale-upstream", source="socrates_current", url="https://celestrak.org/SOCRATES/",
        content_sha256="x", retrieved_at=datetime(2026, 9, 18, 20, 45, tzinfo=UTC),
        published_at=datetime(2026, 9, 17, 22, 14, 23, tzinfo=UTC),
    )
    monkeypatch.setattr(providers, "fetch_current", lambda *args, **kwargs: (text.encode(), raw, "fresh"))
    events, records, status, coverage = current_conjunctions(refresh=True)
    assert events == []
    assert records == [raw]
    assert status == "stale"
    assert coverage == (datetime(2026, 9, 17, 22, tzinfo=UTC), datetime(2026, 9, 24, 22, tzinfo=UTC))


def test_sources_health_validates_cached_socrates_payload_and_source_timestamp(monkeypatch):
    from app import providers
    now = datetime.now(UTC)
    stale_as_of = now - timedelta(hours=20)
    stale_text = f"""
    <li>Return first 100 items</li>
    Data current as of {stale_as_of:%Y %b %d %H:%M:%S} UTC
    Computation Interval: Start = {stale_as_of:%Y %b %d %H}:00:00 UTC, Stop = {(stale_as_of + timedelta(days=7)):%Y %b %d %H}:00:00 UTC
    Computation Threshold: 5.0 km
    <p>0 records found</p>
    """.encode()
    record = RawRecord(
        id="socrates-health", source="socrates_current", url="https://celestrak.org/SOCRATES/",
        content_sha256="x", retrieved_at=now - timedelta(minutes=5), published_at=stale_as_of,
    )
    monkeypatch.setattr(
        providers, "latest_raw",
        lambda source: (stale_text, record) if source == "socrates_current" else None,
    )
    monkeypatch.delenv("DISABLE_PROVIDERS", raising=False)
    health = providers.current_provider_health()["socrates_current"]
    assert health["state"] == "source_stale"
    assert health["validation_state"] == "valid"
    assert health["source_data_at"].startswith(stale_as_of.strftime("%Y-%m-%dT%H:%M:%S"))

    malformed = b"Data current as of 2026 Sep 18 20:00:00 UTC"
    monkeypatch.setattr(
        providers, "latest_raw",
        lambda source: (malformed, record) if source == "socrates_current" else None,
    )
    assert providers.current_provider_health()["socrates_current"]["state"] == "invalid"


def test_current_tle_fresh_download_with_old_element_epoch_is_stale(monkeypatch):
    from app import providers
    fixture = (Path(__file__).parent / "fixtures" / "iss_20260918.tle").read_bytes()
    lines = [line for line in fixture.decode().splitlines() if line.startswith(("1 ", "2 "))]
    epoch = providers.tle_epoch(lines[0], lines[1])
    raw = RawRecord(
        id="old-tle", source="iss_current", url=providers.ISS_CURRENT,
        content_sha256="x", retrieved_at=epoch + timedelta(days=3),
    )
    monkeypatch.setattr(providers, "fetch_current", lambda *args, **kwargs: (fixture, raw, "fresh"))
    current, records, status = providers.current_tle(refresh=True)
    assert current is not None and records == [raw]
    assert status == "stale"


def test_sources_health_exposes_tle_epoch_and_rejects_old_source_data(monkeypatch):
    from app import providers
    fixture = (Path(__file__).parent / "fixtures" / "iss_20260918.tle").read_bytes()
    lines = [line for line in fixture.decode().splitlines() if line.startswith(("1 ", "2 "))]
    epoch = providers.tle_epoch(lines[0], lines[1])
    record = RawRecord(
        id="tle-health", source="iss_current", url=providers.ISS_CURRENT,
        content_sha256="x", retrieved_at=epoch + timedelta(days=3),
    )
    monkeypatch.setattr(
        providers, "latest_raw",
        lambda source: (fixture, record) if source == "iss_current" else None,
    )
    monkeypatch.delenv("DISABLE_PROVIDERS", raising=False)
    health = providers.current_provider_health()["iss_current"]
    assert health["state"] == "source_stale"
    assert health["validation_state"] == "valid"
    assert datetime.fromisoformat(health["source_data_at"]) == epoch
    assert health["source_data_age_at_retrieval_minutes"] > 2 * 24 * 60
    assert health["source_expected_max_age_minutes"] == 2 * 24 * 60


def test_historical_no_event_never_becomes_favorable_value():
    w = Window(start=dt(10,6), end=dt(10,8))
    factor = conjunction_assessment(w, [], "historical_reconstruction", reconstruction_meta={
        "status": "historical_reconstruction", "candidate_objects": 100,
    })
    assert factor.state == "no_reconstructed_close_approach_within_screen"
    assert factor.comparison_value is None
    assert factor.completeness == "reconstruction_unverified_catalog_completeness"
    assert factor.decision_eligible is False
    assert "catalog completeness" in factor.eligibility_reason


def test_historical_persistent_proximity_is_ambiguous_and_not_comparable():
    w = Window(start=dt(10,6), end=dt(10,8))
    event = ConjunctionEvent(
        id="persistent", tca=dt(10,7), min_separation_km=0.25, relative_speed_km_s=0.01,
        object_norad_id=4242, object_name="UNIDENTIFIED", source_record_ids=["historical"],
        source_url="https://example.org/history", classification="historical_persistent_proximity_ambiguous",
        algorithm_version="test",
    )
    factor = conjunction_assessment(w, [event], "historical_reconstruction", reconstruction_meta={
        "status": "historical_reconstruction", "candidate_objects": 100,
    })
    assert factor.state == "ambiguous_persistent_proximity"
    assert factor.comparison_value is None
    assert factor.decision_eligible is False
    assert any("persistently close" in item for item in factor.limitations)


def test_historical_reconstructed_event_is_validation_only_even_outside_strict_replay():
    w = Window(start=dt(10,6), end=dt(10,8))
    event = ConjunctionEvent(
        id="reconstructed", tca=dt(10,7), min_separation_km=2.5, relative_speed_km_s=12.0,
        object_norad_id=4242, object_name="TEST", source_record_ids=["historical"],
        source_url="https://example.org/history", classification="historical_tle_geometry_reconstruction",
        algorithm_version="test",
    )
    factor = conjunction_assessment(w, [event], "historical_reconstruction", reconstruction_meta={
        "status": "historical_reconstruction", "candidate_objects": 100,
    })
    assert factor.state == "reconstructed_close_approach"
    assert factor.comparison_value == pytest.approx(2.5)
    assert factor.decision_eligible is False
    assert "reconstruction/validation only" in factor.eligibility_reason


def test_missing_current_conjunctions_never_becomes_favorable():
    w = Window(start=dt(10,6), end=dt(10,8))
    factor = conjunction_assessment(w, [], "disabled", coverage=(dt(10), dt(11)))
    assert factor.state == "insufficient"
    assert factor.comparison_value is None


def test_known_iss_visiting_vehicle_not_reported_as_debris_conjunction():
    window = Window(start=datetime(2024, 6, 12, 6, tzinfo=UTC),
                    end=datetime(2024, 6, 12, 8, tzinfo=UTC))
    record = historical_conjunction_source_record()
    events, metadata = reconstruct_historical_conjunctions(window, record.id)
    assert all(event.object_norad_id != 59913 for event in events)
    exclusions = metadata["excluded_known_iss_associations"]
    progress = next(item for item in exclusions if item["norad_id"] == 59913)
    assert progress["association"]["name"] == "Progress MS-27 / Progress 88"
    assert progress["association"]["relationship"] == "ISS visiting vehicle"


def test_historical_screen_refines_all_admitted_intervals_and_finds_deeper_between_sample_pass(monkeypatch):
    start = dt(10, 6)
    window = Window(start=start, end=start + timedelta(seconds=180))

    class FakeSat:
        def __init__(self, kind):
            self.kind = kind

        def sgp4(self, jd, seconds):
            if self.kind == "iss":
                return 0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
            t = float(seconds)
            if t <= 60:
                distance = 0.5 + 0.3 * abs(t - 30)
                speed = 0.3
            elif t < 120:
                distance = 20.0
                speed = 0.0
            else:
                distance = 4.0 + 0.05 * abs(t - 150)
                speed = 0.05
            return 0, (distance, 0.0, 0.0), (speed, 0.0, 0.0)

    iss = FakeSat("iss")
    obj = FakeSat("object")
    monkeypatch.setattr(conjunctions, "julian", lambda at: (0.0, (at - start).total_seconds()))
    monkeypatch.setattr(conjunctions, "_iss_satrec", lambda at: (iss, start))
    monkeypatch.setattr(conjunctions, "_latest_candidate_rows", lambda at: [{
        "norad_id": 4242, "intl_designator": "TEST-OBJECT"
    }])
    monkeypatch.setattr(conjunctions, "_remove_duplicate_states", lambda rows: (rows, []))
    monkeypatch.setattr(conjunctions, "historical_satrec", lambda row: (obj, start))
    monkeypatch.setattr(conjunctions, "_known_association", lambda norad_id, at: None)
    monkeypatch.setattr(conjunctions, "_persistent_proximity", lambda *args: None)
    monkeypatch.setattr(conjunctions, "_candidate_updates_in_window", lambda window: {
        4242: {
            "first_epoch": start + timedelta(seconds=90),
            "last_epoch": start + timedelta(seconds=150),
            "element_count": 2,
        }
    })
    monkeypatch.setattr(conjunctions, "_iss_updates_in_window", lambda window: [start + timedelta(seconds=120)])

    events, metadata = reconstruct_historical_conjunctions(window, "synthetic-source")
    assert len(events) == 1
    assert events[0].min_separation_km == pytest.approx(0.5, abs=1e-3)
    assert abs((events[0].tca - (start + timedelta(seconds=30))).total_seconds()) < 0.1
    assert metadata["screened_candidates"] == 1
    assert metadata["refined_coarse_intervals"] >= 2
    assert metadata["element_snapshot_policy"].startswith("latest element epoch")
    sensitivity = metadata["snapshot_sensitivity"]
    assert sensitivity["candidate_objects_with_later_element_epoch_inside_window"] == 1
    assert sensitivity["candidate_object_fraction_with_later_element_epoch_inside_window"] == pytest.approx(1.0)
    assert sensitivity["iss_later_element_epoch_count_inside_window"] == 1
    assert sensitivity["reported_events"][0]["later_object_element_epoch_precedes_tca"] is False
    assert sensitivity["reported_events"][0]["object_element_age_hours_at_tca"] == pytest.approx(30 / 3600)
    assert metadata["candidate_element_age_hours_at_window_start"]["p50"] == 0
    assert any("window-start snapshot policy" in item for item in events[0].limitations)


def test_comparator_ignores_validation_only_factors():
    first = result(dt(10), 50, 999)
    second = result(dt(10,1), 10, 0)
    for window in (first, second):
        window.factors[0].mechanism = "space_weather"
        window.factors[0].comparison_unit = "daily_probability_percent"
        window.factors[1].mechanism = "historical_geometry"
        window.factors[1].decision_eligible = False
        window.factors[1].eligibility_reason = "publication time unavailable"
    first.factors[0].comparison_value = 50
    second.factors[0].comparison_value = 10
    comparison = compare([first, second])
    assert comparison.outcome == "preferred"
    assert comparison.preferred_index == 1
    assert comparison.decision_mechanisms == ["space_weather"]
    assert comparison.excluded_mechanisms == [{
        "mechanism": "historical_geometry", "reason": "publication time unavailable"
    }]


def test_comparator_rejects_incompatible_units_even_when_values_match():
    first = result(dt(10), 10, 0)
    second = result(dt(10,1), 10, 0)
    first.factors = [first.factors[0]]
    second.factors = [second.factors[0]]
    first.factors[0].mechanism = "space_weather"
    second.factors[0].mechanism = "space_weather"
    first.factors[0].comparison_unit = "percent"
    second.factors[0].comparison_unit = "minutes"
    assert compare([first, second]).outcome == "insufficient"


def test_comparator_rejects_different_noaa_forecast_quantities():
    first = result(dt(10), 10, 0)
    second = result(dt(10, 1), 10, 0)
    first.factors = [first.factors[0]]
    second.factors = [second.factors[0]]
    for window in (first, second):
        window.factors[0].mechanism = "space_weather"
        window.factors[0].comparison_unit = "daily_probability_percent"
    first.factors[0].comparison_quantity = "NOAA S1-or-greater forecast probability"
    second.factors[0].comparison_quantity = "USAF/NOAA proton event probability (daily proxy)"
    assert compare([first, second]).outcome == "insufficient"


def test_comparator_rejects_incompatible_directions_even_when_values_match():
    first = result(dt(10), 10, 0)
    second = result(dt(10,1), 10, 0)
    first.factors = [first.factors[0]]
    second.factors = [second.factors[0]]
    first.factors[0].mechanism = "conjunctions"
    second.factors[0].mechanism = "conjunctions"
    first.factors[0].comparison_direction = "higher_is_better"
    second.factors[0].comparison_direction = "lower_is_better"
    assert compare([first, second]).outcome == "insufficient"


def test_comparator_rejects_duplicate_eligible_mechanism():
    first = result(dt(10), 10, 20)
    second = result(dt(10,1), 10, 20)
    first.factors[1].mechanism = first.factors[0].mechanism
    assert compare([first, second]).outcome == "insufficient"


def test_replay_conjunction_and_lighting_cannot_change_decision():
    first = result(dt(10), 0, 0)
    second = result(dt(10, 1), 0, 0)
    for window, weather in ((first, 40), (second, 10)):
        window.factors = [FactorAssessment(
            mechanism="space_weather", state="attention", covered_minutes=360, overlap_minutes=None,
            comparison_value=weather, comparison_unit="daily_probability_percent",
            completeness="complete", freshness="archive", algorithm_version="test",
        ), FactorAssessment(
            mechanism="conjunctions", state="reconstructed_close_approach", covered_minutes=360, overlap_minutes=None,
            comparison_value=0.1 if window is second else 1000, comparison_unit="minimum_modeled_separation_km",
            comparison_direction="higher_is_better", decision_eligible=False,
            eligibility_reason="historical publication unavailable",
            completeness="reconstruction", freshness="historical", algorithm_version="test",
        ), FactorAssessment(
            mechanism="lighting", role="plan_constraint", state="attention", covered_minutes=360, overlap_minutes=360,
            comparison_value=360 if window is second else 0, comparison_unit="minutes_of_plan_constraint",
            decision_eligible=False, eligibility_reason="historical publication unavailable",
            completeness="reconstruction", freshness="historical", algorithm_version="test",
        )]
    comparison = compare([first, second])
    assert comparison.outcome == "preferred"
    assert comparison.preferred_index == 1
    assert comparison.decision_mechanisms == ["space_weather"]
    assert {item["mechanism"] for item in comparison.excluded_mechanisms} == {"conjunctions", "lighting"}


def test_analyst_must_declare_lighting_constraint():
    with pytest.raises(ValueError):
        AnalysisRequest(mode="replay", start=dt(10, 6), cutoff=dt(10),
                        duration_hours=6, search_hours=12)


def test_db_location_follows_request_environment(tmp_path, monkeypatch):
    from app.storage import store_raw
    location = tmp_path / "isolated.sqlite"
    monkeypatch.setenv("COSMO_DB", str(location))
    store_raw("isolation", "https://example.org/a", b"a")
    assert location.exists()
