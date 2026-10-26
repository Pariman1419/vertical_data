const assert = require('node:assert/strict');
const { chromium } = require('C:/Users/SAM-RPA/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('utl-etl-demo-v1.2', JSON.stringify({connections:[{id:'data-prep-iot',name:'Data Prep IOT',role:'Source',engine:'Oracle',host:'test.invalid',database:'IOT',port:1521,identifier_type:'Service Name',revision:1,remember:false}],scopes:{},analyzed:{},mappings:{},relationships:{}})));
  await page.goto(process.env.UTL_DEMO_URL || 'http://localhost:5173/', { waitUntil: 'networkidle' });

  const nav = page.locator('.nav button');
  assert.deepEqual(await nav.allTextContents(), ['Database Connection', 'U-ETL DataBridge', 'AI Data Bridge', 'Data Set']);
  assert.equal(await page.locator('#screen-picker, [aria-label="เปิดดูหน้าจอ"]').count(), 0);
  assert.equal(await page.locator('.masthead-logo').count(), 1);
  assert((await page.locator('.identity').innerText()).includes('UTAC Thai Limited'));
  assert(await page.getByRole('heading', { name: 'Database Connection' }).isVisible());
  assert(await page.getByText('Test passed means only the Oracle login/read-only test succeeded.', { exact: false }).isVisible());

  await nav.getByText('U-ETL DataBridge', { exact: true }).click();
  assert(await page.getByRole('heading', { name: 'U-ETL DataBridge' }).isVisible());
  assert(await page.getByText('ยังไม่มีข้อมูลที่จัดเก็บ', { exact: false }).isVisible());
  await page.evaluate(() => {
    window.realSourceSnapshots['data-prep-iot|BIDPITDBA|DP_WIP_DATA'] = {
      sourceId:'data-prep-iot',sourceName:'Data Prep IOT',schema:'BIDPITDBA',table:'DP_WIP_DATA',
      columns:[['LOT_NO',1,'VARCHAR2','N'],['OPERATION',2,'VARCHAR2','Y'],['OUTPUT_QTY',3,'NUMBER','Y']],
      keys:[],foreign_keys:[],discoveredAt:'synthetic-test-fixture',configRevision:1
    };
  });
  await nav.getByText('U-ETL DataBridge', { exact: true }).click();
  assert(await page.getByText('DP_WIP_DATA', { exact: true }).isVisible());
  assert(await page.getByText('Not copied', { exact: true }).isVisible());

  await nav.getByText('Data Set', { exact: true }).click();
  await page.getByRole('button', { name: '＋ New Dataset' }).click();
  await page.getByRole('button', { name: 'Continue to suggested plan →' }).click();
  assert(await page.getByText('AI DATA BRIDGE · STEP 1 OF 4', { exact: true }).isVisible());
  await page.getByLabel('Dataset name').fill('Yield by operation');
  await page.getByLabel('Business purpose').fill('Find production steps where yield drops');
  await page.getByLabel('Business fields you need · one per line').fill('Lot number\nProcess step\nOutput quantity');
  assert.equal(await page.locator('[name=sourceIds]:checked').count(), 1);
  await page.getByRole('button', { name: 'Continue to suggested plan →' }).click();
  assert(await page.getByText('AI DATA BRIDGE · STEP 2 OF 4', { exact: true }).isVisible());
  await page.getByRole('button', { name: 'Approve reviewed plan & continue' }).click();
  assert(await page.getByText('AI DATA BRIDGE · STEP 2 OF 4', { exact: true }).isVisible());
  await page.getByRole('button', { name: 'Back · Edit request' }).click();
  assert.equal(await page.getByLabel('Dataset name').evaluate(el => el.value), 'Yield by operation');
  assert.equal(await page.getByLabel('Business purpose').evaluate(el => el.value), 'Find production steps where yield drops');
  assert.equal(await page.getByLabel('Business fields you need · one per line').evaluate(el => el.value), 'Lot number\nProcess step\nOutput quantity');
  await page.getByRole('button', { name: 'Save changes and rebuild plan' }).click();
  assert(await page.getByText('AI DATA BRIDGE · STEP 2 OF 4', { exact: true }).isVisible());
  await page.getByLabel('Dataset grain proposal').selectOption('lot_operation');
  for (const field of ['Lot number', 'Process step', 'Output quantity']) {
    const row = page.locator('#dataset-candidate-review tr').filter({ hasText: field });
    const approve = row.getByRole('button', { name: 'Approve candidate' });
    if (await approve.isEnabled()) await approve.click();
    else {
      await row.getByLabel(`Rationale ${field}`).fill('Confirmed for this synthetic metadata UI test.');
      await row.getByRole('button', { name: 'Override candidate' }).click();
    }
  }
  await page.getByRole('button', { name: 'Approve reviewed plan & continue' }).click();
  assert(await page.getByText('AI DATA BRIDGE · STEP 3 OF 4', { exact: true }).isVisible());
  assert(await page.getByText('REAL SOURCE · metadata only. No real row preview is included or mixed with synthetic rows.', { exact: true }).isVisible());
  assert(await page.getByText('Real Target preview is not implemented', { exact: false }).isVisible());
  await page.getByRole('button', { name: 'Continue to Destination →' }).click();
  assert(await page.getByText('SIMULATION ONLY · No Analytics Target is connected.', { exact: true }).isVisible());
  await page.getByLabel('Dataset / table name').fill('yield_by_operation_review');
  await page.getByLabel('Update schedule').selectOption('Manual');
  await page.getByRole('button', { name: 'Create Dataset (simulation)' }).click();
  assert(await page.getByText('Yield by operation', { exact: true }).isVisible());
  assert(await page.getByText('Draft · session only', { exact: true }).isVisible());
  await page.getByRole('button', { name: 'Activity history' }).click();
  assert(await page.getByText('Yield by operation created', { exact: true }).isVisible());
  await nav.getByText('Database Connection', { exact: true }).click();
  assert(await page.getByText('Analytics Target', { exact: true }).isVisible());
  assert(await page.getByText('No Target configured.', { exact: false }).isVisible());
  assert.deepEqual(errors, []);
  await browser.close();
  console.log('PASS: reference logo/shell and four work areas; no screen-picker; empty copy state; metadata-only table visibility; field/grain/approval gates; four-step AI Data Bridge flow; Data Set and nested Activity; no Target publish.');
})().catch(error => { console.error(error); process.exit(1); });
