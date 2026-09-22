const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const assert = require("node:assert/strict");
const base = process.env.UI_TEST_URL || "http://localhost:3014";
const at = "2026-02-16T09:00:00+08:00";
(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const page = await browser.newPage({ reducedMotion: "reduce" });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    let status = "QUEUED",
      failRetry = true,
      writes = 0;
    const plan = {
      id: "version-1",
      plan_id: "plan-1",
      version: 1,
      status: "PENDING_APPROVAL",
      calculation_mode: "ENGINE",
      lines: [],
      total_purchase_cost: "0",
      delivery_cost: "0",
      total_expected_cost: "0",
      expected_waste_cost: "0",
      expected_stockout_cost: "0",
      emergency_penalty: "0",
      forecast_id: "forecast-1",
      inventory_snapshot_id: "inventory-1",
      run_id: "old",
      created_at: at,
    };
    let decisions = 0;
    await page.route("http://localhost:8000/api/v1/**", async (route) => {
      const path = new URL(route.request().url()).pathname.replace(
        "/api/v1",
        "",
      );
      let body = [],
        code = 200;
      assert.equal(route.request().headers().authorization, undefined);
      if (path === "/auth/me") body = { role: "manager", username: "manager" };
      if (path === "/plan-history") body = [plan];
      if (path === "/plans/version-1") body = plan;
      if (path === "/runs/old")
        body = {
          id: "old",
          status,
          trigger: "MANUAL",
          as_of: at,
          created_at: at,
          snapshot: {},
          outcome: null,
        };
      if (path === "/manager/runs/old/evidence")
        body = {
          run_id: "old",
          run_status: status,
          trigger: "MANUAL",
          active_plan: null,
          plan_history: [],
          approval: {
            required: false,
            status: "NONE",
            latest_attempt: null,
            stale_attempts: [],
          },
          decision: { outcome: null, summary: null, reason_codes: [] },
          routing: {
            specialists: [],
            specialist_calls: 0,
            tool_calls: [],
            tool_call_count: 0,
            retries: 0,
          },
          timeline: [],
          validation: [],
          gaps: [],
          evaluation: null,
        };
      if (
        path.endsWith("/sales-materiality") ||
        path.endsWith("/inventory-adjustment")
      )
        body = null;
      if (route.request().method() !== "GET") {
        if (path === "/plans/version-1/decision") {
          assert.deepEqual(route.request().postDataJSON(), {
            plan_id: "plan-1",
            plan_version: 1,
            decision: "REJECTED",
            instructions: "Use smaller packs",
          });
          decisions++;
          plan.status = "REJECTED";
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(plan),
          });
          return;
        }
        assert.equal(path, "/runs/old/retry");
        assert.equal(route.request().method(), "POST");
        assert.deepEqual(route.request().postDataJSON(), {
          as_of: "2026-02-16T10:30:00+08:00",
        });
        writes++;
        if (failRetry) {
          code = 409;
          body = {
            error: {
              code: "RUN_IN_PROGRESS",
              message: "Another assessment is active",
            },
          };
        } else body = { id: "new-run", status: "QUEUED" };
      }
      await route.fulfill({
        status: code,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    });
    for (const [state, label] of [
      ["QUEUED", "Waiting to be processed"],
      ["RUNNING", "Assessment in progress"],
      ["SUCCEEDED", "Assessment finished"],
      ["FAILED", "Assessment could not finish"],
    ]) {
      status = state;
      await page.goto(base + "/workspace/activity/old");
      await page.getByText(label, { exact: true }).waitFor();
      await page
        .getByRole("heading", { name: "Assessment summary", exact: true })
        .waitFor();
      assert.equal(
        await page
          .locator("details")
          .filter({
            has: page.locator("summary", {
              hasText: "Captured inputs and procurement evidence",
            }),
          })
          .getAttribute("open"),
        null,
      );
    }
    await page
      .getByLabel("Assess through (Singapore time)")
      .fill("2026-02-16T10:30");
    await page
      .getByRole("button", { name: "Confirm reassessment", exact: true })
      .click();
    await page
      .getByText("Another assessment is active", { exact: true })
      .waitFor();
    failRetry = false;
    await page
      .getByRole("button", { name: "Confirm reassessment", exact: true })
      .click();
    const link = page.getByRole("link", {
      name: "Open new assessment →",
      exact: true,
    });
    await link.waitFor();
    assert.equal(
      await link.getAttribute("href"),
      "/workspace/activity/new-run",
    );
    assert(
      await page
        .getByRole("button", { name: "Assessment requested", exact: true })
        .isDisabled(),
    );
    assert.equal(writes, 2);
    status = "SUCCEEDED";
    await page.goto(base + "/workspace/recommendations?version=version-1");
    await page
      .getByRole("button", { name: "Reject with instructions", exact: true })
      .click();
    assert.equal(decisions, 0);
    await page.getByLabel("Instructions (optional)").fill("Use smaller packs");
    await page
      .getByRole("button", { name: "Confirm decision", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "Request a new assessment", exact: true })
      .waitFor();
    assert.equal(decisions, 1);
    assert.equal(writes, 2);
    await page
      .getByLabel("Assess through (Singapore time)")
      .fill("2026-02-16T10:30");
    await page
      .getByRole("button", { name: "Confirm reassessment", exact: true })
      .click();
    await page
      .getByRole("link", { name: "Open new assessment →", exact: true })
      .waitFor();
    assert.equal(writes, 3);
    for (const staleStatus of ["INVALIDATED", "SUPERSEDED"]) {
      plan.status = staleStatus;
      await page.reload();
      await page
        .getByText(
          "This version is no longer actionable. Select the latest recommendation before making a decision.",
          { exact: true },
        )
        .waitFor();
      assert.equal(
        await page
          .getByRole("button", { name: "Approve version 1", exact: true })
          .count(),
        0,
      );
      assert.equal(
        await page
          .getByRole("button", { name: "Confirm reassessment", exact: true })
          .count(),
        0,
      );
    }
    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
      );
    }
    await page.screenshot({
      path: "test-results/assessment-flow.png",
      fullPage: true,
    });
    assert.deepEqual(errors, []);
    console.log(
      "PASS: four lifecycle states, collapsed evidence, explicit retry time, failure recovery, exact new-run link and duplicate prevention.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
