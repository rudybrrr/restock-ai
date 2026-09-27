const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const filename = path.resolve(__dirname, "../components/prepared-feature-views.tsx");
const compiled = new Module(filename, module);
compiled.paths = Module._nodeModulePaths(path.dirname(filename));
compiled._compile(ts.transpileModule(fs.readFileSync(filename, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText, filename);
const { ForecastResultView, ProjectionResultView, EconomicsResultView, WastePreparationForm } = compiled.exports;
const render = (component, result) => renderToStaticMarkup(React.createElement(component, { result }));
// Test fixtures only; no synthetic result is supplied by the preparation page.
const capture = { artifactId: "test-artifact", runId: "test-run", version: "v1", asOf: "2026-02-16T08:00:00+08:00", knownAt: "2026-02-16T08:00:00+08:00", stateRevision: "42", horizonStart: "2026-02-16", horizonEnd: "2026-02-16", complete: false, warnings: ["Coverage incomplete"] };
test("read states distinguish disconnected, loading, empty and error", () => {
  assert.match(render(ForecastResultView, { state: "not-connected" }), /not connected/);
  assert.match(render(ForecastResultView, { state: "loading" }), /Loading stored result/);
  assert.match(render(ForecastResultView, { state: "empty" }), /not a zero forecast/);
  assert.match(render(ForecastResultView, { state: "error", message: "Read failed" }), /role="alert"/);
});
test("forecast preserves unknown values, incomplete warnings and provenance", () => {
  const html = render(ForecastResultView, { state: "ready", data: { ...capture, method: "TEST", rows: [{ start: "11:00", end: "12:00", dishId: "test", dishName: "Test dish", portions: null, censored: true }] } });
  assert.match(html, /Unknown/); assert.match(html, /Incomplete result/); assert.match(html, /test-artifact/); assert.match(html, /<td>Yes<\/td>/);
});
test("projection separates recommendations, unknown coverage and measured waste", () => {
  const html = render(ProjectionResultView, { state: "ready", data: { ...capture, basis: "WITH_RECOMMENDATION", planVersionId: "test-plan", rows: [{ at: "12:00", ingredientId: "test", ingredientName: "Test", unit: "kg", usableBalance: null, expectedArrivals: "2.000", projectedUsage: null, expiryQuantity: "1.000", shortfall: null, coverage: "UNKNOWN" }] } });
  assert.match(html, /not received stock/); assert.match(html, /not measured staff-recorded waste/); assert.match(html, /Unknown/);
});
test("cash slice cannot masquerade as full-horizon economics", () => {
  const html = render(EconomicsResultView, { state: "ready", data: { ...capture, objective: "CASH_SLICE_V1", planVersionId: "test-plan", currency: "SGD", scope: "NEW_PURCHASE_CASH_ONLY", certifiedOptimal: true, newPurchaseCash: "11.000", purchase: "8.000", shipmentFees: "3.000", emergencyFees: "0", expectedWaste: "999", expectedStockout: "999", expectedTotal: "999" } });
  assert.match(html, /S\$ 11.000/); assert.doesNotMatch(html, /999/); assert.match(html, /unavailable—not zero/); assert.match(html, /No complete optimality certification/);
});
test("full economics displays stored totals without inventing missing values", () => {
  const html = render(EconomicsResultView, { state: "ready", data: { ...capture, complete: true, objective: "TEST", planVersionId: "test-plan", currency: "SGD", scope: "FULL_HORIZON_ECONOMICS", certifiedOptimal: false, newPurchaseCash: null, purchase: "8.000", shipmentFees: "3.000", emergencyFees: "0", expectedWaste: null, expectedStockout: null, expectedTotal: null } });
  assert.match(html, /Expected economic total/); assert.match(html, /Unavailable/); assert.match(html, /No complete optimality/);
});
test("waste scaffold cannot submit or claim inventory persistence", () => {
  const html = renderToStaticMarkup(React.createElement(WastePreparationForm));
  assert.match(html, /Nothing here is saved/); assert.match(html, /type="submit" disabled=""/);
});
