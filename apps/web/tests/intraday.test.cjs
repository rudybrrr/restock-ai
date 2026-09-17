const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("typescript");
const filename = path.resolve(__dirname, "../lib/intraday.ts");
const compiled = new Module(filename, module);
compiled._compile(
  ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
  }).outputText,
  filename,
);
const { intervalSummary, activeBatches, recipeUsage } = compiled.exports;
const at = (hour) => `2026-02-16T${hour}:00+08:00`;
const batch = (id, start, end, sales = { chicken: 3 }) => ({
  id,
  source: "simulator",
  batch_id: id,
  period_start: at(start),
  period_end: at(end),
  sales,
  revision: 1,
  active: true,
  replaces_id: null,
});

test("correction chains and duplicate event records do not double count", () => {
  const first = batch("first", "08:00", "09:00");
  const second = { ...first, id: "second", replaces_id: "first", revision: 2 };
  const third = {
    ...second,
    id: "third",
    replaces_id: "second",
    revision: 3,
    sales: { chicken: 7 },
  };
  assert.deepEqual(
    activeBatches([first, second, third, third]).map((b) => b.id),
    ["third"],
  );
  assert.equal(
    intervalSummary([first, second, third], at("08:00"), at("09:00")).totals
      .chicken,
    7,
  );
});

test("gaps and boundary reports remain visible; no prorating", () => {
  const result = intervalSummary(
    [batch("cross", "07:30", "08:30"), batch("inside", "09:00", "10:00")],
    at("08:00"),
    at("11:00"),
  );
  assert.equal(result.crossing.length, 1);
  assert.equal(result.gaps.length, 2);
  assert.equal(result.totals.chicken, 3);
  assert.equal(result.overlaps, false);
});

test("overlap is detected while adjacent intervals are valid", () => {
  const first = batch("first", "08:00", "09:00");
  assert.equal(
    intervalSummary(
      [first, batch("second", "08:30", "10:00")],
      at("08:00"),
      at("10:00"),
    ).overlaps,
    true,
  );
  const adjacent = intervalSummary(
    [first, batch("second", "09:00", "10:00")],
    at("08:00"),
    at("10:00"),
  );
  assert.equal(adjacent.overlaps, false);
  assert.deepEqual(adjacent.gaps, []);
});

test("empty coverage is unknown, not a fabricated complete zero-sales interval", () => {
  const result = intervalSummary([], at("08:00"), at("10:00"));
  assert.deepEqual(result.totals, {});
  assert.equal(result.gaps.length, 1);
});

test("recipe arithmetic preserves decimal precision and rejects invalid portions", () => {
  assert.equal(recipeUsage("0.125", 3), "0.375");
  assert.equal(recipeUsage("0.1", 7), "0.7");
  assert.equal(recipeUsage("2", 150), "300");
  assert.equal(recipeUsage("1.25", 0), "0.00");
  assert.equal(recipeUsage("1", 0.5), "Unavailable");
});
