from __future__ import annotations

import html
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, ALGORITHM_VERSION
from .analysis import run
from .domain import AnalysisRequest, SavedAnalysis
from .providers import current_provider_health
from .storage import load_analysis, store_analysis

app = FastAPI(title="ВКД: исследовательская система поддержки решений", version=__version__)
PAGE = Path(__file__).resolve().parent / "index.html"
app.mount("/static", StaticFiles(directory=PAGE.parent / "static"), name="static")


@app.get("/api/examples/{name}", response_model=SavedAnalysis)
def example(name: str):
    """Read-only, explicitly archived research snapshots for instant exploration."""
    if name not in {"window_demo", "event", "control"}:
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
    esc = lambda x: html.escape(str(x))
    rows = []
    for i, win in enumerate(item["windows"], 1):
        factors = "".join(f"<li>{esc(f['mechanism'])}: {esc(f['state'])}, overlap {esc(f['overlap_minutes'])} min, data {esc(f['completeness'])}, freshness {esc(f['freshness'])}</li>" for f in win["factors"])
        evidence = "".join(f"<details><summary>{esc(f['mechanism'])} — evidence</summary><pre>{esc(f['evidence'])}</pre><p>{esc('; '.join(f['limitations']))}</p></details>" for f in win["factors"])
        rows.append(f"<section><h2>Window {i}: {esc(win['window']['start'])} — {esc(win['window']['end'])}</h2><ul>{factors}</ul>{evidence}</section>")
    sources = "".join(f"<li><a href='{esc(r['url'])}'>{esc(r['source'])}</a> — SHA-256 {esc(r['content_sha256'])}, published {esc(r['published_at'])}, retrieved {esc(r['retrieved_at'])}</li>" for r in item["source_records"])
    body = f"<!doctype html><html lang='ru'><meta charset='utf-8'><title>Анализ ВКД</title><style>body{{font:16px system-ui;max-width:900px;margin:3rem auto;line-height:1.5}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}section{{border-top:1px solid #bbb;padding:1rem 0}}</style><h1>Анализ ВКД</h1><p>Исследовательский прототип; не допуск к реальной ВКД.</p><p>Версия алгоритма: {esc(item['algorithm_version'])}. Режим: {esc(item['request']['mode'])}. Cutoff: {esc(item['request']['cutoff'])}.</p><h2>Сравнение</h2><p>{esc(item['comparison']['outcome'])}: {esc('; '.join(item['comparison']['reasons']))}</p>{''.join(rows)}<h2>Исходные записи</h2><ul>{sources}</ul></html>"
    return HTMLResponse(body, headers={"Content-Disposition": f'attachment; filename="analysis-{identifier}.html"'})
