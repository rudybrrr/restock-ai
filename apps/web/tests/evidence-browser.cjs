const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const assert = require("node:assert/strict");
const base = process.env.UI_TEST_URL || "http://localhost:3012";
const screenshotsEnabled = process.env.ENABLE_SCREENSHOTS === "1";
const at = (time) => `2026-02-16T${time}:00+08:00`;
const policy = {
  id: "policy-1",
  policy_id: "TEST_POLICY",
  version: 1,
  effective_at: at("08:00"),
  recorded_at: at("08:00"),
  payload: {
    objective_policy: "CASH_SLICE_V1",
    target_date: "2026-02-16",
    new_order_budget_sgd: "100.00",
    issue_time: at("08:00"),
    horizon_end: at("21:00"),
    timezone: "Asia/Singapore",
    bucket_minutes: 30,
    service_profile: [{ start: at("11:00"), end: at("14:00"), weight: "0.4" }],
    safety_stock: { chicken: "0" },
    storage_limits: { chicken: "30" },
    fee_policy: "SUPPLIER_ARRIVAL_ONCE_V1",
    fee_grouping: "SUPPLIER_ID_AND_ARRIVAL_AT",
    emergency_mode: "NORMAL_ONLY",
    reliability_mode: "CONTEXT_ONLY",
    fefo_policy: "FEFO_EXPIRY_RECEIVED_LOT_ID_V1",
    new_supply_expiry_policy: "EXPIRY_ARRIVAL_PLUS_SHELF_LIFE_MINUS_ONE_V1",
    tie_break_policy: "SUPPLIER_ID_THEN_INGREDIENT_ID_V1",
    search_policy: "COMPLETE_PRUNED_DOMAIN_V1",
    approved_supplier_ids: ["fresh"],
    expected_offer_count: 1,
    expected_opportunity_count: 1,
    explicit_empty_post_count_activity: true,
    explicit_empty_outstanding_commitments: true,
  },
};
const evidence = {
  policy,
  activity_semantics: {
    version: "FORECAST_ACTIVITY_V1",
    baseline_history_mode: "VERSIONED_FORECAST_INPUT_IMMUTABLE",
    intraday_sales_mode: "INVENTORY_ESTIMATE_AND_REASSESSMENT_ONLY",
    closing_sales_mode: "LATEST_DAILY_REVISION_AUTHORITATIVE",
    reconciliation_mode: "COMPARE_NEVER_ADD",
  },
  commitment_projection: {
    complete: true,
    as_of: at("08:00"),
    known_at: at("08:00"),
    captured_state_revision: "42",
    findings: [],
    supplies: [
      {
        delivery: {
          id: "delivery-fixed",
          ingredient_id: "chicken",
          supplier_id: "fresh",
          expected_quantity: "10.000",
          received_quantity: "2.000",
          cancelled_quantity: "3.000",
          outstanding_quantity: "5.000",
          expected_at: at("10:00"),
        },
        expiry_date: "2026-02-20",
        projected_lot_id: "projected-delivery:delivery-fixed",
        expiry_evidence: {
          reference: "frozen-offer-expiry",
          available_at: at("08:00"),
          captured_revision: "42",
        },
      },
    ],
  },
  domain: {
    id: "domain",
    domain_id: "TEST_DOMAIN",
    version: 1,
    source_revision: "seed-1",
    recorded_at: at("08:00"),
    payload: {
      source_kind: "FIRST_SLICE_SYNTHETIC_FIXTURE",
      source_description: "Browser test only",
      opening_lot_ids: ["lot-1"],
    },
    offers: [
      {
        id: "revision-1",
        offer_id: "offer-1",
        supplier_id: "fresh",
        ingredient_id: "chicken",
        source_revision: "seed-1",
        offer: {
          unit_price: "4.50",
          pack_size: "1.000",
          available_quantity: "200.000",
        },
      },
    ],
    opportunities: [
      {
        id: "op-1",
        opportunity_id: "opportunity-1",
        offer_id: "offer-1",
        ordered_at: at("08:00"),
        arrival_at: at("10:00"),
        expiry_date: "2026-02-20",
        kind: "NORMAL",
        source_revision: "seed-1",
      },
    ],
  },
  forecast_input: {
    artifact_id: "HISTORY_ONLY",
    version: 1,
    source_revision: "history-1",
    effective_at: at("08:00"),
    recorded_at: at("08:00"),
    payload: {
      source_kind: "FIRST_SLICE_SYNTHETIC_HISTORY",
      forecast_method: "SEASONAL_BASELINE_V1",
      target_date: "2026-02-16",
      menu_item_ids: ["dish"],
      history: [
        {
          service_date: "2026-02-09",
          available_at: at("08:00"),
          revision: 1,
          promotion: false,
          censored: false,
          portions: { dish: 120 },
        },
      ],
    },
  },
};
const first = {
  id: "batch-1",
  source: "simulator",
  batch_id: "sales-1",
  period_start: at("08:00"),
  period_end: at("09:00"),
  sales: { dish: 3 },
  revision: 1,
  active: true,
  replaces_id: null,
};
let reports = [
  first,
  {
    ...first,
    id: "batch-2",
    sales: { dish: 7 },
    revision: 2,
    replaces_id: "batch-1",
  },
];
const managerEvidence = {
  run_id: "run-1",
  run_status: "SUCCEEDED",
  trigger: "SUPPLIER_AVAILABILITY_CHANGED",
  trigger_event_id: "event-1",
  operational_cutoff: at("08:00"),
  input_revision: 42,
  claimed_at: at("08:01"),
  completed_at: at("09:00"),
  active_plan: {
    id: "version-1",
    plan_id: "plan-1",
    version: 1,
    status: "PENDING_APPROVAL",
    calculation_mode: "ENGINE",
    run_id: "run-1",
    created_at: at("08:30"),
    line_count: 1,
    total_expected_cost: "100.00",
  },
  plan_history: [],
  approval: {
    required: true,
    status: "PENDING_APPROVAL",
    plan_id: "plan-1",
    plan_version: 1,
    latest_attempt: null,
    stale_attempts: [
      {
        id: "approval-stale-1",
        status: "STALE",
        timestamp: at("08:45"),
        actor: "manager",
        summary: "Approval used an older plan version.",
        reason_codes: ["PLAN_VERSION_STALE"],
      },
    ],
  },
  timeline: [
    {
      id: "event-1",
      kind: "TRIGGER_EVENT",
      timestamp: at("08:00"),
      actor: "backend",
      event_type: "SUPPLIER_AVAILABILITY_CHANGED",
      state_revision: null,
      invocation_mode: null,
      plan_id: null,
      plan_version: null,
      specialist: null,
      specialist_call_id: null,
      call_sequence: null,
      tool_call_id: null,
      tool_name: null,
      attempt_number: null,
      tool_succeeded: null,
      reason_codes: [],
      evidence_refs: [],
      summary: "Supplier availability changed.",
    },
    {
      id: "audit-specialist",
      kind: "SPECIALIST_CALLED",
      timestamp: at("08:10"),
      actor: "COORDINATOR",
      event_type: "SUPPLIER_AVAILABILITY_CHANGED",
      state_revision: "42",
      invocation_mode: "EVENT",
      plan_id: "plan-1",
      plan_version: 1,
      specialist: "PROCUREMENT",
      specialist_call_id: "task-1",
      call_sequence: 1,
      tool_call_id: null,
      tool_name: null,
      attempt_number: null,
      tool_succeeded: null,
      reason_codes: [],
      evidence_refs: [],
      summary: "Called PROCUREMENT specialist.",
    },
    {
      id: "audit-tool",
      kind: "TOOL_RESULT_RECORDED",
      timestamp: at("08:20"),
      actor: "PROCUREMENT",
      event_type: null,
      state_revision: "42",
      invocation_mode: null,
      plan_id: "plan-1",
      plan_version: 1,
      specialist: "PROCUREMENT",
      specialist_call_id: "task-1",
      call_sequence: 1,
      tool_call_id: "tool-1",
      tool_name: "check_supplier_feasibility",
      attempt_number: 1,
      tool_succeeded: true,
      reason_codes: [],
      evidence_refs: [],
      summary: "Supplier evidence returned.",
    },
    {
      id: "audit-validation",
      kind: "VALIDATION_COMPLETED",
      timestamp: at("08:25"),
      actor: "BACKEND",
      event_type: null,
      state_revision: "42",
      invocation_mode: null,
      plan_id: "plan-1",
      plan_version: 1,
      specialist: null,
      specialist_call_id: null,
      call_sequence: null,
      tool_call_id: null,
      tool_name: null,
      attempt_number: null,
      tool_succeeded: true,
      reason_codes: [],
      evidence_refs: [],
      summary: "Candidate is feasible.",
    },
    {
      id: "audit-complete",
      kind: "RUN_COMPLETED",
      timestamp: at("09:00"),
      actor: "COORDINATOR",
      event_type: null,
      state_revision: "42",
      invocation_mode: "EVENT",
      plan_id: "plan-1",
      plan_version: 1,
      specialist: null,
      specialist_call_id: null,
      call_sequence: null,
      tool_call_id: null,
      tool_name: null,
      attempt_number: null,
      tool_succeeded: null,
      reason_codes: [],
      evidence_refs: [],
      summary: "A validated plan is ready for manager approval.",
    },
  ],
  routing: {
    invocation_mode: "EVENT",
    trigger_type: "SUPPLIER_AVAILABILITY_CHANGED",
    specialists: ["PROCUREMENT"],
    specialist_calls: 1,
    tool_calls: ["check_supplier_feasibility"],
    tool_call_count: 1,
    retries: 0,
  },
  validation: [
    {
      id: "audit-validation",
      timestamp: at("08:25"),
      state_revision: "42",
      succeeded: true,
      evidence_refs: [],
      summary: "Candidate is feasible.",
    },
  ],
  decision: {
    outcome: "REQUEST_HUMAN_APPROVAL",
    reason_codes: [],
    summary: "A validated plan is ready for manager approval.",
  },
  evaluation: null,
  gaps: [
    {
      code: "EVALUATION_NOT_PERSISTED",
      message: "Local evaluation results are not persisted with this run.",
    },
  ],
};
let savedResult = null;
async function main() {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({
    reducedMotion: "reduce",
    viewport: { width: 1440, height: 1000 },
  });
  page.setDefaultTimeout(5000);
  page.setDefaultNavigationTimeout(5000);
  const errors = [],
    paths = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("http://localhost:8000/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    paths.push(path);
    assert.equal(route.request().headers().authorization, undefined);
    assert.equal(route.request().method(), "GET");
    let body = [];
    let status = 200;
    if (path === "/auth/me") body = { role: "manager", username: "manager" };
    if (path === "/ingredients")
      body = [{ id: "chicken", name: "Chicken", unit: "kg" }];
    if (path === "/menu-items") body = [{ id: "dish", name: "Chicken rice" }];
    if (path === "/recipes")
      body = [
        { menu_item_id: "dish", ingredient_id: "chicken", quantity: "0.125" },
      ];
    if (path === "/events")
      body = reports.map((batch) => ({
        id: batch.id,
        type: "SALES_UPDATED",
        timestamp: batch.period_end,
        source: "simulator",
        payload: { batch },
      }));
    if (path === "/events")
      body.push({
        id: "correction-1",
        type: "INVENTORY_ADJUSTED",
        timestamp: at("09:00"),
        source: "manager",
        payload: {
          day: "2026-02-16",
          effective_at: at("08:00"),
          revision_id: "count-2",
          replaces_revision_id: "count-1",
          adjustments: [
            {
              ingredient_id: "chicken",
              lot_id: "lot-1",
              unit: "kg",
              previous_quantity: "12.000",
              corrected_quantity: "9.000",
              delta: "-3.000",
            },
          ],
        },
      });
    if (path === "/manager/events/correction-1/assessments")
      body = [{ run_id: "run-1" }];
    if (path === "/events")
      body.push({
        id: "delay-1",
        type: "DELIVERY_DELAYED",
        timestamp: at("09:00"),
        source: "manager",
        payload: {
          effective_at: at("08:30"),
          delivery: {
            id: "delivery-fixed",
            expected_at: at("13:00"),
            expected_quantity: "10.000",
            outstanding_quantity: "5.000",
            cancelled_quantity: "3.000",
          },
        },
      });
    if (path === "/manager/events/delay-1/assessments")
      body = [{ run_id: "run-delay" }];
    if (path === "/manager/runs/run-1/procurement-evidence") body = evidence;
    if (path === "/inventory/estimated")
      body = [
        {
          id: "lot-1",
          ingredient_id: "chicken",
          quantity: "12.000",
          unit: "kg",
          status: "ACTIVE",
          coverage_complete: false,
          unallocated_consumption: "0",
        },
      ];
    if (path === "/manager/procurement-policies") body = [policy];
    if (path.startsWith("/manager/procurement-policies/")) body = evidence;
    if (path === "/runs")
      body = [
        {
          id: "run-1",
          status: "SUCCEEDED",
          trigger: "MANUAL",
          as_of: at("08:00"),
          created_at: at("08:00"),
          input_revision: 42,
          completed_at: at("09:00"),
          outcome: "REQUEST_HUMAN_APPROVAL",
          plan_version_id: "missing-version",
          snapshot: { known_at: at("08:00"), missing_offer_history: [] },
        },
      ];
    if (path === "/plan-history")
      body = [
        {
          id: "version-1",
          plan_id: "plan-1",
          version: 1,
          status: "PENDING_APPROVAL",
          calculation_mode: "ENGINE",
          lines: [],
          total_purchase_cost: "100.00",
          delivery_cost: "0",
          total_expected_cost: "100.00",
          expected_waste_cost: "0",
          expected_stockout_cost: "0",
          emergency_penalty: "0",
          forecast_id: "forecast-1",
          inventory_snapshot_id: "inventory-1",
          run_id: "run-1",
          created_at: at("08:30"),
        },
      ];
    if (path === "/manager/runs/run-1/evidence") body = managerEvidence;
    if (path === "/manager/runs/run-1/sales-materiality")
      body = {
        result_reference: null,
        completed_at: null,
        result: savedResult,
      };
    if (path === "/manager/runs/run-1/inventory-adjustment") body = null;
    if (path === "/runs/run-1")
      body = {
        id: "run-1",
        status: "SUCCEEDED",
        trigger: "MANUAL",
        as_of: at("08:00"),
        created_at: at("08:00"),
        input_revision: 42,
        outcome: "CALCULATION_INCOMPLETE",
        snapshot: { procurement_contract: { captured_state_revision: "42" } },
      };
    if (path === "/plans/missing-version") {
      status = 404;
      body = {
        error: {
          code: "NOT_FOUND",
          message: "Requested version is unavailable",
        },
      };
    }
    if (path === "/plans/older-version")
      body = {
        id: "older-version",
        plan_id: "historical-plan",
        version: 2,
        status: "SUPERSEDED",
        calculation_mode: "ENGINE",
        lines: [],
        total_purchase_cost: "0",
        delivery_cost: "0",
        total_expected_cost: "0",
        expected_waste_cost: "0",
        expected_stockout_cost: "0",
        emergency_penalty: "0",
        forecast_id: "forecast-old",
        inventory_snapshot_id: "stock-old",
        run_id: "run-old",
        created_at: at("08:00"),
      };
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  try {
    await page.goto(base + "/workspace/sales");
    await page.getByRole("cell", { name: "7", exact: true }).waitFor();
    assert.equal(
      await page.getByRole("cell", { name: "3", exact: true }).count(),
      0,
    );
    await page.getByRole("tab", { name: "Ingredient usage", exact: true }).click();
    await page.getByRole("cell", { name: "0.875 kg", exact: true }).waitFor();
    await page.getByRole("tab", { name: "Stock estimates", exact: true }).click();
    await page.getByText("Incomplete", { exact: true }).first().waitFor();
    await page.getByRole("tab", { name: "Reported sales", exact: true }).click();
    await page.getByLabel("Refresh every 10 seconds").uncheck();
    reports.push({
      ...first,
      id: "overlap",
      period_start: at("08:30"),
      period_end: at("09:30"),
    });
    await page.getByRole("button", { name: "Refresh now" }).click();
    await page.getByText(/Overlapping intervals detected/).waitFor();
    await page.getByRole("tab", { name: "Ingredient usage", exact: true }).click();
    assert.equal(
      await page.getByRole("cell", { name: "0.875 kg", exact: true }).count(),
      0,
    );
    await page.getByRole("cell", { name: "Unavailable kg", exact: true }).waitFor();
    await page.getByRole("tab", { name: "Reported sales", exact: true }).click();
    if (screenshotsEnabled) {
      await page.screenshot({
        path: "test-results/intraday-wide.png",
        fullPage: true,
      });
    }
    for (const width of [390, 768]) {
      await page.setViewportSize({ width, height: 900 });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
        `Sales overflow at ${width}`,
      );
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(base + "/workspace/recommendations");
    await page.getByText("Why this recommendation?", { exact: true }).click();
    await page.getByText("Calculation references", { exact: true }).click();
    await page.getByText("Assessment summary", { exact: true }).waitFor();
    await page.getByText("Plan & approval details", { exact: true }).click();
    await page.getByText(/1 stale attempt/).waitFor();
    await page.getByRole("tab", { name: "Policy", exact: true }).click();
    await page.getByText("S$100.00", { exact: true }).waitFor();
    await page.getByText("fresh · chicken · offer-1", { exact: true }).click();
    await page.getByText("4.50", { exact: true }).waitFor();
    await page.getByText(/opportunity-1 · NORMAL/).waitFor();
    if (screenshotsEnabled) {
      await page.screenshot({
        path: "test-results/policy-wide.png",
        fullPage: true,
      });
    }
    for (const width of [390, 768]) {
      await page.setViewportSize({ width, height: 900 });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
        `Policy overflow at ${width}`,
      );
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole("tab", { name: "Policy", exact: true }).click();
    await page
      .getByRole("heading", { name: "Forecast inputs—not forecast results" })
      .waitFor();
    await page.getByRole("cell", { name: "120", exact: true }).waitFor();
    for (const width of [390, 768]) {
      await page.setViewportSize({ width, height: 900 });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
        `Overflow at ${width}`,
      );
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(base + "/workspace/activity");
    await page
      .locator("summary")
      .filter({ hasText: "delivery delayed" })
      .click();
    assert.equal(
      await page
        .getByRole("link", { name: "Open assessment run-delay →", exact: true })
        .getAttribute("href"),
      "/workspace/activity/run-delay",
    );
    await page
      .getByText(/delivery delayed · recorded by manager · expected arrival/)
      .waitFor();
    await page
      .locator("summary")
      .filter({ hasText: "inventory adjusted" })
      .click();
    await page.getByRole("cell", { name: "-3.000 kg", exact: true }).waitFor();
    await page
      .getByRole("link", { name: "Open assessment run-1 →", exact: true })
      .click();
    await page
      .getByText("Captured inputs and procurement evidence", { exact: true })
      .click();
    await page
      .getByRole("heading", { name: "Purchases already accounted for" })
      .waitFor();
    await page.getByRole("cell", { name: "5.000", exact: true }).waitFor();
    await page
      .getByText(
        "Closing totals are compared with intraday reports for reconciliation; the two are never added together.",
        { exact: true },
      )
      .waitFor();
    await page.getByText("Purchase evidence", { exact: true }).click();
    await page
      .getByText("Expiry source: frozen-offer-expiry", { exact: true })
      .waitFor();
    await page.goto(base + "/workspace/activity");
    await page.getByRole("tab", { name: "Assessments", exact: true }).click();
    await page.locator(".record-details").first().locator("summary").first().click();
    await page
      .getByText("Captured inputs and procurement evidence", { exact: true })
      .click();
    await page.getByText("42", { exact: true }).waitFor();
    await page.getByText("Plan & approval details", { exact: true }).click();
    await page.getByText(/Pending approval for version 1/).waitFor();
    await page
      .locator("summary")
      .filter({ hasText: "Coordinator routing" })
      .click();
    await page.getByText("procurement", { exact: true }).waitFor();
    await page
      .getByText("check supplier feasibility", { exact: true })
      .waitFor();
    await page
      .locator("summary")
      .filter({ hasText: /^Validation/ })
      .click();
    await page
      .getByText("Candidate is feasible.", { exact: true })
      .first()
      .waitFor();
    await page.getByText("Evidence gaps (1)", { exact: true }).click();
    await page
      .getByText("Local evaluation results are not persisted with this run.", {
        exact: true,
      })
      .waitFor();
    await page.getByRole("link", { name: "View recommendation" }).click();
    await page
      .getByText("Requested version is unavailable", { exact: true })
      .waitFor();
    assert(paths.includes("/plans/missing-version"));
    await page.goto(base + "/workspace/recommendations?version=older-version");
    await page.getByRole("combobox", { name: "Plan history" }).waitFor();
    assert.equal(
      await page.getByRole("combobox", { name: "Plan history" }).inputValue(),
      "older-version",
    );
    assert(paths.includes("/plans/older-version"));
    await page.goto(base + "/workspace/activity/run-1");
    await page
      .getByRole("heading", { name: "Review this assessment." })
      .waitFor();
    await page.getByText("CALCULATION_INCOMPLETE", { exact: true }).waitFor();
    await page
      .getByText("Sales and stock-correction assessments", { exact: true })
      .click();
    await page
      .getByText("Calculation requested; result has not been recorded.", {
        exact: true,
      })
      .waitFor();
    await page
      .getByText("No assessment recorded for this run.", { exact: true })
      .waitFor();
    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
        `Assessment overflow at ${width}`,
      );
    }
    await page.screenshot({
      path: "test-results/assessment-wide.png",
      fullPage: true,
    });
    savedResult = {
      complete: false,
      material_change: null,
      inventory_feasible: null,
      as_of: at("09:00"),
      known_at: at("09:00"),
      captured_state_revision: "42",
      findings: [{ code: "MISSING_SALES_INTERVAL", source: "batch-gap" }],
      required_follow_up: ["SUBMIT_MISSING_INTERVAL"],
      evidence_refs: ["snapshot-42"],
      sales: [
        {
          dish_id: "dish",
          expected: "10",
          observed: null,
          deviation: null,
          threshold: "0.2",
          adequate_exposure: null,
          material: null,
        },
      ],
      missing_intervals: [[at("08:30"), at("09:00")]],
      limitations: [],
    };
    await page.reload();
    await page
      .getByText("Sales and stock-correction assessments", { exact: true })
      .click();
    await page
      .getByText(
        "Assessment incomplete. The effect on the plan remains unresolved.",
        { exact: true },
      )
      .waitFor();
    await page.getByText("submit missing interval", { exact: true }).waitFor();
    await page
      .getByRole("cell", { name: "Unknown", exact: true })
      .first()
      .waitFor();
    assert.equal(
      await page
        .getByText(/completed assessment found no material change/)
        .count(),
      0,
    );
    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
        `Populated assessment overflow at ${width}`,
      );
    }
    await page.screenshot({
      path: "test-results/assessment-populated.png",
      fullPage: true,
    });
    savedResult = {
      ...savedResult,
      complete: true,
      material_change: false,
      inventory_feasible: true,
      findings: [],
      missing_intervals: [],
      required_follow_up: [],
    };
    await page.reload();
    await page
      .getByText("Sales and stock-correction assessments", { exact: true })
      .click();
    await page
      .getByText(
        "The completed assessment found no material change within its assessed scope.",
        { exact: true },
      )
      .waitFor();
    assert.deepEqual(errors, []);
    console.log(
      "PASS: correction-aware totals, exact usage, overlap suppression, estimates, policy/domain/history display, mobile overflow, run evidence, exact-version failure, no agent token or writes.",
    );
  } finally {
    await browser.close();
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
