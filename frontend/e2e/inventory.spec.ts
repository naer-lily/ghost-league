import { expect, test, type Browser, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const TOKEN_KEY = 'gl.token.v1'
const BASE = 'http://127.0.0.1:4174'
const REPO_ROOT = path.resolve(process.cwd(), '..')
const OUT_DIR = path.join(REPO_ROOT, 'artifacts', 'ghost-inventory-shop')

const VIEWPORTS = [
  { name: '390', width: 390, height: 844 },
  { name: '1440', width: 1440, height: 1000 },
] as const

function readToken(): string | null {
  const direct = process.env.GHOST_LEAGUE_TOKEN?.trim()
  if (direct) return direct
  const file = process.env.GHOST_LEAGUE_TOKEN_FILE
  if (!file) return null
  try {
    return fs.readFileSync(file, 'utf8').trim() || null
  } catch {
    return null
  }
}

async function makeContext(
  browser: Browser,
  viewport: { width: number; height: number },
  token: string,
) {
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 1,
    hasTouch: true,
    ignoreHTTPSErrors: true,
  })
  await context.addInitScript(
    ([key, value]) => window.localStorage.setItem(key, value),
    [TOKEN_KEY, token] as const,
  )
  return context
}

async function assertNoOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () =>
      Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) -
      window.innerWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
}

const token = readToken()
test.skip(!token, 'Set GHOST_LEAGUE_TOKEN or GHOST_LEAGUE_TOKEN_FILE to run UI capture.')

for (const viewport of VIEWPORTS) {
  test(`inventory and shop walk ${viewport.name}`, async ({ browser }) => {
    if (!token) throw new Error('missing token')
    fs.mkdirSync(OUT_DIR, { recursive: true })
    const context = await makeContext(browser, viewport, token)
    const page = await context.newPage()
    const consoleErrors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })

    await page.goto(`${BASE}/inventory`)
    await expect(page.getByRole('heading', { name: '物品' })).toBeVisible()
    await expect(page.getByTestId('inventory-shop')).toBeVisible()
    for (const category of ['stars', 'embers', 'cap', 'other']) {
      const card = page.getByTestId(`shop-category-${category}`)
      if (await card.count()) await expect(card).toBeVisible()
    }
    await assertNoOverflow(page)
    await page.screenshot({
      path: path.join(OUT_DIR, `inventory-${viewport.name}.png`),
      fullPage: true,
    })
    await page.getByTestId('inventory-shop').screenshot({
      path: path.join(OUT_DIR, `inventory-shop-${viewport.name}.png`),
    })

    for (const id of ['frames', 'titles', 'other']) {
      await page.getByTestId(`inventory-tab-${id}`).click()
      await expect(page.getByTestId(`inventory-tab-${id}`)).toHaveAttribute(
        'aria-selected',
        'true',
      )
      await assertNoOverflow(page)
      await page.screenshot({
        path: path.join(OUT_DIR, `inventory-${id}-${viewport.name}.png`),
        fullPage: true,
      })
    }

    expect(consoleErrors).toEqual([])
    await context.close()
  })
}
