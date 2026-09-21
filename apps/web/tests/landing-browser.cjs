const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    for (const reducedMotion of ['reduce', 'no-preference']) {
      const page = await browser.newPage({reducedMotion, viewport: {width:1440,height:1000}});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.goto(process.env.UI_TEST_URL || 'http://localhost:3013');
      assert.equal(await page.title(), 'ReStock');
      const icon = await page.locator('link[rel="icon"]').getAttribute('href');
      assert(icon.startsWith('/icon.svg'));
      assert.equal((await page.request.get(new URL(icon, page.url()).href)).status(), 200);
      await page.getByRole('button', {name:'Incoming',exact:true}).click();
      await page.getByText('Arranged purchases are not stock until received.', {exact:true}).waitFor();
      await page.getByRole('button', {name:'Purchase plan',exact:true}).click();
      await page.getByText('A recommendation, not an order. You decide.', {exact:true}).waitFor();
      await page.getByRole('button', {name:'Kitchen stock',exact:true}).click();
      await page.screenshot({path:`test-results/landing-${reducedMotion}.png`,fullPage:true});
      await page.getByRole('link',{name:'Explore ReStock',exact:true}).click();
      await page.locator('#approach').waitFor();
      await page.waitForFunction(() => {
        const target = document.querySelector('#approach').getBoundingClientRect().top + scrollY - 24;
        return Math.abs(scrollY - Math.min(target, document.documentElement.scrollHeight - innerHeight)) < 3;
      });
      assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior), reducedMotion === 'reduce' ? 'auto' : 'smooth');
      for (const width of [390,768,1440]) {
        await page.setViewportSize({width,height:900});
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `Overflow at ${width}`);
      }
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log('PASS: landing preview interactions, responsive widths, reduced-motion modes, no page errors.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode=1; });
