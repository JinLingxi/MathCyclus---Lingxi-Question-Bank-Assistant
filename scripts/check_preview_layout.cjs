const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const links='C:/Users/pc/AppData/Local/ms-playwright/.links';
const {chromium}=require(fs.readFileSync(path.join(links,fs.readdirSync(links)[0]),'utf8').trim());
(async()=>{
 const b=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 try{
  const p=await b.newPage({viewport:{width:1600,height:1000}});
  p.on('pageerror',e=>console.log('browser error:',e.message));
  await p.goto('http://127.0.0.1:8640');
  await p.locator('[data-mc-choice-grid]').first().waitFor({timeout:90000});
  const records=[];
  for(const width of [1600,1000,420]){
   await p.setViewportSize({width,height:1000});await p.waitForTimeout(3500);
   await p.locator('[data-mc-choice-grid]').first().waitFor({timeout:15000});
   const grids=await p.locator('[data-mc-choice-grid]').evaluateAll(gs=>gs.map(g=>({width:g.clientWidth,columns:g.dataset.columns,children:g.children.length,overflow:g.scrollWidth>g.clientWidth+2})));
   const errors=await p.locator('.katex-error,[data-testid="stException"]').allTextContents();
   const frames=[];
   for(const f of p.frames()){
    if(await f.locator('.mc-review-image-frame').count()){
     frames.push(await f.evaluate(()=>({height:innerHeight,content:document.querySelector('.mc-review-image-frame').getBoundingClientRect().height,caption:document.querySelector('.mc-review-image-caption').textContent})));
    }
   }
   records.push({width,grids,errors,frames});
   await p.screenshot({path:`reports/preview_layout_${width}.png`,fullPage:true});
  }
  fs.writeFileSync('reports/preview_layout_checks.json',JSON.stringify(records,null,2));
  console.log(JSON.stringify(records));
  assert(records.every(r=>!r.errors.length && r.grids.length===3 && r.grids.every(g=>!g.overflow)));
  assert(records.every(r=>r.frames.every(f=>f.height-f.content<10 && !f.caption.includes('点击图片') && !f.caption.includes(' · '))));
  assert.equal(records[0].grids[0].columns,'4');
  assert.equal(records[0].grids[2].columns,'2');
  assert.equal(records.at(-1).grids[2].columns,'1');
  assert(await p.locator('mstyle[displaystyle="true"]').count()>0);
  const pic=p.frames().find(f=>f!==p.mainFrame() && f.url()==='about:srcdoc');
  for(const f of p.frames())if(await f.locator('.mc-review-image-thumb').count()){
   await f.locator('.mc-review-image-thumb').click();
   await p.getByRole('dialog',{name:'图片大图'}).waitFor();
   await p.getByRole('dialog',{name:'图片大图'}).click();break;
  }
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
