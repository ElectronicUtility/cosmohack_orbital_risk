import {
  conclusion,
  esc,
  modes,
  stamp,
  numeric,
  names,
  factorValue,
  label,
  safeURL,
} from "./model.js?v=20260919-5";
function link(url, text) {
  const safe = safeURL(url);
  return safe
    ? `<a href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>`
    : esc(text);
}
export function buildReport(a, example = null) {
  const title = conclusion(a)[1];
  const html = `<!doctype html><html lang="ru"><meta charset="utf-8"><title>Орбитальный риск – заключение</title><style>body{font:15px/1.6 system-ui;max-width:1000px;margin:40px auto;padding:0 24px;color:#17251c}h1{font-size:32px}h2{margin-top:30px}table{border-collapse:collapse;width:100%}th,td{padding:12px;border:1px solid #ccd4cb;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px}a{color:#28562a}p{overflow-wrap:anywhere}small{color:#586353}@media print{details{display:block}}</style><h1>Орбитальный риск</h1><p>${example ? "Сохранённый исследовательский пример" : "Сохранённый расчёт"}, ${esc(modes[a.request.mode])}, ${esc(stamp(a.created_at))}</p><h2>${esc(title)}</h2><p>${a.comparison.reasons.map(esc).join(" ")}</p><p>Начало ${esc(stamp(a.request.start))}, длительность ${numeric(a.request.duration_hours, 1)} ч, перенос до ${numeric(a.request.search_hours, 1)} ч, солнечный свет ${a.request.requires_sunlight ? "нужен" : "не требуется"}${a.request.cutoff ? ", cutoff " + esc(stamp(a.request.cutoff)) : ""}</p>${a.windows.map((w) => `<h2>Выход с ${esc(stamp(w.window.start))} до ${esc(stamp(w.window.end))}</h2><table><tr><th>Фактор</th><th>Результат</th><th>Статус</th><th>В сравнении</th></tr>${w.factors.map((f) => `<tr><td>${esc(names[f.mechanism])}</td><td>${esc(factorValue(f))}</td><td>${esc(label(f.state))}</td><td>${f.decision_eligible ? "Да" : "Нет"}</td></tr>`).join("")}</table><p>${w.limitations.map(esc).join(" ")}</p>`).join("")}<h2>Источники</h2>${a.source_records.map((r) => `<p>${link(r.url, r.source)}<br>Опубликовано ${esc(stamp(r.published_at))}, получено ${esc(stamp(r.retrieved_at))}<br><small>SHA-256 ${esc(r.content_sha256)}</small></p>`).join("")}<h2>Полные основания и параметры</h2><details open><summary>Снимок расчёта, алгоритм ${esc(a.algorithm_version)}</summary><pre>${esc(JSON.stringify(a, null, 2))}</pre></details><p>Исследовательский прототип. Оценка выбранных факторов не является разрешением на ВКД. Суточная вероятность не равна вероятности воздействия в окне.</p></html>`;
  return html;
}
