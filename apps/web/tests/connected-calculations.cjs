const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage();
    const errors = [], reads = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('http://localhost:8000/api/v1/**', async route => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      if (path.includes('calculation-results')) reads.push(path);
      // Forward to the isolated *real* API; do not supply mocked responses.
      const response = await route.fetch({ url: process.env.CONNECTED_API_URL + path + new URL(request.url()).search });
      if (response.status() >= 400) console.log('API error', path, response.status());
      await route.fulfill({ response });
    });
    const ui = process.env.UI_TEST_URL || 'http://localhost:3025';
    await page.goto(ui + '/login');
    await page.getByLabel('Username', { exact: true }).fill('manager');
    await page.getByLabel('Password', { exact: true }).fill('test-manager-password');
    await page.getByRole('button', { name: /sign in|log in/i }).click();
    await page.waitForURL('**/workspace/**');
    await page.goto(ui + '/workspace/inventory');
    await page.getByRole('link', { name: 'Forecast & projections', exact: true }).click();
    await page.getByRole('heading', { name: 'Forecast & projections', exact: true }).waitFor().catch(async error => { console.log('Page URL', page.url(), 'Page text', (await page.locator('body').innerText()).slice(0, 1800)); throw error; });
    await page.getByLabel(/^Assessment/).selectOption(process.env.CONNECTED_RUN_ID);
    await page.getByRole('heading', { name: 'Daily baseline', exact: true }).waitFor();
    assert.match(await page.locator('body').innerText(), /Chicken noodles/);
    await page.getByLabel(/^Dish/).selectOption('chicken-rice');
    assert.match(await page.locator('body').innerText(), /6\.666667/);
    await page.getByRole('tab', { name: 'Stock projection', exact: true }).click();
    await page.getByLabel(/^Ingredient/).selectOption('chicken');
    assert.match(await page.locator('body').innerText(), /17\.000/);
    await page.getByLabel(/^Projection basis/).selectOption('candidate');
    assert.match(await page.locator('body').innerText(), /not orders or received stock/);
    fs.mkdirSync('test-results', { recursive: true });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.screenshot({ path: `test-results/connected-calculations-${width}.png`, fullPage: true });
    }
    assert(reads.length >= 1);
    assert(reads.every(path => path.includes(process.env.CONNECTED_RUN_ID)));
    assert.deepEqual(errors, []);
    console.log('PASS: real manager login, exact run read, frozen forecast, both projection bases, desktop/mobile, no browser errors.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
