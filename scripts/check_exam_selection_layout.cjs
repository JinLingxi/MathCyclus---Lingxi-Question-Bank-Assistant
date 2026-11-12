/* Read-only UI regression: two rendered columns and basket scroll stability. */
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const links = 'C:/Users/pc/AppData/Local/ms-playwright/.links';
const {chromium} = require(fs.readFileSync(path.join(links,fs.readdirSync(links)[0]),'utf8').trim());
(async () => {
  const browser = await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const dir = 'reports/exam_selection_layout'; fs.mkdirSync(dir,{recursive:true});
  try {
    const page = await browser.newPage({viewport:{width:1600,height:1000}});
    await page.goto(process.env.MATHCYCLUS_UI_URL || 'http://127.0.0.1:8652');
    await page.locator('[data-testid="stSidebar"]').getByText(/组卷服务/).first().click({timeout:60000});
    const cards = page.locator('[data-testid="stVerticalBlockBorderWrapper"]').filter({has:page.locator('.mc-db-browse-card-anchor')});
    await page.locator('.mc-db-browse-card-anchor').first().waitFor({state:'attached',timeout:60000});
    await page.waitForTimeout(4000);
    await page.screenshot({path:path.join(dir,'initial.png')});
    fs.writeFileSync(path.join(dir,'initial_text.txt'),await page.locator('body').innerText());
    const initial = await page.evaluate(() => {
      const anchors = [...document.querySelectorAll('.mc-db-browse-card-anchor')];
      const rect = a => {const r=a.closest('[data-testid="stVerticalBlockBorderWrapper"]').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,right:r.right};};
      window.__examFirstCard = anchors[0];
      return {cards:anchors.slice(0,2).map(rect),sources:document.querySelectorAll('[data-testid="stCode"]').length};
    });
    assert.equal(initial.sources,0,'Exam selection must not display source code');
    assert.equal(initial.cards.length,2);
    assert(Math.abs(initial.cards[0].y-initial.cards[1].y)<3,'First two questions must share a row');
    assert(initial.cards[0].right<=initial.cards[1].x+1,'Question columns overlap');
    await page.evaluate(() => {
      let node=document.querySelector('.mc-db-browse-card-anchor');
      while(node){
        if(node.scrollHeight>node.clientHeight+100 && ['auto','scroll'].includes(getComputedStyle(node).overflowY))break;
        node=node.parentElement;
      }
      window.__examScrollOwner=node || document.scrollingElement;
      window.__examScrollOwner.scrollTop=850;
    });
    await page.waitForTimeout(400);
    const measure = () => page.evaluate(() => ({
      scroll:window.__examScrollOwner.scrollTop,
      sameCard:window.__examFirstCard===document.querySelector('.mc-db-browse-card-anchor'),
      errors:[...document.querySelectorAll('[data-testid="stException"]')].map(n=>n.textContent)
    }));
    const before = await measure();
    assert(before.scroll>300,'Fixture must start scrolled down');
    await page.getByRole('button',{name:/^🧺\s*\d+$/}).click();
    await page.getByRole('button',{name:'关闭试题篮',exact:true}).waitFor({timeout:30000});
    await page.waitForTimeout(600);
    const opened = await measure();
    await page.screenshot({path:path.join(dir,'basket_open.png')});
    await page.getByRole('button',{name:'关闭试题篮',exact:true}).click();
    await page.getByRole('button',{name:/^🧺\s*\d+$/}).waitFor({timeout:30000});
    await page.waitForTimeout(600);
    const closed = await measure();
    for (const state of [opened,closed]) {
      assert.equal(state.errors.length,0);
      assert(state.sameCard,'Basket toggle rebuilt the question list');
      assert(Math.abs(state.scroll-before.scroll)<5,`Basket toggle moved scroll: ${JSON.stringify({before,state})}`);
    }
    await page.screenshot({path:path.join(dir,'two_columns.png')});
    // Populated basket also includes a custom sortable component and preview.
    await page.getByRole('button',{name:'加入试题篮',exact:true}).first().click();
    await page.getByRole('button',{name:'关闭试题篮',exact:true}).waitFor({timeout:30000});
    await page.getByRole('button',{name:'关闭试题篮',exact:true}).click();
    await page.getByRole('button',{name:/^🧺\s*1$/}).waitFor({timeout:30000});
    await page.evaluate(()=>{
      window.__examFirstCard=document.querySelector('.mc-db-browse-card-anchor');
      window.__examScrollOwner.scrollTop=850;
    });
    await page.waitForTimeout(300);
    const populatedBefore=await measure();
    await page.getByRole('button',{name:/^🧺\s*1$/}).click();
    await page.getByRole('button',{name:'关闭试题篮',exact:true}).waitFor({timeout:30000});
    await page.waitForTimeout(600);
    const populatedOpen=await measure();
    await page.screenshot({path:path.join(dir,'populated_basket.png')});
    await page.getByRole('button',{name:'关闭试题篮',exact:true}).click();
    await page.getByRole('button',{name:/^🧺\s*1$/}).waitFor({timeout:30000});
    await page.waitForTimeout(600);
    const populatedClosed=await measure();
    for(const state of [populatedOpen,populatedClosed]){
      assert.equal(state.errors.length,0);
      assert(state.sameCard,'Populated basket rebuilt the question list');
      assert(Math.abs(state.scroll-populatedBefore.scroll)<5,'Populated basket moved scroll');
    }
    const result = {initial,before,opened,closed,populatedBefore,populatedOpen,populatedClosed};
    fs.writeFileSync(path.join(dir,'checks.json'),JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
