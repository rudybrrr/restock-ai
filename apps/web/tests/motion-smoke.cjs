const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright-core");
const assert = require("node:assert/strict");

async function main() {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    for (const reducedMotion of ["no-preference", "reduce"]) {
      const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion });
      await page.goto(process.env.UI_TEST_URL || "http://localhost:3002");
      await page.getByRole("link", { name: "Explore ReStock" }).waitFor();
      const result = await page.evaluate(async () => {
        const target = document.querySelector("#approach");
        const behavior = getComputedStyle(document.documentElement).scrollBehavior;
        const entrance = getComputedStyle(document.querySelector(".hero-copy")).animationName;
        const destination = Math.min(target.getBoundingClientRect().top + scrollY - 24,
          document.documentElement.scrollHeight - innerHeight);
        document.querySelector('.hero-actions a[href="#approach"]').click();
        const samples = [];
        const start = performance.now();
        await new Promise(resolve => {
          const sample = () => {
            samples.push(scrollY);
            if (performance.now() - start < 1300) requestAnimationFrame(sample);
            else resolve();
          };
          requestAnimationFrame(sample);
        });
        return { behavior, entrance, destination, samples, end: scrollY, hash: location.hash };
      });
      assert.equal(result.hash, "#approach");
      assert(Math.abs(result.end - result.destination) <= 2, "anchor reaches its target");
      if (reducedMotion === "reduce") {
        assert.equal(result.behavior, "auto");
        assert.equal(result.entrance, "none");
      } else {
        assert.equal(result.behavior, "smooth");
        assert(result.samples.some(y => y > 0 && y < result.destination - 5), "scroll includes intermediate frames");
      }
      await page.close();
    }
    console.log("PASS: animated anchor scrolling, destination, and reduced-motion fallback.");
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
