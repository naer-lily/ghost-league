import { expect, test, type Browser, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const TOKEN_KEY = 'gl.token.v1'
const NEW_BASE = process.env.E2E_NEW_BASE_URL ?? 'http://127.0.0.1:4174'
const FRONTEND_DIR = process.cwd()
const REPO_ROOT = path.resolve(FRONTEND_DIR, '..')
const OUT_DIR = path.join(
  REPO_ROOT,
  'artifacts',
  'prototype-today-progress-web-next',
)

const TIER_MINUTES = [10, 30, 60, 120, 180, 240] as const
const TIER_XP = [100, 300, 600, 1200, 1800, 2400] as const

const numberFormat = new Intl.NumberFormat('zh-CN')

function format(value: number): string {
  return numberFormat.format(Math.max(0, Math.trunc(value)))
}

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

interface StatusPayload {
  user_id: string
  display_name: string
  today_xp: number
  today_seconds: number
  updated_at: string
}

interface ProfilePayload {
  display_name: string
  [key: string]: unknown
}

interface StandingsPayload {
  [key: string]: unknown
}

function expectedView(todayXp: number) {
  const completed = TIER_XP.filter((xp) => todayXp >= xp).length
  const allComplete = completed === TIER_XP.length
  const currentIndex = allComplete ? TIER_XP.length - 1 : completed
  return {
    completed,
    currentIndex,
    currentMinutes: TIER_MINUTES[currentIndex]!,
    remaining: allComplete ? 0 : TIER_XP[currentIndex]! - todayXp,
    allComplete,
  }
}

async function assertTodayProgress(
  page: Page,
  todayXp: number,
  todayMinutes: number,
): Promise<{
  states: string[]
  progress: string | null
  valueText: string
}> {
  const expected = expectedView(todayXp)
  const scope = page.getByTestId('today-progress')
  await expect(scope).toBeVisible()
  await expect(scope.getByRole('heading', { name: '今日进度' })).toBeVisible()

  const xpStat = scope.locator('dl > div').nth(0)
  await expect(xpStat.locator('dt')).toHaveText('今日 XP')
  await expect(xpStat.locator('dd')).toContainText(format(todayXp))
  const minutesStat = scope.locator('dl > div').nth(1)
  await expect(minutesStat.locator('dt')).toHaveText('今日分钟')
  await expect(minutesStat.locator('dd')).toContainText(String(todayMinutes))

  const bar = page.getByRole('progressbar', { name: '今日 XP 目标' })
  await expect(bar).toBeVisible()
  await expect(bar).toHaveAttribute('aria-valuemin', '0')
  await expect(bar).toHaveAttribute('aria-valuemax', '2400')
  await expect(bar).toHaveAttribute(
    'aria-valuenow',
    String(Math.min(2400, todayXp)),
  )
  const valueText = (await bar.getAttribute('aria-valuetext')) ?? ''
  expect(valueText).toContain(`${todayXp} XP`)
  if (expected.allComplete) {
    expect(valueText).toContain('六档目标全部达成')
  } else {
    expect(valueText).toContain(`还差 ${expected.remaining} XP`)
  }

  const tiers = page.getByTestId('today-tier')
  await expect(tiers).toHaveCount(6)
  const tierTexts = await tiers.evaluateAll((nodes) =>
    nodes.map((node) => (node.textContent ?? '').replace(/\s+/g, '')),
  )
  expect(tierTexts).toEqual(
    TIER_MINUTES.map((minutes) => `${minutes}分钟`),
  )
  const states = await tiers.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute('data-state') ?? ''),
  )
  expect(states).toEqual(
    TIER_XP.map((xp, index) =>
      todayXp >= xp ? 'complete' : index === expected.currentIndex ? 'current' : 'future',
    ),
  )

  await expect(page.getByTestId('today-current-tier')).toHaveText(
    `第 ${expected.currentIndex + 1} 档 · ${expected.currentMinutes} 分钟`,
  )
  await expect(page.getByTestId('today-remaining')).toHaveText(
    expected.allComplete ? '六档全部达成' : `还差 ${expected.remaining} XP`,
  )

  const readability = await tiers.evaluateAll((nodes) =>
    nodes.map((node) => {
      const label = node.querySelector<HTMLElement>('span')
      const number = label?.querySelector<HTMLElement>('span')
      const rect = label?.getBoundingClientRect()
      return {
        width: rect?.width ?? 0,
        height: rect?.height ?? 0,
        fontSize: number
          ? Number.parseFloat(window.getComputedStyle(number).fontSize)
          : 0,
        overflow: node.scrollWidth - node.clientWidth,
      }
    }),
  )
  for (const entry of readability) {
    expect(entry.width).toBeGreaterThan(20)
    expect(entry.height).toBeGreaterThan(8)
    expect(entry.fontSize).toBeGreaterThanOrEqual(8)
    expect(entry.overflow).toBeLessThanOrEqual(1)
  }

  return {
    states,
    progress: await bar.getAttribute('data-progress'),
    valueText,
  }
}

async function assertNoOverflow(page: Page): Promise<number> {
  const overflow = await page.evaluate(() => {
    return (
      Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) -
      window.innerWidth
    )
  })
  expect(overflow).toBeLessThanOrEqual(1)
  return overflow
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

async function makeContext(
  browser: Browser,
  viewport: { width: number; height: number },
  token: string,
) {
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 1,
    ignoreHTTPSErrors: true,
  })
  await context.addInitScript(
    ([key, value]) => window.localStorage.setItem(key, value),
    [TOKEN_KEY, token] as const,
  )
  return context
}

const PROFILE = {
  user_id: 'naer-lily',
  display_name: '那尔',
  avatar_url: null,
  activity_label: '绘画',
  icon_theme: 'material',
  tier: 'Bronze',
  group_id: 1,
  group_no: 1,
  joined_week: '2026-10-26',
  week_start: '2026-10-26',
  equipped_title: '小丑',
  frame: '余烬',
  backdrop: null,
  badge_accent: null,
  updated_at: '2026-10-31T09:06:34+08:00',
}

function mockStatus(updatedAt: string) {
  return {
    user_id: 'naer-lily',
    display_name: '那尔',
    avatar_url: null,
    activity_label: '绘画',
    icon_theme: 'material',
    tier: 'Bronze',
    group: {
      id: 1,
      no: 1,
      tier: 'Bronze',
      week_start: '2026-10-26',
      size: 5,
    },
    group_id: 1,
    group_size: 5,
    week_start: '2026-10-26',
    seconds: 3149,
    xp: 524,
    rank: 4,
    power: 1667,
    power_percentile: 0.625,
    power_updated_at: updatedAt,
    power_provisional: false,
    today_seconds: 779,
    today_xp: 129,
    required_xp: 100,
    checkin: 'verified',
    streak: {
      current: 2,
      longest: 2,
      clean_current: 2,
      last_checked_date: '2026-10-31',
    },
    embers: { balance: 0, cap: 3, earned_this_week: 0 },
    gems: 52,
    diamonds: 720,
    diamond_cap: 1000,
    diamond_cap_level: 0,
    diamond_excess: 0,
    inventory: { star: 0, seasonal_star: 0, ember: 0 },
    stars: [],
    equipped_title: '小丑',
    equipped_title_id: 'title_clown',
    frame: '余烬',
    frame_id: 'frame_ember',
    backdrop: null,
    badge_accent: null,
    next_settlement_at: '2026-11-02T00:00:00+08:00',
    updated_at: updatedAt,
  }
}

function standingRow(
  rank: number,
  user_id: string,
  display_name: string,
  xp: number,
  is_me = false,
  checkin: string | null = rank === 1 ? null : 'verified',
  streak = 2,
) {
  return {
    rank,
    user_id,
    display_name,
    avatar_url: null,
    is_me,
    xp,
    power: 1200,
    checkin,
    streak,
    title: rank === 1 ? '点火' : '三日不息',
    frame: '余烬',
    frame_id: 'frame_ember',
    backdrop: null,
  }
}

const STANDINGS = {
  week_start: '2026-10-26',
  group: {
    id: 1,
    no: 1,
    tier: 'Bronze',
    week_start: '2026-10-26',
    size: 5,
  },
  group_id: 1,
  group_size: 5,
  me: { rank: 4, xp: 524 },
  standings: [
    standingRow(1, 'ch-xkein', '@Xkein', 8019),
    standingRow(2, 'ch-roger', 'RogerRordo', 4975),
    standingRow(3, 'ch-red', 'RedMcro', 4244),
    standingRow(4, 'naer-lily', '那尔', 524, true),
    standingRow(5, 'ch-shai', '筛滤淘', 453, false, 'verified', 2),
  ],
}

async function mockHomeApi(page: Page, updatedAt: string) {
  await page.route('**/v1/me/profile', (route) =>
    route.fulfill({ json: PROFILE }),
  )
  await page.route('**/v1/me/status', (route) =>
    route.fulfill({ json: mockStatus(updatedAt) }),
  )
  await page.route('**/v1/league/standings', (route) =>
    route.fulfill({ json: STANDINGS }),
  )
}

const token = readToken()

test.describe('today progress live capture', () => {
  test.skip(
    !token,
    'Set GHOST_LEAGUE_TOKEN or GHOST_LEAGUE_TOKEN_FILE to capture live data.',
  )

  test('captures the real home at 390x844 and 1440x1000', async ({
    browser,
    request,
  }) => {
    if (!token) return
    fs.mkdirSync(OUT_DIR, { recursive: true })

    const headers = { Authorization: `Bearer ${token}` }
    const [profileResponse, statusResponse, standingsResponse] =
      await Promise.all([
        request.get(`${NEW_BASE}/v1/me/profile`, { headers }),
        request.get(`${NEW_BASE}/v1/me/status`, { headers }),
        request.get(`${NEW_BASE}/v1/league/standings`, { headers }),
      ])
    expect(profileResponse.ok()).toBeTruthy()
    expect(statusResponse.ok()).toBeTruthy()
    expect(standingsResponse.ok()).toBeTruthy()
    const profile = (await profileResponse.json()) as ProfilePayload
    const status = (await statusResponse.json()) as StatusPayload
    const standings = (await standingsResponse.json()) as StandingsPayload
    expect(standings).toBeTruthy()

    const todayMinutes = Math.floor(status.today_seconds / 60)
    const report: Record<string, unknown> = {
      generatedAt: new Date().toISOString(),
      base: NEW_BASE,
      data: {
        user_id: status.user_id,
        display_name: status.display_name,
        today_xp: status.today_xp,
        today_seconds: status.today_seconds,
        today_minutes: todayMinutes,
        updated_at: status.updated_at,
      },
      viewports: {},
    }
    const viewportReports: Record<string, unknown> = {}

    for (const viewport of [
      { width: 390, height: 844, name: '390' },
      { width: 1440, height: 1000, name: '1440' },
    ]) {
      const context = await makeContext(browser, viewport, token)
      const page = await context.newPage()
      const errors = trackErrors(page)

      await page.goto(NEW_BASE, { waitUntil: 'domcontentloaded' })
      await expect(
        page.getByRole('heading', { name: profile.display_name }),
      ).toBeVisible()

      const barInfo = await assertTodayProgress(
        page,
        status.today_xp,
        todayMinutes,
      )
      // The live API stamps updated_at when the status is read, so the live
      // capture should show the recent-update marker. The stale/absent case is
      // covered separately with deterministic route fixtures below.
      await expect(page.getByTestId('recent-update')).toBeVisible()
      const overflow = await assertNoOverflow(page)

      const shot = path.join(OUT_DIR, `home-${viewport.name}.png`)
      fs.mkdirSync(path.dirname(shot), { recursive: true })
      await page.screenshot({
        path: shot,
        fullPage: false,
        animations: 'disabled',
      })

      expect(errors.console).toEqual([])
      expect(errors.page).toEqual([])
      viewportReports[viewport.name] = {
        ...barInfo,
        overflow,
        fireVisible: true,
        screenshot: path.relative(REPO_ROOT, shot),
        consoleErrors: errors.console,
        pageErrors: errors.page,
      }
      await context.close()
    }

    report.viewports = viewportReports
    const reportPath = path.join(OUT_DIR, 'report.json')
    fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8')
    expect(fs.existsSync(reportPath)).toBeTruthy()
  })
})

test.describe('today progress recent/stale marker', () => {
  for (const viewport of [
    { width: 390, height: 844, name: '390' },
    { width: 1440, height: 1000, name: '1440' },
  ]) {
    test(`handles recent and stale updates at ${viewport.name}`, async ({
      browser,
    }) => {
      fs.mkdirSync(OUT_DIR, { recursive: true })
      const results: Record<string, unknown> = {}

      for (const scenario of [
        { name: 'recent', ageMs: 2 * 60_000, shouldShow: true },
        { name: 'stale', ageMs: 20 * 60_000, shouldShow: false },
      ]) {
        const context = await browser.newContext({
          viewport,
          deviceScaleFactor: 1,
          ignoreHTTPSErrors: true,
        })
        await context.addInitScript(
          ([key, value]) => window.localStorage.setItem(key, value),
          [TOKEN_KEY, 'e2e-fixture-token'] as const,
        )
        const page = await context.newPage()
        const errors = trackErrors(page)
        const updatedAt = new Date(Date.now() - scenario.ageMs).toISOString()
        await mockHomeApi(page, updatedAt)

        await page.goto(NEW_BASE, { waitUntil: 'domcontentloaded' })
        await expect(page.getByTestId('today-progress')).toBeVisible()

        const barInfo = await assertTodayProgress(page, 129, 12)
        if (scenario.shouldShow) {
          await expect(page.getByTestId('recent-update')).toBeVisible()
          await expect(page.getByTestId('recent-update')).toHaveText(
            '刚刚更新',
          )
        } else {
          await expect(page.getByTestId('recent-update')).toHaveCount(0)
        }
        const overflow = await assertNoOverflow(page)
        expect(errors.console).toEqual([])
        expect(errors.page).toEqual([])

        results[scenario.name] = {
          updatedAt,
          fireVisible: scenario.shouldShow,
          overflow,
          ...barInfo,
          consoleErrors: errors.console,
          pageErrors: errors.page,
        }
        await context.close()
      }

      const reportPath = path.join(
        OUT_DIR,
        `recent-stale-${viewport.name}.json`,
      )
      fs.writeFileSync(reportPath, `${JSON.stringify(results, null, 2)}\n`, 'utf8')
    })
  }

  test('keeps the bar readable with prefers-reduced-motion', async ({
    browser,
  }) => {
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 1,
      ignoreHTTPSErrors: true,
    })
    await context.addInitScript(
      ([key, value]) => window.localStorage.setItem(key, value),
      [TOKEN_KEY, 'e2e-fixture-token'] as const,
    )
    const page = await context.newPage()
    const errors = trackErrors(page)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await mockHomeApi(page, new Date(Date.now() - 2 * 60_000).toISOString())

    await page.goto(NEW_BASE, { waitUntil: 'domcontentloaded' })
    await assertTodayProgress(page, 129, 12)
    await expect(page.getByTestId('recent-update')).toBeVisible()
    await assertNoOverflow(page)

    const activeAnimations = await page.evaluate(() => {
      const root = document.querySelector('[data-testid="today-progress"]')
      if (!root) return ['missing']
      return Array.from(root.querySelectorAll<HTMLElement>('*'))
        .map((node) => {
          const style = window.getComputedStyle(node)
          const duration = Number.parseFloat(style.animationDuration)
          return {
            name: style.animationName,
            duration: Number.isFinite(duration) ? duration : 0,
          }
        })
        .filter((entry) => entry.name !== 'none' && entry.duration > 0.01)
        .map((entry) => entry.name)
    })
    expect(activeAnimations).toEqual([])
    expect(errors.console).toEqual([])
    expect(errors.page).toEqual([])
    await context.close()
  })
})
