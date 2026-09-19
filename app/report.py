"""Self-contained HTML export using the same renderer as the browser."""
import html
import json
import re

from .storage import ROOT


def build_report(analysis):
    static = ROOT / "app" / "static"
    model = (static / "model.js").read_text(encoding="utf-8")
    renderer = (static / "report.js").read_text(encoding="utf-8")
    renderer = re.sub(r'^import\s*\{.*?\}\s*from\s*"[^"]+";', '', renderer, count=1, flags=re.S)
    code = re.sub(r'\bexport (?=const |function )', '', model + '\n' + renderer)
    snapshot = json.dumps(analysis, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    # Inline dependencies keep the report usable offline. Untrusted strings never
    # become script markup; buildReport escapes every displayed source field.
    return ("<!doctype html><html lang='ru'><meta charset='utf-8'><title>Анализ ВКД</title>"
            "<noscript><p>Для оформления отчёта включите JavaScript. Полный расчёт:</p><pre>"
            + html.escape(json.dumps(analysis, ensure_ascii=False, indent=2))
            + "</pre></noscript><script>" + code + "\nconst snapshot = " + snapshot
            + ";document.open();document.write(buildReport(snapshot));document.close();</script></html>")
