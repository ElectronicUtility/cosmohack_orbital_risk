import json
import math
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.analysis import lighting_assessment
from app.domain import Window
from app.orbit import trajectory, interpolate_orbit
from app.storage import connect
from scripts.verify_bundle import verify
from scripts.validate_planning import reference_check

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def test_shadow_resolution_on_all_benchmark_windows():
    report = json.loads((ROOT / 'research_results/planning_validation.json').read_text())
    for row in report['rows']:
        from datetime import timedelta
        for shift in (0, 6, 12):
            start = datetime.fromisoformat(row['start']) + timedelta(hours=shift)
            window = Window(start=start, end=start + timedelta(hours=row['duration_hours']))
            values = [lighting_assessment(window, trajectory(window, 'reconstruction', step_minutes=step), True).overlap_minutes
                      for step in (5, 1)]
            assert abs(values[0] - values[1]) < .1, (row['start'], shift, values)


def test_arc_interpolation_preserves_altitude_and_reference_vector():
    window = Window(start='2024-05-05T01:00Z', end='2024-05-05T02:00Z')
    a, b = trajectory(window, 'reconstruction')[:2]
    midpoint = interpolate_orbit(a, b, .5)
    radius = lambda state: math.sqrt(sum(x*x for x in state.position_teme_km))
    assert radius(midpoint) == pytest.approx((radius(a)+radius(b))/2, abs=1e-8)
    assert reference_check()['position_error_km'] < 1e-5


@pytest.mark.parametrize('name', ['sunlight', 'tradeoff', 'window_demo', 'event', 'control'])
def test_bundled_examples_include_original_bytes_on_clean_install(name, tmp_path, monkeypatch):
    monkeypatch.setenv('COSMO_DB', str(tmp_path / 'clean.db'))
    response = client.get(f'/api/examples/{name}/bundle.zip')
    assert response.status_code == 200, response.text[:200] if response.status_code != 200 else ''
    bundle = tmp_path / 'evidence.zip'
    bundle.write_bytes(response.content)
    assert verify(bundle) > 0
    with zipfile.ZipFile(bundle) as archive:
        snapshot = json.loads(archive.read('analysis.json'))
    assert snapshot == client.get(f'/api/examples/{name}').json()


def test_parallel_plans_keep_parameters_and_export_rejects_corrupted_source(tmp_path, monkeypatch):
    monkeypatch.setenv('COSMO_DB', str(tmp_path / 'sessions.db'))
    request = dict(mode='reconstruction', start='2024-05-05T01:00Z', duration_hours=1,
                   search_hours=12, requires_sunlight=True)
    def calculate(name):
        with TestClient(app) as session:
            response = session.post('/api/analyze', json={**request, 'task_name': name})
            assert response.status_code == 200
            return response.json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(calculate, ['РћСЃРјРѕС‚СЂ A', 'РћСЃРјРѕС‚СЂ B'])
    assert first['id'] != second['id']
    for item in (first, second):
        assert client.get('/api/analyses/' + item['id']).json()['request'] == item['request']
    endpoint = '/api/analyses/' + first['id'] + '/bundle.zip'
    assert client.get(endpoint).status_code == 200
    with connect() as con:
        con.execute('UPDATE raw SET payload=?', (b'corrupted',))
    assert client.get(endpoint).status_code == 409


def test_refresh_with_disabled_sources_returns_health_without_network(tmp_path, monkeypatch):
    monkeypatch.setenv('COSMO_DB', str(tmp_path / 'offline.db'))
    monkeypatch.setenv('DISABLE_PROVIDERS', 'noaa_current,iss_current,socrates_current')
    response = client.post('/api/sources/refresh')
    assert response.status_code == 200
    assert all(provider['state'] == 'disabled' for provider in response.json().values())
    assert client.get('/api/examples/sunlight').json()['comparison']['outcome'] == 'preferred'


def test_validation_report_and_unknown_bundle():
    data = client.get('/api/validation').json()
    assert data['cases'] == 36 and data['windows'] == 108
    assert data['worse_cases'] == 0
    assert client.get('/api/examples/unknown/bundle.zip').status_code == 404
    assert client.get('/api/analyses/' + '0'*32 + '/bundle.zip').status_code == 404
