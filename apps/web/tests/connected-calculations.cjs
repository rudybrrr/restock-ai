const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage();
    await page.addInitScript(() => localStorage.setItem("restock:workspace-tour:v1:manager", "seen"));
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
    await page.getByRole('heading', { name: 'Assessment in progress', exact: true }).waitFor();
    const pendingReads = reads.length;
    let navigationCount = 0;
    page.on('framenavigated', frame => { if (frame === page.mainFrame()) navigationCount++; });
    const finished = await page.request.post(process.env.CONNECTED_API_URL + '/_test/finish');
    assert.equal(finished.status(), 200);
    await page.getByRole('heading', { name: 'Daily baseline', exact: true }).waitFor({ timeout: 20000 });
    await page.getByText('Assessment status: succeeded.', { exact: true }).waitFor({ timeout: 15000 });
    assert.equal(navigationCount, 0, 'Worker completion must appear without reload/navigation');
    assert(reads.length > pendingReads, 'Pending output must be fetched again');
    assert.match(await page.locator('body').innerText(), /Chicken noodles/);
    await page.getByLabel(/^Dish/).selectOption('chicken-rice');
    assert.match(await page.locator('body').innerText(), /6\.666667/);
    await page.getByRole('tab', { name: 'Stock projection', exact: true }).click();
    await page.getByLabel(/^Ingredient/).selectOption('chicken');
    assert.match(await page.locator('body').innerText(), /17\.000/);
    await page.getByLabel(/^Projection basis/).selectOption('candidate');
    const rounded = page.locator('span[title]').filter({ hasText: /^≈ / }).first();
    await rounded.waitFor();
    const exactValue = await rounded.getAttribute('title');
    await page.getByText('Full-precision balance values', { exact: true }).click();
    await page.getByRole('cell', { name: exactValue, exact: true }).first().waitFor();
    await page.getByText('Full-precision balance values', { exact: true }).click();
    await page.waitForFunction(() => [...document.querySelectorAll('p')].some(p => p.textContent.startsWith('Published plan version: ') && !p.textContent.includes('Not published')));
    assert.match(await page.locator('body').innerText(), /not orders or received stock/);
    fs.mkdirSync('test-results', { recursive: true });
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.screenshot({ path: `test-results/connected-calculations-${width}.png`, fullPage: true });
    }
    assert(reads.length >= 1);
    assert(reads.every(path => path.includes(process.env.CONNECTED_RUN_ID)));
    await page.setViewportSize({ width: 1440, height: 900 });
    const published = (await page.locator('p').allTextContents()).find(p => p.startsWith('Published plan version: ')).split(': ')[1].split('.')[0];
    await page.goto(ui + '/workspace/recommendations?version=' + encodeURIComponent(published));
    await page.getByRole('button', { name: /^Approve version/ }).waitFor();
    const reviewUrl = page.url();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      const button = page.getByRole('button', { name: 'Forecast & stock projection', exact: true });
      await button.scrollIntoViewIfNeeded();
      const before = await page.evaluate(() => scrollY);
      await button.click();
      const drawer = page.getByRole('dialog', { name: 'Forecast & stock projection', exact: true });
      await drawer.getByRole('heading', { name: 'Daily baseline', exact: true }).waitFor();
      await drawer.getByRole('tab', { name: 'Stock projection', exact: true }).click();
      await drawer.getByLabel(/^Projection basis/).selectOption('candidate');
      assert.equal(page.url(), reviewUrl, 'Supporting details must not leave the recommendation');
      assert.equal(await drawer.getByRole('link').count(), 0);
      assert(await drawer.evaluate(el => el.scrollWidth <= el.clientWidth + 1), 'Drawer overflow');
      await page.screenshot({ path: `test-results/recommendation-drawer-${width}.png` });
      await page.keyboard.press('Escape');
      await drawer.waitFor({ state: 'hidden' });
      assert(await button.evaluate(el => document.activeElement === el), 'Focus returns to the review');
      assert(Math.abs(await page.evaluate(() => scrollY) - before) < 2, 'Review scroll must be retained');
      await page.getByRole('button', { name: /^Approve version/ }).waitFor();
    }
    assert.deepEqual(errors, []);
    console.log('PASS: real manager login, queued-to-success automatic refresh without reload, exact run read, frozen forecast, both projection bases, desktop/mobile, no browser errors.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
