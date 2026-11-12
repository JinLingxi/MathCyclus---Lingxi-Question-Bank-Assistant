/* Read-only checks for inline metadata and the source drawer position. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const links='C:/Users/pc/AppData/Local/ms-playwright/.links';
const {chromium}=require(fs.readFileSync(path.join(links,fs.readdirSync(links)[0]),'utf8').trim());
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const dir='reports/browse_card_header';fs.mkdirSync(dir,{recursive:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100}});
  await page.goto(process.env.MATHCYCLUS_UI_URL||'http://127.0.0.1:8652');
  await page.locator('[data-testid="stSidebar"]').getByText(/全局浏览/).first().click({timeout:60000});
  await page.getByPlaceholder(/Q000765/).first().fill('ID:Q014101');
  await page.getByRole('button',{name:'开始搜索',exact:true}).click();
  await page.locator('.mc-db-browse-title').filter({hasText:'Q014101'}).waitFor({timeout:60000});
  const card=page.locator('.mc-db-full-preview-anchor').first().locator('xpath=ancestor::div[@data-testid="stVerticalBlockBorderWrapper"][1]');
  const measure=()=>card.evaluate(n=>{
   const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
   const meta=n.querySelector('.mc-db-inline-meta-anchor');
   const button=[...n.querySelectorAll('button')].find(b=>b.textContent.includes('标签信息') && b.getBoundingClientRect().width>0);
   const tags=meta.querySelectorAll('.mc-db-browse-pill');
   const heading=[...n.querySelectorAll('[data-testid="stMarkdownContainer"]')].find(e=>e.textContent==='TeX 源码');
   return {card:rect(n),meta:rect(meta),lastTag:rect(tags[tags.length-1]),button:rect(button),drawer:rect(n.querySelector('.mc-db-material-drawer summary')),source:rect(n.querySelector('.mc-db-browse-source')),code:rect(heading)};
  });
  await page.waitForTimeout(800);
  const desktop=await measure();
  fs.writeFileSync(path.join(dir,'button_parents.json'),JSON.stringify(await card.getByRole('button',{name:'标签信息 ▾',exact:true}).evaluate(b=>{
   const out=[];let n=b;for(let i=0;n&&i<7;i++,n=n.parentElement){const r=n.getBoundingClientRect(),s=getComputedStyle(n);out.push({testid:n.dataset.testid,classes:n.className,y:r.y,height:r.height,margin:s.margin,padding:s.padding,display:s.display});}return out;
  }),null,2));
  fs.writeFileSync(path.join(dir,'desktop_geometry.json'),JSON.stringify(desktop,null,2));
  fs.writeFileSync(path.join(dir,'meta_parents.json'),JSON.stringify(await card.evaluate(n=>{
   const out={};for(const cls of ['.mc-db-inline-meta-anchor','.mc-db-browse-note','.mc-db-browse-source']){let e=n.querySelector(cls);out[cls]=[];for(let i=0;e&&i<5;i++,e=e.parentElement){const r=e.getBoundingClientRect(),s=getComputedStyle(e);out[cls].push({testid:e.dataset.testid,classes:e.className,y:r.y,height:r.height,margin:s.margin,padding:s.padding,display:s.display,gap:s.gap,align:s.alignItems,shrink:s.flexShrink});}}return out;
  }),null,2));
  await page.screenshot({path:path.join(dir,'initial.png')});
  assert(Math.abs(desktop.button.y+desktop.button.height/2-desktop.meta.y-desktop.meta.height/2)<5,'Tag action is not on the metadata line');
  assert(desktop.button.x-desktop.lastTag.right>=0 && desktop.button.x-desktop.lastTag.right<25,'Tag action is separated from the tags');
  assert(desktop.drawer.y-desktop.card.y<35,'Source drawer is not at the card top');
  assert(desktop.code.y-desktop.source.bottom<60,'Source drawer leaves a blank row above code');
  await card.locator('summary').click();await page.waitForTimeout(200);
  assert(Math.abs((await measure()).code.y-desktop.code.y)<2,'Opening drawer moves the source layout');
  await card.locator('summary').click();
  await card.getByRole('button',{name:'标签信息 ▾',exact:true}).click();
  await page.getByRole('dialog').waitFor();
  await page.getByRole('button',{name:'Close',exact:true}).click();
  const records=[{width:1600,...desktop}];
  for(const width of [1600,1000,420]){
   await page.setViewportSize({width,height:1100});await page.waitForTimeout(500);
   await card.scrollIntoViewIfNeeded();
   const geometry=await measure();
   assert(geometry.drawer.right<=geometry.card.right+1,'Source drawer overflows the card');
   assert(geometry.button.right<=geometry.card.right+1,'Metadata action overflows the card');
   assert(geometry.button.width>0,'Metadata action is hidden');
   if(width<=1100)assert(geometry.code.y>=geometry.drawer.bottom,'Drawer overlaps the source heading');
   await page.screenshot({path:path.join(dir,'header_'+width+'.png')});
   if(width!==1600)records.push({width,...geometry});
  }
  const errors=await page.locator('[data-testid="stException"]').allTextContents();assert.equal(errors.length,0);
  fs.writeFileSync(path.join(dir,'checks.json'),JSON.stringify({records,errors},null,2));console.log(JSON.stringify({records,errors}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
