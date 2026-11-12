const fs=require('fs'),path=require('path'),assert=require('assert/strict'),crypto=require('crypto');
const {pathToFileURL}=require('url');
const year=process.argv[2];if(!year)throw Error('year required');
const root=path.resolve(__dirname,'..'),work=path.join(root,'data/imports','codex_'+year+'_restart');
const links='C:/Users/pc/AppData/Local/ms-playwright/.links';
const {chromium}=require(fs.readFileSync(path.join(links,fs.readdirSync(links)[0]),'utf8').trim());
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.goto(pathToFileURL(path.join(work,'browser_preview.html')).href);
  await page.waitForFunction(()=>window.previewReady===true);
  await page.waitForFunction(()=>[...document.images].every(i=>i.complete&&i.naturalWidth>0));
  const payload=JSON.parse(fs.readFileSync(path.join(work,'visual_payloads.json'),'utf8'));
  const questions=await page.locator('article').count(),images=await page.locator('img').count();
  assert.equal(questions,payload.length);assert.equal(images,payload.reduce((s,x)=>s+x.assets.length,0));
  const errors=await page.evaluate(()=>window.previewErrors);
  const failedMath=await page.locator('.math-error').evaluateAll(nodes=>nodes.map(node=>({
    question:node.closest('article')?.querySelector('h2')?.textContent,math:node.textContent
  })));
  assert.equal(errors.length,0,JSON.stringify({errors,failedMath}));
  await page.screenshot({path:path.join(work,'browser_first_screen.png')});
  const result={status:'ok',questions,images,katex_errors:errors,
    payload_sha256:crypto.createHash('sha256').update(fs.readFileSync(path.join(work,'visual_payloads.json'))).digest('hex'),
    scope:'actual_latex_to_markdown_plus_local_browser_katex_and_images',task_ui_checked_separately:true};
  fs.writeFileSync(path.join(work,'preview_browser_checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
