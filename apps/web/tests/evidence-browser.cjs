const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const assert = require("node:assert/strict");
const base = process.env.UI_TEST_URL || "http://localhost:3012";
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
async function main() {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({
    reducedMotion: "reduce",
    viewport: { width: 1440, height: 1000 },
  });
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
    await page.getByRole("cell", { name: "0.875 kg", exact: true }).waitFor();
    await page.getByRole("cell", { name: "7", exact: true }).waitFor();
    assert.equal(
      await page.getByRole("cell", { name: "3", exact: true }).count(),
      0,
    );
    await page.getByText("Incomplete", { exact: true }).first().waitFor();
    await page.getByLabel("Refresh every 10 seconds").uncheck();
    reports.push({
      ...first,
      id: "overlap",
      period_start: at("08:30"),
      period_end: at("09:30"),
    });
    await page.getByRole("button", { name: "Refresh now" }).click();
    await page.getByText(/Overlapping intervals detected/).waitFor();
    assert.equal(
      await page.getByRole("cell", { name: "0.875 kg", exact: true }).count(),
      0,
    );
    await page.screenshot({
      path: "test-results/intraday-wide.png",
      fullPage: true,
    });
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
    await page.getByRole("tab", { name: "Policy", exact: true }).click();
    await page.getByText("S$100.00", { exact: true }).waitFor();
    await page.getByText("fresh · chicken · offer-1", { exact: true }).click();
    await page.getByText("4.50", { exact: true }).waitFor();
    await page.getByText(/opportunity-1 · NORMAL/).waitFor();
    await page.screenshot({
      path: "test-results/policy-wide.png",
      fullPage: true,
    });
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
    await page.getByRole("tab", { name: "Forecast", exact: true }).click();
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
    await page.getByRole("tab", { name: "Assessments", exact: true }).click();
    await page.locator("details").first().locator("summary").first().click();
    await page.getByText("42", { exact: true }).waitFor();
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
