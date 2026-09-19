from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__, ALGORITHM_VERSION
from .analysis import run
from .domain import AnalysisRequest, SavedAnalysis
from .providers import current_provider_health, current_weather, current_tle, current_conjunctions
from .storage import load_analysis, store_analysis

app = FastAPI(title="ВКД: исследовательская система поддержки решений", version=__version__)
PAGE = Path(__file__).resolve().parent / "index.html"
app.mount("/static", StaticFiles(directory=PAGE.parent / "static"), name="static")


@app.get("/api/examples/{name}", response_model=SavedAnalysis)
def example(name: str):
    """Read-only, explicitly archived research snapshots for instant exploration."""
    if name not in {"window_demo", "event", "control", "sunlight", "tradeoff"}:
        raise HTTPException(404, "Unknown research example")
    path = PAGE.parent.parent / "research_results" / f"{name}.json"
    if not path.is_file():
        raise HTTPException(404, "Research example unavailable")
    return SavedAnalysis.model_validate_json(path.read_text(encoding="utf-8"))


@app.get("/", response_class=HTMLResponse)
@app.get("/planner", response_class=HTMLResponse)
@app.get("/archive", response_class=HTMLResponse)
@app.get("/sources", response_class=HTMLResponse)
@app.get("/method", response_class=HTMLResponse)
def index():
    return PAGE.read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__, "algorithm_version": ALGORITHM_VERSION}


@app.get("/api/sources")
def sources():
    return current_provider_health()


@app.post("/api/sources/refresh")
def refresh_sources():
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda provider: provider(True), (current_weather, current_tle, current_conjunctions)))
    return current_provider_health()


@app.get("/api/validation")
def validation():
    import json
    path = PAGE.parent.parent / "research_results" / "planning_validation.json"
    if not path.is_file():
        raise HTTPException(404, "Validation report unavailable")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/validation/weather")
def weather_validation():
    import json
    path = PAGE.parent.parent / "research_results" / "weather_validation.json"
    if not path.is_file():
        raise HTTPException(404, "Weather validation report unavailable")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/analyze", response_model=SavedAnalysis)
def analyze(request: AnalysisRequest):
    windows, comparison, records = run(request)
    saved = SavedAnalysis(id=uuid.uuid4().hex, request=request, windows=windows,
                          comparison=comparison, created_at=datetime.now(timezone.utc),
                          algorithm_version=ALGORITHM_VERSION, source_records=records)
    store_analysis(saved)
    return saved


@app.get("/api/analyses/{identifier}")
def saved(identifier: str):
    item = load_analysis(identifier)
    if item is None:
        raise HTTPException(404, "Analysis not found")
    return item


@app.get("/api/analyses/{identifier}/export.json")
def export_json(identifier: str):
    item = load_analysis(identifier)
    if item is None:
        raise HTTPException(404, "Analysis not found")
    return JSONResponse(item, headers={"Content-Disposition": f'attachment; filename="analysis-{identifier}.json"'})


@app.get("/api/analyses/{identifier}/export.html", response_class=HTMLResponse)
def export_html(identifier: str):
    item = load_analysis(identifier)
    if item is None:
        raise HTTPException(404, "Analysis not found")
    from .report import build_report
    return HTMLResponse(build_report(item), headers={"Content-Disposition": f'attachment; filename="analysis-{identifier}.html"'})



def bundle_response(item):
    from .bundle import build_bundle
    try:
        payload = build_bundle(item)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(payload, media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="orbital-risk-evidence.zip"'})


@app.get("/api/analyses/{identifier}/bundle.zip")
def export_bundle(identifier: str):
    item = load_analysis(identifier)
    if item is None:
        raise HTTPException(404, "Analysis not found")
    return bundle_response(item)


@app.get("/api/examples/{name}/bundle.zip")
def example_bundle(name: str):
    return bundle_response(example(name).model_dump(mode="json"))
