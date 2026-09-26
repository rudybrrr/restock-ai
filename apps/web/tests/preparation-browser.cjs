const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const assert = require("node:assert/strict");
const fs = require("node:fs");
(async () => {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    fs.mkdirSync("test-results", { recursive: true });
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", e => errors.push(e.message));
    await page.route("http://localhost:8000/api/v1/**", async route => {
      assert.equal(route.request().method(), "GET");
      assert.equal(new URL(route.request().url()).pathname, "/api/v1/auth/me", "Preparation must not guess feature endpoints");
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ role: "manager", username: "manager" }) });
    });
    await page.goto((process.env.UI_TEST_URL || "http://localhost:3025") + "/workspace/preparation");
    await page.getByRole("heading", { name: "Pending feature views", exact: true }).waitFor();
    for (const tab of ["Forecast results", "Stock projections", "Waste entry", "Economic results"]) {
      await page.getByRole("tab", { name: tab, exact: true }).click();
      if (tab === "Waste entry") {
        const submit = page.getByRole("button", { name: "Waste recording not connected", exact: true });
        assert(await submit.isDisabled());
        await page.getByLabel("Observed waste quantity", { exact: true }).fill("2.000");
        await page.getByRole("button", { name: "Clear draft", exact: true }).click();
        assert.equal(await page.getByLabel("Observed waste quantity", { exact: true }).inputValue(), "");
      } else await page.getByRole("heading", { name: "Waiting for an agreed manager data source.", exact: true }).waitFor();
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: 900 });
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
        await page.screenshot({ path: `test-results/preparation-${tab.replaceAll(" ", "-")}-${width}.png`, fullPage: true });
      }
    }
    assert.deepEqual(errors, []);
    console.log("PASS: four disconnected preparation views, disabled waste submission, draft reset, no guessed API or writes, desktop/mobile.");
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
