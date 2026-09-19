// Pure presentation helpers: no new forecast or decision logic lives in the UI.
export const names = {
  space_weather: "Космическая погода",
  conjunctions: "Сближения",
  lighting: "Освещение",
};
export const modes = {
  current: "Текущая обстановка",
  reconstruction: "Реконструкция",
  replay: "Прогноз из прошлого",
};
export const statuses = {
  attention: "Требует внимания",
  insufficient: "Недостаточно данных",
  forecast_below_experimental_threshold: "Ниже экспериментального порога",
  no_restriction_detected: "Ограничение не выявлено",
  not_requested: "Условие не задано",
  no_reconstructed_close_approach_within_screen: "В выборке не обнаружено",
  no_reported_close_approach_within_screen: "В сводке не обнаружено",
  reconstructed_close_approach: "Реконструированное сближение",
  reported_close_approach: "Сближение в сводке",
  ambiguous_persistent_proximity: "Неоднозначная близость",
  complete: "Полное покрытие",
  partial_or_absent: "Неполное покрытие",
  reconstruction_unverified_catalog_completeness:
    "Полнота каталога не доказана",
  stale_or_unavailable: "Устаревшие или отсутствующие данные",
  fresh: "Получено от источника",
  cached: "Кеш",
  stale: "Устаревшие данные",
  archive: "Архив",
  missing: "Нет данных",
  disabled: "Источник отключён",
  invalid: "Ошибка данных",
  truncated: "Неполная сводка",
  historical_reconstruction: "Реконструкция",
  historical_reconstruction_publication_unknown: "Время публикации не доказано",
  orbit_missing: "Нет подходящих элементов",
  current: "Текущие элементы",
};
export const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const label = (s) => statuses[s] || names[s] || modes[s] || s || "—";
Object.assign(statuses, {
  archived: "Архивная запись",
  archived_local_extract: "Архивная выборка",
  unknown: "Неизвестно",
  historical_reconstruction_publication_unknown:
    "Реконструкция, публикация неизвестна",
});
export function eligibility(f) {
  if (f.decision_eligible) return "Допустим для решения";
  if (f.mechanism === "lighting" && f.state === "not_requested")
    return "Требование прямого солнечного света не задано аналитиком.";
  if (f.mechanism === "lighting")
    return "Время публикации исторических орбитальных элементов не подтверждено. В строгом replay освещение показывается отдельно и не меняет рекомендацию.";
  if (f.mechanism === "conjunctions")
    return "Доступность исторических элементов и полнота каталога на момент решения не доказаны. Сближения показаны как реконструкция, вне рекомендации.";
  return f.eligibility_reason || "Фактор не включён в рекомендацию.";
}
export const clock = (t) => new Date(t).toISOString().slice(11, 16);
export const stamp = (t) =>
  t
    ? new Date(t).toISOString().replace("T", " ").slice(0, 16) + " UTC"
    : "Неизвестно";
export const dateLabel = (t) =>
  new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(t));
export const numeric = (n, d = 0) =>
  Number.isFinite(n)
    ? n.toLocaleString("ru-RU", { maximumFractionDigits: d })
    : "—";
export function safeURL(value) {
  try {
    const u = new URL(value);
    return ["https:", "http:"].includes(u.protocol) ? u.href : null;
  } catch {
    return null;
  }
}
export function factorValue(f) {
  if (f.state === "insufficient") return "Нет данных";
  if (f.mechanism === "space_weather")
    return f.forecast_probability_percent === null
      ? "Разные выпуски"
      : numeric(f.forecast_probability_percent, 1) + "% / сутки";
  if (f.mechanism === "lighting")
    return f.state === "not_requested"
      ? "Не задано"
      : numeric(f.overlap_minutes) + " мин в тени";
  if (f.state === "ambiguous_persistent_proximity") return "Неоднозначно";
  const events = f.evidence
    .map((e) => e.event)
    .filter((e) => Number.isFinite(e?.min_separation_km));
  return events.length
    ? numeric(Math.min(...events.map((e) => e.min_separation_km)), 2) + " км"
    : f.state === "no_reported_close_approach_within_screen"
      ? "Нет в сводке"
      : "Нет в выборке";
}
export function conclusion(a) {
  const c = a.comparison;
  if (
    c.outcome === "equivalent" &&
    c.pareto_frontier_indices.length < a.windows.length
  ) {
    return [
      "=",
      "Равнозначны окна " +
        c.pareto_frontier_indices
          .map((i) => String.fromCharCode(65 + i))
          .join(", "),
      "Эти варианты равнозначны в пределах допусков. Остальные уступают по учитываемым условиям; подробности — в основаниях.",
    ];
  }
  return (
    {
      preferred: [
        "↗",
        `Предпочтительно окно ${String.fromCharCode(65 + (c.preferred_index ?? 0))}`,
        "По факторам, допустимым для этого режима. Откройте основания, чтобы проверить выбор.",
      ],
      equivalent: [
        "=",
        "Окна равнозначны",
        "По доступным для решения факторам различий недостаточно. Геометрические условия показаны отдельно.",
      ],
      insufficient: [
        "!",
        "Недостаточно данных для выбора",
        "Покрытие или качество одного из факторов не позволяет обосновать предпочтение. Проверьте источники.",
      ],
      tradeoff: [
        "↔",
        "Есть компромисс между факторами",
        "Ни одно окно не лучше по всем учитываемым условиям. Сопоставьте различия и основания.",
      ],
    }[c.outcome] || ["↔", "Сравнение окон", c.reasons.join(" ")]
  );
}
export function intervalPercent(start, end, window) {
  const lo = Date.parse(window.start),
    hi = Date.parse(window.end);
  const a = Math.max(lo, Date.parse(start)),
    b = Math.min(hi, Date.parse(end));
  if (!Number.isFinite(a + b) || b <= a || hi <= lo) return null;
  return {
    left: (100 * (a - lo)) / (hi - lo),
    width: (100 * (b - a)) / (hi - lo),
  };
}
export function requestFromValues(v) {
  const body = {
    mode: v.mode,
    start: new Date(v.start + "Z").toISOString(),
    duration_hours: Number(v.duration),
    search_hours: Number(v.search),
    requires_sunlight: !!v.sunlight,
    refresh: false,
  };
  if (v.mode === "replay") body.cutoff = new Date(v.cutoff + "Z").toISOString();
  return body;
}
export function sameRequest(a, b) {
  return (
    a.mode === b.mode &&
    Date.parse(a.start) === Date.parse(b.start) &&
    a.duration_hours === b.duration_hours &&
    a.search_hours === b.search_hours &&
    a.requires_sunlight === b.requires_sunlight &&
    (a.mode !== "replay" || Date.parse(a.cutoff) === Date.parse(b.cutoff))
  );
}
export function normalizeWindow(index, count) {
  return Number.isInteger(index) && index >= 0 && index < count ? index : 0;
}
export function shadowAt(factor, time) {
  return (
    factor?.evidence.some((e) =>
      (e.intervals || []).some(
        (i) =>
          Date.parse(i.start) <= Date.parse(time) &&
          Date.parse(time) < Date.parse(i.end),
      ),
    ) || false
  );
}
