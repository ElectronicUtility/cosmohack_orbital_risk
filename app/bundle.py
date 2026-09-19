"""Portable evidence bundle; missing or mismatched bytes fail closed."""
import hashlib
import io
import json
import platform
import zipfile

from .storage import ROOT, connect
from .providers import ARCHIVE, ISS_ARCHIVE
from .conjunctions import HISTORY


def source_bytes(record):
    digest = record['content_sha256']
    with connect() as con:
        row = con.execute('SELECT payload FROM raw WHERE id=?', (record['id'],)).fetchone()
    if row:
        if hashlib.sha256(row[0]).hexdigest() != digest:
            raise ValueError('Stored source failed its SHA-256 check')
        return row[0]
    # Only known bundled inputs, never a URL or an artifact_path from a record.
    candidates = {'iss_history_extract': [ISS_ARCHIVE],
                  'conjunction_tle_history': [HISTORY],
                  'noaa_archive': list(ARCHIVE.glob('*/*.txt'))}.get(record['source'], [])
    for path in candidates:
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() == digest:
            return payload
    raise ValueError('Original bytes are unavailable for ' + record['source'])


def build_bundle(analysis):
    files = {'analysis.json': json.dumps(analysis, ensure_ascii=False, indent=2).encode('utf-8'),
             'requirements.txt': (ROOT / 'requirements.txt').read_bytes()}
    sources = []
    for record in analysis['source_records']:
        payload = source_bytes(record)
        filename = 'sources/' + hashlib.sha256(payload).hexdigest() + '.bin'
        files[filename] = payload
        sources.append({'record_id': record['id'], 'file': filename})
    manifest = {'schema_version': 1, 'algorithm_version': analysis['algorithm_version'],
                'python_version': platform.python_version(), 'sources': sources,
                'files': {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}}
    files['manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return result.getvalue()
