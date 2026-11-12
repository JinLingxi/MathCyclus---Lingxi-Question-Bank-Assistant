/* Browser regression for basket window handles, close button, and persistence. */
const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
const links='C:/Users/pc/AppData/Local/ms-playwright/.links';
const {chromium}=require(fs.readFileSync(path.join(links,fs.readdirSync(links)[0]),'utf8').trim());
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const dir='reports/exam_basket_resize';fs.mkdirSync(dir,{recursive:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}});
  await page.goto(process.env.MATHCYCLUS_UI_URL||'http://127.0.0.1:8652');
  await page.locator('[data-testid="stSidebar"]').getByText(/组卷服务/).first().click({timeout:60000});
  await page.locator('.mc-db-browse-card-anchor').first().waitFor({state:'attached',timeout:60000});
  await page.getByRole('button',{name:/^🧺\s*0$/}).click();
  const panel=page.locator('#mc-exam-basket-panel');
  const close=()=>page.getByRole('button',{name:'关闭试题篮',exact:true});
  await panel.waitFor();
  const rect=()=>panel.boundingBox();
  const drag=async(side,dx,dy)=>{
   const handle=page.locator('.mc-basket-resize-'+side);
   const r=await handle.boundingBox();
   await page.mouse.move(r.x+r.width/2,r.y+r.height/2);
   await page.mouse.down();
   await page.mouse.move(r.x+r.width/2+dx,r.y+r.height/2+dy,{steps:8});
   await page.mouse.up();
  };
  const initial=await rect();
  await drag('right',-110,-85);
  const right=await rect();
  assert(Math.abs(right.width-(initial.width-110))<3,'Right handle did not resize width');
  assert(Math.abs(right.height-(initial.height-85))<3,'Right handle did not resize height');
  await drag('left',-80,60);
  const left=await rect();
  assert(Math.abs(left.width-(right.width+80))<3,'Left handle did not resize width');
  assert(Math.abs(left.height-(right.height+60))<3,'Left handle did not resize height');
  assert(Math.abs(left.x+left.width-right.x-right.width)<3,'Left resize moved the opposite edge');
  await page.locator('.mc-basket-resize-right').focus();
  await page.keyboard.press('ArrowRight');
  const keyboard=await rect();
  assert(Math.abs(keyboard.width-left.width-16)<3,'Keyboard resize failed');
  const button=await close().evaluate(b=>({width:b.offsetWidth,height:b.offsetHeight,icon:getComputedStyle(b,'::before').maskImage}));
  assert.equal(button.width,36);assert.equal(button.height,36);assert(button.icon.includes('svg'));
  await close().click();
  await page.getByRole('button',{name:/^🧺\s*0$/}).click();
  await panel.waitFor();
  await page.locator('.mc-basket-resize-right').waitFor();
  const reopened=await rect();
  assert(Math.abs(reopened.width-keyboard.width)<3 && Math.abs(reopened.height-keyboard.height)<3,'Window size was lost after reopening');
  await close().click();
  await page.getByRole('button',{name:'加入试题篮',exact:true}).first().click();
  await panel.waitFor();
  await page.locator('.mc-basket-resize-right').waitFor();
  const populated=await rect();
  await drag('right',50,40);
  const populatedResized=await rect();
  assert(Math.abs(populatedResized.width-populated.width-50)<3,'Populated basket failed to resize');
  assert(Math.abs(populatedResized.height-populated.height-40)<3,'Populated basket height failed to resize');
  await close().hover();
  const chrome=await panel.evaluate(p=>({
   background:getComputedStyle(p).backgroundColor,
   padding:parseFloat(getComputedStyle(p.querySelector(':scope > div > [data-testid="stVerticalBlock"]')).paddingLeft)
  }));
  assert(!['transparent','rgba(0, 0, 0, 0)'].includes(chrome.background),'Basket surface is transparent');
  assert(chrome.padding>=16,'Basket content lacks inner spacing');
  await page.screenshot({path:path.join(dir,'desktop.png')});
  await page.setViewportSize({width:420,height:800});
  await page.waitForTimeout(400);
  const mobile=await rect();
  assert(mobile.x>=0 && mobile.x+mobile.width<=421 && mobile.y+mobile.height<=801,'Window exceeds narrow viewport');
  const mobileClose=await close().boundingBox();
  assert.equal(mobileClose.width,36);assert.equal(mobileClose.height,36);
  assert(mobileClose.y<mobile.y+50,'Close button left the window header on mobile');
  await page.screenshot({path:path.join(dir,'mobile.png')});
  const errors=await page.locator('[data-testid="stException"]').allTextContents();
  assert.equal(errors.length,0);
  const results={initial,right,left,keyboard,reopened,populated,populatedResized,mobile,mobileClose,button,chrome,errors};
  fs.writeFileSync(path.join(dir,'checks.json'),JSON.stringify(results,null,2));
  console.log(JSON.stringify(results));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
