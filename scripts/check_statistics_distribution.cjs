/* Browser checks for chart readability, native controls, and iframe sizing. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const links='C:/Users/pc/AppData/Local/ms-playwright/.links';
const {chromium}=require(fs.readFileSync(path.join(links,fs.readdirSync(links)[0]),'utf8').trim());
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const dir='reports/statistics_distribution';fs.mkdirSync(dir,{recursive:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100}});
  await page.goto(process.env.MATHCYCLUS_UI_URL||'http://127.0.0.1:8652');
  let frame;
  for(let i=0;i<60&&!frame;i++){
   for(const candidate of page.frames())if(await candidate.locator('.distribution').count()){frame=candidate;break;}
   if(!frame)await page.waitForTimeout(500);
  }
  assert(frame,'Distribution panel did not render');
  await page.waitForTimeout(600);
  const standalone=await browser.newPage();
  const standaloneHtml=(await frame.content()).replace('</head>','<style>body{background:#f5f2fb}</style></head>');
  fs.writeFileSync(path.join(dir,'distribution.html'),standaloneHtml);
  await standalone.setContent(standaloneHtml);
  const records=[];
  for(const width of [1600,1000,420]){
   await page.setViewportSize({width,height:1100});await page.waitForTimeout(600);
   const metrics=await frame.evaluate(()=>({
    viewport:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth+1,
    columns:getComputedStyle(document.querySelector('.distribution')).gridTemplateColumns,
    initialRows:document.querySelector('.coverage-pane .ranking').children.length,
    panels:document.querySelectorAll('.panel').length,
    height:document.querySelector('.distribution').getBoundingClientRect().height,
    frameHeight:window.frameElement?.clientHeight
   }));
   assert.equal(metrics.overflow,false,`Horizontal overflow at ${width}`);
   assert(metrics.initialRows<=10);assert.equal(metrics.panels,3);
   await frame.locator('.mode-switch label').filter({hasText:'主板块题数'}).click();
   assert(await frame.locator('.primary-pane').isVisible());
   assert(!(await frame.locator('.coverage-pane').isVisible()));
   await frame.locator('.mode-switch label').filter({hasText:'覆盖题数'}).click();
   const more=frame.locator('.coverage-pane summary');
   if(await more.count()){
    await more.click();await page.waitForTimeout(250);
    const height=await frame.locator('.distribution').evaluate(n=>n.getBoundingClientRect().height);
    const host=await frame.frameElement();const hostHeight=(await host.boundingBox()).height;
    assert(hostHeight>=height,'Expanded details are clipped by the iframe');
    await more.click();await page.waitForTimeout(250);
   }
   // Capture outside the parent page's scroll clipping for a readable artifact.
   await standalone.setViewportSize({width:metrics.viewport,height:1100});
   await standalone.locator('.distribution').screenshot({path:path.join(dir,`distribution_${width}.png`)});
   records.push({width,...metrics});
  }
  const errors=await page.locator('[data-testid="stException"]').allTextContents();
  assert.equal(errors.length,0);
  const totals=await frame.evaluate(()=>[...document.querySelectorAll('.categories')].map(list=>[...list.querySelectorAll('strong')].reduce((sum,n)=>sum+Number(n.textContent.replaceAll(',','')),0)));
  assert.equal(totals[0],totals[1],'Category totals must include unclassified questions');
  const result={records,totals,errors};
  fs.writeFileSync(path.join(dir,'checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
