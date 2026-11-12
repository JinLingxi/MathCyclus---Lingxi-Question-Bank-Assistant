/* Native calendar scrolling, newest-date arrival, and redundant heading checks. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const links='C:/Users/pc/AppData/Local/ms-playwright/.links';
const {chromium}=require(fs.readFileSync(path.join(links,fs.readdirSync(links)[0]),'utf8').trim());
(async()=>{
 const browser=await chromium.launch({headless:true,ignoreDefaultArgs:['--hide-scrollbars'],executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const dir='reports/activity_heatmap';fs.mkdirSync(dir,{recursive:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100}});
  await page.goto(process.env.MATHCYCLUS_UI_URL||'http://127.0.0.1:8652');
  const find=async selector=>{
   for(let i=0;i<60;i++){
    for(const frame of page.frames())if(await frame.locator(selector).count())return frame;
    await page.waitForTimeout(300);
   }throw new Error('Missing frame: '+selector);
  };
  const frame=await find('.heatmap-scroll-area');
  await page.waitForTimeout(500);
  const area=frame.locator('.heatmap-scroll-area');
  const measure=()=>area.evaluate(n=>{
   return {left:n.scrollLeft,max:n.scrollWidth-n.clientWidth,width:n.clientWidth,scrollWidth:n.scrollWidth,
    heading:document.querySelectorAll('.heatmap-title').length,
    lastVisible:[...n.querySelectorAll('.heatmap-cell:not(.hidden)')].at(-1).getBoundingClientRect().right<=n.getBoundingClientRect().right+1};
  });
  const initial=await measure();
  assert(initial.max>20,'Need an overflowing calendar to exercise its scrollbar');
  assert(Math.abs(initial.left-initial.max)<2,'Calendar did not open at the latest date');
  assert(initial.lastVisible);assert.equal(initial.heading,0);
  const curve=await find('.activity-card');
  assert.equal(await curve.locator('.activity-title').count(),0);
  const box=await area.boundingBox();
  const thumbWidth=initial.width*initial.width/initial.scrollWidth;
  const startX=box.x+initial.width-thumbWidth/2;
  const endX=box.x+thumbWidth/2;
  await page.mouse.move(startX,box.y+box.height-6);await page.mouse.down();
  const positions=[];
  for(let i=1;i<=8;i++){
   await page.mouse.move(startX+(endX-startX)*i/8,box.y+box.height-6);
   await page.waitForTimeout(32);
   positions.push((await measure()).left);
  }
  await page.mouse.up();await page.waitForTimeout(300);
  const dragged=await measure();
  assert(new Set(positions.map(Math.round)).size>=5,'Scrollbar did not update continuously during dragging');
  assert(dragged.left<initial.left-20,'Drag did not move to older dates');
  await page.waitForTimeout(700);
  assert(Math.abs((await measure()).left-dragged.left)<2,'Calendar snapped right after user interaction');
  await page.screenshot({path:path.join(dir,'activity.png')});
  await page.setViewportSize({width:1000,height:1100});await page.waitForTimeout(350);
  const resized=await measure();
  assert(Math.abs(resized.left-dragged.left)<2,'Resizing reset the user scroll position');
  const sidebar=page.locator('[data-testid="stSidebar"]');
  await sidebar.getByText(/项目介绍/).first().click();
  await page.getByRole('heading').filter({hasText:'项目体系介绍'}).first().waitFor();
  await sidebar.getByText(/数据统计/).first().click();
  const reentered=await find('.heatmap-scroll-area');await page.waitForTimeout(400);
  const arrival=await reentered.locator('.heatmap-scroll-area').evaluate(n=>({left:n.scrollLeft,max:n.scrollWidth-n.clientWidth}));
  assert(Math.abs(arrival.left-arrival.max)<2,'Re-entered calendar did not show the latest date');
  const errors=await page.locator('[data-testid="stException"]').allTextContents();assert.equal(errors.length,0);
  const result={initial,positions,dragged,resized,arrival,errors};
  fs.writeFileSync(path.join(dir,'checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
