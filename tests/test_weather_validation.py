import json
from datetime import datetime
from pathlib import Path

import pytest

from scripts.validate_weather import benchmark, observation

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'data/validation/sgas'


@pytest.mark.parametrize('filename,expected', [
    ('20240503SGAS.txt', False),  # Explicit None, not absence from an onset catalogue.
    ('20240511SGAS.txt', True),
    ('20240611SGAS.txt', None),   # Repeats an event that ended the preceding day.
    ('20240613SGAS.txt', False),  # Elevated, but explicitly below threshold.
])
def test_verification_does_not_mislabel_previous_events_or_elevated_flux(filename, expected):
    assert observation((ARCHIVE/filename).read_text())['reported_event'] is expected


def test_validation_reproduces_saved_results_with_past_only_baseline(tmp_path, monkeypatch):
    monkeypatch.setenv('COSMO_DB', str(tmp_path/'validation.db'))
    actual = benchmark()
    assert actual == json.loads((ROOT/'research_results/weather_validation.json').read_text())
    for row in actual['rows']:
        cutoff = datetime.fromisoformat(row['cutoff'])
        assert datetime.fromisoformat(row['forecast_published_at']) <= cutoff
        assert datetime.fromisoformat(row['persistence_available_at']) <= cutoff
        assert datetime.fromisoformat(row['issued_at']) > cutoff
    assert actual['labelled_days'] == 60
