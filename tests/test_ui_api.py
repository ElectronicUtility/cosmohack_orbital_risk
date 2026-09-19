import json
from pathlib import Path
from fastapi.testclient import TestClient
from app.api import app

client = TestClient(app)


def test_examples_preserve_research_results_without_writing_database(tmp_path, monkeypatch):
    database = tmp_path / 'not-created.db'
    monkeypatch.setenv('COSMO_DB', str(database))
    for name in ('window_demo', 'event', 'control'):
        response = client.get(f'/api/examples/{name}')
        assert response.status_code == 200
        original = json.loads((Path(__file__).parents[1] / 'research_results' / f'{name}.json').read_text(encoding='utf-8'))
        result = response.json()
        assert result['comparison'] == original['comparison']
        assert result['request'] == original['request']
        assert result['windows'] == original['windows']
    assert not database.exists()


def test_examples_are_allowlisted_and_static_app_is_available():
    assert client.get('/api/examples/summary').status_code == 404
    assert client.get('/api/examples/unknown').status_code == 404
    assert client.get('/').status_code == 200
    for path in ('app.js', 'model.js', 'orbit.js', 'report.js', 'styles.css'):
        assert client.get('/static/' + path).status_code == 200
