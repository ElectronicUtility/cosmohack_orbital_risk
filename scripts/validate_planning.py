"""Deterministic lighting benchmark, with a separate SGP4 published-vector check.

The one-minute reference shares the physical model and is a resolution check,
not independent orbital truth or a probabilistic weather validation.
"""
from __future__ import annotations
import hashlib
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.analysis import lighting_assessment
from app.domain import Window
from app.orbit import trajectory
from app.providers import ISS_ARCHIVE
from sgp4.api import Satrec

def reference_check():
    # Vallado verification case 00005, tcppver.out (distributed with python-sgp4).
    # https://github.com/brandon-rhodes/python-sgp4/blob/master/sgp4/tcppver.out
    sat = Satrec.twoline2rv(
        '1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753',
        '2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667')
    error, actual, _ = sat.sgp4(sat.jdsatepoch, sat.jdsatepochF + 360 / 1440)
    expected = (-7154.03120202, -3783.17682504, -3536.19412294)
    delta = sum((x-y)**2 for x,y in zip(actual, expected))**0.5
    assert error == 0 and delta < 1e-5
    return {'case': 'Vallado 00005, epoch +360 min', 'position_error_km': delta,
            'expected_teme_km': expected, 'actual_teme_km': actual,
            'scope': 'SGP4 propagation reference, not validation of ISS element accuracy or shadow model'}

def benchmark():
    rows=[]; errors=[]; false_alerts=misses=0
    for day in range(0,60,5):
        for duration in (1,2,6):
            start=datetime(2024,5,1,6,tzinfo=timezone.utc)+timedelta(days=day)
            coarse=[]; reference=[]
            for shift in (0,6,12):
                w=Window(start=start+timedelta(hours=shift),end=start+timedelta(hours=shift+duration))
                values=[]
                for step in (5,1):
                    factor=lighting_assessment(w,trajectory(w,'reconstruction',step_minutes=step),True)
                    assert factor.overlap_minutes is not None, w
                    values.append(factor.overlap_minutes)
                coarse.append(values[0]);reference.append(values[1]);errors.append(abs(values[0]-values[1]))
                false_alerts+=int(values[0]>0 and values[1]==0)
                misses+=int(values[0]==0 and values[1]>0)
            best=min(range(3), key=lambda i:coarse[i])
            optimal=min(reference)
            rows.append({'start':start.isoformat(),'duration_hours':duration,
                         'shadow_minutes_5m':coarse,'shadow_minutes_1m':reference,
                         'selected_index':best,'baseline_shadow_minutes':reference[0],
                         'selected_shadow_minutes':reference[best],
                         'improvement_minutes':reference[0]-reference[best],
                         'selection_regret_minutes':reference[best]-optimal})
    return {'schema_version':1, 'cases':len(rows),'windows':len(errors),
            'method':'Light-only selection among start, +6h, +12h; baseline is original start; evaluated on one-minute grid',
            'scope':'Lighting constraint only. Neither full multi-factor recommendation nor weather skill; reference uses same orbit and shadow model.',
            'source_sha256':hashlib.sha256(ISS_ARCHIVE.read_bytes()).hexdigest(),
            'improved_cases':sum(r['improvement_minutes']>0 for r in rows),
            'worse_cases':sum(r['improvement_minutes']<0 for r in rows),
            'mean_improvement_minutes':statistics.mean(r['improvement_minutes'] for r in rows),
            'mean_absolute_error_minutes':statistics.mean(errors),'max_absolute_error_minutes':max(errors),
            'max_selection_regret_minutes':max(r['selection_regret_minutes'] for r in rows),
            'false_shadow_alerts_vs_1m':false_alerts,'missed_shadow_windows_vs_1m':misses,
            'orbit_reference':reference_check(),'rows':rows}

if __name__=='__main__':
    result=benchmark()
    target=ROOT/'research_results'/'planning_validation.json'
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False,indent=2))
