"""Bulletin-based validation over all May-June 2024 days, not a dose model.

SGAS prose is an independent verification product, not continuous flux truth.
Ambiguous prose is excluded. RSGA Proton and S1 probabilities stay separate;
we do not compute a Brier score for an unverified common probability target.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.providers import archived_weather, published

UTC = timezone.utc
ARCHIVE = ROOT / "data/validation/sgas"


def observation(text):
    issue = published(text)
    date_match = re.search(r'data received at SWO on (\d{2} \w{3})', text)
    if not date_match:
        raise ValueError("Missing observation day")
    day = datetime.strptime(str(issue.year) + ' ' + date_match[1], '%Y %d %b').replace(tzinfo=UTC)
    body = re.search(r'B\.\s+Proton Events:\s*(.*?)\nC\.', text, re.S)
    if not body:
        raise ValueError("Missing proton section")
    body = ' '.join(body[1].split())
    label = None
    if body.rstrip('.') == 'None' or 'has yet to cross the 10 pfu threshold' in body:
        label = False
    elif 'ended at 09/2140z' in body and day == datetime(2024, 6, 10, tzinfo=UTC):
        # This bulletin repeats the preceding day's event. It cannot label June 10.
        label = None
    elif (re.search(r'S[1-5] \(', body) or re.search(r'10 Me[vV] protons reached a peak flux of 116 pfu', body)
          or 'proton flux exceeded 10 pfu through' in body or 'proton flux reached 10 pfu beginning' in body):
        label = True
    return {'day': day.isoformat(), 'issued_at': issue.isoformat(), 'reported_event': label,
            'evidence': body}


def confusion(rows, key):
    pairs = [(r[key], r['reported_event']) for r in rows if r.get(key) is not None and r['reported_event'] is not None]
    tp = sum(p and y for p, y in pairs); fp = sum(p and not y for p, y in pairs)
    fn = sum(not p and y for p, y in pairs); tn = sum(not p and not y for p, y in pairs)
    return {'n': len(pairs), 'hits': tp, 'false_alerts': fp, 'misses': fn, 'correct_negatives': tn,
            'precision': tp/(tp+fp) if tp+fp else None, 'recall': tp/(tp+fn) if tp+fn else None}


def benchmark():
    records = []
    for item in json.loads((ARCHIVE/'manifest.json').read_text()):
        if item['status'] != 200:
            continue
        path = ROOT / item['path']; payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != item['sha256']:
            raise ValueError('Changed verification bytes: ' + str(path))
        row = observation(payload.decode())
        row.update(source_url=item['url'], source_sha256=item['sha256'])
        # Retrospective availability evidence for the baseline, same limitation
        # as the forecast archive; never claim a signed historical snapshot.
        row['available_at'] = max(datetime.fromisoformat(row['issued_at']),
                                  parsedate_to_datetime(item['last_modified'])).isoformat() if item['last_modified'] else None
        records.append(row)
    rows = []
    for offset in range(61):
        day = datetime(2024, 5, 1, tzinfo=UTC) + timedelta(days=offset)
        # Lock the forecast before looking up this day's verification record.
        events, sources, status = archived_weather(day, day, day+timedelta(days=1))
        forecasts = [e for e in events if e.kind == 'external_forecast' and e.valid_start == day]
        forecast = forecasts[0] if len(forecasts) == 1 and status == 'archive' else None
        row = next((dict(r) for r in records if r['day'] == day.isoformat()),
                   {'day': day.isoformat(), 'reported_event': None, 'evidence': 'Missing summary'})
        previous = [r for r in records if r['available_at'] and datetime.fromisoformat(r['available_at']) <= day
                    and r['reported_event'] is not None]
        prior = max(previous, key=lambda r: r['available_at']) if previous else None
        row.update(cutoff=day.isoformat(), probability_percent=forecast.value if forecast else None,
                   forecast_quantity=forecast.quantity if forecast else None,
                   forecast_source=forecast.source_url if forecast else None,
                   forecast_published_at=forecast.published_at.isoformat() if forecast else None,
                   forecast_sha256=sources[0].content_sha256 if sources else None,
                   alert_30_percent=forecast.value >= 30 if forecast else None,
                   persistence_alert=prior['reported_event'] if prior else None,
                   persistence_available_at=prior['available_at'] if prior else None,
                   persistence_source=prior['source_url'] if prior else None)
        rows.append(row)
    comparable = [r for r in rows if r['alert_30_percent'] is not None and r['persistence_alert'] is not None]
    return {'days': len(rows), 'labelled_days': sum(r['reported_event'] is not None for r in rows),
            'scope': 'Warnings at fixed 30% versus proton activity explicitly reported in subsequent NOAA SGAS. Bulletin labels, not continuous observed flux, ISS dose or proof of all-day quiet. Ambiguous days excluded.',
            'baseline': 'Persist the last SGAS event/no-event state whose issue and retrospective Last-Modified precede 00:00 UTC cutoff.',
            'forecast_method': 'Existing archived_weather selection with publication cutoff and archive SHA-256 validation; no fitting.',
            'alert_threshold_percent': 30,
            'forecast': confusion(comparable, 'alert_30_percent'),
            'persistence': confusion(comparable, 'persistence_alert'),
            'by_quantity': {q: confusion([r for r in comparable if r['forecast_quantity']==q], 'alert_30_percent')
                            for q in sorted({r['forecast_quantity'] for r in comparable})},
            'threshold_sensitivity': {str(t): confusion([{**r, 'alert': r['probability_percent']>=t} for r in comparable], 'alert')
                                      for t in (10, 30, 50)},
            'rows': rows}


if __name__ == '__main__':
    report = benchmark()
    (ROOT/'research_results/weather_validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}, ensure_ascii=False, indent=2))
