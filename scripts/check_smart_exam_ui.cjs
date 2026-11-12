/* Compact default controls, difficulty presets, and explicit candidate refresh. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const links='C:/Users/pc/AppData/Local/ms-playwright/.links';
const {chromium}=require(fs.readFileSync(path.join(links,fs.readdirSync(links)[0]),'utf8').trim());
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const dir='reports/smart_exam_ui';fs.mkdirSync(dir,{recursive:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}});
  await page.goto(process.env.MATHCYCLUS_UI_URL||'http://127.0.0.1:8652');
  await page.locator('[data-testid="stSidebar"]').getByText(/组卷服务/).first().click({timeout:60000});
  await page.getByRole('button',{name:'智能组卷',exact:true}).click();
  const generate=page.getByRole('button',{name:'生成候选池',exact:true});
  await generate.waitFor({timeout:60000});
  const records=[];
  for(const width of [1600,1366,420]){
   await page.setViewportSize({width,height:1000});await page.waitForTimeout(350);
   await page.locator('.mc-smart-exam-header').evaluate(n=>n.scrollIntoView({block:'start'}));
   const button=await generate.boundingBox();
   const advanced=page.getByRole('spinbutton',{name:'抽题编号',exact:true});
   assert(!(await advanced.isVisible()),'Advanced parameters are visible by default');
   assert(button.y+button.height<1000,'Primary action falls below the first screen');
   const surface=await page.locator('.mc-smart-exam-root').evaluate(n=>{
    const panel=n.closest('[data-testid="stVerticalBlockBorderWrapper"]');
    const r=panel.getBoundingClientRect();
    return {background:getComputedStyle(panel).backgroundColor,width:r.width,viewport:innerWidth};
   });
   assert(!['transparent','rgba(0, 0, 0, 0)'].includes(surface.background),'Panel has no distinct surface');
   assert(surface.width<=width,'Form overflows its viewport');
   await page.screenshot({path:path.join(dir,'default_'+width+'.png')});
   records.push({width,button,surface});
  }
  await page.setViewportSize({width:1600,height:1000});
  const goal=page.getByRole('spinbutton',{name:'目标题数',exact:true});
  await goal.fill('12');await goal.press('Tab');
  await page.waitForTimeout(400);
  assert.equal(await page.getByRole('spinbutton',{name:'本次组卷数量',exact:true}).inputValue(),'12');
  await goal.fill('10');await goal.press('Tab');
  await page.waitForTimeout(300);
  const preset=page.getByTestId('stSelectbox').filter({hasText:'难度偏好'});
  await preset.locator('[data-baseweb="select"]').click();
  await page.getByRole('option',{name:'基础为主',exact:true}).click();
  await page.getByText('高级设置',{exact:true}).click();
  await page.waitForFunction(()=>{
   const sliders=[...document.querySelectorAll('[role="slider"]')];
   return sliders.length===2 && sliders[0].getAttribute('aria-valuenow')==='0' && sliders[1].getAttribute('aria-valuenow')==='2';
  });
  const values=await page.getByRole('slider').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('aria-valuenow')));
  assert.deepEqual(values,['0','2'],'Difficulty preset did not update the actual bounds');
  await page.getByText('高级设置',{exact:true}).click();
  await generate.click();
  await page.getByText(/全库匹配 .*同题去重后/).waitFor({timeout:60000});
  assert.equal(await page.locator('.mc-smart-exam-progress .current').textContent(),'候选池');
  await page.getByRole('button',{name:'换一批候选',exact:true}).click();
  await page.getByText(/全库匹配 .*同题去重后/).waitFor({timeout:60000});
  await page.getByText('高级设置',{exact:true}).click();
  const seed=page.getByRole('spinbutton',{name:'抽题编号',exact:true});
  await page.waitForFunction(()=>[...document.querySelectorAll('input')].some(n=>n.value==='43'));
  assert.equal(await seed.inputValue(),'43','Candidate refresh did not advance the reproducible draw');
  const errors=await page.locator('[data-testid="stException"]').allTextContents();
  assert.equal(errors.length,0);
  const result={records,presetBounds:values,goalSync:true,refreshSeed:43,errors};
  fs.writeFileSync(path.join(dir,'checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
