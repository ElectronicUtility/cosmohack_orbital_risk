// Pure presentation helpers: no new forecast or decision logic lives in the UI.
export const names = {
  space_weather: "Космическая погода",
  conjunctions: "Сближения",
  lighting: "Освещение",
};
export const modes = {
  current: "Текущая обстановка",
  reconstruction: "Восстановленные условия",
  replay: "Известно на момент решения",
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
  historical_reconstruction: "Восстановленные условия",
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
export const label = (s) => statuses[s] || names[s] || modes[s] || s || "–";
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
    return "Время публикации исторических орбитальных элементов не подтверждено. В режиме «Известно на момент решения» освещение показывается отдельно и не меняет рекомендацию.";
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
    : "–";
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
    return !Number.isFinite(f.forecast_probability_percent)
      ? "Разные выпуски"
      : numeric(f.forecast_probability_percent, 1) + "% / сутки";
  if (f.mechanism === "lighting")
    return f.state === "not_requested"
      ? "Не задано"
      : numeric(f.overlap_minutes, 1) + " мин в тени";
  if (f.state === "ambiguous_persistent_proximity") return "Неоднозначно";
  const events = f.evidence
    .map((e) => e.event)
    .filter((e) => Number.isFinite(e?.min_separation_km));
  return events.length
    ? numeric(Math.min(...events.map((e) => e.min_separation_km)), 2) + " км"
    : f.state === "no_reported_close_approach_within_screen"
      ? "Не найдено в сводке"
      : "Полнота не подтверждена";
}
export function decisionRows(a) {
  return a.comparison.decision_mechanisms.map((name) => ({
    name,
    title:
      name === "space_weather" ? "Космическая погода" : names[name],
    values: a.windows.map((w) =>
      factorValue(w.factors.find((f) => f.mechanism === name)),
    ),
  }));
}
export function windowRole(a, i) {
  const c = a.comparison;
  if (c.outcome === "insufficient") return "Данных недостаточно";
  if (c.preferred_index === i) return "Предпочтительно";
  if (!c.pareto_frontier_indices.includes(i)) return "Уступает другим";
  return c.outcome === "tradeoff" ? "Компромисс" : "Равнозначно";
}
export function conclusion(a) {
  const c = a.comparison,
    rows = decisionRows(a);
  const details = rows
    .map(
      (r) =>
        `${r.title}: ${[...new Set(c.pareto_frontier_indices.map((i) => r.values[i]))].join(" / ")}.`,
    )
    .join(" ");
  const excludedLight =
    a.request.requires_sunlight && !c.decision_mechanisms.includes("lighting");
  if (c.outcome === "insufficient") {
    const missing = [...new Set(a.windows.flatMap((w) => w.factors
      .filter((f) => f.decision_eligible && (f.state === "insufficient" || f.comparison_value == null))
      .map((f) => {
        const title = names[f.mechanism];
        if (f.freshness === "disabled") return title + ": источник отключён на сервере";
        if (f.freshness === "stale") return title + ": выпуск устарел, нужен новый выпуск источника";
        if (f.freshness === "truncated") return title + ": источник вернул неполную сводку";
        if (f.freshness === "invalid") return title + ": ответ источника не прошёл проверку";
        if (f.completeness === "complete" && f.comparison_value == null)
          return title + ": окно пересекает разные суточные вероятности, единого значения нет";
        return title + ": нет покрытия выбранного периода";
      })))];
    return [
      "!",
      "Для выбора нужны данные",
      `${missing.join(". ") || "Величины факторов несовместимы между окнами"}. Подробности в источниках.`,
    ];
  }
  if (c.outcome === "preferred") {
    const i = c.preferred_index,
      w = a.windows[i];
    const reasons = rows
      .filter((r) => new Set(r.values).size > 1)
      .map(
        (r) =>
          `${r.title}: ${r.values[i]}; в остальных вариантах ${[...new Set(r.values.filter((v, j) => j !== i))].join(" / ")}.`,
      );
    return [
      "↗",
      `Начать в ${clock(w.window.start)} UTC`,
      `${dateLabel(w.window.start)} ${reasons.join(" ") || "Учитываемые условия не хуже, чем у остальных вариантов."}`,
    ];
  }
  if (c.outcome === "tradeoff") {
    const alternatives = c.pareto_frontier_indices
      .map(
        (i) =>
          `${clock(a.windows[i].window.start)} UTC: ${rows.map((r) => r.values[i]).join(", ")}`,
      )
      .join("; ");
    return [
      "↔",
      "Выберите приоритет работы",
      `${alternatives}. Меньше тени или ниже суточная вероятность события — единственного лучшего варианта нет.`,
    ];
  }
  const subset = c.pareto_frontier_indices.length < a.windows.length;
  return [
    "=",
    subset ? "Есть равнозначные варианты" : "Варианты равнозначны",
    `${subset ? "Равнозначны начала в " + c.pareto_frontier_indices.map((i) => clock(a.windows[i].window.start) + " UTC").join(" и ") + ". " : ""}${details} ${subset ? "Другие варианты уступают по учитываемым условиям. " : ""}${excludedLight ? "Тень рассчитана отдельно: время публикации исторической орбиты не подтверждено." : "Различия внутри этой группы не превышают допуски сравнения."}`,
  ];
}
export function parseUTC(value) {
  let text = String(value).trim();
  const ru = text.match(/^(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2})$/);
  if (ru) text = `${ru[3]}-${ru[2]}-${ru[1]}T${ru[4]}:${ru[5]}`;
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(text))
    throw Error("Введите дату и время: ДД.ММ.ГГГГ ЧЧ:ММ, UTC.");
  const date = new Date(text + "Z");
  if (
    !Number.isFinite(date.valueOf()) ||
    date.toISOString().slice(0, 16) !== text
  )
    throw Error("Проверьте день, месяц и время.");
  return date.toISOString();
}
export function inputUTC(value) {
  const s = new Date(value).toISOString();
  return `${s.slice(8, 10)}.${s.slice(5, 7)}.${s.slice(0, 4)} ${s.slice(11, 16)}`;
}
export function publicationLabel(value) {
  if (!value || value === "unknown") return "Время публикации не подтверждено";
  if (/Issued.*Last-Modified/i.test(value))
    return "Дата выпуска сверена с архивной отметкой изменения";
  return "Основание сохранено в исходной записи";
}
export function quantityLabel(value) {
  if (/proton/i.test(value || ""))
    return "Вероятность солнечного протонного события за сутки";
  if (/S1/i.test(value || "")) return "Вероятность события S1+ за сутки";
  if (/Kp/i.test(value || "")) return "Геомагнитный индекс Kp";
  return "Величина из источника";
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
    task_name: (v.task_name || "").trim(),
    start: parseUTC(v.start),
    duration_hours: Number(v.duration),
    search_hours: Number(v.search),
    requires_sunlight: !!v.sunlight,
    refresh: false,
  };
  if (v.mode === "replay") body.cutoff = parseUTC(v.cutoff);
  return body;
}
export function sameRequest(a, b) {
  return (
    (a.task_name || "") === (b.task_name || "") &&
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
