import { chromium } from '../frontend/node_modules/@playwright/test/index.mjs';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import assert from 'node:assert/strict';
const files = new Map([['/demo/','index.html'],['/demo/index.html','index.html'],['/demo/app.js','app.js'],['/demo/style.css','style.css'],['/demo/map.svg','map.svg']]);
const types = {html:'text/html',js:'text/javascript',css:'text/css',svg:'image/svg+xml'};
const server = createServer(async (request,response) => {
  const file = files.get(request.url);
  if (!file) {response.writeHead(404);response.end();return;}
  response.setHeader('Content-Type',types[file.split('.').pop()]);
  response.end(await readFile(new URL(file,import.meta.url)));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({executablePath:process.env.DEMO_CHROMIUM || '/usr/bin/chromium',args:['--no-sandbox']});
const failures = [];
try {
  await mkdir('artifacts/static-demo',{recursive:true});
  for (const width of [390,768,1440]) {
    const page = await browser.newPage({viewport:{width,height:900}});
    const requests = [];
    await page.route('**/*',route=>{
      const request = route.request();
      requests.push(request.url());
      if (!request.url().startsWith(`${origin}/demo/`) || ['fetch','xhr','websocket','eventsource'].includes(request.resourceType())) {
        failures.push(request.url());return route.abort();
      }
      return route.continue();
    });
    page.on('pageerror',error=>failures.push(error.message));
    for (const route of ['upcoming','past','map','settings','trip/coast','trip/mountains','trip/city']) {
      await page.goto(`${origin}/demo/#${route}`);
      await page.locator('h1').waitFor();
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),true,`${width}: ${route} overflow`);
      assert.equal(await page.locator('button:not([disabled])').count(),0);
      assert.equal(await page.locator('input,form,iframe').count(),0);
      await page.screenshot({path:`artifacts/static-demo/${route.replace('/','-')}-${width}.png`,fullPage:true});
    }
    await page.goto(`${origin}/demo/`);
    await page.getByRole('link',{name:/View itinerary/}).first().click();
    await page.getByRole('heading',{name:'A week by the coast'}).waitFor();
    await page.getByRole('link',{name:'Travel map',exact:true}).click();
    await page.getByRole('heading',{name:'Travel map',exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>document.querySelector('.map img').naturalWidth > 0),true);
    console.log(`${width}px: all routes passed; requests limited to bundled static files (${new Set(requests).size} unique URLs)`);
    await page.close();
  }
  assert.deepEqual(failures,[]);
} finally {
  await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
