/* Browser contract tests use intercepted API responses, never a live database.
 * Run against the local production server: node tests/browser-smoke.cjs
 * PLAYWRIGHT_MODULE may point at a separately installed playwright-core package.
 */
const { chromium } = require(
  process.env.PLAYWRIGHT_MODULE ||
    "../../../node_modules/.pnpm/playwright-core@1.62.1/node_modules/playwright-core",
);
const assert = require("node:assert/strict");
const fs = require("node:fs");
const base = process.env.UI_TEST_URL || "http://localhost:3000";
const now = "2026-02-16T08:00:00+08:00";
const ingredient = {
  id: "chicken",
  name: "Chicken",
  unit: "kg",
  interval_days: 7,
  starting_date: "2026-02-16",
};
const lot = {
  id: "chicken-01",
  ingredient_id: "chicken",
  unit: "kg",
  quantity: "12.000",
  initial_quantity: "20.000",
  received_at: "2026-02-15T08:00:00+08:00",
  counted_at: now,
  expiry_date: "2026-02-18",
  provenance: "PHYSICAL",
};
const line = {
  id: "line-1",
  plan_version_id: "version-1",
  ingredient_id: "chicken",
  supplier_id: "fresh",
  quantity: "3.000",
  unit_price: "4.50",
  arrival_at: now,
  linked_quantity: "0.000",
  uncommitted_quantity: "3.000",
};
const plan = {
  id: "version-1",
  plan_id: "plan-1",
  version: 1,
  status: "PENDING_APPROVAL",
  calculation_mode: "DEVELOPMENT_FIXTURE",
  lines: [line],
  total_purchase_cost: "13.50",
  delivery_cost: "5.00",
  expected_waste_cost: "0.00",
  expected_stockout_cost: "0.00",
  emergency_penalty: "0.00",
  total_expected_cost: "18.50",
  forecast_id: "forecast-1",
  inventory_snapshot_id: "stock-1",
  run_id: "run-1",
  created_at: now,
};
const delivery = {
  id: "delivery-1",
  supplier_id: "fresh",
  ingredient_id: "chicken",
  kind: "NORMAL",
  expected_quantity: "5.000",
  received_quantity: "0.000",
  cancelled_quantity: "0.000",
  outstanding_quantity: "5.000",
  expected_at: now,
  ordered_at: now,
  source_plan_line_id: null,
  source_validation: "MANUAL",
  receipts: [],
};
const offer = {
  id: "offer-1",
  supplier_id: "fresh",
  ingredient_id: "chicken",
  unit_price: "4.50",
  available_quantity: "30.000",
  moq: "1.000",
  pack_size: "1.000",
  lead_time_minutes: 60,
  order_cutoff: { kind: "NONE" },
  feasible_delivery_at: [now],
  current_status: "AVAILABLE",
  recent_on_time_rate: "0.95",
  shelf_life_days_on_arrival: 3,
  delivery_fee_sgd: "5.00",
  emergency_fee_sgd: "12.00",
  observed_at: now,
};
async function main() {
  fs.mkdirSync("test-results", { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let authenticated = false,
    stale = false,
    offline = false,
    expire = false;
  let history = { draft: null, revisions: [] };
  const writes = [];
  await page.route("http://localhost:8000/api/v1/**", async (route) => {
    const req = route.request(),
      url = new URL(req.url()),
      p = url.pathname.replace("/api/v1", "");
    const reply = (body, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (offline) return route.abort("failed");
    if (p === "/auth/login") {
      const body = req.postDataJSON();
      if (body.password !== "test-password")
        return reply(
          {
            error: { code: "UNAUTHENTICATED", message: "Invalid credentials" },
          },
          401,
        );
      authenticated = true;
      return reply({ role: "manager", username: "manager" });
    }
    if (!authenticated || expire)
      return reply(
        { error: { code: "UNAUTHENTICATED", message: "Session expired" } },
        401,
      );
    if (p === "/auth/me")
      return reply({ role: "manager", username: "manager" });
    if (p === "/auth/logout") {
      authenticated = false;
      return route.fulfill({ status: 204 });
    }
    if (req.method() !== "GET") {
      const body = req.postData() ? req.postDataJSON() : null;
      writes.push({ p, body });
      if (p.endsWith("/decision") && p.startsWith("/plans/")) {
        if (stale)
          return reply(
            {
              error: {
                code: "STALE_PLAN",
                message: "New facts require reassessment.",
              },
            },
            409,
          );
        plan.status = body.decision;
        return reply(plan);
      }
      if (p.endsWith("/draft")) {
        assert.deepEqual(Object.keys(body).sort(), [
          "counts",
          "cutoff",
          "sales",
        ]);
        history.draft = body;
        return reply(body);
      }
      if (p.endsWith("/submit")) {
        assert.equal(body, null, "submit endpoint must not receive a body");
        const revision = {
          ...history.draft,
          id: "revision-1",
          day: "2026-02-16",
          revision: 1,
          recorded_at: now,
          actor: "manager",
          reconciliation: null,
        };
        history.revisions.push(revision);
        history.draft = null;
        return reply(revision);
      }
      if (p.endsWith("/receive")) {
        assert.equal(body.quantity, "2");
        delivery.received_quantity = "2.000";
        delivery.outstanding_quantity = "3.000";
        return reply(delivery);
      }
      return reply({ id: "created", status: "QUEUED", ...body });
    }
    if (p === "/ingredients") return reply([ingredient]);
    if (p === "/inventory") return reply([lot]);
    if (p === "/inventory/estimated")
      return reply([
        {
          ...lot,
          provenance: "ESTIMATED",
          quantity: "10.000",
          as_of: now,
          coverage_complete: false,
          status: "ACTIVE",
          unallocated_consumption: "0.000",
        },
      ]);
    if (p === "/menu-items")
      return reply([{ id: "chicken-rice", name: "Chicken rice" }]);
    if (p === "/recipes")
      return reply([
        {
          menu_item_id: "chicken-rice",
          ingredient_id: "chicken",
          quantity: "0.200",
        },
      ]);
    if (p === "/suppliers") return reply([{ id: "fresh", name: "Fresh" }]);
    if (p === "/supplier-offers") return reply([offer]);
    if (p === "/plan-history") return reply([plan]);
    if (p === "/plans/version-1") return reply(plan);
    if (p.endsWith("/lines")) return reply([line]);
    if (p === "/runs")
      return reply([
        {
          id: "failed-1",
          status: "FAILED",
          trigger: "MANUAL_REASSESSMENT_REQUESTED",
          as_of: now,
          created_at: now,
          outcome: null,
          escalation_reason: null,
          failure_reason: "TOOL_FAILURE",
          plan_version_id: null,
        },
      ]);
    if (p === "/deliveries") return reply([delivery]);
    if (p.startsWith("/daily-updates/")) return reply(history);
    if (p === "/holidays")
      return reply([
        {
          date: "2026-02-17",
          name: "Chinese New Year",
          source_url: "https://www.mom.gov.sg/",
        },
      ]);
    return reply([]);
  });
  try {
    await page.goto(base);
    await page.getByRole("heading", { name: /Good service starts/ }).waitFor();
    await page.setViewportSize({ width: 1920, height: 1080 });
    const heroBounds = await page.locator(".landing-hero").boundingBox();
    assert(heroBounds.width >= 1918, "Homepage should use the full wide-screen width");
    await page.screenshot({path: "test-results/home-wide.png", fullPage: true});
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.screenshot({
      path: "test-results/home-desktop.png",
      fullPage: true,
    });
    await page.goto(base + "/workspace/inventory");
    await page.waitForURL("**/login?**");
    await page.getByLabel("Username").fill("manager");
    await page.getByLabel("Password", { exact: true }).fill("wrong");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.getByText("Invalid credentials", { exact: true }).waitFor();
    await page.getByLabel("Password", { exact: true }).fill("test-password");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.waitForURL("**/workspace/inventory");
    await page.getByText("chicken-01", { exact: true }).waitFor();
    await page.setViewportSize({ width: 1920, height: 1080 });
    const contentBounds = await page.locator(".workspace-content").boundingBox();
    assert(contentBounds.width >= 1678, "Workspace should use all space beside the sidebar");
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole("tab", { name: "Estimates", exact: true }).click();
    await page.getByText("incomplete", { exact: true }).waitFor();
    for (const route of [
      "overview",
      "inventory",
      "daily",
      "recommendations",
      "deliveries",
      "suppliers",
      "activity",
    ]) {
      await page.goto(base + "/workspace/" + route);
      await page.locator("#workspace-main h1").waitFor();
      await page.screenshot({
        path: `test-results/${route}-desktop.png`,
        fullPage: true,
      });
    }
    await page.goto(base + "/workspace/daily");
    await page.getByLabel("Closing quantity for chicken-01").fill("7");
    await page.getByLabel("Final sales for Chicken rice").fill("1.5");
    assert(
      await page
        .getByRole("button", { name: "Review submission" })
        .isDisabled(),
      "fractional sales cannot be submitted",
    );
    await page.getByLabel("Final sales for Chicken rice").fill("20");
    await page.getByRole("button", { name: "Review submission" }).click();
    await page.getByRole("button", { name: "Confirm submission" }).click();
    await page.getByText(/Closing update submitted/).waitFor();
    assert.equal(
      writes.find((w) => w.p.endsWith("/draft")).body.counts["chicken-01"],
      "7",
    );
    await page.goto(base + "/workspace/daily");
    await page.getByLabel("Closing quantity for chicken-01").fill("6");
    await page.getByRole("button", { name: "Save draft", exact: true }).click();
    await page.getByText(/Draft saved/).waitFor();
    assert.equal(
      writes.filter((w) => w.p.endsWith("/draft")).at(-1).body.counts[
        "chicken-01"
      ],
      "6",
    );
    await page.goto(base + "/workspace/recommendations");
    stale = true;
    await page.getByRole("button", { name: "Approve version 1" }).click();
    await page.getByRole("button", { name: "Confirm decision" }).click();
    await page.getByText("New facts require reassessment.").waitFor();
    assert.equal(
      writes.find((w) => w.p.includes("/plans/") && w.p.endsWith("/decision"))
        .body.plan_version,
      1,
    );
    assert(
      !writes.some((w) => w.p === "/deliveries"),
      "approval must not create a purchase",
    );
    await page.goto(base + "/workspace/deliveries");
    await page.getByRole("button", { name: "Receive", exact: true }).click();
    await page.getByLabel("Quantity received").fill("2");
    await page.getByLabel("Actual expiry date").fill("2026-02-19");
    await page.getByRole("button", { name: "Confirm receipt" }).click();
    await page.getByText("Receipt recorded and inventory updated.").waitFor();
    assert.equal(
      writes.find((w) => w.p.endsWith("/receive")).body.remainder,
      "EXPECTED",
    );
    await page.goto(base + "/workspace/activity");
    await page.getByRole("tab", { name: "Assessments", exact: true }).click();
    await page.locator(".record-details summary").first().click();
    await page
      .getByRole("button", { name: "Retry assessment", exact: true })
      .click();
    await page.getByText(/Assessment created is queued/).waitFor();
    assert.equal(writes.find((w) => w.p.endsWith("/retry")).body.as_of, now);
    await page.goto(base + "/workspace/daily");
    await page.getByRole("tab", { name: "Sales intervals" }).click();
    await page.getByLabel("Batch identity").fill("batch-test");
    await page.getByLabel("Interval end (Singapore)").fill("2026-02-16T08:00");
    await page.getByRole("button", { name: "Submit complete report" }).click();
    await page
      .getByText("The interval end must be later than its start.")
      .waitFor();
    await page.getByLabel("Interval end (Singapore)").fill("2026-02-16T08:30");
    await page.getByRole("button", { name: "Submit complete report" }).click();
    await page.getByText(/Batch batch-test/).waitFor();
    assert.deepEqual(
      writes.find((w) => w.p === "/sales-batches").body.sales,
      {},
    );
    await page.goto(base + "/workspace/suppliers");
    await page.getByRole("button", { name: "Update", exact: true }).click();
    await page.getByLabel("Unit price (SGD)").fill("5.50");
    await page.getByRole("button", { name: "Save supplier change" }).click();
    await page.getByText(/Change recorded/).waitFor();
    assert.equal(
      writes.find((w) => w.p === "/supplier-offers/offer-1").body.unit_price,
      "5.50",
    );
    await page.getByRole("tab", { name: "Promotions", exact: true }).click();
    await page.getByRole("button", { name: "Add promotion" }).click();
    await page.getByLabel("Promotion identifier").fill("promo-test");
    await page.getByLabel("Name", { exact: true }).fill("Lunch special");
    await page.getByLabel("Declared demand multiplier").fill("1.2");
    await page.getByRole("button", { name: "Save promotion revision" }).click();
    await page.getByText(/Choose at least one dish/).waitFor();
    await page.getByRole("checkbox", { name: "Chicken rice" }).check();
    await page.getByRole("button", { name: "Save promotion revision" }).click();
    await page.getByText(/Change recorded/).waitFor();
    assert.deepEqual(
      writes.find((w) => w.p === "/promotions/promo-test").body.menu_item_ids,
      ["chicken-rice"],
    );
    await page.goto(base + "/workspace/deliveries?plan=version-1&line=line-1");
    await page
      .getByRole("button", {
        name: "Record an unlinked manual purchase instead",
      })
      .click();
    await page
      .getByRole("heading", { name: "Record a manual purchase" })
      .waitFor();
    await page.locator('select[name="supplier"]').selectOption("fresh");
    await page.locator('select[name="ingredient"]').selectOption("chicken");
    await page.getByLabel("Quantity", { exact: true }).fill("4");
    await page
      .locator("form")
      .getByRole("button", { name: "Record actual purchase", exact: true })
      .click();
    await page.getByText(/Actual purchase recorded/).waitFor();
    assert.equal(
      writes.find((w) => w.p === "/deliveries").body.source_plan_line_id,
      null,
    );
    await page.setViewportSize({ width: 390, height: 844 });
    for (const route of [
      "",
      "login",
      "workspace/overview",
      "workspace/deliveries",
      "workspace/inventory",
      "workspace/daily",
      "workspace/recommendations",
      "workspace/suppliers",
      "workspace/activity",
    ]) {
      await page.goto(base + "/" + route);
      await page.locator("h1:visible,h2:visible").first().waitFor();
      await page.screenshot({
        path: `test-results/${route.replaceAll("/", "-") || "home"}-mobile.png`,
        fullPage: true,
      });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth + 1,
        ),
        `page overflow on ${route}`,
      );
    }
    await page.setViewportSize({ width: 820, height: 1180 });
    for (const route of [
      "overview",
      "inventory",
      "daily",
      "recommendations",
      "deliveries",
      "suppliers",
      "activity",
    ]) {
      await page.goto(base + "/workspace/" + route);
      await page.locator("#workspace-main h1").waitFor();
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
        `tablet overflow on ${route}`,
      );
    }
    await page.screenshot({
      path: "test-results/activity-tablet.png",
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + "/workspace/overview");
    await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page.getByRole("link", { name: "Stock & sales", exact: true }).click();
    await page.waitForURL("**/workspace/inventory");
    expire = true;
    await page.goto(base + "/workspace/activity");
    await page.waitForURL("**/login?**");
    expire = false;
    offline = true;
    await page.goto(base + "/login");
    await page.getByLabel("Username").fill("manager");
    await page.getByLabel("Password", { exact: true }).fill("test-password");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.getByText(/Cannot reach ReStock/).waitFor();
    assert.deepEqual(errors, []);
    console.log(
      "PASS: routes, login/return, invalid credentials, daily draft/submit/correction, stale approval, partial receipt, retry, sales interval validation, supplier update, promotion validation, unlinked purchase, mobile/tablet overflow, navigation, expired session and API outage.",
    );
  } catch (error) {
    await page.screenshot({ path: "test-results/failure.png", fullPage: true });
    console.error(await page.locator("body").innerText());
    throw error;
  } finally {
    await browser.close();
  }
}
main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
