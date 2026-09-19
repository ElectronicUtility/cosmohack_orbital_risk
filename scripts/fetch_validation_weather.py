"""Download subsequent NOAA summaries for validation only, never for replay input."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "validation" / "sgas"
BASE = "https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports/solar_geophysical_activity_summaries"


def fetch(day):
    name = f"{day:%Y%m%d}SGAS.txt"
    url = f"{BASE}/{day:%Y/%m}/{name}"
    response = httpx.get(url, timeout=30, follow_redirects=True)
    if response.status_code == 404:
        return {"url": url, "status": 404}
    response.raise_for_status()
    (OUT / name).write_bytes(response.content)
    return {"path": str((OUT / name).relative_to(ROOT)), "url": url,
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "last_modified": response.headers.get("Last-Modified"), "status": 200}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    # Two preceding days supply a publication-aware persistence baseline.
    days = [datetime(2024, 4, 30) + timedelta(days=i) for i in range(63)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        manifest = list(pool.map(fetch, days))
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Archived {sum(r['status'] == 200 for r in manifest)} summaries; missing {sum(r['status'] == 404 for r in manifest)}")
