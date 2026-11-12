// Candidate generation and session-only basket updates; never click final export.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const links='C:/Users/pc/AppData/Local/ms-playwright/.links';
const {chromium}=require(fs.readFileSync(path.join(links,fs.readdirSync(links)[0]),'utf8').trim());
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const dir='reports/smart_exam_flow';fs.mkdirSync(dir,{recursive:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1100}});
  await page.goto(process.env.MATHCYCLUS_UI_URL||'http://127.0.0.1:8652');
  await page.locator('[data-testid="stSidebar"]').getByText(/组卷服务/).first().click({timeout:60000});
  await page.getByRole('button',{name:'加入试题篮',exact:true}).first().click({timeout:60000});
  await page.getByRole('button',{name:'关闭试题篮',exact:true}).click();
  const manual=await page.locator('.mc-db-browse-title').first().textContent();
  await page.getByRole('button',{name:'智能组卷',exact:true}).click();
  await page.getByRole('button',{name:'生成候选池',exact:true}).click();
  await page.getByText(/全库匹配 .*同题去重后/).waitFor({timeout:60000});
  await page.getByRole('button',{name:'生成初选方案',exact:true}).click();
  await page.getByText(/初选 10 \/ 10 题 · 保留手选 1 题/).waitFor({timeout:60000});
  await page.getByText('高级设置',{exact:true}).click();
  const unknownLimit=page.getByRole('spinbutton',{name:'未标注难度题的数量上限',exact:true});
  await unknownLimit.fill('0');await unknownLimit.press('Tab');
  await page.getByText('条件已变化，请重新生成候选池。',{exact:true}).waitFor();
  await page.getByRole('button',{name:'确认放入试题篮',exact:true}).waitFor({state:'detached'});
  assert.equal(await page.getByRole('button',{name:'确认放入试题篮',exact:true}).count(),0);
  await unknownLimit.fill('10');await unknownLimit.press('Tab');
  await page.getByText(/初选 10 \/ 10 题 · 保留手选 1 题/).waitFor({timeout:60000});
  const acknowledgement=page.getByRole('checkbox',{name:'已核对上述范围或相似关系提醒',exact:true});
  if(await acknowledgement.count())await acknowledgement.check();
  await page.getByRole('button',{name:'确认放入试题篮',exact:true}).click();
  await page.getByRole('heading',{name:/试题篮 · 10 题/}).waitFor({timeout:60000});
  const manualCard=page.locator('.mc-db-browse-title').filter({hasText:manual}).locator('xpath=ancestor::div[@data-testid="stVerticalBlockBorderWrapper"][1]');
  await manualCard.getByRole('button',{name:'移出试题篮',exact:true}).waitFor({timeout:30000});
  await page.getByRole('button',{name:'选题完成，进入排版工作台',exact:false}).click();
  await page.getByRole('heading',{name:/试卷排版工作台/}).waitFor({timeout:60000});
  await page.getByRole('button',{name:'⬅️ 返回继续选题',exact:true}).waitFor();
  assert.equal(await page.locator('[data-testid="stException"]').count(),0);
  await page.getByRole('button',{name:'⬅️ 返回继续选题',exact:true}).click();
  await page.getByRole('button',{name:'关闭试题篮',exact:true}).click();
  // Explicitly impossible type quota must not replace the existing basket.
  const smallerGoal=page.getByRole('spinbutton',{name:'目标题数',exact:true});
  await smallerGoal.fill('5');await smallerGoal.press('Tab');
  await page.waitForTimeout(400);
  assert.equal(await smallerGoal.inputValue(),'5','Existing basket forcibly reset the new target');
  await page.getByText('重新生成整套',{exact:true}).click();
  await page.getByText('指定题型数量',{exact:true}).click();
  const single=page.getByRole('spinbutton',{name:'单选题',exact:true});
  await single.fill('0');await single.press('Tab');
  const other=page.getByRole('spinbutton',{name:'其他',exact:true});
  await other.fill('20');await other.press('Tab');
  await page.waitForTimeout(600);
  fs.writeFileSync(path.join(dir,'quota_state.txt'),await page.locator('body').innerText());
  await page.getByText(/本次目标 20 题，以以上题型配额为准/).waitFor();
  await page.getByRole('button',{name:'生成候选池',exact:true}).click();
  await page.getByText(/全库匹配 .*同题去重后/).waitFor({timeout:60000});
  await page.getByRole('button',{name:'生成初选方案',exact:true}).click();
  await page.getByText(/其他还缺/).waitFor({timeout:60000});
  assert(await page.getByRole('button',{name:'确认放入试题篮',exact:true}).isDisabled());
  await page.screenshot({path:path.join(dir,'desktop.png')});
  await page.setViewportSize({width:420,height:1000});await page.waitForTimeout(400);
  await page.screenshot({path:path.join(dir,'mobile.png')});
  const errors=await page.locator('[data-testid="stException"]').allTextContents();
  assert.equal(errors.length,0);
  const result={manual,preservedManual:true,basketCount:10,typesettingPrepared:true,
    shortageBlocked:true,conditionChangesInvalidatePlan:true,smallerTargetAllowed:true,finalExportClicked:false,errors};
  fs.writeFileSync(path.join(dir,'checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
