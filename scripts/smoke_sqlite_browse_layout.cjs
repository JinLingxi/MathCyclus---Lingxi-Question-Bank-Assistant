/* Browser regression check for the shared SQLite browse/exam layout.
 * Requires a running local app and Playwright (no application dependency).
 * MATHCYCLUS_PLAYWRIGHT_MODULE may point to an existing playwright-core install.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.MATHCYCLUS_PLAYWRIGHT_MODULE || 'playwright');

async function measure(page) {
  return page.evaluate(() => {
    const columnSelector = '[data-testid="column"], [data-testid="stColumn"]';
    const left = document.querySelector('.mc-db-browse-left-anchor').closest(columnSelector);
    const code = document.querySelector('.mc-db-code-preview-anchor').closest(columnSelector);
    const row = code.parentElement;
    const preview = row.lastElementChild;
    const rect = node => {
      const r = node.getBoundingClientRect();
      return {x: r.x, y: r.y, width: r.width, right: r.right};
    };
    return {left:rect(left), code:rect(code), preview:rect(preview), viewport:innerWidth};
  });
}

(async () => {
  const outputDir = process.env.MATHCYCLUS_LAYOUT_REPORT_DIR
    ? path.resolve(process.env.MATHCYCLUS_LAYOUT_REPORT_DIR)
    : path.resolve(__dirname, '../reports/sqlite_browse_layout');
  fs.mkdirSync(outputDir, {recursive:true});
  const browser = await chromium.launch({
    headless:true,
    ...(process.env.MATHCYCLUS_BROWSER_EXECUTABLE
      ? {executablePath:process.env.MATHCYCLUS_BROWSER_EXECUTABLE} : {}),
  });
  const results = [];
  try {
    for (const width of [2048, 1366]) {
      const page = await browser.newPage({viewport:{width, height:1100}});
      await page.goto(process.env.MATHCYCLUS_UI_URL || 'http://127.0.0.1:8501');
      const sidebar = page.locator('[data-testid="stSidebar"]');
      await sidebar.getByText(/全局浏览/).first().click({timeout:30000});
      for (const surface of ['browse', 'exam']) {
        if (surface === 'exam') {
          await sidebar.getByText(/组卷服务/).first().click();
          await page.getByText('SQLite 试用选题预览', {exact:true}).waitFor({timeout:30000});
        }
        await page.locator('.mc-db-code-preview-anchor').first().waitFor({state:'attached',timeout:30000});
        await page.waitForFunction(() => !document.querySelector('[data-testid="stSpinner"]'));
        // Allow Streamlit's ResizeObserver and final CSS injection to settle.
        await page.waitForTimeout(1000);
        const geometry = await measure(page);
        assert(geometry.left.width >= 280, `${surface}/${width}: collapsed filter column`);
        assert(geometry.code.width >= 280, `${surface}/${width}: collapsed source column`);
        assert(geometry.preview.width >= 280, `${surface}/${width}: collapsed preview column`);
        assert(geometry.code.right <= geometry.preview.x + 1, `${surface}/${width}: overlapping source/preview`);
        assert(geometry.preview.right <= geometry.viewport, `${surface}/${width}: preview outside viewport`);
        await page.screenshot({path:path.join(outputDir, `${surface}_${width}.png`)});
        results.push({surface, width, ...geometry});
      }
      await page.close();
    }
    fs.writeFileSync(path.join(outputDir, 'geometry.json'), JSON.stringify(results, null, 2));
    console.log(JSON.stringify({status:'ok', results}));
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
