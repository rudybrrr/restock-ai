const { chromium } = require(process.env.PLAYWRIGHT_MODULE);
const assert = require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({reducedMotion:'reduce'});
 const base=process.env.UI_TEST_URL||'http://localhost:3002';
 try{
  page.on('request',r=>{if(r.url().includes('/api/v1/')&&r.method()!=='GET'&&r.method()!=='OPTIONS')assert(/\/auth\/(login|logout)$/.test(r.url()),'Unexpected operational write');});
  await page.goto(base+'/login');
  await page.getByLabel('Username').fill(process.env.RESTOCK_TEST_USERNAME||'manager');
  await page.getByLabel('Password',{exact:true}).fill(process.env.RESTOCK_TEST_PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.waitForURL('**/workspace/**');
  for(const name of ['overview','inventory','daily','sales','recommendations','deliveries','suppliers','activity']){
   await page.goto(base+'/workspace/'+name);
   await page.locator('.page-heading').waitFor();
   await page.waitForLoadState('networkidle');
   for(const width of [1440,390]){
    await page.setViewportSize({width,height:1000});
    await page.screenshot({path:`test-results/layout-${name}-${width}.png`,fullPage:true});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' overflow '+width);
   }
  }
  console.log('PASS: eight live workspace pages, desktop/mobile, no horizontal page overflow.');
 }finally{await page.evaluate(()=>fetch('http://localhost:8000/api/v1/auth/logout',{method:'POST',credentials:'include'})).catch(()=>{});await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
