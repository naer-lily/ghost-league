import { expect, test, type Browser, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const TOKEN_KEY = 'gl.token.v1'
const BASE = process.env.E2E_NEW_BASE_URL ?? 'http://127.0.0.1:4174'
const REPO_ROOT = path.resolve(process.cwd(), '..')
const OUT_DIR = path.join(REPO_ROOT, 'artifacts', 'ghost-ui-group1')

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

function trackErrors(page: Page): { console: string[]; page: string[] } {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => pageErrors.push(error.message))
  return { console: consoleErrors, page: pageErrors }
}

async function assertNoOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () =>
      Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) -
      window.innerWidth,
  )
  expect(overflow).toBeLessThanOrEqual(1)
}

async function assertNoGroupCopy(page: Page): Promise<void> {
  const text = await page.locator('body').innerText()
  expect(text).not.toMatch(/我的组|组号|G0\d/)
  expect(text).not.toContain('第 2 档')
  expect(text).not.toContain('星库')
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

async function pullToRefresh(page: Page): Promise<void> {
  await page.evaluate(() => window.scrollTo(0, 0))
  const wrap = page.getByTestId('pull-to-refresh')
  await expect(wrap).toBeVisible()
  await wrap.evaluate((node) => {
    const target = node as HTMLElement
    const start = new Touch({
      identifier: 1,
      target,
      clientX: 60,
      clientY: 20,
    })
    const move = new Touch({
      identifier: 1,
      target,
      clientX: 60,
      clientY: 220,
    })
    target.dispatchEvent(
      new TouchEvent('touchstart', {
        bubbles: true,
        cancelable: true,
        touches: [start],
        targetTouches: [start],
        changedTouches: [start],
      }),
    )
    target.dispatchEvent(
      new TouchEvent('touchmove', {
        bubbles: true,
        cancelable: true,
        touches: [move],
        targetTouches: [move],
        changedTouches: [move],
      }),
    )
    target.dispatchEvent(
      new TouchEvent('touchend', {
        bubbles: true,
        cancelable: true,
        touches: [],
        targetTouches: [],
        changedTouches: [move],
      }),
    )
  })
}

const token = readToken()
test.skip(!token, 'Set GHOST_LEAGUE_TOKEN or GHOST_LEAGUE_TOKEN_FILE to run UI capture.')

for (const viewport of VIEWPORTS) {
  test(`group 1 UI walk ${viewport.name}x${viewport.height}`, async ({
    browser,
  }) => {
    if (!token) throw new Error('missing token')
    fs.mkdirSync(OUT_DIR, { recursive: true })
    const context = await makeContext(browser, viewport, token)
    const page = await context.newPage()
    const errors = trackErrors(page)

    // Home with the real rival state.
    await page.goto(`${BASE}/`)
    await expect(page.getByTestId('home-rival')).toBeVisible()
    await expect(page.getByTestId('today-progress')).toBeVisible()
    await expect(page.getByTestId('player-tier')).not.toContainText('G0')
    await expect(page.getByText('小组榜')).toHaveCount(0)
    const rivalCard = page.getByTestId('rival-duel-card')
    if (await rivalCard.count()) {
      await expect(rivalCard).toBeVisible()
      await expect(page.getByTestId('rival-bet-status-日注')).toBeVisible()
      await expect(page.getByTestId('rival-bet-status-周注')).toHaveCount(0)
      await expect(page.getByTestId('rival-week-countdown')).toHaveCount(0)
      await expect(page.getByTestId('rival-daily-countdown')).toBeVisible()
      await expect(page.getByTestId('rival-bet-status-组注')).toHaveCount(0)
      await expect(rivalCard).not.toContainText('组注')
      const openBets = page.getByRole('button', { name: '下注' })
      await expect(openBets).toBeVisible()
      await openBets.click()
      const betDialog = page.getByTestId('rival-bet-dialog')
      await expect(betDialog).toBeVisible()
      await expect(betDialog.getByRole('tab')).toHaveCount(0)
      await expect(
        betDialog.getByText('押「今天我比宿敌多多少 XP」'),
      ).toBeVisible()
      await expect(betDialog.getByTestId('rival-target-50')).toBeVisible()
      await expect(betDialog.getByTestId('rival-target-150')).toHaveCount(0)
      await expect(betDialog.getByTestId('rival-bet-paid-input')).toBeVisible()
      await page.screenshot({
        path: path.join(OUT_DIR, `home-bet-dialog-${viewport.name}.png`),
        fullPage: true,
      })
      await betDialog.getByRole('button', { name: '关闭下注对话框' }).click()
    }
    await assertNoGroupCopy(page)
    await assertNoOverflow(page)
    await page.screenshot({
      path: path.join(OUT_DIR, `home-${viewport.name}.png`),
      fullPage: true,
    })

    // Pull to refresh uses the real callback and shows the refresh status.
    await pullToRefresh(page)
    await expect(page.getByText('联赛数据已刷新。')).toBeVisible({
      timeout: 20_000,
    })

    // Home without a rival: force only the rival payload to be empty.
    const rivalResponse = await page.request.get(`${BASE}/v1/me/rival`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(rivalResponse.ok()).toBeTruthy()
    const liveRival = await rivalResponse.json()
    await page.route('**/v1/me/rival', async (route) => {
      if (route.request().method() !== 'GET') return route.continue()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...liveRival, rival: null }),
      })
    })
    await page.reload()
    await expect(page.getByText('还没有宿敌')).toBeVisible()
    const candidateResponse = page.waitForResponse((response) =>
      response.url().includes('/v1/me/rival/candidates'),
    )
    await page.getByRole('button', { name: '选择宿敌' }).click()
    await candidateResponse
    await expect(page.getByLabel('宿敌候选区域')).toBeVisible()
    await expect(
      page
        .locator('[data-testid^="rival-candidate-"]')
        .first()
        .or(page.getByText('本周暂时没有可选的跨组候选。')),
    ).toBeVisible()
    await assertNoOverflow(page)
    await page.screenshot({
      path: path.join(OUT_DIR, `home-no-rival-${viewport.name}.png`),
      fullPage: true,
    })
    await page.unroute('**/v1/me/rival')

    // League tabs and the personal top-three group bet entry.
    await page.goto(`${BASE}/league`)
    await expect(page.getByTestId('board-tab-group')).toBeVisible()
    await expect(page.getByTestId('board-tab-friends')).toBeVisible()
    await expect(page.getByRole('list', { name: '完整小组榜' })).toBeVisible()
    const groupCard = page.getByTestId('group-bet-card')
    if (await groupCard.count()) {
      await expect(groupCard).toContainText('押前三')
      await expect(groupCard).toContainText('押升段')
      await expect(groupCard).not.toContainText('小组总 XP')
      await expect(
        groupCard.getByTestId('group-market-odds-top3'),
      ).toBeVisible()
      await page.screenshot({
        path: path.join(OUT_DIR, `league-group-${viewport.name}.png`),
        fullPage: true,
      })
      await groupCard.getByTestId('group-bet-open-top3').click()
      const groupDialog = page.getByTestId('group-bet-dialog')
      await expect(groupDialog).toBeVisible()
      await expect(
        groupDialog.getByRole('heading', { name: '押前三' }),
      ).toBeVisible()
      await expect(groupDialog.getByTestId('group-bet-paid-input')).toBeVisible()
      await page.evaluate(() => window.scrollTo(0, 0))
      await page.screenshot({
        path: path.join(OUT_DIR, `league-group-dialog-${viewport.name}.png`),
        fullPage: true,
      })
      await groupDialog.getByRole('button', { name: '关闭押前三对话框' }).click()
    } else {
      await page.screenshot({
        path: path.join(OUT_DIR, `league-group-${viewport.name}.png`),
        fullPage: true,
      })
    }
    await page.getByTestId('board-tab-friends').click()
    await expect(
      page
        .getByRole('list', { name: '好友榜' })
        .or(page.getByTestId('friends-empty')),
    ).toBeVisible()
    await expect(page.getByTestId('group-bet-card')).toHaveCount(0)
    await assertNoOverflow(page)
    await page.screenshot({
      path: path.join(OUT_DIR, `league-friends-${viewport.name}.png`),
      fullPage: true,
    })

    // No group option: the card must disappear instead of faking a bet.
    const betsResponse = await page.request.get(`${BASE}/v1/me/bets`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    expect(betsResponse.ok()).toBeTruthy()
    const liveBets = await betsResponse.json()
    await page.route('**/v1/me/bets', async (route) => {
      if (route.request().method() !== 'GET') return route.continue()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...liveBets,
          group: null,
          groups: [],
          bets: { ...liveBets.bets, group: null, groups: [] },
          bet_options: { ...liveBets.bet_options, group: null },
        }),
      })
    })
    await page.goto(`${BASE}/league`)
    await expect(page.getByRole('list', { name: '完整小组榜' })).toBeVisible()
    await expect(page.getByTestId('group-bet-card')).toHaveCount(0)
    await assertNoOverflow(page)
    await page.screenshot({
      path: path.join(OUT_DIR, `league-no-group-bet-${viewport.name}.png`),
      fullPage: true,
    })
    await page.unroute('**/v1/me/bets')

    // Inventory categories.
    await page.goto(`${BASE}/inventory`)
    await expect(page.getByRole('heading', { name: '物品' })).toBeVisible()
    await expect(page.getByTestId('inventory-shop')).toBeVisible()
    await expect(page.getByTestId('shop-category-stars')).toBeVisible()
    await expect(page.getByTestId('shop-category-embers')).toBeVisible()
    for (const id of ['stars', 'frames', 'titles', 'other']) {
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

    // Me page: horizontal stages, diamonds/streak, settings volume.
    await page.goto(`${BASE}/me`)
    await expect(page.getByTestId('tier-progress')).toBeVisible()
    await expect(page.getByTestId('tier-stage')).toHaveCount(10)
    const currentStage = page.locator(
      '[data-testid="tier-stage"][data-state="current"]',
    )
    await expect(currentStage).toHaveCount(1)
    const currentIndex = await page
      .locator('[data-testid="tier-stage"]')
      .evaluateAll((nodes) =>
        nodes.findIndex((node) => node.getAttribute('data-state') === 'current'),
      )
    if (currentIndex < 8) {
      await expect(
        page.locator('[data-testid="tier-stage"][data-state="fog"]').first(),
      ).toBeVisible()
    }
    await expect(page.getByTestId('player-diamonds')).toBeVisible()
    await expect(page.getByTestId('streak-badge')).toBeVisible()
    await expect(page.getByTestId('me-stat-week')).toBeVisible()
    await expect(page.getByTestId('me-stat-rank')).toBeVisible()
    await assertNoGroupCopy(page)
    await assertNoOverflow(page)
    await page.screenshot({
      path: path.join(OUT_DIR, `me-${viewport.name}.png`),
      fullPage: true,
    })

    await page.getByRole('button', { name: /设置/ }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByRole('heading', { name: '音量' })).toBeVisible()
    await page.screenshot({
      path: path.join(OUT_DIR, `me-settings-${viewport.name}.png`),
      fullPage: true,
    })

    expect(errors.page).toEqual([])
    expect(errors.console).toEqual([])
    await context.close()
  })
}
