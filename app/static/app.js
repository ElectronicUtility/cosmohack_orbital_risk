import {
  names,
  modes,
  esc,
  label,
  clock,
  stamp,
  dateLabel,
  numeric,
  safeURL,
  factorValue,
  conclusion,
  intervalPercent,
  requestFromValues,
  sameRequest,
  normalizeWindow,
  shadowAt,
  eligibility,
} from "./model.js";
import { OrbitScene } from "./orbit.js";
import { buildReport } from "./report.js";

const $ = (id) => document.getElementById(id),
  $$ = (s) => [...document.querySelectorAll(s)];
const state = {
  analysis: null,
  example: null,
  selected: 0,
  sample: 0,
  busy: false,
  controller: null,
  timer: null,
};
const scene = new OrbitScene($("orbit-canvas"));
const quick = document.createElement("div");
quick.className = "quick-windows";
quick.setAttribute("role", "group");
quick.setAttribute("aria-label", "Выбор окна на орбите");
$("scene").before(quick);
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
const examples = {
  window_demo: "Свет и тень",
  event: "Солнечное событие",
  control: "Контрольный период",
};
let toastTimer;
function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("toast").hidden = true), 4000);
}
function status(message, kind = "ready") {
  $("status").textContent = message;
  $("statusbar").dataset.state = kind;
}
function busy(value) {
  state.busy = value;
  $("plan-fields").disabled = value;
  $("calculate").disabled = value;
  $("refresh").disabled = value;
  $("calculate").innerHTML = value
    ? "Расчёт… <span>◌</span>"
    : "Рассчитать окна <span>↗</span>";
  $("workspace").setAttribute("aria-busy", String(value));
}
function link(url, text = "Открыть первоисточник ↗") {
  const safe = safeURL(url);
  return safe
    ? `<a href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>`
    : "<span>Ссылка недоступна</span>";
}
function modeUI() {
  const replay = $("mode").value === "replay";
  $("cutoff-label").hidden = !replay;
  $("cutoff").required = replay;
  $("cutoff").setCustomValidity("");
  $("mode-help").textContent = {
    replay:
      "Только сведения, доступные к моменту отсечения. Геометрия — отдельно.",
    reconstruction:
      "Восстанавливаем условия мая–июня 2024. Это не прогноз из прошлого.",
    current:
      "Новый запрос к текущим источникам. Актуальность проверяется при расчёте.",
  }[$("mode").value];
}
function fillForm(request) {
  $("mode").value = request.mode;
  $("start").value = request.start.slice(0, 16);
  $("duration").value = request.duration_hours;
  $("search").value = request.search_hours;
  $("cutoff").value = (request.cutoff || request.start).slice(0, 16);
  $("sunlight").checked = request.requires_sunlight;
  modeUI();
  $("start").setCustomValidity("");
  $("restore").hidden = true;
}
function formRequest() {
  return requestFromValues({
    mode: $("mode").value,
    start: $("start").value,
    duration: $("duration").value,
    search: $("search").value,
    cutoff: $("cutoff").value,
    sunlight: $("sunlight").checked,
  });
}
function dirty() {
  if (!state.analysis || state.busy) return;
  let changed = true;
  try {
    changed = !sameRequest(formRequest(), state.analysis.request);
  } catch {}
  $("restore").hidden = !changed;
  if (changed)
    status(
      "Параметры изменены. На экране предыдущий результат — пересчитайте окна.",
      "dirty",
    );
  else readyStatus();
}
function readyStatus() {
  const a = state.analysis;
  if (!a) return;
  status(
    `${state.example ? "Сохранённый пример «" + examples[state.example] + "»" : "Расчёт сохранён"} · ${stamp(a.request.start)} · ${numeric(a.request.duration_hours, 1)} ч · ${modes[a.request.mode]}.`,
  );
}
function updateURL(push = false) {
  if (!state.analysis) return;
  const url = new URL(location.href);
  url.search = "";
  url.searchParams.set(
    state.example ? "example" : "analysis",
    state.example || state.analysis.id,
  );
  url.searchParams.set("window", state.selected);
  history[push ? "pushState" : "replaceState"]({}, "", url);
}
async function readJSON(url, options = {}) {
  const response = await fetch(url, options);
  let result;
  try {
    result = await response.json();
  } catch {
    throw Error("Сервис вернул некорректный ответ");
  }
  if (!response.ok) {
    const detail = Array.isArray(result.detail)
      ? result.detail.map((e) => e.msg).join("; ")
      : result.detail;
    throw Error(detail || `HTTP ${response.status}`);
  }
  return result;
}
async function loadExample(name, index = 0, push = true) {
  if (!examples[name]) name = "window_demo";
  await load(`/api/examples/${name}`, name, index, push);
}
async function load(url, example, index, push) {
  state.controller?.abort();
  state.controller = new AbortController();
  const controller = state.controller;
  stop();
  busy(true);
  status("Открываем сохранённый расчёт…", "loading");
  try {
    const a = await readJSON(url, { signal: controller.signal });
    if (controller !== state.controller) return;
    accept(a, example, index, push);
  } catch (e) {
    if (e.name !== "AbortError" && controller === state.controller) {
      status(
        "Не удалось открыть расчёт: " +
          e.message +
          (state.analysis ? ". Предыдущий результат сохранён на экране." : ""),
        "error",
      );
      if (!state.analysis)
        $("scene-empty").textContent =
          "Пример недоступен. Выберите другой сценарий или выполните расчёт.";
    }
  } finally {
    if (controller === state.controller) busy(false);
  }
}
function accept(a, example, index = 0, push = false) {
  state.analysis = a;
  state.example = example;
  state.selected = normalizeWindow(index, a.windows.length);
  state.sample = 0;
  fillForm(a.request);
  render();
  scene.reset();
  updateURL(push);
  readyStatus();
}
function render() {
  const a = state.analysis,
    [icon, title, summary] = conclusion(a);
  for (const id of [
    "conclusion",
    "comparison-panel",
    "timeline-panel",
    "source-strip",
  ])
    $(id).hidden = false;
  $("conclusion-icon").textContent = icon;
  $("conclusion-title").textContent = title;
  $("conclusion-text").textContent = summary;
  $("conclusion").dataset.outcome = a.comparison.outcome;
  $("result-label").textContent = state.example
    ? "СОХРАНЁННЫЙ РАСЧЁТ / " + modes[a.request.mode].toUpperCase()
    : "ЗАКЛЮЧЕНИЕ / " + modes[a.request.mode].toUpperCase();
  $("context-date").textContent = dateLabel(a.request.start) + " · UTC";
  $("mode-badge").textContent = modes[a.request.mode];
  $("equal-duration").textContent =
    `Все окна по ${numeric(a.request.duration_hours, 1)} ч · одинаковые условия плана`;
  $$("[data-example]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.example === state.example)),
  );
  $("source-summary").textContent =
    `${a.source_records.length} исходных записей · алгоритм ${a.algorithm_version} · результат от ${stamp(a.created_at)}`;
  renderWindows();
  renderSelected();
  renderReplay();
}
function renderWindows() {
  const a = state.analysis;
  $("window-cards").innerHTML = a.windows
    .map(
      (w, i) =>
        `<button class="window-card" data-window="${i}" aria-pressed="${i === state.selected}" aria-label="Выбрать окно ${String.fromCharCode(65 + i)}: ${clock(w.window.start)} — ${clock(w.window.end)} UTC"><span class="window-top"><span class="window-id">ОКНО ${String.fromCharCode(65 + i)}</span><span class="window-selected">${i === state.selected ? "● В фокусе" : a.comparison.preferred_index === i ? "↗ Предпочтительно" : "Исследовать ↗"}</span></span><span class="window-time">${clock(w.window.start)} — ${clock(w.window.end)}</span><span class="window-day">${esc(dateLabel(w.window.start))}${w.window.start.slice(0, 10) !== w.window.end.slice(0, 10) ? " → " + esc(dateLabel(w.window.end)) : ""} · UTC</span><span class="window-factors">${w.factors.map((f) => `<span class="factor-mini"><span>${esc(names[f.mechanism] || f.mechanism)}</span><strong class="${f.state === "attention" ? "attention" : f.state === "insufficient" ? "unknown" : ""}">${esc(factorValue(f))}</strong></span>`).join("")}</span><span class="card-foot">${w.factors.some((f) => f.state === "insufficient") ? "Есть пробелы в данных · вывод ограничен" : w.factors.some((f) => !f.decision_eligible) ? "Есть факторы вне рекомендации · подробности по клику на шкале" : "Учитываются только доступные для решения факторы"}</span></button>`,
    )
    .join("");
}
function selectWindow(index) {
  if (!state.analysis) return;
  stop();
  state.selected = normalizeWindow(index, state.analysis.windows.length);
  state.sample = 0;
  const update = () => {
    renderWindows();
    renderSelected();
    updateURL();
  };
  if (document.startViewTransition && !reduced.matches)
    document.startViewTransition(update);
  else update();
}
function renderSelected() {
  const w = state.analysis.windows[state.selected];
  quick.innerHTML = state.analysis.windows
    .map(
      (window, i) =>
        `<button data-quick-window="${i}" aria-pressed="${i === state.selected}"><span>${String.fromCharCode(65 + i)}</span> ${clock(window.window.start)}–${clock(window.window.end)}</button>`,
    )
    .join("");
  $("timeline-window").textContent =
    "Окно " + String.fromCharCode(65 + state.selected);
  $("scene-title").textContent =
    `Окно ${String.fromCharCode(65 + state.selected)} · ${clock(w.window.start)} — ${clock(w.window.end)} UTC`;
  $("scrub").max = Math.max(0, w.orbit.length - 1);
  $("scrub").value = 0;
  $("scrub").disabled = !w.orbit.length;
  $("play").disabled = w.orbit.length < 2;
  $("orbit-start").textContent = clock(w.window.start);
  $("orbit-end").textContent = clock(w.window.end);
  $("scene-empty").hidden = !!w.orbit.length;
  $("scene-empty").textContent =
    "Нет подходящих орбитальных элементов для этого окна.";
  renderTimeline(w);
  setSample(0);
}
function renderTimeline(w) {
  const { window: win } = w,
    lo = Date.parse(win.start),
    hi = Date.parse(win.end);
  const interval = (start, end, kind) => {
    const p = intervalPercent(start, end, win);
    return p
      ? `<span class="interval ${kind}" style="left:${p.left}%;width:${p.width}%"></span>`
      : "";
  };
  const rows = w.factors.map((f) => {
    let marks = "",
      text = "",
      hint = "";
    const missing = f.state === "insufficient";
    if (f.mechanism === "space_weather") {
      marks = f.evidence
        .filter(
          (e) => e.event?.kind === "external_forecast" && e.event.unit === "%",
        )
        .map((e) => interval(e.event.valid_start, e.event.valid_end, "weather"))
        .join("");
      text = missing ? "Неполное покрытие" : factorValue(f);
      hint = "Внешний прогноз · суточная вероятность";
    } else if (f.mechanism === "lighting") {
      const intervals = f.evidence.flatMap((e) => e.intervals || []);
      marks = intervals.map((i) => interval(i.start, i.end, "shadow")).join("");
      text = missing
        ? "Геометрия недоступна"
        : f.state === "not_requested"
          ? "Условие не задано"
          : factorValue(f);
      hint = "Штриховка — тень · геометрия";
    } else {
      marks = f.evidence
        .filter((e) => e.event?.tca)
        .map((e) => {
          const p = (100 * (Date.parse(e.event.tca) - lo)) / (hi - lo);
          return p >= 0 && p <= 100
            ? `<span class="event-mark" style="left:${p}%"></span>`
            : "";
        })
        .join("");
      text = missing ? "Нет полных актуальных данных" : factorValue(f);
      hint = f.decision_eligible
        ? "Сводка сближений МКС"
        : "Реконструкция · вне рекомендации";
    }
    return `<div class="timeline-row"><button class="lane-label" data-factor="${esc(f.mechanism)}">${esc(names[f.mechanism])}<small>${esc(hint)}</small></button><div class="track ${missing ? "unknown" : ""}" role="img" aria-label="${esc(names[f.mechanism] + ": " + text)}">${marks}<span class="track-text">${esc(text)}</span><span class="track-cursor"></span></div><button class="detail-button" data-factor="${esc(f.mechanism)}" aria-label="Доказательства: ${esc(names[f.mechanism])}">↗</button></div>`;
  });
  $("timeline").innerHTML =
    `<div class="timeline-axis">${[0, 0.25, 0.5, 0.75, 1].map((p) => `<span>${clock(lo + p * (hi - lo))}</span>`).join("")}</div>` +
    rows.join("");
}
function setSample(index) {
  const w = state.analysis?.windows[state.selected];
  if (!w) return;
  state.sample = normalizeWindow(Number(index), w.orbit.length);
  $("scrub").value = state.sample;
  const s = w.orbit[state.sample];
  scene.setData(state.analysis.windows, state.selected, state.sample);
  if (!s) {
    $("orbit-time").textContent = "—";
    $("orbit-meta").textContent = "Геометрия недоступна";
    $("sample-label").textContent = "Нет точек";
    $$(".track-cursor").forEach((e) => (e.hidden = true));
    return;
  }
  $("orbit-time").textContent = clock(s.at) + " UTC";
  const altitude = Math.hypot(...s.position_teme_km) - 6378.137;
  $("orbit-meta").textContent = `h ≈ ${numeric(altitude)} км · TEME · схема`;
  const lighting = w.factors.find((f) => f.mechanism === "lighting");
  $("sample-label").textContent =
    `${state.sample + 1}/${w.orbit.length} · ${!lighting || lighting.state === "insufficient" ? "Освещение неизвестно" : shadowAt(lighting, s.at) ? "Тень" : "Вне отмеченной тени"}`;
  const pct =
    (100 * (Date.parse(s.at) - Date.parse(w.window.start))) /
    (Date.parse(w.window.end) - Date.parse(w.window.start));
  $$(".track-cursor").forEach((e) => {
    e.hidden = false;
    e.style.left = `${Math.min(99.8, pct)}%`;
  });
  $("scrub").setAttribute("aria-valuetext", stamp(s.at));
}
function stop() {
  clearInterval(state.timer);
  state.timer = null;
  $("play").textContent = "▶";
  $("play").setAttribute("aria-label", "Воспроизвести траекторию");
  $("play").setAttribute("aria-pressed", "false");
}
function play() {
  if (state.timer) {
    stop();
    return;
  }
  const count = state.analysis?.windows[state.selected]?.orbit.length;
  if (!count || count < 2) return;
  if (state.sample === count - 1) setSample(0);
  $("play").textContent = "Ⅱ";
  $("play").setAttribute("aria-label", "Остановить воспроизведение");
  $("play").setAttribute("aria-pressed", "true");
  state.timer = setInterval(() => {
    if (state.sample >= count - 1) {
      stop();
      return;
    }
    setSample(state.sample + 1);
  }, 800);
}
function renderReplay() {
  const a = state.analysis;
  $("replay-panel").hidden = a.request.mode !== "replay";
  if (a.request.mode !== "replay") return;
  const releases = a.windows
    .flatMap((w) =>
      w.factors
        .filter((f) => f.mechanism === "space_weather")
        .flatMap((f) =>
          f.evidence.map((e) => e.event?.published_at).filter(Boolean),
        ),
    )
    .sort();
  $("issue-time").textContent = releases.length
    ? stamp(releases.at(-1))
    : "Нет допустимого выпуска";
  $("cutoff-time").textContent = stamp(a.request.cutoff);
  $("replay-note").textContent =
    "Историческая орбита и сближения показаны как реконструкция. Если время публикации элементов не доказано, они не меняют строгую рекомендацию.";
}
function drawer(title, html) {
  stop();
  $("drawer-title").textContent = title;
  $("drawer-body").innerHTML = html;
  if (!$("drawer").open) $("drawer").showModal();
  $("drawer").scrollTop = 0;
}
function grid(items) {
  return `<dl class="evidence-grid">${items.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>`;
}
function sourceBlock(r) {
  return `<article class="evidence-block"><h3>${esc(r.source)}</h3>${grid([
    ["Опубликовано", stamp(r.published_at)],
    ["Получено", stamp(r.retrieved_at)],
    ["Состояние записи", label(r.cache_state)],
    ["Основание времени", label(r.publication_basis || "unknown")],
  ])}${link(r.url)}<details><summary>Идентификатор и контрольная сумма</summary><pre>${esc(r.id)}\nSHA-256 ${esc(r.content_sha256)}</pre></details></article>`;
}
function showSources() {
  if (!state.analysis) {
    toast("Сначала откройте или рассчитайте сценарий");
    return;
  }
  drawer(
    "Источники расчёта",
    `<p class="evidence-intro">${state.example ? "Это записи сохранённого исследовательского примера. Они не являются текущими данными." : "Происхождение данных именно этого расчёта. Время получения не заменяет время публикации."}</p>${state.analysis.source_records.map(sourceBlock).join("") || "<p>Исходные записи отсутствуют.</p>"}`,
  );
}
function showWhy() {
  const a = state.analysis;
  if (!a) return;
  drawer(
    conclusion(a)[1],
    `<p class="evidence-intro">Сравниваются окна одинаковой длительности: ${numeric(a.request.duration_hours, 1)} ч. Результат рассчитывает backend; интерфейс не добавляет общий балл риска.</p>${grid(
      [
        ["Режим", modes[a.request.mode]],
        ["Начало плана", stamp(a.request.start)],
        [
          "Учитываемые механизмы",
          a.comparison.decision_mechanisms
            .map((s) => names[s] || s)
            .join(", ") || "Недостаточно данных",
        ],
        ["Версия алгоритма", a.algorithm_version],
      ],
    )}<div class="evidence-block"><h3>Основания сравнения</h3>${a.comparison.reasons.map((r) => `<p>${esc(r)}</p>`).join("")}</div>${a.comparison.excluded_mechanisms.length ? `<div class="eligibility">Вне рекомендации: ${a.comparison.excluded_mechanisms.map((f) => esc(names[f.mechanism])).join(", ")}. Эти сведения доступны для исследования и не подменяют допустимые для решения данные.</div>` : ""}<details><summary>Точные правила и исключения из API</summary><pre>${esc(JSON.stringify(a.comparison, null, 2))}</pre></details>`,
  );
}
function showFactor(mechanism) {
  const w = state.analysis?.windows[state.selected],
    f = w?.factors.find((f) => f.mechanism === mechanism);
  if (!f) return;
  const context = {
    space_weather:
      "Внешняя суточная вероятность погодного события. Это не вероятность воздействия на космонавта за выбранный час и не оценка дозы.",
    conjunctions:
      "Геометрия сближений станции и каталогизированных объектов. Отсутствие события в выборке не доказывает отсутствия мусора.",
    lighting:
      "Время в цилиндрической тени Земли по рассчитанным точкам орбиты. Условие влияет на план, только если работе нужен прямой солнечный свет.",
  }[mechanism];
  const records = new Set();
  const blocks = f.evidence
    .map((e) => {
      if (e.event) {
        const ev = e.event;
        if (ev.raw_record_id) records.add(ev.raw_record_id);
        for (const id of ev.source_record_ids || []) records.add(id);
        return `<article class="evidence-block"><h3>${ev.tca ? "Событие сближения" : "Внешний прогноз"}</h3>${grid(
          ev.tca
            ? [
                ["Сближение, UTC", stamp(ev.tca)],
                [
                  "Минимальная дистанция",
                  numeric(ev.min_separation_km, 3) + " км",
                ],
                ["Объект", ev.object_name || String(ev.object_norad_id)],
                ["Классификация", ev.classification],
              ]
            : [
                ["Величина", ev.quantity],
                ["Значение", numeric(ev.value, 2) + " " + ev.unit],
                ["Действует с", stamp(ev.valid_start)],
                ["Действует до", stamp(ev.valid_end)],
                ["Опубликовано", stamp(ev.published_at)],
                [
                  "Наблюдалось",
                  ev.observed_at ? stamp(ev.observed_at) : "Это прогноз",
                ],
              ],
        )}${link(ev.source_url)}${e.rule ? `<p>${esc(e.rule)}</p>` : ""}</article>`;
      }
      for (const id of e.orbit_records || []) records.add(id);
      if (e.intervals)
        return `<article class="evidence-block"><h3>Интервалы в тени Земли</h3><p>${e.intervals.length ? e.intervals.map((i) => `${clock(i.start)}–${clock(i.end)} UTC · ${numeric(i.minutes)} мин`).join("<br>") : "В рассчитанных интервалах тень не отмечена."}</p>${grid(
          [
            ["Суммарно", numeric(e.value) + " мин"],
            ["Эпоха элементов", (e.orbit_epochs || []).map(stamp).join(", ")],
          ],
        )}${link(e.source)}</article>`;
      return "";
    })
    .join("");
  drawer(
    names[mechanism],
    `<p class="evidence-intro">${context}</p>${grid([
      [
        "Выбранное окно",
        String.fromCharCode(65 + state.selected) +
          " · " +
          clock(w.window.start) +
          "–" +
          clock(w.window.end) +
          " UTC",
      ],
      ["Результат", factorValue(f)],
      ["Состояние", label(f.state)],
      [
        "Покрытие",
        numeric(f.covered_minutes) + " мин · " + label(f.completeness),
      ],
      ["Источник / свежесть", label(f.freshness)],
      [
        "Участие в сравнении",
        !f.decision_eligible
          ? "Не участвует"
          : f.state === "insufficient"
            ? "Не хватает данных"
            : "Допустим для решения",
      ],
    ])}${!f.decision_eligible ? `<div class="eligibility">${esc(eligibility(f))}</div>` : ""}${blocks}${state.analysis.source_records
      .filter(
        (r) =>
          records.has(r.id) ||
          (mechanism === "conjunctions" && r.source === "socrates_current"),
      )
      .map(sourceBlock)
      .join(
        "",
      )}<details><summary>Ограничения метода (${f.limitations.length})</summary><ul class="evidence-list">${f.limitations.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></details><details><summary>Полные доказательства и правило из API</summary><pre>${esc(JSON.stringify(f, null, 2))}</pre></details>`,
  );
}
function download(text, type, name) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
function report() {
  const a = state.analysis;
  if (!a) return;
  download(
    buildReport(a, state.example),
    "text/html;charset=utf-8",
    `orbital-risk-${state.example || a.id}.html`,
  );
  toast("Отчёт подготовлен для скачивания");
}

async function calculate(refresh = false) {
  if (state.busy) return;
  const replay = $("mode").value === "replay";
  $("cutoff").setCustomValidity(
    replay && $("cutoff").value > $("start").value
      ? "Отсечение не может быть позже начала работ."
      : "",
  );
  const historical = $("mode").value !== "current";
  $("start").setCustomValidity(
    historical &&
      ($("start").value < "2024-05-01T00:00" ||
        $("start").value >= "2024-07-01T00:00")
      ? "Для истории выберите дату в мае–июне 2024."
      : "",
  );
  if (!$("form").reportValidity()) return;
  const request = formRequest();
  request.refresh = refresh;
  state.controller?.abort();
  state.controller = new AbortController();
  const controller = state.controller;
  const timeout = setTimeout(() => controller.abort("timeout"), 120000);
  stop();
  busy(true);
  status(
    refresh
      ? "Обновляем источники и рассчитываем. Предыдущий результат пока остаётся на экране."
      : "Рассчитываем окна. Предыдущий результат пока остаётся на экране.",
    "loading",
  );
  try {
    const a = await readJSON("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    if (controller !== state.controller) return;
    accept(a, null, 0, true);
  } catch (e) {
    if (controller !== state.controller) return;
    status(
      "Расчёт не завершён: " +
        (controller.signal.aborted
          ? "истекло время ожидания. Попробуйте ещё раз."
          : e instanceof TypeError
            ? "нет связи с сервером. Проверьте подключение и повторите запрос."
            : e.message) +
        (state.analysis ? " На экране предыдущий результат." : ""),
      "error",
    );
    $("restore").hidden = !state.analysis;
  } finally {
    clearTimeout(timeout);
    if (controller === state.controller) busy(false);
  }
}

$("form").addEventListener("submit", (e) => {
  e.preventDefault();
  calculate();
});
$("refresh").addEventListener("click", () => calculate(true));
$("form").addEventListener("input", () => {
  $("start").setCustomValidity("");
  $("cutoff").setCustomValidity("");
  dirty();
});
$("mode").addEventListener("change", () => {
  const history = $("mode").value !== "current";
  if (history && $("start").value.slice(0, 4) !== "2024") {
    $("start").value = "2024-05-10T06:00";
    $("cutoff").value = "2024-05-10T00:00";
  } else if (!history)
    $("start").value = new Date(Date.now() + 3600000)
      .toISOString()
      .slice(0, 16);
  modeUI();
  dirty();
});
$$("[data-example]").forEach((b) =>
  b.addEventListener("click", () => {
    if (!state.busy) loadExample(b.dataset.example);
  }),
);
$("window-cards").addEventListener("click", (e) => {
  const b = e.target.closest("[data-window]");
  if (b) selectWindow(Number(b.dataset.window));
});
quick.addEventListener("click", (e) => {
  const b = e.target.closest("[data-quick-window]");
  if (b) selectWindow(Number(b.dataset.quickWindow));
});
$("timeline").addEventListener("click", (e) => {
  const b = e.target.closest("[data-factor]");
  if (b) showFactor(b.dataset.factor);
});
$("scrub").addEventListener("input", () => {
  stop();
  setSample(Number($("scrub").value));
});
$("play").addEventListener("click", play);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stop();
});
$("rotate-left").addEventListener("click", () => scene.rotate(-0.3));
$("rotate-right").addEventListener("click", () => scene.rotate(0.3));
$("reset-camera").addEventListener("click", () => scene.reset());
$("why").addEventListener("click", showWhy);
$("sources").addEventListener("click", showSources);
$("sources-nav").addEventListener("click", showSources);
$("close-drawer").addEventListener("click", () => $("drawer").close());
$("drawer").addEventListener("click", (e) => {
  if (e.target === $("drawer")) {
    const r = $("drawer").getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right) $("drawer").close();
  }
});
$("restore").addEventListener("click", () => {
  fillForm(state.analysis.request);
  readyStatus();
});
$("export").addEventListener("click", report);
$("export-json").addEventListener("click", () => {
  if (state.analysis)
    download(
      JSON.stringify(state.analysis, null, 2),
      "application/json",
      `orbital-risk-${state.example || state.analysis.id}.json`,
    );
});
$("copy-link").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(location.href);
    toast(
      state.example
        ? "Ссылка на исследовательский пример скопирована"
        : "Ссылка на расчёт скопирована · доступна на этом сервере",
    );
  } catch {
    drawer(
      "Ссылка на расчёт",
      `<p class="evidence-intro">Скопируйте адрес:</p><input readonly value="${esc(location.href)}" aria-label="Адрес расчёта">`,
    );
  }
});
$("present").addEventListener("click", () => {
  const on = document.body.classList.toggle("presenting");
  $("present").setAttribute("aria-pressed", String(on));
  $("present").textContent = on ? "Обычный вид ↙" : "Режим показа ↗";
  scene.draw();
});
async function fromURL() {
  const p = new URLSearchParams(location.search),
    index = Number(p.get("window") || 0);
  if (p.has("analysis") && /^[a-f0-9]{32}$/.test(p.get("analysis")))
    await load("/api/analyses/" + p.get("analysis"), null, index, false);
  else await loadExample(p.get("example") || "window_demo", index, false);
}
window.addEventListener("popstate", fromURL);
fromURL();
