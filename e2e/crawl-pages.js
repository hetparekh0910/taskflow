const { chromium } = require('playwright')
const OUT = __dirname
;(async () => {
  const b = await chromium.launch()
  const pg = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
  const errs = []
  pg.on('pageerror', e => errs.push('pageerror: ' + e.message))
  pg.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)) })
  await pg.goto('http://localhost:5173/login')
  await pg.getByRole('button', { name: /Alice/ }).click(); await pg.getByRole('button', { name: 'Sign in' }).click()
  await pg.waitForURL(/\/w\/acme-robotics/)
  const base = 'http://localhost:5173/w/acme-robotics'
  const pid = (await pg.getByRole('link', { name: /Web Storefront/ }).getAttribute('href')).split('/').pop()
  const routes = ['', '/projects', `/projects/${pid}`, `/projects/${pid}/backlog`, `/projects/${pid}/settings`, '/my-issues', '/team', '/webhooks', '/audit', '/reports', '/billing']
  for (const r of routes) {
    await pg.goto(base + r); await pg.waitForLoadState('networkidle'); await pg.waitForTimeout(400)
    const bad = await pg.locator('.error').count()
    console.log((r || '/dashboard').padEnd(24), bad ? 'API ERROR BOX' : 'ok', '|', (await pg.locator('h1').first().innerText().catch(() => '?')).slice(0, 40))
    await pg.screenshot({ path: `${OUT}/p-${(r || 'dash').replace(/\//g, '_')}.png` })
  }
  // mock upgrade: Globex (free) as owner Gina
  await pg.evaluate(() => localStorage.clear()); await pg.goto('http://localhost:5173/login')
  await pg.getByRole('button', { name: /Gina/ }).click(); await pg.getByRole('button', { name: 'Sign in' }).click()
  await pg.waitForURL(/globex-labs/); await pg.goto('http://localhost:5173/w/globex-labs/billing'); await pg.waitForLoadState('networkidle')
  await pg.screenshot({ path: OUT + '/billing-free.png' })
  await pg.getByRole('button', { name: /Upgrade to Pro|Choose Pro|Upgrade/ }).first().click()
  await pg.waitForURL(/mock-checkout/); await pg.waitForLoadState('networkidle')
  await pg.screenshot({ path: OUT + '/mock-checkout.png' })
  await pg.getByRole('button', { name: /Pay|Confirm|Subscribe/ }).first().click()
  await pg.waitForTimeout(1500); await pg.waitForLoadState('networkidle')
  console.log('after pay url:', pg.url(), '| plan badge:', (await pg.locator('.sidebar .badge').first().innerText()))
  console.log('errors:', errs.length ? errs : 'none')
  await b.close()
})().catch(e => { console.error('FAIL', e.message.split('\n')[0]); process.exit(1) })
