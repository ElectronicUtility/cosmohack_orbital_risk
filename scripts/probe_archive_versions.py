"""Record current NOAA archive bytes and HTTP Last-Modified for replay eligibility.

This is retrospective evidence, not an immutable, signed 2024 snapshot.
"""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports/"
paths = sorted((ROOT / "data" / "noaa").glob("*/*.txt"))


def probe(path: Path):
    issue = path.read_text(encoding="utf-8", errors="replace").split(":Issued: ", 1)[1].splitlines()[0]
    date = datetime.strptime(issue, "%Y %b %d %H%M UTC").replace(tzinfo=timezone.utc)
    url = f"{BASE}{path.parent.name}/{date:%Y/%m}/{path.name}"
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
    digest = hashlib.sha256(response.content).hexdigest()
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError(f"Archive bytes changed: {url}")
    modified = response.headers.get("Last-Modified")
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "url": url,
            "sha256": digest, "issued_at": date.isoformat(),
            "http_last_modified": parsedate_to_datetime(modified).astimezone(timezone.utc).isoformat() if modified else None,
            "checked_at": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=5) as pool:
        rows = list(pool.map(probe, paths))
    output = ROOT / "data" / "noaa" / "availability_manifest.json"
    output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Verified {len(rows)} responses and Last-Modified metadata in {output}")
