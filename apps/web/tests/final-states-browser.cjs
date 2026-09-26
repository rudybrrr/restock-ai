// UI contract fixtures only: no live purchases or approvals are written.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const assert = require("node:assert/strict");
const base = process.env.UI_TEST_URL || "http://localhost:3014";
const at = "2026-02-16T09:00:00+08:00";
(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", e => errors.push(e.message));
    let outcome = "REVISE_PLAN", contingency = false, stale = false, approved = false, decisions = 0, deliveries = 0;
    const line = { id: "line-1", ingredient_id: "vegetables", supplier_id: "fresh", quantity: "2.000", unit_price: "4.000", arrival_at: at, ordered_at: "2026-02-16T08:30:00+08:00", expiry_date: "2026-02-18", kind: "EMERGENCY", linked_quantity: "0.000", uncommitted_quantity: "2.000" };
    const plan = () => ({ id: "version-1", plan_id: "plan-1", version: 1, status: "PENDING_APPROVAL", calculation_mode: contingency ? "CONTINGENCY_ENGINE" : "ENGINE", cost_scope: contingency ? "NEW_PURCHASE_CASH_ONLY" : "LEGACY_FIELDS", new_purchase_cash_cost: contingency ? "11.000" : null, total_purchase_cost: "8.000", delivery_cost: "3.000", emergency_penalty: "0.000", total_expected_cost: contingency ? null : "11.000", expected_waste_cost: contingency ? null : "0.000", expected_stockout_cost: contingency ? null : "0.000", lines: [line], run_id: "run-1", forecast_id: "forecast-1", inventory_snapshot_id: "inventory-1", created_at: at });
    await page.route("http://localhost:8000/api/v1/**", async route => {
      const req = route.request(), path = new URL(req.url()).pathname.replace("/api/v1", "");
      assert.equal(req.headers().authorization, undefined);
      let body = [], status = 200;
      if (path === "/auth/me") body = { role: "manager", username: "manager" };
      if (path === "/ingredients") body = [{ id: "vegetables", name: "Vegetables", unit: "kg" }];
      if (path === "/suppliers") body = [{ id: "fresh", name: "Fresh" }];
      if (path === "/plan-history") body = [plan()];
      if (path === "/plans/version-1") body = plan();
      if (path === "/plans/version-1/lines") body = [line];
      if (path === "/runs/run-1") body = { id: "run-1", status: "SUCCEEDED", trigger: outcome === "ESCALATE" ? "SALES_UPDATED" : "MANUAL", outcome, escalation_reason: outcome === "ESCALATE" ? "CALCULATION_INCOMPLETE" : null, plan_version_id: outcome === "REVISE_PLAN" ? "version-1" : null, as_of: at, created_at: at, snapshot: {} };
      if (path.endsWith("/evidence")) body = null;
      if (path.endsWith("/inventory-adjustment")) body = null;
      if (path.endsWith("/sales-materiality")) body = { result_reference: "sales-1", result: { complete: true, material_change: true, inventory_feasible: null, findings: [], required_follow_up: [], evidence_refs: [], as_of: at, known_at: at, captured_state_revision: "1" } };
      if (req.method() === "POST") {
        if (path.endsWith("/decision")) {
          decisions++;
          assert.deepEqual(req.postDataJSON(), { plan_id: "plan-1", plan_version: 1, decision: "APPROVED", instructions: null });
          if (stale) { status = 409; body = { error: { code: "PLAN_VERSION_STALE", message: "The plan version has changed." } }; }
          else { approved = true; body = { ...plan(), status: "APPROVED" }; }
        } else if (path === "/deliveries") {
          deliveries++;
          const sent = req.postDataJSON();
          assert.equal(sent.kind, "EMERGENCY");
          assert.equal(sent.expected_quantity, "2.000");
          assert.equal(sent.ordered_at, "2026-02-16T08:30:00+08:00");
          assert.equal(sent.expected_expiry_date, "2026-02-18");
          assert.equal(sent.source_plan_line_id, "line-1");
          body = { id: "delivery-1" };
        } else assert.fail("Unexpected mutation: " + path);
      }
      await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    });
    await page.goto(base + "/workspace/recommendations");
    await page.getByText("Awaiting your approval · version 1", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Approve version 1", exact: true }).click();
    await page.getByRole("button", { name: "Confirm decision", exact: true }).click();
    await page.getByText("This version is approved. Record an actual purchase after you arrange it with the supplier.", { exact: true }).waitFor();
    assert.equal(approved, true);
    assert.equal(deliveries, 0);
    contingency = true;
    await page.reload();
    await page.getByText("ADDITIONAL PURCHASE ONLY", { exact: true }).waitFor();
    await page.getByText("New purchase cash only: S$ 11.00", { exact: true }).waitFor();
    await page.getByRole("cell", { name: "2.000 kg", exact: true }).waitFor();
    stale = true;
    await page.getByRole("button", { name: "Approve version 1", exact: true }).click();
    await page.getByRole("button", { name: "Confirm decision", exact: true }).click();
    await page.getByText("Approval not saved. This version is out of date.", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Approve version 1", exact: true }).count(), 0);
    assert.equal(decisions, 2);
    assert.equal(deliveries, 0);
    outcome = "KEEP_CURRENT_PLAN";
    await page.goto(base + "/workspace/activity/run-1");
    await page.getByRole("heading", { name: "No additional purchase recommended.", exact: true }).waitFor();
    outcome = "ESCALATE";
    await page.reload();
    await page.getByRole("heading", { name: "Manager review needed. No new purchase authorized.", exact: true }).waitFor();
    await page.getByText("A material change was recorded. Review the final outcome; materiality alone does not authorize a new purchase.", { exact: true }).waitFor();
    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    }
    await page.goto(base + "/workspace/deliveries?plan=version-1&line=line-1");
    await page.locator('select[name="kind"]').waitFor();
    assert.equal(await page.locator('select[name="kind"]').inputValue(), "EMERGENCY");
    await page.locator("form").getByRole("button", { name: "Record actual purchase", exact: true }).click();
    await page.getByText("Actual purchase recorded. The quantity is expected supply until a receipt is recorded.", { exact: true }).waitFor();
    assert.equal(deliveries, 1);
    assert.deepEqual(errors, []);
    console.log("PASS: normal pending, additional-only 2kg/S$11, KEEP, sales escalation, stale approval, purchase prefill and responsive states.");
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
