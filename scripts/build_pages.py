"""Build a read-only Pages demo from validated, portable research snapshots."""
from pathlib import Path
import argparse
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.api import example
from app.bundle import build_bundle


def build(destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("Output directory must be empty")
    shutil.copytree(ROOT / "app/static", destination / "static")
    briefing = destination / "static/briefing.html"
    briefing.write_text(briefing.read_text(encoding="utf-8").replace('href="/planner?', 'href="../?'), encoding="utf-8")
    html = (ROOT / "app/index.html").read_text(encoding="utf-8")
    html = html.replace('<head>', '<head>\n    <meta name="static-demo" content="true" />')
    html = html.replace('"/static/', '"./static/')
    for page in ("planner", "archive", "sources", "method"):
        html = html.replace(f'href="/{page}"', f'href="?page={page}"')
    html = html.replace('<div class="plan-toolbar">', '<p class="demo-label">Демо: сохранённые расчёты</p>\n          <div class="plan-toolbar">')
    (destination / "index.html").write_text(html, encoding="utf-8")
    (destination / ".nojekyll").touch()
    for name in ("sunlight", "tradeoff", "window_demo", "event", "control"):
        snapshot = example(name).model_dump(mode="json")
        folder = destination / "api/examples" / name
        folder.mkdir(parents=True)
        folder.with_suffix(".json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        (folder / "bundle.zip").write_bytes(build_bundle(snapshot))
    (destination / "api/validation").mkdir()
    shutil.copyfile(ROOT / "research_results/planning_validation.json", destination / "api/validation.json")
    shutil.copyfile(ROOT / "research_results/weather_validation.json", destination / "api/validation/weather.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, nargs="?", default=ROOT / "dist")
    build(parser.parse_args().destination)
