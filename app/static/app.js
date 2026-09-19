import { orbitSample, sampleAtTime } from "./orbit-math.js?v=20260919-9";
import { initTooltips, infoButton } from "./tooltips.js";
const tips = initTooltips();
import { staticDemo, apiURL, routeURL } from "./runtime.js";
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
  decisionRows,
  windowRole,
  parseUTC,
  inputUTC,
  publicationLabel,
  quantityLabel,
} from "./model.js?v=20260919-9";
import { OrbitScene } from "./orbit.js?v=20260919-9";
import { buildReport } from "./report.js?v=20260919-9";

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
if (staticDemo) {
  document.body.dataset.staticDemo = "true";
  for (const link of $$("a[data-route]")) link.href = routeURL(link.dataset.route);
}
const scene = new OrbitScene($("orbit-canvas"));
const examples = {
  sunlight: "Работа на свету",
  tradeoff: "Свет или погодный прогноз",
  window_demo: "Проверка прошлого решения",
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
  $("statusbar").hidden = kind === "ready";
  $("form-status").textContent = kind === "ready" ? "" : message;
}
function busy(value) {
  state.busy = value;
  $("plan-fields").disabled = value;
  $("calculate").disabled = value;
  $("refresh").disabled = value;
  $("calculate").innerHTML = value ? "Расчёт…" : "Рассчитать";
  $("workspace").setAttribute("aria-busy", String(value));
  $("scenario").disabled = value;
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
      "Только сведения, доступные к моменту отсечения. Геометрия показана отдельно.",
    reconstruction:
      "Восстанавливаем условия мая–июня 2024. Это не прогноз из прошлого.",
    current:
      "Новый запрос к текущим источникам. Актуальность проверяется при расчёте.",
  }[$("mode").value];
}
function fillForm(request) {
  $("mode").value = request.mode;
  $("start").value = inputUTC(request.start);
  $("task-name").value = request.task_name || "";
  $("duration").value = request.duration_hours;
  $("search").value = request.search_hours;
  $("cutoff").value = inputUTC(request.cutoff || request.start);
  $("sunlight").checked = request.requires_sunlight;
  modeUI();
  $("start").setCustomValidity("");
  $("restore").hidden = true;
}
function formRequest() {
  return requestFromValues({
    mode: $("mode").value,
    task_name: $("task-name").value,
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
      "Параметры изменены. На экране предыдущий результат. Пересчитайте варианты.",
      "dirty",
    );
  else readyStatus();
}
function readyStatus() {
  const a = state.analysis;
  if (!a) return;
  status(
    `${state.example ? "Сохранённый пример «" + examples[state.example] + "»" : "Расчёт сохранён"}, ${stamp(a.request.start)}, ${numeric(a.request.duration_hours, 1)} ч, ${modes[a.request.mode]}.`,
  );
}
function updateURL(push = false) {
  if (!state.analysis) return;
  const url = new URL(location.href);
  const page = url.searchParams.get("page");
  url.search = "";
  if (staticDemo && page) url.searchParams.set("page", page);
  url.searchParams.set(
    state.example ? "example" : "analysis",
    state.example || state.analysis.id,
  );
  url.searchParams.set("window", state.selected);
  history[push ? "pushState" : "replaceState"]({}, "", url);
}
async function readJSON(url, options = {}) {
  const response = await fetch(apiURL(url), options);
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
  if (!examples[name]) name = "sunlight";
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
  $("monitor").checked = false;
  $("monitor-control").hidden = staticDemo || a.request.mode !== "current";
  $("monitor-next").textContent = "";
  state.analysis = a;
  state.example = example;
  state.selected = normalizeWindow(index, a.windows.length);
  state.sample = 0;
  fillForm(a.request);
  render();
  scene.reset();
  rememberAnalysis(a, example);
  renderSourcesPage();
  if ($("plan-dialog").open) $("plan-dialog").close();
  updateURL(push);
  readyStatus();
}
function render() {
  const a = state.analysis,
    [, title] = conclusion(a);
  for (const id of [
    "conclusion",
    "comparison-panel",
    "timeline-panel",
    "source-strip",
  ])
    $(id).hidden = false;
  $("conclusion-title").textContent = title;
  $("fullscreen-decision").textContent = title;
  $("conclusion").dataset.outcome = a.comparison.outcome;
  $("context-date").textContent = dateLabel(a.request.start);
  $("plan-duration").textContent =
    `${numeric(a.request.duration_hours, 1)} ч / UTC`;
  $("scenario").value = state.example || "custom";
  $("mode-badge").textContent = {
    replay: "Архивный прогноз",
    reconstruction: "Реконструкция",
    current: "Текущий прогноз",
  }[a.request.mode];
  $$("[data-example]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.example === state.example)),
  );
  $("source-summary").textContent =
    `${a.source_records.length} исходных записей, алгоритм ${a.algorithm_version}, результат от ${stamp(a.created_at)}`;
  renderWindows();
  renderSelected();
  renderReplay();
}
function renderWindows() {
  const a = state.analysis;
  $("window-cards").innerHTML = a.windows
    .map((w, i) => {
      const light = w.factors.find((f) => f.mechanism === "lighting"),
        weather = w.factors.find((f) => f.mechanism === "space_weather");
      const role = windowRole(a, i),
        dominated = role === "Уступает другим";
      const shadow = (light?.evidence || [])
        .flatMap((e) => e.intervals || [])
        .map((t) => {
          const p = intervalPercent(t.start, t.end, w.window);
          return p ? `<i style="left:${p.left}%;width:${p.width}%"></i>` : "";
        })
        .join("");
      const tip = `${i === 0 ? "Исходное начало" : "Перенос на " + numeric((Date.parse(w.window.start) - Date.parse(a.request.start)) / 3600000, 1) + " ч"}. ${role}.`;
      return `<div class="window-option"><button class="window-card ${dominated ? "dominated" : ""}" data-window="${i}" aria-pressed="${i === state.selected}" aria-label="Выбрать выход с ${stamp(w.window.start)} до ${stamp(w.window.end)}. ${esc(tip)}"><span><span class="window-time">${clock(w.window.start)}–${clock(w.window.end)}</span><span class="window-day">${w.window.start.slice(0, 10) !== a.request.start.slice(0, 10) ? esc(dateLabel(w.window.start)) : ""}</span></span><span class="compare-weather"><strong>${weather ? esc(factorValue(weather)) : "Нет данных"}</strong><small>${weather?.decision_eligible ? "" : "Вне сравнения"}</small></span><span><strong>${!light || light.state === "insufficient" ? "Нет данных" : light.state === "not_requested" ? "Не задано" : numeric(light.overlap_minutes, 1) + " мин"}</strong><span class="shadow-mini" aria-hidden="true">${shadow}</span><small>${light?.decision_eligible ? "" : "Справочно"}</small></span></button>${infoButton(tip, "Об окне " + clock(w.window.start))}</div>`;
    })
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
    $("window-cards")
      .querySelector(`[data-window="${state.selected}"]`)
      .focus({ preventScroll: true });
  };
  update();
}
function renderSelected() {
  const w = state.analysis.windows[state.selected];
  $("timeline-window").textContent =
    `с ${clock(w.window.start)} до ${clock(w.window.end)}`;
  $("scene-title").textContent = "Орбита МКС";
  $("scrub").max = Math.max(0, w.orbit.length - 1);
  $("scrub").value = 0;
  $("scrub").disabled = !w.orbit.length;
  $("play").disabled = w.orbit.length < 2;
  $("orbit-start").textContent = clock(w.window.start);
  $("orbit-end").textContent = clock(w.window.end);
  $("scene-empty").hidden = !!w.orbit.length;
  $("scene-empty").textContent =
    "Нет подходящих орбитальных элементов для этого окна.";
  $("selected-factors").innerHTML = w.factors
    .filter((f) => f.mechanism !== "lighting")
    .map(
      (f) =>
        `<div class="factor-row"><button data-factor="${esc(f.mechanism)}">${esc(f.mechanism === "space_weather" ? "Космическая погода" : names[f.mechanism])} <span aria-hidden="true">›</span></button><div><strong class="${f.state === "attention" ? "attention" : ""}">${f.decision_eligible ? esc(factorValue(f)) : "Справочно"}</strong>${!f.decision_eligible ? infoButton(factorValue(f) + ". " + eligibility(f), "О полноте данных") : ""}</div></div>`,
    )
    .join("");
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
    } else if (f.mechanism === "lighting") {
      const intervals = f.evidence.flatMap((e) => e.intervals || []);
      marks = intervals.map((i) => interval(i.start, i.end, "shadow")).join("");
      text = missing
        ? "Геометрия недоступна"
        : f.state === "not_requested"
          ? "Условие не задано"
          : factorValue(f);
      hint = f.decision_eligible ? "" : "Вне сравнения";
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
      hint = f.decision_eligible ? "" : "Вне сравнения";
    }
    return `<div class="timeline-row"><button class="lane-label" data-tip="${esc(text + (hint ? ". " + hint : ""))}" data-factor="${esc(f.mechanism)}">${esc(names[f.mechanism])}</button><div class="track ${missing ? "unknown" : ""}" role="img" aria-label="${esc(names[f.mechanism] + ": " + text)}">${marks}<span class="track-text">${esc(f.mechanism === "conjunctions" && !f.decision_eligible ? "Справочно" : text)}</span><span class="track-cursor"></span></div><button class="detail-button" data-factor="${esc(f.mechanism)}" aria-label="Доказательства: ${esc(names[f.mechanism])}">›</button></div>`;
  });
  $("timeline").innerHTML =
    `<div class="timeline-axis">${[0, 0.25, 0.5, 0.75, 1].map((p) => `<span>${clock(lo + p * (hi - lo))}</span>`).join("")}</div>` +
    rows.join("");
}
function setSample(index) {
  const w = state.analysis?.windows[state.selected];
  if (!w) return;
  state.sample = Math.max(0, Math.min(w.orbit.length - 1, Number(index) || 0));
  $("scrub").value = state.sample;
  const s = orbitSample(w.orbit, state.sample);
  scene.setData(state.analysis.windows, state.selected, state.sample);
  if (!s) {
    $("orbit-time").textContent = "–";
    $("orbit-meta").textContent = "Геометрия недоступна";
    $("sample-label").textContent = "Нет точек";
    $$(".track-cursor").forEach((e) => (e.hidden = true));
    return;
  }
  $("orbit-time").textContent = clock(s.at) + " UTC";
  const altitude = Math.hypot(...s.position_teme_km) - 6378.137;
  $("orbit-meta").textContent = `Высота ≈ ${numeric(altitude)} км`;
  const lighting = w.factors.find((f) => f.mechanism === "lighting");
  $("sample-label").textContent =
    `${!lighting || lighting.state === "insufficient" ? "Освещение неизвестно" : shadowAt(lighting, s.at) ? "В тени" : "Вне тени"}`;
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
  cancelAnimationFrame(state.timer);
  state.timer = null;
  $("play").innerHTML = '<svg aria-hidden="true"><use href="#i-play" /></svg>';
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
  $("play").innerHTML = '<svg aria-hidden="true"><use href="#i-pause" /></svg>';
  $("play").setAttribute("aria-label", "Остановить воспроизведение");
  $("play").setAttribute("aria-pressed", "true");
  const orbit = state.analysis.windows[state.selected].orbit;
  const start = Date.parse(orbitSample(orbit, state.sample).at);
  const end = Date.parse(orbit.at(-1).at);
  const started = performance.now();
  function frame(now) {
    // Preserve the previous playback speed: five simulated minutes per 800 ms.
    const at = Math.min(end, start + (now - started) * 375);
    setSample(sampleAtTime(orbit, at));
    if (at >= end) stop();
    else state.timer = requestAnimationFrame(frame);
  }
  state.timer = requestAnimationFrame(frame);
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
  return `<article class="evidence-block"><h3>${esc(sourceNames[r.source] || r.source)}</h3>${grid(
    [
      ["Опубликовано", stamp(r.published_at)],
      ["Получено", stamp(r.retrieved_at)],
      ["Состояние записи", label(r.cache_state)],
      ["Основание времени", publicationLabel(r.publication_basis)],
    ],
  )}${link(r.url)}<details><summary>Идентификатор и контрольная сумма</summary><pre>${esc(r.source)}\n${esc(r.id)}\nSHA-256 ${esc(r.content_sha256)}
${esc(r.publication_basis)}</pre></details></article>`;
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
  const rows = decisionRows(a);
  drawer(
    conclusion(a)[1],
    `<p class="evidence-intro">${esc(conclusion(a)[2])}</p><div class="comparison-table-wrap"><table class="comparison-table"><thead><tr><th>Условие</th>${a.windows.map((w) => `<th>${clock(w.window.start)}<small>${esc(dateLabel(w.window.start))}</small></th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr><th>${esc(r.title)}</th>${r.values.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("")}<tr><th>Выбор</th>${a.windows.map((w, i) => `<td>${esc(windowRole(a, i))}</td>`).join("")}</tr></tbody></table></div><p>Сравниваем одинаковую длительность: ${numeric(a.request.duration_hours, 1)} ч. Вариант уступает, если другой не хуже по всем учитываемым условиям и лучше хотя бы по одному.</p>${a.comparison.excluded_mechanisms.length ? `<p class="eligibility">Справочно, вне выбора: ${a.comparison.excluded_mechanisms.map((f) => esc(names[f.mechanism])).join(", ")}. ${a.request.mode === "replay" ? "Время публикации исторической орбиты не подтверждено." : "Полнота исторического каталога сближений не подтверждена."}</p>` : ""}<div class="evidence-actions">${rows.map((r) => `<button class="outline" data-factor="${esc(r.name)}">${esc(r.title)}</button>`).join("")}</div><details><summary>Метод и точные правила</summary><p>${a.comparison.reasons.map(esc).join(" ")}</p><pre>${esc(JSON.stringify(a.comparison, null, 2))}</pre></details>`,
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
                [
                  "Классификация",
                  ev.published_at
                    ? "Сводка источника"
                    : "Историческая геометрия",
                ],
              ]
            : [
                ["Величина", quantityLabel(ev.quantity)],
                ["Значение", numeric(ev.value, 2) + " " + ev.unit],
                ["Действует с", stamp(ev.valid_start)],
                ["Действует до", stamp(ev.valid_end)],
                ["Опубликовано", stamp(ev.published_at)],
                [
                  "Наблюдалось",
                  ev.observed_at ? stamp(ev.observed_at) : "Это прогноз",
                ],
              ],
        )}${link(ev.source_url)}</article>`;
      }
      for (const id of e.orbit_records || []) records.add(id);
      if (e.intervals)
        return `<article class="evidence-block"><h3>Интервалы в тени Земли</h3><p>${e.intervals.length ? e.intervals.map((i) => `${clock(i.start)}–${clock(i.end)} UTC, ${numeric(i.minutes)} мин`).join("<br>") : "В рассчитанных интервалах тень не отмечена."}</p>${grid(
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
    `<p class="evidence-intro">${esc(factorValue(f))}. ${mechanism === "space_weather" ? "Внешний прогноз NOAA/USAF за указанные сутки." : mechanism === "lighting" ? "Пересечение работы с тенью, рассчитанное командой." : "Сближения станции в охвате выбранного источника."}</p>${grid(
      [
        [
          "Выбранный вариант",
          "с " + clock(w.window.start) + " до " + clock(w.window.end) + " UTC",
        ],
        ["Результат", factorValue(f)],
        ["Состояние", label(f.state)],
        [
          "Покрытие",
          numeric(f.covered_minutes) + " мин, " + label(f.completeness),
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
      ],
    )}${!f.decision_eligible ? `<div class="eligibility">${esc(eligibility(f))}</div>` : ""}${blocks}${state.analysis.source_records
      .filter(
        (r) =>
          records.has(r.id) ||
          (mechanism === "conjunctions" && r.source === "socrates_current"),
      )
      .map(sourceBlock)
      .join(
        "",
      )}<details><summary>Технические ограничения источника (${f.limitations.length})</summary><ul class="evidence-list">${f.limitations.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></details><details><summary>Модель и исходные поля</summary><p>${context}</p><pre>${esc(JSON.stringify(f, null, 2))}</pre></details>`,
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

async function calculate(refresh = false, automatic = false) {
  if (staticDemo) return openPlan();
  if (state.busy) return;
  $("start").setCustomValidity("");
  $("cutoff").setCustomValidity("");
  let request;
  try {
    request = formRequest();
  } catch (e) {
    status(e.message, "error");
    return;
  }
  if (request.mode === "replay" && request.cutoff > request.start)
    $("cutoff").setCustomValidity(
      "Этот момент должен быть не позже начала работы.",
    );
  if (
    request.mode !== "current" &&
    (request.start < "2024-05-01T00:00" || request.start >= "2024-07-01T00:00")
  )
    $("start").setCustomValidity("Доступен архив за май–июнь 2024.");
  if (!$("form").reportValidity()) return;

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
    if (automatic && (!$("monitor").checked || $("plan-dialog").open)) {
      readyStatus();
      return;
    }
    navigate("planner", false);
    accept(a, null, automatic ? state.selected : 0, !automatic);
    $("monitor").checked = request.mode === "current";
    scheduleMonitor();
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
  if ($("mode").value === "current")
    $("start").value = inputUTC(Date.now() + 3600000);
  else {
    try {
      if (parseUTC($("start").value).slice(0, 4) !== "2024") throw Error();
    } catch {
      $("start").value = "05.05.2024 01:00";
      $("cutoff").value = "04.05.2024 23:00";
    }
  }
  modeUI();
  dirty();
});

$("scenario").addEventListener("change", () => {
  if (!state.busy && examples[$("scenario").value])
    loadExample($("scenario").value);
});
$("window-cards").addEventListener("click", (e) => {
  const b = e.target.closest("[data-window]");
  if (b) selectWindow(Number(b.dataset.window));
});
$("selected-factors").addEventListener("click", (e) => {
  const b = e.target.closest("[data-factor]");
  if (b) showFactor(b.dataset.factor);
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
const orbitPanel = $("orbit-panel");
let fullscreenFallback = false;
function syncOrbitFullscreen() {
  const expanded =
    document.fullscreenElement === orbitPanel || fullscreenFallback;
  orbitPanel.classList.toggle("scene-fullscreen", expanded);
  document.body.classList.toggle("orbit-expanded", expanded);
  $("orbit-fullscreen").setAttribute("aria-pressed", String(expanded));
  $("orbit-fullscreen").setAttribute(
    "aria-label",
    expanded ? "Выйти из полноэкранного 3D" : "Развернуть 3D на весь экран",
  );
  $("orbit-fullscreen").title = expanded
    ? "Выйти из полного экрана"
    : "На весь экран";
  $("orbit-fullscreen").innerHTML =
    `<svg aria-hidden="true"><use href="#i-${expanded ? "minimize" : "maximize"}" /></svg>`;
  requestAnimationFrame(() => scene.draw());
}
$("orbit-fullscreen").addEventListener("click", async () => {
  if (document.fullscreenElement === orbitPanel) {
    await document.exitFullscreen();
  } else if (fullscreenFallback) {
    fullscreenFallback = false;
  } else {
    try {
      if (!orbitPanel.requestFullscreen)
        throw new Error("Fullscreen unavailable");
      await orbitPanel.requestFullscreen();
    } catch {
      // iPhone and embedded browsers may only support fullscreen video.
      fullscreenFallback = true;
    }
  }
  syncOrbitFullscreen();
});
document.addEventListener("fullscreenchange", syncOrbitFullscreen);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && fullscreenFallback) {
    fullscreenFallback = false;
    syncOrbitFullscreen();
    $("orbit-fullscreen").focus();
  }
});
$("rotate-left").addEventListener("click", () => scene.rotate(-0.3));
$("rotate-right").addEventListener("click", () => scene.rotate(0.3));
$("reset-camera").addEventListener("click", () => scene.reset());
$("why").addEventListener("click", showWhy);
$("sources").addEventListener("click", showSources);

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
        : "Ссылка на расчёт скопирована, доступна на этом сервере",
    );
  } catch {
    drawer(
      "Ссылка на расчёт",
      `<p class="evidence-intro">Скопируйте адрес:</p><input readonly value="${esc(location.href)}" aria-label="Адрес расчёта">`,
    );
  }
});
const pages = {
  planner: "Планирование",
  archive: "Расчёты",
  sources: "Источники",
  method: "Методика",
};
let archiveExamples = [];
const historyKey = "orbital-risk-calculations-v1";
function remembered() {
  try {
    const rows = JSON.parse(localStorage.getItem(historyKey) || "[]");
    return Array.isArray(rows)
      ? rows
          .filter(
            (r) =>
              /^[a-f0-9]{32}$/.test(r.id) &&
              typeof r.start === "string" &&
              Number.isFinite(Date.parse(r.start)) &&
              modes[r.mode] &&
              Number.isFinite(r.duration),
          )
          .slice(0, 50)
      : [];
  } catch {
    return [];
  }
}
function rememberAnalysis(a, example) {
  if (example) return;
  try {
    const rows = remembered().filter((r) => r.id !== a.id);
    rows.unshift({
      id: a.id,
      start: a.request.start,
      duration: a.request.duration_hours,
      mode: a.request.mode,
      task_name: a.request.task_name || "",
      result: conclusion(a)[1],
    });
    localStorage.setItem(historyKey, JSON.stringify(rows.slice(0, 50)));
  } catch {
    /* Server save remains usable when browser storage is unavailable. */
  }
}
function currentPage() {
  return (staticDemo ? new URLSearchParams(location.search).get("page") : location.pathname.split("/")[1]) || "planner";
}
function applyRoute() {
  tips.hide();
  const page = pages[currentPage()] ? currentPage() : "planner";
  document.body.dataset.route = page;
  document.title = pages[page] + ": Орбитальный риск";
  $("page-title").textContent = pages[page];
  $("breadcrumb").textContent = pages[page];
  $$("[data-page]").forEach((el) => (el.hidden = el.dataset.page !== page));
  $$("nav [data-route]").forEach((el) => {
    if (el.dataset.route === page) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  });
  $("export").hidden = page === "archive" || page === "method";
  if (page !== "planner") {
    stop();
    fullscreenFallback = false;
    if (document.fullscreenElement === orbitPanel) document.exitFullscreen();
    syncOrbitFullscreen();
  }
  if (page === "archive") renderArchive();
  if (page === "sources") loadProviderHealth();
  if (page === "planner") requestAnimationFrame(() => scene.draw());
  if (page !== "planner") $("monitor").checked = false;
}
function navigate(page, push = true) {
  if (!pages[page]) return;
  const url = routeURL(page);
  for (const key of ["example", "analysis", "window"]) {
    const value = new URLSearchParams(location.search).get(key);
    if (value !== null) url.searchParams.set(key, value);
  }
  history[push ? "pushState" : "replaceState"]({}, "", url);
  applyRoute();
  window.scrollTo(0, 0);
}
function openPlan() {
  if (staticDemo) return toast("Новые расчёты доступны при запуске сервера. Здесь можно выбрать сохранённый пример.");
  $("form-status").textContent = "";
  $("plan-dialog").showModal();
}
function archiveRow(row, example = false) {
  const title = example
    ? examples[row.name]
    : row.task_name || "Работа " + clock(row.start);
  const url = routeURL("planner");
  url.searchParams.set(
    example ? "example" : "analysis",
    example ? row.name : row.id,
  );
  const detail = `${dateLabel(row.start)} / ${numeric(row.duration, 1)} ч`;
  return `<a class="archive-row" href="${esc(url.pathname + url.search)}" data-open-analysis><span class="row-icon"><svg><use href="#i-${example ? "orbit" : "plan"}"/></svg></span><span><strong>${esc(title)}</strong><small>${esc(detail)}</small><small>${esc(row.result || "")}</small></span><span class="row-meta row-date">${clock(row.start)} UTC</span><span class="row-meta row-mode">${esc(modes[row.mode])}</span><span class="row-arrow" aria-hidden="true">›</span></a>`;
}
function renderArchive() {
  const query = $("archive-search").value.trim().toLocaleLowerCase();
  const matches = (r, example) =>
    `${example ? examples[r.name] : r.task_name || "Работа"} ${r.result || ""} ${r.start} ${dateLabel(r.start)} ${modes[r.mode]}`
      .toLocaleLowerCase()
      .includes(query);
  const recent = staticDemo ? [] : remembered().filter((r) => matches(r, false));
  const samples = archiveExamples.filter((r) => matches(r, true));
  $("archive-count").textContent = `Найдено: ${recent.length + samples.length}`;
  $("archive-list").innerHTML =
    `<section class="archive-group"><h2>Сохранённые примеры</h2>${samples.map((r) => archiveRow(r, true)).join("") || `<p class="empty-state">${archiveExamples.length ? "Нет совпадений." : "Загрузка примеров…"}</p>`}</section><section class="archive-group"><h2>Мои расчёты</h2>${recent.map((r) => archiveRow(r)).join("") || `<p class="empty-state">${query ? "Нет совпадений." : 'Здесь появятся ваши расчёты. <button class="text-link" data-new>Создать расчёт</button>'}</p>`}</section>`;
}
async function loadArchiveExamples() {
  const result = await Promise.allSettled(
    Object.keys(examples).map(async (name) => {
      const a = await readJSON("/api/examples/" + name);
      return {
        name,
        start: a.request.start,
        mode: a.request.mode,
        task_name: a.request.task_name || "",
        result: conclusion(a)[1],
        duration: a.request.duration_hours,
      };
    }),
  );
  archiveExamples = result
    .filter((r) => r.status === "fulfilled")
    .map((r) => r.value);
  renderArchive();
  if (!archiveExamples.length)
    $("archive-list").innerHTML =
      '<p class="empty-state">Не удалось загрузить примеры. <button class="text-link" id="retry-archive">Повторить</button></p>';
}
const sourceNames = {
  noaa_archive: "NOAA: прогноз космической погоды",
  iss_history_extract: "МКС: орбитальные элементы",
  conjunction_tle_history: "Каталог объектов: исторические TLE",
  noaa: "NOAA: космическая погода",
  noaa_current: "NOAA: текущий прогноз",
  iss_current: "МКС: текущие элементы",
  socrates_current: "SOCRATES: текущие сближения",
  celestrak: "CelesTrak: орбитальные элементы",
  socrates: "SOCRATES: сближения",
};
function renderSourcesPage() {
  const a = state.analysis;
  if (!a) return;
  $("sources-context").textContent = state.example
    ? `Пример «${examples[state.example]}»`
    : `Расчёт ${dateLabel(a.request.start)}, ${clock(a.request.start)} UTC`;
  $("source-summary").textContent =
    `${modes[a.request.mode]}. Исходных записей: ${a.source_records.length}. Сохранено ${stamp(a.created_at)}.`;
  const groups = Map.groupBy
    ? Map.groupBy(a.source_records, (r) => r.source)
    : a.source_records.reduce(
        (m, r) => m.set(r.source, [...(m.get(r.source) || []), r]),
        new Map(),
      );
  $("source-table").innerHTML =
    [...groups]
      .map(
        ([name, records]) =>
          `<details class="source-group"><summary><span>${esc(sourceNames[name] || name)}<small>${esc([...new Set(records.map((r) => label(r.cache_state)))].join(", "))}</small></span><span class="source-count">Записей: ${records.length}</span></summary><div class="source-records">${records.map(sourceBlock).join("")}</div></details>`,
      )
      .join("") ||
    '<p class="empty-state">Нет исходных записей для этого расчёта.</p>';
}
document.addEventListener("click", (e) => {
  const route = e.target.closest("a[data-route]");
  if (route && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
    e.preventDefault();
    navigate(route.dataset.route);
    return;
  }
  if (e.target.closest("[data-new]")) {
    openPlan();
    return;
  }
  if (e.target.closest("#retry-archive")) {
    loadArchiveExamples();
    return;
  }
  const row = e.target.closest("[data-open-analysis]");
  if (row && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
    e.preventDefault();
    history.pushState({}, "", row.href);
    fromURL();
    window.scrollTo(0, 0);
  }
});
$("archive-search").addEventListener("input", renderArchive);
$("edit-plan").addEventListener("click", openPlan);
$("close-plan").addEventListener("click", () => $("plan-dialog").close());
loadArchiveExamples();

async function fromURL() {
  applyRoute();
  const p = new URLSearchParams(location.search),
    index = Number(p.get("window") || 0);
  if (!staticDemo && p.has("analysis") && /^[a-f0-9]{32}$/.test(p.get("analysis")))
    await load("/api/analyses/" + p.get("analysis"), null, index, false);
  else await loadExample(p.get("example") || "sunlight", index, false);
}
window.addEventListener("popstate", fromURL);
fromURL();
loadValidation();

$("drawer-body").addEventListener("click", (e) => {
  const b = e.target.closest("[data-factor]");
  if (b) showFactor(b.dataset.factor);
});
$("present").addEventListener("click", () => {
  const active = document.body.classList.toggle("presentation");
  $("present").setAttribute("aria-pressed", String(active));
  $("present").textContent = active ? "Рабочий вид" : "Для защиты";
  scene.draw();
});
async function loadProviderHealth(refresh = false) {
  if (staticDemo) return;
  const button = $("refresh-providers");
  if (button.disabled) return;
  button.disabled = true;
  $("provider-status").textContent = refresh
    ? "Получаем новые выпуски…"
    : "Проверяем кеш источников…";
  try {
    const data = await readJSON(
      refresh ? "/api/sources/refresh" : "/api/sources",
      refresh ? { method: "POST" } : {},
    );
    const states = {
      cache_fresh: "Кеш актуален",
      cache_stale: "Обновите кеш",
      source_stale: "Выпуск устарел",
      missing: "Ещё не загружен",
      disabled: "Источник отключён",
      invalid: "Запись не прошла проверку",
      truncated: "Сводка неполная",
    };
    $("provider-health").innerHTML = Object.entries(data)
      .map(
        ([name, p]) =>
          `<article class="provider-row"><strong>${esc(sourceNames[name] || name)}</strong><span>${esc(states[p.state] || "Состояние неизвестно")}</span><small>Выпуск: ${stamp(p.source_data_at || p.last_successful_record?.published_at)}<br>Получен: ${stamp(p.last_successful_record?.retrieved_at)}</small></article>`,
      )
      .join("");
    $("provider-status").textContent = refresh
      ? "Состояние источников обновлено. Сохранённый расчёт не изменён; новый план использует новые данные."
      : "Состояние кеша на сервере. Пригодность и покрытие проверяются для каждого плана.";
  } catch (e) {
    $("provider-status").textContent =
      "Не удалось проверить источники. Повторите обновление. " + e.message;
  } finally {
    button.disabled = false;
  }
}
$("refresh-providers").addEventListener("click", () =>
  loadProviderHealth(true),
);
async function loadValidation() {
  try {
    const d = await readJSON("/api/validation");
    $("validation-summary").innerHTML =
      `<div class="validation-metrics"><span><strong>${d.windows}</strong> окон</span><span><strong>${d.improved_cases}/${d.cases}</strong> планов улучшено</span><span><strong>${d.worse_cases}</strong> ухудшений</span>${infoButton(`Сравнение по освещению с исходным началом. Проверка шагом 1 мин: средняя ошибка ${numeric(d.mean_absolute_error_minutes, 3)} мин, максимальная ${numeric(d.max_absolute_error_minutes, 2)} мин. Одна модель тени, не оценка точности погодного прогноза.`, "О проверке освещения")}<a href="${apiURL("/api/validation")}" target="_blank" rel="noopener">Данные</a></div>`;
  } catch {
    $("validation-summary").textContent =
      "Отчёт проверки пока недоступен. Команда воспроизведения: python scripts/validate_planning.py";
  }
}

$("export-bundle").addEventListener("click", async () => {
  if (!state.analysis) return;
  const button = $("export-bundle");
  button.disabled = true;
  try {
    const url = state.example
      ? `/api/examples/${state.example}/bundle.zip`
      : `/api/analyses/${state.analysis.id}/bundle.zip`;
    const response = await fetch(apiURL(url));
    if (!response.ok)
      throw Error("Исходные байты недоступны или не прошли проверку.");
    download(
      await response.blob(),
      "application/zip",
      "orbital-risk-evidence.zip",
    );
  } catch (e) {
    toast(e.message);
  } finally {
    button.disabled = false;
  }
});

let monitorTimer;
function scheduleMonitor() {
  clearTimeout(monitorTimer);
  const active = $("monitor").checked && state.analysis?.request.mode === "current";
  $("monitor-next").textContent = active ? "(следующая проверка " + clock(Date.now() + 300000) + " UTC)" : "";
  if (!active) return;
  monitorTimer = setTimeout(async () => {
    if ($("monitor").checked && state.analysis?.request.mode === "current" && !document.hidden && currentPage() === "planner" && !state.busy && !$("plan-dialog").open) {
      let unchanged = false;
      try { unchanged = sameRequest(formRequest(), state.analysis.request); } catch {}
      if (unchanged) await calculate(false, true);
    }
    scheduleMonitor();
  }, 300000);
}
$("monitor").addEventListener("change", scheduleMonitor);

async function loadWeatherValidation() {
  try {
    const d = await readJSON("/api/validation/weather");
    $("weather-validation").innerHTML = `<details class="validation-details"><summary>Проверка погодных предупреждений</summary><div class="validation-metrics"><span>${numeric(d.labelled_days)} суток</span><span>Порог ${numeric(d.alert_threshold_percent)}%</span>${infoButton("Проверка по текстовым сводкам NOAA SGAS, не по непрерывному потоку частиц. Один неоднозначный день исключён.", "О погодной проверке")}<a href="${apiURL("/api/validation/weather")}" target="_blank" rel="noopener">Данные</a></div><div class="validation-table"><table><thead><tr><th>Метод</th><th>Обнаружено</th><th>Пропущено</th><th>Ложные тревоги</th></tr></thead><tbody>${[["Прогноз NOAA",d.forecast],["Последняя известная обстановка",d.persistence]].map(([name,r])=>`<tr><th>${name}</th><td>${numeric(r.hits)}</td><td>${numeric(r.misses)}</td><td>${numeric(r.false_alerts)}</td></tr>`).join("")}</tbody></table></div></details>`;
  } catch { $("weather-validation").textContent = "Погодная проверка недоступна."; }
}
loadWeatherValidation();
