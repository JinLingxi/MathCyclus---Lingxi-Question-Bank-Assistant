// Read-only navigation check against a separately running local app.
const fs = require('node:fs'), path = require('node:path');
const links = 'C:/Users/pc/AppData/Local/ms-playwright/.links';
const {chromium} = require(fs.readFileSync(path.join(links, fs.readdirSync(links)[0]), 'utf8').trim());
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const output = path.resolve('reports/navigation_profile');
  fs.mkdirSync(output, {recursive:true});
  try {
    const page = await browser.newPage({viewport:{width:1600, height:1000}});
    await page.goto(process.env.MATHCYCLUS_UI_URL || 'http://127.0.0.1:8652');
    const sidebar = page.locator('[data-testid="stSidebar"]');
    await sidebar.getByText('项目介绍', {exact:false}).first().waitFor({timeout:60000});
    await page.waitForTimeout(3000);
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Profiler.enable');
    await cdp.send('Profiler.start');
    const results = [];
    for (const label of ['项目介绍', '规范说明', '工具箱', '全局浏览', '项目介绍', '规范说明', '工具箱']) {
      const started = Date.now();
      await sidebar.getByText(label, {exact:false}).first().click();
      const headings = {项目介绍:'项目体系介绍', 规范说明:'规范', 工具箱:'工具箱', 全局浏览:'全局浏览'};
      await page.locator('h1,h2,h3').filter({hasText:headings[label]}).first().waitFor({timeout:60000});
      results.push({label, visibleMs:Date.now()-started});
      await page.waitForTimeout(1500);
    }
    const errors = await page.locator('[data-testid="stException"]').allTextContents();
    const {profile} = await cdp.send('Profiler.stop');
    fs.writeFileSync(path.join(output,'browser.cpuprofile'),JSON.stringify(profile));
    fs.writeFileSync(path.join(output,'browser_timings.json'),JSON.stringify({results, errors},null,2));
    console.log(JSON.stringify({results,errors}));
    await page.screenshot({path:path.join(output,'navigation.png')});
    if(errors.length) process.exitCode = 1;
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
