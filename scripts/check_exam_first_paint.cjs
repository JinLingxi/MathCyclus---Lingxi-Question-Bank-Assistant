/* Sample the launcher from its first visible frame, before utility scripts. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const links='C:/Users/pc/AppData/Local/ms-playwright/.links';
const {chromium}=require(fs.readFileSync(path.join(links,fs.readdirSync(links)[0]),'utf8').trim());
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const dir='reports/exam_first_paint';fs.mkdirSync(dir,{recursive:true});
 try{
  const page=await browser.newPage({viewport:{width:2048,height:1100}});
  await page.addInitScript(()=>{
   window.__basketPaintFrames=[];window.__basketPaintRunning=true;
   const sample=()=>{
    if(!window.__basketPaintRunning)return;
    const button=[...document.querySelectorAll('button')].find(b=>/^🧺\s*\d+$/.test(b.textContent.trim()));
    if(button){
     const host=button.closest('[data-testid="element-container"], [data-testid="stElementContainer"]');
     const r=button.getBoundingClientRect();
     if(r.width && r.height)window.__basketPaintFrames.push({x:r.x,y:r.y,right:r.right,width:r.width,position:getComputedStyle(host).position});
    }
    requestAnimationFrame(sample);
   };requestAnimationFrame(sample);
  });
  const cdp=await page.context().newCDPSession(page);
  await cdp.send('Emulation.setCPUThrottlingRate',{rate:3});
  await page.goto(process.env.MATHCYCLUS_UI_URL||'http://127.0.0.1:8652');
  const sidebar=page.locator('[data-testid="stSidebar"]');
  await sidebar.getByText(/组卷服务/).first().click({timeout:60000});
  await page.locator('.mc-db-browse-card-anchor').nth(9).waitFor({state:'attached',timeout:60000});
  await page.waitForTimeout(1500);
  await sidebar.getByText(/项目介绍/).first().click();
  await page.getByRole('heading').filter({hasText:'项目体系介绍'}).first().waitFor();
  await sidebar.getByText(/组卷服务/).first().click();
  await page.locator('.mc-db-browse-card-anchor').nth(9).waitFor({state:'attached',timeout:60000});
  await page.waitForTimeout(1500);
  await cdp.send('Emulation.setCPUThrottlingRate',{rate:1});
  const frames=await page.evaluate(()=>{window.__basketPaintRunning=false;return window.__basketPaintFrames;});
  const preview=await page.getByRole('heading',{name:'SQLite 试用选题预览',exact:true}).boundingBox();
  const controls=await page.getByRole('button',{name:'智能组卷',exact:true}).boundingBox();
  const gap=preview.y-controls.y-controls.height;
  const errors=await page.locator('[data-testid="stException"]').allTextContents();
  const bad=frames.filter(f=>f.position!=='fixed'||f.right<1900||f.right>2049);
  const result={samples:frames.length,first:frames[0],last:frames.at(-1),badFrames:bad,controlsToResultsGap:gap,errors};
  fs.writeFileSync(path.join(dir,'checks.json'),JSON.stringify(result,null,2));
  await page.screenshot({path:path.join(dir,'first_paint.png')});
  console.log(JSON.stringify(result));
  assert(frames.length>=10,'Did not sample initial rendering');
  assert.equal(bad.length,0,'Basket launcher appeared in normal flow before moving right');
  assert(gap<80,`Hidden utility rows leave a ${gap}px gap`);
  assert.equal(errors.length,0);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
