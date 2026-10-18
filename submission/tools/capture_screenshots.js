/* Capture the report and poster screenshots from the published website.
 *
 *   cd submission/tools && npm install && node capture_screenshots.js
 *
 * Optional: SITE_URL=http://localhost:8000/ node capture_screenshots.js
 * (after `python -m http.server 8000 -d site` from the repository root).
 *
 * Writes PNGs at 2x device scale into submission/screenshots/. Each shot puts
 * the page into a documented interaction state first (layers, a selected
 * district, pinned comparison districts, a hovered row, a chosen year), so the
 * figures can be regenerated exactly. Uses the locally installed Chrome
 * (override with CHROME_PATH); MapLibre's WebGL map renders through SwiftShader
 * in headless mode.
 */
const path = require('path');
const puppeteer = require('puppeteer-core');

const SITE_URL = process.env.SITE_URL || 'https://tashkent-transit-walkability.saidkamolbahodirov.workers.dev/';
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const OUT = path.resolve(__dirname, '..', 'screenshots');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function openPage(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 2 });
  page.on('pageerror', (e) => console.warn('page error:', e.message));
  await page.goto(SITE_URL, { waitUntil: 'networkidle0', timeout: 120000 });
  await sleep(6000);                       // let the basemap tiles and charts settle
  // Unpin the sticky top bar so it never overlaps an element screenshot.
  await page.addStyleTag({ content: '.topbar{position:absolute !important;}' });
  return page;
}

async function shot(page, selector, name) {
  const el = await page.$(selector);
  if (!el) throw new Error(`missing element ${selector}`);
  await el.evaluate((e) => e.scrollIntoView({ block: 'center' }));
  await sleep(900);
  await el.screenshot({ path: path.join(OUT, `${name}.png`) });
  console.log('saved', name);
}

async function clickRankingRow(page, district) {
  await page.evaluate((district) => {
    const row = [...document.querySelectorAll('#ranking .rk-row-hit')]
      .find((e) => e.getAttribute('aria-label').startsWith(`${district} district`));
    row.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  }, district);
  await sleep(2500);
}

async function toggleLayers(page, layers) {
  await page.click('#layers-toggle'); await sleep(300);
  for (const layer of layers) { await page.click(`input[data-layer="${layer}"]`); await sleep(200); }
  await page.click('#layers-toggle'); await sleep(2500);
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--window-size=1600,1000'],
  });
  try {
    const page = await openPage(browser);

    // Headline and access map at rest.
    await shot(page, '#hero', '01_hero_headline');
    await shot(page, '#workspace', '02_access_map_overview');
    await shot(page, '#map', '02b_access_map_only');

    // Map with the optional bus-stop and bazaar layers.
    await toggleLayers(page, ['bus', 'bazaars']);
    await shot(page, '#workspace', '03_access_map_bus_bazaar_layers');
    await toggleLayers(page, ['bus', 'bazaars']);

    // Select Chilanzar from the ranking; zoom out one step to keep context.
    await clickRankingRow(page, 'Chilanzar');
    await sleep(1500);
    await page.click('#zoom-out'); await sleep(2500);
    await shot(page, '#workspace', '04_access_map_selected_district');
    await shot(page, '#ranking-panel', '05_ranked_dot_plot');
    await shot(page, '#context-panel', '05b_district_context_panel');
    await shot(page, '.deck-panel--composition', '06_composition_stacked_bars');
    await shot(page, '.deck-panel--scatter', '07_density_access_scatter');

    // Hover Uchtepa in the composition chart: tooltip + linked highlight.
    const deck = await page.$('#district-analysis');
    await deck.evaluate((e) => e.scrollIntoView({ block: 'center' }));
    await sleep(800);
    const hit = await page.evaluateHandle(() => [...document.querySelectorAll('#composition [role="button"]')]
      .find((e) => /Uchtepa/.test(e.getAttribute('aria-label'))));
    const box = await hit.boundingBox();
    await page.mouse.move(box.x + box.width * 0.6, box.y + box.height / 2);
    await sleep(1200);
    await deck.screenshot({ path: path.join(OUT, '09_linked_hover_district_deck.png') });
    console.log('saved 09_linked_hover_district_deck');
    await page.mouse.move(5, 5); await sleep(600);

    // Pin Chilanzar, Mirabad, Uchtepa and Sergeli for comparison; reselect Chilanzar.
    const addToComparison = async () => { await page.evaluate(() => document.getElementById('compare-add').click()); await sleep(800); };
    await addToComparison();
    for (const d of ['Mirabad', 'Uchtepa', 'Sergeli']) { await clickRankingRow(page, d); await addToComparison(); }
    await clickRankingRow(page, 'Chilanzar');
    await shot(page, '.deck-panel--parallel', '08_parallel_coordinates_compare');
    await shot(page, '#district-analysis', '09b_district_deck_compare');

    // Current destinations and the bazaar-transit overlap.
    await shot(page, '#dest-cards', '10_destination_cards');
    await shot(page, '.bazaar-transit', '11_bazaar_transit_overlap');
    // 11b: the same block cropped to the composition bar and the city table.
    const clip = await page.evaluate(() => {
      const block = document.querySelector('.bazaar-transit').getBoundingClientRect();
      const city = document.getElementById('bazaar-transit-city-body').closest('table').getBoundingClientRect();
      return { x: block.left + scrollX, y: block.top + scrollY, width: block.width, height: city.bottom - block.top + 8 };
    });
    await page.screenshot({ path: path.join(OUT, '11b_bazaar_transit_city.png'), clip, captureBeyondViewport: true });
    console.log('saved 11b_bazaar_transit_city');
    await page.evaluate(() => [...document.querySelectorAll('#dest-cards button')].find((b) => /Bazaar/i.test(b.textContent)).click());
    await sleep(1500);
    await shot(page, '.dest-map-panel', '12_destination_map_bazaars');

    // Methodological bridge and the standardized temporal chapter at 2020.
    await shot(page, '#metric-bridge', '13_two_metrics_bridge');
    await page.evaluate(() => {
      const r = document.getElementById('year-range');
      r.value = '2020';
      r.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await sleep(1500);
    await shot(page, '#temporal-story .tpanel--series', '14_temporal_series_2020');
    await shot(page, '#temporal-story', '15_temporal_chapter');

    // District Explorer for Chilanzar.
    await page.evaluate(() => {
      const s = document.getElementById('district-explorer-select');
      s.value = [...s.options].find((o) => /Chilanzar/.test(o.textContent)).value;
      s.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await sleep(1500);
    await shot(page, '#district-explorer', '16_district_explorer');

    // Method dialog and its sensitivity table.
    await page.evaluate(() => document.querySelector('.navbtn[data-view="method"]').click());
    await sleep(1200);
    await shot(page, '#method-dialog', '17_method_dialog');
    await shot(page, '#method-body table', '18_sensitivity_table');
  } finally {
    await browser.close();
  }
})();
