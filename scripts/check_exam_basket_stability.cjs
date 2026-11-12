/* Check continuous layout stability, including native widget style updates. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const links='C:/Users/pc/AppData/Local/ms-playwright/.links';
const {chromium}=require(fs.readFileSync(path.join(links,fs.readdirSync(links)[0]),'utf8').trim());
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const dir='reports/exam_basket_stability';fs.mkdirSync(dir,{recursive:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}});
  await page.goto(process.env.MATHCYCLUS_UI_URL||'http://127.0.0.1:8652');
  await page.locator('[data-testid="stSidebar"]').getByText(/组卷服务/).first().click({timeout:60000});
  await page.getByRole('button',{name:'加入试题篮',exact:true}).first().click({timeout:60000});
  await page.locator('#mc-exam-basket-panel').waitFor();
  await page.waitForTimeout(2000);
  const sample=()=>page.evaluate(()=>new Promise(resolve=>{
   const samples=[];
   const tick=()=>{
    const panel=document.querySelector('#mc-exam-basket-panel');
    const grid=panel.querySelector('.mc-choice-grid-anchor').closest('[data-testid="stVerticalBlock"]');
    const content=panel.querySelector(':scope > div > [data-testid="stVerticalBlock"]');
    const rect=panel.getBoundingClientRect(),style=getComputedStyle(grid);
    samples.push({columns:style.display==='grid'?style.gridTemplateColumns.split(' ').length:1,
     height:Math.round(rect.height),top:Math.round(rect.top),scrollbar:content.scrollHeight>content.clientHeight+1});
    if(samples.length===80)resolve(samples);else setTimeout(tick,100);
   };tick();
  }));
  const initial=await sample();
  const nativeUpdate=await page.evaluate(()=>{
   const grid=document.querySelector('#mc-exam-basket-panel .mc-choice-grid-anchor').closest('[data-testid="stVerticalBlock"]');
   const before=getComputedStyle(grid).gridTemplateColumns;
   // Streamlit owns class/style and may replace both when widths are reported.
   grid.classList.remove('mc-choice-grid');grid.style.removeProperty('--mc-choice-columns');
   return {before,after:getComputedStyle(grid).gridTemplateColumns,display:getComputedStyle(grid).display};
  });
  const handle=await page.locator('.mc-basket-resize-right').boundingBox();
  await page.mouse.move(handle.x+15,handle.y+15);await page.mouse.down();
  await page.mouse.move(handle.x-105,handle.y-65,{steps:10});await page.mouse.up();
  await page.waitForTimeout(800);
  const resized=await sample();
  const errors=await page.locator('[data-testid="stException"]',).allTextContents();
  const result={initial,resized,nativeUpdate,errors};
  fs.writeFileSync(path.join(dir,'samples.json'),JSON.stringify(result,null,2));
  await page.screenshot({path:path.join(dir,'stable_basket.png')});
  const states=records=>new Set(records.map(s=>JSON.stringify(s))).size;
  console.log(JSON.stringify({initialStates:states(initial),resizedStates:states(resized),nativeUpdate,errors}));
  assert.equal(states(initial),1,'Idle basket alternates layout/scrollbar states');
  assert.equal(nativeUpdate.display,'grid','Native style update disabled the option grid');
  assert.equal(nativeUpdate.after,nativeUpdate.before,'Native style update reset option columns');
  assert.equal(states(resized),1,'Resized basket alternates layout/scrollbar states');
  assert.equal(errors.length,0);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
