import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildReport } from "../app/static/report.js";
import {
  intervalPercent,
  requestFromValues,
  sameRequest,
  factorValue,
  conclusion,
  shadowAt,
  safeURL,
  esc,
  normalizeWindow,
  parseUTC,
  inputUTC,
  windowRole,
  decisionRows,
} from "../app/static/model.js";
const example = JSON.parse(
  readFileSync(
    new URL("../research_results/window_demo.json", import.meta.url),
    "utf8",
  ),
);

test("HTML export includes the exact displayed snapshot and preserves replay semantics", () => {
  const report = buildReport(example, "window_demo");
  assert.ok(report.includes("Сохранённый исследовательский пример"));
  assert.ok(report.includes("Варианты равнозначны"));
  assert.ok(report.includes("22,1 мин в тени"));
  assert.ok(report.includes(esc(JSON.stringify(example, null, 2))));
  const untrusted = structuredClone(example);
  untrusted.comparison.reasons = ["<script>alert(1)</script>"];
  untrusted.source_records[0].url = "javascript:alert(1)";
  const safe = buildReport(untrusted);
  assert.equal(safe.includes("<script>"), false);
  assert.equal(safe.includes('href="javascript:'), false);
});

test("archived replay cannot imply an improvement from excluded lighting", () => {
  assert.equal(conclusion(example)[1], "Варианты равнозначны");
  assert.deepEqual(
    example.windows.map((w) =>
      factorValue(w.factors.find((f) => f.mechanism === "lighting")),
    ),
    ["0 мин в тени", "10,8 мин в тени", "22,1 мин в тени"],
  );
  assert.ok(
    example.windows.every(
      (w) =>
        !w.factors.find((f) => f.mechanism === "lighting").decision_eligible,
    ),
  );
  assert.equal(factorValue(example.windows[0].factors[0]), "15% / сутки");
});

test("equivalent Pareto subset is not described as all windows equivalent", () => {
  const a = {
    ...example,
    comparison: { ...example.comparison, pareto_frontier_indices: [0, 1] },
  };
  assert.equal(conclusion(a)[1], "Есть равнозначные варианты");
});
test("timeline clips intervals to the selected window, including a UTC day boundary", () => {
  const w = { start: "2024-05-01T23:00Z", end: "2024-05-02T01:00Z" };
  assert.deepEqual(
    intervalPercent("2024-05-01T00:00Z", "2024-05-02T00:00Z", w),
    { left: 0, width: 50 },
  );
  assert.deepEqual(
    intervalPercent("2024-05-02T00:00Z", "2024-05-03T00:00Z", w),
    { left: 50, width: 50 },
  );
  assert.equal(
    intervalPercent("2024-04-30T00:00Z", "2024-05-01T00:00Z", w),
    null,
  );
});
test("form time is UTC independent of host timezone; reconstruction omits cutoff", () => {
  const a = requestFromValues({
    mode: "reconstruction",
    start: "2024-05-05T01:00",
    duration: "1.5",
    search: "12",
    sunlight: true,
    cutoff: "2024-05-04T23:00",
  });
  assert.equal(a.start, "2024-05-05T01:00:00.000Z");
  assert.equal(a.duration_hours, 1.5);
  assert.equal("cutoff" in a, false);
});
test("editing any scientific parameter invalidates the displayed request", () => {
  const a = example.request;
  assert.ok(sameRequest(a, { ...a, start: "2024-05-05T01:00:00.000Z" }));
  for (const change of [
    { duration_hours: 2 },
    { search_hours: 24 },
    { requires_sunlight: false },
    { mode: "current" },
    { cutoff: "2024-05-04T22:00Z" },
  ])
    assert.equal(sameRequest(a, { ...a, ...change }), false);
});
test("missing weather is never rendered as zero percent", () => {
  assert.equal(
    factorValue({
      ...example.windows[0].factors[0],
      state: "insufficient",
      forecast_probability_percent: null,
    }),
    "Нет данных",
  );
});
test("shadow intervals use an exclusive end", () => {
  const f = {
    evidence: [
      { intervals: [{ start: "2024-05-01T01:00Z", end: "2024-05-01T01:05Z" }] },
    ],
  };
  assert.ok(shadowAt(f, "2024-05-01T01:00Z"));
  assert.equal(shadowAt(f, "2024-05-01T01:05Z"), false);
});
test("evidence cannot inject markup or unsafe navigation", () => {
  assert.equal(safeURL("javascript:alert(1)"), null);
  assert.equal(safeURL("data:text/html,x"), null);
  assert.equal(
    safeURL("https://example.com/source"),
    "https://example.com/source",
  );
  assert.equal(esc('<script>"&'), "&lt;script&gt;&quot;&amp;");
});
test("invalid shared selection falls back to the first existing window", () => {
  for (const value of [-1, 3, NaN, 0.2])
    assert.equal(normalizeWindow(value, 3), 0);
  assert.equal(normalizeWindow(2, 3), 2);
});

test("Russian UTC date entry rejects calendar overflow and round trips leap days", () => {
  assert.equal(parseUTC("29.02.2024 23:59"), "2024-02-29T23:59:00.000Z");
  assert.equal(inputUTC(parseUTC("05.05.2024 01:00")), "05.05.2024 01:00");
  for (const bad of [
    "31.02.2024 01:00",
    "01.05.2024 24:00",
    "05/01/24 1 PM",
    "29.02.2023 10:00",
  ])
    assert.throws(() => parseUTC(bad));
});
test("decision excludes historical lighting in replay and distinguishes dominated windows", () => {
  assert.deepEqual(
    decisionRows(example).map((r) => r.name),
    ["space_weather"],
  );
  const a = JSON.parse(
    readFileSync(
      new URL("../research_results/sunlight.json", import.meta.url),
      "utf8",
    ),
  );
  assert.equal(conclusion(a)[1], "Начать в 01:00 UTC");
  assert.equal(windowRole(a, 0), "Предпочтительно");
  assert.equal(windowRole(a, 1), "Уступает другим");
  a.request.task_name = "<img src=x onerror=alert(1)>";
  assert.equal(buildReport(a).includes("<img src=x"), false);
});

test("tooltip metadata cannot inject markup or break attribute boundaries", async () => {
  const { infoButton } = await import("../app/static/tooltips.js");
  const button = infoButton(
    '<img src=x onerror="alert(1)">',
    '" autofocus onfocus="alert(1)',
  );
  assert.equal(button.includes("<img"), false);
  assert.equal(button.includes('aria-label="" autofocus'), false);
  assert.ok(button.includes("&lt;img"));
  assert.ok(button.includes('type="button"'));
});
