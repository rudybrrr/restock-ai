const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("typescript");
const filename = path.resolve(__dirname, "../lib/plan-cost.ts");
const compiled = new Module(filename, module);
compiled._compile(ts.transpileModule(fs.readFileSync(filename, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, filename);
const { moneyOrUnavailable, planCostSummary } = compiled.exports;
test("cash-only totals never fall back to full economics", () => {
  assert.deepEqual(planCostSummary({ cost_scope: "NEW_PURCHASE_CASH_ONLY", new_purchase_cash_cost: "11.000", total_expected_cost: null }), { label: "New purchase cash only", value: "11.000" });
  assert.equal(planCostSummary({ cost_scope: "NEW_PURCHASE_CASH_ONLY", new_purchase_cash_cost: null, total_expected_cost: "500" }).value, null);
});
test("money formatting preserves exact decimal precision", () => {
  assert.equal(moneyOrUnavailable("11.000"), "S$ 11.00");
  assert.equal(moneyOrUnavailable("0"), "S$ 0.00");
  assert.equal(moneyOrUnavailable("0.001"), "S$ 0.001");
  assert.equal(moneyOrUnavailable("123456789123456789.1200"), "S$ 123,456,789,123,456,789.12");
  assert.equal(moneyOrUnavailable(null), "Unavailable");
  assert.equal(moneyOrUnavailable(undefined), "Unavailable");
  assert.equal(moneyOrUnavailable("not-a-cost"), "Unavailable");
});
