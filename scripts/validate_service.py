"""Exercise concurrent plans and exports against an isolated local HTTP server."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]


def validate(count=24, workers=4):
    with tempfile.TemporaryDirectory(prefix="orbital-service-") as directory:
        env = {**os.environ, "COSMO_DB": str(Path(directory) / "analyses.db"),
               "DISABLE_PROVIDERS": "noaa_current,iss_current,socrates_current"}
        # Pass an already bound socket so another process cannot take the port.
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            base = f"http://127.0.0.1:{listener.getsockname()[1]}"
            with open(Path(directory) / "server.log", "w+") as log:
                server = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "app.api:app", "--fd", str(listener.fileno())],
                    cwd=ROOT, env=env, pass_fds=(listener.fileno(),), stdout=log, stderr=log,
                )
                try:
                    with httpx.Client(base_url=base, timeout=120) as client:
                        deadline = time.monotonic() + 20
                        while True:
                            try:
                                client.get("/api/health").raise_for_status()
                                break
                            except httpx.TransportError:
                                if server.poll() is not None or time.monotonic() >= deadline:
                                    log.seek(0)
                                    raise RuntimeError(log.read())
                                time.sleep(.1)

                    def plan(index):
                        request = dict(mode="reconstruction", task_name=f"Проверка {index}",
                                       start=f"2024-05-{1 + index % 28:02d}T06:00:00Z",
                                       duration_hours=1 + index % 8, search_hours=6 + index % 19,
                                       requires_sunlight=index % 2 == 0)
                        started = time.monotonic()
                        with httpx.Client(base_url=base, timeout=120) as client:
                            response = client.post("/api/analyze", json=request)
                            response.raise_for_status()
                            saved = response.json()
                            for key, value in request.items():
                                assert saved["request"][key] == value, (index, key)
                            endpoint = "/api/analyses/" + saved["id"]
                            loaded = client.get(endpoint)
                            loaded.raise_for_status()
                            assert loaded.json() == saved, index
                            exported = client.get(endpoint + "/export.json")
                            exported.raise_for_status()
                            assert exported.json() == saved, index
                            assert len(saved["windows"]) == 3
                            return {"index": index, "id": saved["id"],
                                    "outcome": saved["comparison"]["outcome"],
                                    "elapsed_seconds": round(time.monotonic() - started, 3)}

                    started = time.monotonic()
                    with ThreadPoolExecutor(max_workers=workers) as pool:
                        rows = list(pool.map(plan, range(count)))
                    assert len({row["id"] for row in rows}) == count
                    return {"plans": count, "workers": workers, "transport": "local HTTP / uvicorn",
                            "database": "isolated temporary SQLite", "network_sources": "disabled",
                            "elapsed_seconds": round(time.monotonic() - started, 3),
                            "checks": ["distinct IDs", "request parameters preserved", "saved JSON equals response",
                                       "export JSON equals response", "three windows per plan"],
                            "limitations": "Short local concurrency check, not a sustained load or live-provider test.",
                            "rows": rows}
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "research_results/service_validation.json")
    args = parser.parse_args()
    report = validate()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, ensure_ascii=False))
