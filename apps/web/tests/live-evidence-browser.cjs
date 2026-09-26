// Opt-in live read check. Login/logout mutate only this test's session.
// Never records sales, purchases, assessments or policy changes.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const assert = require("node:assert/strict");
const base = process.env.UI_TEST_URL || "http://localhost:3002";
async function main() {
  assert(
    process.env.RESTOCK_TEST_PASSWORD,
    "Supply RESTOCK_TEST_PASSWORD securely",
  );
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage({ reducedMotion: "reduce" });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/") && request.method() !== "GET") {
      assert(
        ["/auth/login", "/auth/logout"].some((path) =>
          request.url().endsWith(path),
        ),
        "Unexpected live write",
      );
    }
  });
  try {
    await page.goto(base + "/login");
    await page
      .getByLabel("Username")
      .fill(process.env.RESTOCK_TEST_USERNAME || "manager");
    await page
      .getByLabel("Password", { exact: true })
      .fill(process.env.RESTOCK_TEST_PASSWORD);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.waitForURL("**/workspace/**");
    await page.goto(base + "/workspace/recommendations");
    await page.getByRole("tab", { name: "Policy", exact: true }).click();
    await page.getByText("S$100.000", { exact: true }).waitFor();
    await page.getByText(/24\/24 offers · 24\/24 opportunities/).waitFor();
    await page.getByRole("tab", { name: "Policy", exact: true }).click();
    await page.getByRole("cell", { name: "2026-01-19", exact: true }).waitFor();
    await page.getByRole("cell", { name: "2026-02-09", exact: true }).waitFor();
    await page.goto(base + "/workspace/sales");
    await page.getByRole("tab", { name: "Stock estimates", exact: true }).click();
    await page
      .getByRole("heading", { name: "Estimated-stock timeline", exact: true })
      .waitFor();
    await page
      .getByRole("cell", { name: "Chicken", exact: true })
      .first()
      .waitFor();
    assert.deepEqual(errors, []);
    console.log(
      "PASS: live manager login, canonical policy, 24-offer/opportunity domain, persisted history and inventory read; no operational writes.",
    );
  } finally {
    await page
      .evaluate(async () => {
        await fetch("http://localhost:8000/api/v1/auth/logout", {
          method: "POST",
          credentials: "include",
        });
      })
      .catch(() => {});
    await browser.close();
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
