"""Check solar direction and shadow duration against a separate ERFA ephemeris.

Uses direct SGP4 states, not production arc interpolation, at 10-second midpoints.
The cylinder and source TLE are shared, so this is not orbital ground truth.
"""
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import astropy
import numpy as np
from astropy.coordinates import TEME, get_sun
from astropy.time import Time
from astropy.utils import iers

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.analysis import lighting_assessment
from app.domain import Window
from app.orbit import historical_row_at, historical_satrec, sun_vector, trajectory
from app.providers import ISS_ARCHIVE


def benchmark():
    iers.conf.auto_download = False
    dates = [datetime(2024, 5, 1, tzinfo=timezone.utc)+timedelta(hours=6*i) for i in range(244)]
    times = Time(dates)
    solar = get_sun(times).transform_to(TEME(obstime=times)).cartesian.xyz.value.T
    solar /= np.linalg.norm(solar, axis=1)[:, None]
    model = np.array([sun_vector(d) for d in dates])
    angles = np.degrees(np.arccos(np.clip(np.sum(model*solar, axis=1), -1, 1)))
    rows = []
    for offset in range(0, 60, 5):
        start = datetime(2024, 5, 1, 6, tzinfo=timezone.utc)+timedelta(days=offset)
        for duration in (1, 2, 6):
            window = Window(start=start, end=start+timedelta(hours=duration))
            dates = [start+timedelta(seconds=5+10*i) for i in range(duration*360)]
            times = Time(dates)
            sat, _ = historical_satrec(historical_row_at(start))
            errors, positions, _ = sat.sgp4_array(times.jd1, times.jd2)
            assert not errors.any()
            solar = get_sun(times).transform_to(TEME(obstime=times)).cartesian.xyz.value.T
            solar /= np.linalg.norm(solar, axis=1)[:, None]
            dot = np.sum(positions*solar, axis=1)
            dark = (dot < 0) & (np.sum(positions*positions, axis=1)-dot*dot < 6378.137**2)
            reference = float(np.sum(dark))/6
            actual = lighting_assessment(window, trajectory(window, 'reconstruction'), True).overlap_minutes
            rows.append({'start': start.isoformat(), 'duration_hours': duration,
                         'production_shadow_minutes': actual, 'reference_shadow_minutes': reference,
                         'absolute_difference_minutes': abs(actual-reference)})
    return {'astropy_version': astropy.__version__, 'solar_samples': len(angles), 'shadow_windows': len(rows),
            'reference': 'Astropy get_sun (ERFA), transformed GCRS to TEME, direct SGP4 at 10-second midpoints',
            'reference_documentation': 'https://docs.astropy.org/en/stable/api/astropy.coordinates.get_sun.html',
            'source_sha256': hashlib.sha256(ISS_ARCHIVE.read_bytes()).hexdigest(),
            'max_solar_direction_difference_degrees': float(max(angles)),
            'max_shadow_difference_minutes': max(r['absolute_difference_minutes'] for r in rows),
            'mean_shadow_difference_minutes': float(np.mean([r['absolute_difference_minutes'] for r in rows])),
            'limitations': 'Independent solar ephemeris and direct propagation; shared TLE and cylindrical shadow. Does not validate actual ISS position, atmospheric refraction, penumbra or crew illumination.',
            'rows': rows}


if __name__ == '__main__':
    result = benchmark()
    (ROOT/'research_results/solar_validation.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}, indent=2))
