// Export a project's issues to CSV, import the file back, and confirm the new issues appear.
const { chromium } = require('playwright')
;(async () => {
  const b = await chromium.launch(); const pg = await (await b.newContext({ acceptDownloads: true, viewport: { width: 1440, height: 900 } })).newPage()
  await pg.goto('http://localhost:5173/login'); await pg.getByRole('button', { name: /Alice/ }).click(); await pg.getByRole('button', { name: 'Sign in' }).click()
  await pg.waitForURL(/acme-robotics/)
  await pg.getByRole('link', { name: /Web Storefront/ }).click(); await pg.waitForSelector('[data-testid^="card-"]')
  const total = async () => Number((await pg.locator('text=/\\d+ issues/').first().innerText()).match(/\d+/)[0])
  const before = await total()
  await pg.getByRole('link', { name: /Workflow/ }).click(); await pg.waitForSelector('text=Import / export issues')
  const [dl] = await Promise.all([pg.waitForEvent('download'), pg.getByRole('button', { name: /Export CSV/ }).click()])
  const path = __dirname + '/exported.csv'; await dl.saveAs(path)
  const rows = require('fs').readFileSync(path, 'utf8').trim().split('\n').length - 1
  console.log('exported file:', dl.suggestedFilename(), '| data rows:', rows)
  await pg.locator('input[type=file]').setInputFiles(path)
  await pg.waitForSelector('.toast'); console.log('toast:', await pg.locator('.toast').first().innerText())
  await pg.goBack(); await pg.waitForSelector('[data-testid^="card-"]'); await pg.reload(); await pg.waitForSelector('[data-testid^="card-"]')
  console.log('board issues before/after:', before, '->', await total()); await b.close()
})().catch(e => { console.error('FAIL', e.message.split('\n')[0]); process.exit(1) })
