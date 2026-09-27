// Isolated API fixtures. The tour must never mutate operational data.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const assert = require("node:assert/strict");
const fs = require("node:fs");
const base = process.env.UI_TEST_URL || "http://localhost:3025";
const key = "restock:workspace-tour:v1:manager";
const routes = ["overview", "inventory", "sales", "calculations", "daily", "recommendations", "deliveries", "deliveries", "activity", "suppliers", "suppliers", "inventory?view=menu", "inventory?view=schedules"];
(async () => {
  fs.mkdirSync("test-results", { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    for (const width of [1440, 390, 320]) {
      const context = await browser.newContext({ viewport: { width, height: width === 320 ? 640 : 900 }, reducedMotion: "reduce" });
      const page = await context.newPage();
      const errors = [], writes = [];
      let authenticated = false, username = "manager";
      page.on("pageerror", e => errors.push(e.message));
      await page.route("http://localhost:8000/api/v1/**", async route => {
        const req = route.request(), path = new URL(req.url()).pathname.replace("/api/v1", "");
        let body = [], status = 200;
        if (req.method() !== "GET" && req.method() !== "OPTIONS") {
          writes.push(path);
          assert.equal(path, "/auth/login", "Tour must not submit operational data");
          authenticated = true;
        }
        if (path === "/auth/me" || path === "/auth/login") {
          body = authenticated ? { role: "manager", username } : { error: { code: "UNAUTHENTICATED", message: "Sign in" } };
          if (!authenticated) status = 401;
        } else if (path.startsWith("/daily-updates/")) body = { draft: null, revisions: [] };
        else if (path === "/sales/usage") body = { complete: false, dishes: [], ingredient_usage: [], reports: [], gaps: [], overlaps: [] };
        await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
      });
      await page.goto(base + "/login?next=%2Fworkspace%2Fsales");
      await page.getByLabel("Username", { exact: true }).fill("manager");
      await page.getByLabel("Password", { exact: true }).fill("fixture-only");
      await page.getByRole("button", { name: "Sign in", exact: true }).click();
      const dialog = page.getByRole("dialog", { name: "A quick tour of your workspace" });
      await dialog.waitFor();
      assert.equal(new URL(page.url()).pathname, "/workspace/sales", "Welcome must preserve login destination");
      await dialog.getByRole("button", { name: "Skip tour" }).click();
      assert.equal(await page.evaluate(k => localStorage.getItem(k), key), "seen");
      await page.reload();
      await page.getByRole("button", { name: "Workspace tour" }).waitFor();
      assert.equal(await page.locator("dialog[open]").count(), 0, "Skipped tour must not reopen");
      await page.getByRole("button", { name: "Workspace tour" }).click();
      await page.getByRole("button", { name: "Start tour" }).click();
      for (let i = 0; i < routes.length; i++) {
        await page.waitForURL(base + "/workspace/" + routes[i]);
        const card = page.locator(".tour-card");
        await card.locator(".tour-top").getByText(new RegExp(`^${i + 1} / 13`)).waitFor();
        await page.locator(".tour-spotlight").waitFor();
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `No overflow at ${width}, step ${i}`);
        assert(await card.evaluate(el => { const r = el.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth + 1 && r.top >= 0 && r.bottom <= innerHeight + 1; }), "Tour card must fit viewport");
        assert(await card.locator(".tour-actions").evaluate(el => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }), "Next/Back must remain visible without scrolling");
        if (width < 600) assert(await page.evaluate(() => document.querySelector(".tour-card").getBoundingClientRect().top >= document.querySelector(".tour-spotlight").getBoundingClientRect().bottom), "Mobile card must not hide spotlight");
        assert(await page.evaluate(() => document.activeElement.closest(".workspace-tour") !== null), "Focus stays inside modal");
        if ([0, 3, 5, 12].includes(i)) await page.screenshot({ path: `test-results/tour-${width}-${i + 1}.png`, animations: "disabled" });
        if (i === 1) {
          await page.getByRole("button", { name: "Back", exact: true }).click();
          await page.waitForURL(base + "/workspace/overview");
          await page.getByRole("button", { name: "Next", exact: true }).click();
          await page.waitForURL(base + "/workspace/inventory");
        }
        await page.getByRole("button", { name: i === 12 ? "Finish tour" : "Next", exact: true }).click();
      }
      await page.waitForURL(base + "/workspace/sales");
      assert.equal(await page.locator("dialog[open]").count(), 0);
      await page.reload();
      await page.getByRole("button", { name: "Workspace tour" }).waitFor();
      assert.equal(await page.locator("dialog[open]").count(), 0, "Finished tour must stay dismissed");
      await page.getByRole("button", { name: "Workspace tour" }).click();
      await page.keyboard.press("Escape");
      assert.equal(await page.locator("dialog[open]").count(), 0);
      // A different manager on the same browser gets their own first-use tour.
      username = "another-manager";
      await page.reload();
      await page.getByRole("dialog", { name: "A quick tour of your workspace" }).waitFor();
      await page.keyboard.press("Tab");
      assert(await page.evaluate(() => !!document.activeElement.closest("dialog")));
      await page.getByRole("button", { name: "Skip tour" }).click();
      assert.deepEqual(writes, ["/auth/login"]);
      assert.deepEqual(errors, []);
      await context.close();
    }
    console.log("PASS first-login welcome, skip/completion persistence per manager, replay, all 13 read-only steps, Back, Escape, focus and responsive spotlight (1440/390/320)");
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
