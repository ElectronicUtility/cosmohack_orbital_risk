"""Verify exported bytes without extracting a ZIP: python scripts/verify_bundle.py bundle.zip."""
import hashlib
import json
import sys
import zipfile


def verify(path):
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        for name, digest in manifest['files'].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError('SHA-256 mismatch: ' + name)
        analysis = json.loads(archive.read('analysis.json'))
        records = {r['id']: r for r in analysis['source_records']}
        if {s['record_id'] for s in manifest['sources']} != set(records):
            raise ValueError('Source set differs from saved analysis')
        for source in manifest['sources']:
            if hashlib.sha256(archive.read(source['file'])).hexdigest() != records[source['record_id']]['content_sha256']:
                raise ValueError('Source differs from saved analysis: ' + source['record_id'])
        return len(records)


if __name__ == '__main__':
    print(f'Verified {verify(sys.argv[1])} source records and all bundled files.')
