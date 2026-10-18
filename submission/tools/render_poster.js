/* Render submission/poster/poster.html to an A0 PDF plus a PNG preview.
 *
 *   cd submission/tools && npm install && node render_poster.js
 *
 * Uses the locally installed Chrome (override with CHROME_PATH). The page is
 * laid out at 3179 x 4494 CSS px, which is exactly 841 x 1189 mm at 96 dpi, so
 * the PDF needs no scaling. The script fails if any block overflows the page
 * or its own box, so a text edit can't silently push content off the poster.
 */
const path = require('path');
const fs = require('fs');
const { pathToFileURL } = require('url');
const puppeteer = require('puppeteer-core');

const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const POSTER_DIR = path.resolve(__dirname, '..', 'poster');
const SOURCE = path.join(POSTER_DIR, 'poster.html');
const PDF = path.join(POSTER_DIR, 'Tashkent_Transit_Walkability_Poster_A0.pdf');
const PREVIEW = path.join(POSTER_DIR, 'poster_preview.png');
const W = 3179;
const H = 4494;

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new', args: ['--allow-file-access-from-files'] });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
    await page.goto(pathToFileURL(SOURCE).href, { waitUntil: 'networkidle0', timeout: 120000 });
    await page.waitForFunction(() => document.body.dataset.ready === '1' && document.fonts.status === 'loaded');
    await page.evaluate(() => Promise.all([...document.images].map((img) => img.decode().catch(() => null))));

    const report = await page.evaluate((H) => {
      const problems = [];
      const footer = document.querySelector('.footer').getBoundingClientRect();
      const blocks = [...document.body.children].filter((n) => n.tagName !== 'SCRIPT');
      const used = blocks.reduce((sum, n) => sum + n.getBoundingClientRect().height, 0);
      if (footer.bottom > H + 0.5) problems.push(`footer ends at ${Math.round(footer.bottom)}px, page is ${H}px`);
      for (const n of document.querySelectorAll('.step, .card, .linked, .cap, .split > section, .title-block, .intro-block')) {
        if (n.scrollHeight > n.clientHeight + 1) problems.push(`${n.className} overflows by ${n.scrollHeight - n.clientHeight}px`);
      }
      const missing = [...document.images].filter((img) => !img.naturalWidth).map((img) => img.getAttribute('src'));
      if (missing.length) problems.push(`images failed to load: ${missing.join(', ')}`);
      return { problems, used: Math.round(used), slack: Math.round(H - used), font: document.fonts.check('700 40px Inter') };
    }, H);

    console.log(`content height ${report.used}px of ${H}px (slack ${report.slack}px); Inter loaded: ${report.font}`);
    if (report.problems.length) {
      console.error('LAYOUT PROBLEMS:\n  ' + report.problems.join('\n  '));
      process.exitCode = 1;
    }

    await page.pdf({ path: PDF, width: '841mm', height: '1189mm', printBackground: true, pageRanges: '1' });
    await page.screenshot({ path: PREVIEW, clip: { x: 0, y: 0, width: W, height: H } });
    console.log(`wrote ${path.relative(process.cwd(), PDF)} (${(fs.statSync(PDF).size / 1e6).toFixed(1)} MB)`);
    console.log(`wrote ${path.relative(process.cwd(), PREVIEW)}`);
  } finally {
    await browser.close();
  }
})();
