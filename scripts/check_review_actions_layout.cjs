const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const links='C:/Users/pc/AppData/Local/ms-playwright/.links';
const {chromium}=require(fs.readFileSync(path.join(links,fs.readdirSync(links)[0]),'utf8').trim());
const out=path.resolve('data/reports/review_actions');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const results=[];
 try{
  for(const width of [1440,430]){
   const page=await browser.newPage({viewport:{width,height:1000}});const start=Date.now();
   await page.goto('http://127.0.0.1:8517');
   const approve=page.getByRole('button',{name:'✅ 确认本题审核通过',exact:true});
   const reject=page.getByRole('button',{name:'❌ 本题放弃录入',exact:true});
   await approve.first().waitFor({timeout:60000});
   await page.waitForFunction(()=>!document.querySelector('[data-testid="stStatusWidget"] [data-testid="stSpinner"]'));
   assert.equal(await approve.count(),7);assert.equal(await reject.count(),7);
   const body=await page.locator('body').innerText();
   assert(!body.includes('原始 PDF 页面证据已保留在导入任务中；不会作为题目图片插入正文。'));
   assert(!body.includes('对照原书扫描页转写，保留原书答案及解法。'));
   await approve.first().scrollIntoViewIfNeeded();
   const a=await approve.first().boundingBox(),r=await reject.first().boundingBox();
   assert(Math.abs(a.y-r.y)<2,JSON.stringify({width,a,r}));assert(a.x+a.width<=r.x+2);
   assert(r.x+r.width<=width+1);assert(a.width>=120);
   await page.screenshot({path:path.join(out,`review_${width}.png`)});
   results.push({width,load_ms:Date.now()-start,approve:a,reject:r});await page.close();
  }
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.goto('http://127.0.0.1:8517/?view=browse');
  await page.locator('.mc-db-code-preview-anchor').first().waitFor({state:'attached',timeout:60000});
  assert.equal(await page.locator('.mc-db-code-preview-anchor').count(),10);
  await page.screenshot({path:path.join(out,'browse_1440.png')});await page.close();
  fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({status:'ok',results},null,2));
  console.log(JSON.stringify({status:'ok',results}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
