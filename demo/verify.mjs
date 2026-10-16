import { chromium } from '../frontend/node_modules/@playwright/test/index.mjs';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const root = path.resolve('frontend/demo-dist');
const data = JSON.parse(await readFile('frontend/demo/data.json','utf8'));
const prefix = '/Waypoint/demo/';
const types = {html:'text/html',js:'text/javascript',css:'text/css',svg:'image/svg+xml',woff2:'font/woff2'};
const server = createServer(async (request,response)=>{
  const url = new URL(request.url,'http://localhost');
  const file = path.resolve(root,url.pathname.slice(prefix.length) || 'index.html');
  if (!url.pathname.startsWith(prefix) || !file.startsWith(`${root}/`)) {response.writeHead(404);response.end();return;}
  try {response.setHeader('Content-Type',types[file.split('.').pop()] || 'application/octet-stream');response.end(await readFile(file));}
  catch {response.writeHead(404);response.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const executablePath = process.env.DEMO_CHROMIUM || (existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined);
const browser = await chromium.launch({executablePath,args:['--no-sandbox']});
const failures = [];
try {
  await mkdir('artifacts/static-demo',{recursive:true});
  for (const width of [390,768,1440]) {
    const context = await browser.newContext({viewport:{width,height:900},reducedMotion:'no-preference'});
    await context.addInitScript(()=>{
      window.fetch = ()=>{throw new Error("Runtime fetch attempted in static demo");};
      if (navigator.credentials) {
        navigator.credentials.get = ()=>{throw new Error("Authentication attempted in static demo");};
        navigator.credentials.create = ()=>{throw new Error("Authentication attempted in static demo");};
      }
    });
    const page = await context.newPage();
    await page.clock.setFixedTime(new Date('2040-01-01T00:00:00Z'));
    const requests = [];
    await context.route('**/*',route=>{
      const request = route.request();requests.push(request.url());
      if (!request.url().startsWith(`${origin}${prefix}`) || /\/api\//.test(request.url()) || ['fetch','xhr','websocket','eventsource'].includes(request.resourceType())) {failures.push(request.url());return route.abort();}
      return route.continue();
    });
    page.on('pageerror',error=>failures.push(error.message));
    page.on('console',message=>{if (message.type() === 'error') failures.push(message.text());});
    page.on('requestfailed',request=>failures.push(`Failed request: ${request.url()}`));
    page.on('response',response=>{if (response.status() >= 400) failures.push(`${response.status()}: ${response.url()}`);});
    const routes = ['upcoming','trips','review','people','stats','settings',...['account','mail','travel','offline','assistants','backup'].map(group=>`settings/${group}`),...data.trips.map(trip=>`trip/${trip.id}`)];
    for (const route of routes) {
      await page.goto(`${origin}${prefix}#${route}`);
      await page.locator('h1').first().waitFor();
      try { await page.waitForFunction(()=>!document.querySelector('[aria-busy="true"]'),null,{timeout:5000}); } catch (error) {
        console.log(route,failures,await page.locator('body').innerText());
        await page.screenshot({path:'artifacts/static-demo/parity-failure.png',fullPage:true});
        throw error;
      }
      assert.deepEqual(failures,[],`${route}: browser requests or errors`);
      assert.equal(await page.evaluate(()=>Date.now()),Date.parse(`${data.asOf}T12:00:00Z`),`${route}: demo clock drifted`);
      if (route === 'upcoming') {
        assert.equal(await page.getByText('Nothing coming up:',{exact:false}).count(),0,'Upcoming itinerary expired');
        await page.locator('section.pass[data-kind]').first().waitFor();
        assert.ok(await page.locator('section.pass[data-kind] a[href^="#trip/"]').count(),'Upcoming trip action missing');
        assert.equal(await page.getByRole('link',{name:'Camden Guesthouse',exact:true}).count(),1,'Duplicate Camden stay');
      }
      assert.ok(await page.locator('main').evaluate(element=>parseFloat(getComputedStyle(element).paddingLeft) >= 16),`${route}: app styles missing`);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),true,`${width}: ${route} overflow`);
      assert.equal(await page.locator('input[type="file"]:not([disabled])').count(),0,`${route}: import enabled`);
      assert.equal(await page.locator('button[data-demo-disabled]:not([disabled])').count(),0,`${route}: mutation enabled`);
      assert.equal(await page.locator('a[href]:not([href^="#"])').count(),0,`${route}: external navigation enabled`);
      if (route.startsWith('trip/')) {
        assert.equal(await page.getByRole('button',{name:'Add a booking',exact:true}).isDisabled(),true,'Trip editing enabled');
        const trip = data.trips.find(item=>item.id === Number(route.slice(5)));
        const buttons = page.getByRole('button',{name:/^View email for/});
        assert.equal(await buttons.count(),trip.segments.length,`${route}: missing source emails`);
        for (let index = 0; index < trip.segments.length; index++) await buttons.first().click();
        await page.getByText('SIMULATED BOOKING EMAIL',{exact:false}).first().waitFor();
        assert.equal(await page.getByText('SIMULATED BOOKING EMAIL',{exact:false}).count(),trip.segments.length);
        if (trip.end_date < data.asOf) assert.equal(await page.locator('[data-testid="offline-status"]').count(),0);
      }
      await page.screenshot({path:`artifacts/static-demo/${route.replace('/','-')}-${width}.png`,fullPage:true});
    }
    const past = data.trips.find(trip=>trip.end_date < data.asOf && trip.segments.some(segment=>segment.kind === 'flight'));
    await page.goto(`${origin}${prefix}#trip/${past.id}`);
    const replay = page.getByRole('region',{name:'Route replay'});await replay.waitFor();
    const scrubber = page.getByRole('slider',{name:'Position along the route'});
    const before = await scrubber.inputValue();
    await page.waitForFunction(value=>document.querySelector('input[aria-label="Position along the route"]')?.value !== value,before);
    await replay.getByRole('button',{name:'Pause',exact:true}).click();
    assert.equal(await replay.getByRole('button',{name:'Resume',exact:true}).count(),1);
    await replay.getByRole('button',{name:/Playback speed/}).click();
    await page.goto(`${origin}${prefix}#review`);
    await page.getByRole('button',{name:/View email/}).first().click();
    await page.getByText('SIMULATED BOOKING EMAIL',{exact:false}).first().waitFor();
    assert.equal(await page.locator('[data-testid="match-item"] button:not([disabled]), [data-testid="who-item"] button:not([disabled])').count(),0,'Review matching enabled');
    const suggestions = page.getByRole('button',{name:/^Check (?:\d+ )?suggestions?: /});
    assert.equal(await suggestions.count(),3);
    for (let index=0; index<3; index++) {
      await suggestions.nth(index).click();
      const dialog = page.getByRole('dialog');await dialog.waitFor();
      const bookingTab = dialog.getByRole('button',{name:'Booking',exact:true});
      if (await bookingTab.isVisible()) await bookingTab.click();
      const cost = dialog.getByRole('textbox',{name:'Cost amount'});
      assert.ok(await cost.inputValue(),'Review booking cost missing');
      assert.equal(await cost.isDisabled(),true,'Review booking editing enabled');
      assert.equal(await dialog.locator('input:not([disabled]),textarea:not([disabled]),select:not([disabled])').count(),0,'Review editing enabled');
      await dialog.getByRole('button',{name:'Close',exact:true}).click();
      await dialog.waitFor({state:'hidden'});
    }
    await page.goto(`${origin}${prefix}#stats`);await page.locator('h1').waitFor();
    const selects = page.locator('select');
    if (await selects.count()) {assert.equal(await selects.first().isDisabled(),false,'Stats filter disabled');await selects.first().selectOption({index:0});}
    assert.equal(await page.evaluate(()=>navigator.serviceWorker ? navigator.serviceWorker.getRegistrations().then(items=>items.length) : 0),0);
    assert.equal(await page.evaluate(()=>localStorage.length),0);
    console.log(`${width}px: main app views, ${data.trips.reduce((count,trip)=>count+trip.segments.length,0)} booking emails, review and animated past replay passed; ${new Set(requests).size} bundled URLs`);
    await context.close();
  }
  assert.deepEqual(failures,[]);
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
