import {
  expect,
  test,
  type APIRequestContext,
  type Browser,
  type Page,
} from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const TOKEN_KEY = 'gl.token.v1'
const NEW_BASE = process.env.E2E_NEW_BASE_URL ?? 'http://127.0.0.1:4174'
const FRONTEND_DIR = process.cwd()
const REPO_ROOT = path.resolve(FRONTEND_DIR, '..')
const OUT_DIR = path.join(REPO_ROOT, 'artifacts', 'frontend-iteration-2')

const TIER_LABELS: Record<string, string> = {
  Bronze: '青铜',
  Silver: '白银',
  Gold: '黄金',
  Sapphire: '蓝宝石',
  Ruby: '红宝石',
  Emerald: '翡翠',
  Amethyst: '紫水晶',
  Pearl: '珍珠',
  Obsidian: '黑曜石',
  Diamond: '钻石',
}

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
  avatar_url: string | null
  icon_theme: string
  tier: string
  today_xp: number
  required_xp: number
  xp: number
  rank: number | null
  group_size: number
  checkin: string | null
  streak: { current: number; longest: number }
  embers: { balance: number; cap: number }
  group: { no: number; tier: string } | null
  next_settlement_at: string
}

interface StandingRowPayload {
  rank: number
  user_id: string
  display_name: string
  avatar_url: string | null
  is_me: boolean
  xp: number
  checkin: string | null
  streak: number
}

interface StandingsPayload {
  group: { no: number; tier: string } | null
  group_size: number
  standings: StandingRowPayload[]
}

interface Snapshot {
  status: StatusPayload
  standings: StandingsPayload
}

function signature(snapshot: Snapshot): string {
  const { status, standings } = snapshot
  return JSON.stringify({
    user_id: status.user_id,
    today_xp: status.today_xp,
    xp: status.xp,
    rank: status.rank,
    streak: status.streak.current,
    rows: standings.standings.map((row) => [
      row.rank,
      row.display_name,
      row.xp,
      row.checkin,
      row.streak,
    ]),
    group: standings.group,
  })
}

async function fetchSnapshot(
  request: APIRequestContext,
  token: string,
): Promise<Snapshot> {
  const headers = { Authorization: `Bearer ${token}` }
  const [statusResponse, standingsResponse] = await Promise.all([
    request.get(`${NEW_BASE}/v1/me/status`, { headers }),
    request.get(`${NEW_BASE}/v1/league/standings`, { headers }),
  ])
  expect(statusResponse.ok()).toBeTruthy()
  expect(standingsResponse.ok()).toBeTruthy()
  return {
    status: (await statusResponse.json()) as StatusPayload,
    standings: (await standingsResponse.json()) as StandingsPayload,
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
    ignoreHTTPSErrors: true,
  })
  await context.addInitScript(
    ([key, value]) => window.localStorage.setItem(key, value),
    [TOKEN_KEY, token] as const,
  )
  return context
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

async function assertTouchTargets(page: Page): Promise<void> {
  const smallTargets = await page.evaluate(() => {
    const selector =
      'a[href], button, [role="button"], [role="switch"], [role="radio"], input, select'
    return Array.from(document.querySelectorAll<HTMLElement>(selector))
      .filter((node) => {
        const style = window.getComputedStyle(node)
        if (style.display === 'none' || style.visibility === 'hidden') return false
        const rect = node.getBoundingClientRect()
        return (
          rect.width > 0 &&
          rect.height > 0 &&
          rect.bottom > 0 &&
          rect.top < window.innerHeight &&
          rect.right > 0 &&
          rect.left < window.innerWidth
        )
      })
      .map((node) => {
        const rect = node.getBoundingClientRect()
        return {
          tag: node.tagName.toLowerCase(),
          label:
            node.getAttribute('aria-label') ||
            node.textContent?.trim().slice(0, 40) ||
            '',
          width: Math.round(rect.width * 10) / 10,
          height: Math.round(rect.height * 10) / 10,
        }
      })
      .filter((node) => node.width < 44 || node.height < 44)
  })
  expect(smallTargets).toEqual([])
}

async function assertIconOnlyNav(page: Page): Promise<void> {
  const visibleNav = page.locator('nav[aria-label="主导航"]:visible').first()
  await expect(visibleNav).toBeVisible()
  const links = visibleNav.locator('a')
  const count = await links.count()
  expect(count).toBeGreaterThanOrEqual(5)
  const info = await links.evaluateAll((nodes) =>
    nodes.map((node) => ({
      text: node.textContent?.trim() ?? '',
      label: node.getAttribute('aria-label') ?? '',
    })),
  )
  expect(info.map((entry) => entry.text)).toEqual(
    new Array(count).fill(''),
  )
  expect(info.every((entry) => entry.label.length > 0)).toBeTruthy()
  for (const label of ['首页', '小组', '余烬', '历史', '我的']) {
    expect(info.some((entry) => entry.label === label)).toBeTruthy()
  }
}

async function assertTierIcon(
  page: Page,
  tier: string,
  theme: string,
): Promise<void> {
  const expectedTheme = theme === 'material' ? 'material' : 'classic'
  const slug = tier.toLowerCase()
  const icon = page.getByTestId('tier-icon').first()
  await expect(icon).toBeVisible()
  await expect(icon).toHaveAttribute('data-tier', tier)
  const img = icon.locator('img')
  await expect(img).toHaveAttribute(
    'src',
    new RegExp(`/assets/tiers/${expectedTheme}/${slug}\\.png$`),
  )
  await expect
    .poll(async () => img.evaluate((node: HTMLImageElement) => node.naturalWidth))
    .toBeGreaterThan(0)
}

async function assertNoStreakCopy(page: Page): Promise<void> {
  const text = await page.locator('body').innerText()
  for (const term of ['连胜', '连续', '已打卡']) {
    expect(text).not.toContain(term)
  }
}

async function assertAvatarRows(
  page: Page,
  selector: string,
  expectedRows: number,
): Promise<void> {
  await page.waitForFunction((rowSelector) => {
    return Array.from(
      document.querySelectorAll<HTMLImageElement>(`${rowSelector} img`),
    ).every((img) => img.complete)
  }, selector)

  const checks = await page.evaluate<
    Array<{
      initial: string
      label: string
      hasImage: boolean
      imageLoaded: boolean
      fallbackVisible: boolean
      noEmptyCircle: boolean
    }>,
    string
  >((rowSelector) => {
    return Array.from(document.querySelectorAll<HTMLElement>(rowSelector)).map(
      (row) => {
        const avatar = row.querySelector<HTMLElement>('span[class*="avatar"]')
        const img = avatar?.querySelector<HTMLImageElement>('img') ?? null
        const fallback =
          avatar?.querySelector<HTMLElement>('span[class*="fallback"]') ?? null
        const style = fallback ? window.getComputedStyle(fallback) : null
        const initial = fallback?.textContent?.trim() ?? ''
        const fallbackVisible = Boolean(
          initial &&
            style &&
            style.display !== 'none' &&
            style.visibility !== 'hidden' &&
            Number(style.opacity) > 0 &&
            (fallback?.getBoundingClientRect().width ?? 0) > 0,
        )
        const imageLoaded = Boolean(
          img && img.complete && img.naturalWidth > 0 && img.naturalHeight > 0,
        )
        return {
          initial,
          label: row.getAttribute('aria-label') ?? '',
          hasImage: Boolean(img),
          imageLoaded,
          fallbackVisible,
          noEmptyCircle: imageLoaded || fallbackVisible,
        }
      },
    )
  }, selector)

  expect(checks).toHaveLength(expectedRows)
  expect(checks.every((entry) => entry.initial.length > 0)).toBeTruthy()
  expect(checks.every((entry) => entry.fallbackVisible)).toBeTruthy()
  expect(
    checks.every((entry) => !entry.hasImage || entry.imageLoaded),
  ).toBeTruthy()
  expect(checks.every((entry) => entry.noEmptyCircle)).toBeTruthy()
}

function parseRgb(value: string): [number, number, number] {
  const match = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/)
  if (!match) throw new Error(`not an rgb color: ${value}`)
  return [Number(match[1]), Number(match[2]), Number(match[3])]
}

async function streakStyles(page: Page, rowSelector: string) {
  return page.evaluate((selector) => {
    return Array.from(document.querySelectorAll<HTMLElement>(selector)).map(
      (row) => {
        const badge = row.querySelector<HTMLElement>(
          '[data-testid="streak-badge"]',
        )
        if (!badge) return null
        const flame = badge.querySelector<SVGElement>('svg')
        const number = badge.querySelector<HTMLElement>(
          '[data-streak-value]',
        )
        return {
          checked: badge.getAttribute('data-checked') === 'true',
          text: badge.textContent?.trim() ?? '',
          flame: flame ? window.getComputedStyle(flame).color : '',
          number: number ? window.getComputedStyle(number).color : '',
        }
      },
    )
  }, rowSelector)
}

const token = readToken()
test.skip(!token, 'Set GHOST_LEAGUE_TOKEN or GHOST_LEAGUE_TOKEN_FILE to run live-data capture.')

test('home, league and me use real data at 390 and 1440', async ({
  browser,
  request,
}) => {
  if (!token) return
  fs.mkdirSync(OUT_DIR, { recursive: true })

  const before = await fetchSnapshot(request, token)
  const { status, standings } = before
  if (!standings.group || standings.standings.length === 0) {
    test.skip(true, 'This account has no group this week; live capture needs one.')
    return
  }

  const tierLabel = TIER_LABELS[status.tier] ?? status.tier
  const expectedRows = standings.standings.length
  const report: Record<string, unknown> = {
    generatedAt: new Date().toISOString(),
    base: NEW_BASE,
    expected: {
      user_id: status.user_id,
      display_name: status.display_name,
      tier: status.tier,
      tier_label: tierLabel,
      icon_theme: status.icon_theme,
      today_xp: status.today_xp,
      week_xp: status.xp,
      rank: status.rank,
      group_size: status.group_size,
      streak: status.streak.current,
      rows: expectedRows,
    },
    viewports: {},
    artifacts: {},
  }
  const viewports: Record<string, unknown> = {}

  for (const viewport of [
    { width: 390, height: 844, name: '390' },
    { width: 1440, height: 900, name: '1440' },
  ]) {
    const context = await makeContext(browser, viewport, token)
    const page = await context.newPage()
    const errors = trackErrors(page)
    const pageReport: Record<string, unknown> = {}

    // ---------------------------------------------------------------- home
    await page.goto(NEW_BASE, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: tierLabel })).toBeVisible()
    await expect(page.getByRole('heading', { name: '今日 XP' })).toBeVisible()
    await assertTierIcon(page, status.tier, status.icon_theme)
    await expect(
      page.getByRole('progressbar', { name: '今日 XP 目标' }),
    ).toBeVisible()
    await expect(
      page.getByLabel(`本周名次 第 ${status.rank ?? '—'} 名`),
    ).toBeVisible()
    await expect(
      page.getByText(format(status.xp), { exact: true }).first(),
    ).toBeVisible()
    pageReport.homeOverflow = await assertNoOverflow(page)
    await assertIconOnlyNav(page)
    await assertNoStreakCopy(page)
    await assertTouchTargets(page)

    const homeBoard = page.locator(
      'section[aria-labelledby="board-title"] ol[aria-label] li',
    )
    const homeRows = await homeBoard.count()
    expect(homeRows).toBeGreaterThan(0)
    const homeStreaks = await streakStyles(
      page,
      'section[aria-labelledby="board-title"] ol[aria-label] li',
    )
    for (const entry of homeStreaks) {
      expect(entry).not.toBeNull()
      expect(entry?.text).toMatch(/^\d+$/)
      const [fr, fg, fb] = parseRgb(entry?.flame ?? '')
      const [nr, ng, nb] = parseRgb(entry?.number ?? '')
      if (entry?.checked) {
        expect(fr !== fg || fg !== fb || fr !== fb).toBeTruthy()
      } else {
        expect(fr).toBe(fg)
        expect(fg).toBe(fb)
        expect(nr).toBe(ng)
        expect(ng).toBe(nb)
      }
    }
    await assertAvatarRows(
      page,
      'section[aria-labelledby="board-title"] ol[aria-label] li',
      homeRows,
    )

    const homeShot = path.join(OUT_DIR, viewport.name, 'home.png')
    fs.mkdirSync(path.dirname(homeShot), { recursive: true })
    await page.screenshot({
      path: homeShot,
      fullPage: false,
      animations: 'disabled',
    })
    report.artifacts = {
      ...(report.artifacts as Record<string, string>),
      [`${viewport.name}/home.png`]: path.relative(REPO_ROOT, homeShot),
    }
    pageReport.home = { rows: homeRows, streaks: homeStreaks }

    // -------------------------------------------------------------- league
    await page.goto(`${NEW_BASE}/league`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { name: tierLabel })).toBeVisible()
    const list = page.getByRole('list', { name: '完整小组榜' })
    await expect(list).toBeVisible()
    const leagueRows = list.locator('li')
    await expect(leagueRows).toHaveCount(expectedRows)
    await assertTierIcon(page, status.tier, status.icon_theme)
    await assertNoOverflow(page)
    await assertIconOnlyNav(page)
    await assertNoStreakCopy(page)
    await assertTouchTargets(page)

    const leagueText = await list.innerText()
    for (const term of ['语言', '今日已完成', '今日未完成', '连续', '连胜']) {
      expect(leagueText).not.toContain(term)
    }
    const meRow = list.locator('li[data-me="true"]')
    await expect(meRow).toHaveCount(1)
    await expect(meRow).toHaveAttribute(
      'aria-label',
      new RegExp(`${status.display_name}，第 ${status.rank} 名.*我的位置`),
    )
    const meHighlight = await meRow.evaluate(
      (node) => window.getComputedStyle(node).backgroundImage,
    )
    expect(meHighlight).not.toBe('none')

    const leagueStreaks = await streakStyles(
      page,
      'ol[aria-label="完整小组榜"] li',
    )
    expect(leagueStreaks).toHaveLength(expectedRows)
    let checkedCount = 0
    let uncheckedCount = 0
    for (let index = 0; index < leagueStreaks.length; index += 1) {
      const entry = leagueStreaks[index]!
      const row = standings.standings[index]!
      expect(entry).not.toBeNull()
      expect(entry.text).toMatch(/^\d+$/)
      expect(entry.text).toBe(String(row.streak))
      expect(entry.checked).toBe(Boolean(row.checkin))
      const [fr, fg, fb] = parseRgb(entry.flame)
      const [nr, ng, nb] = parseRgb(entry.number)
      if (entry.checked) {
        checkedCount += 1
        expect(fr !== fg || fg !== fb || fr !== fb).toBeTruthy()
      } else {
        uncheckedCount += 1
        expect(fr).toBe(fg)
        expect(fg).toBe(fb)
        expect(nr).toBe(ng)
        expect(ng).toBe(nb)
      }
    }
    expect(checkedCount).toBeGreaterThan(0)
    expect(uncheckedCount).toBeGreaterThan(0)
    await assertAvatarRows(
      page,
      'ol[aria-label="完整小组榜"] li',
      expectedRows,
    )

    const leagueShot = path.join(OUT_DIR, viewport.name, 'league.png')
    await page.screenshot({
      path: leagueShot,
      fullPage: false,
      animations: 'disabled',
    })
    report.artifacts = {
      ...(report.artifacts as Record<string, string>),
      [`${viewport.name}/league.png`]: path.relative(REPO_ROOT, leagueShot),
    }
    pageReport.league = {
      rows: expectedRows,
      checked: checkedCount,
      unchecked: uncheckedCount,
      me: status.rank,
    }

    // ------------------------------------------------------------------ me
    await page.goto(`${NEW_BASE}/me`, { waitUntil: 'domcontentloaded' })
    await expect(
      page.getByRole('heading', { name: status.display_name }),
    ).toBeVisible()
    await assertTierIcon(page, status.tier, status.icon_theme)
    await assertNoOverflow(page)
    await assertIconOnlyNav(page)
    await assertNoStreakCopy(page)
    await assertTouchTargets(page)
    await expect(
      page.getByRole('progressbar', { name: '今日 XP 目标' }),
    ).toBeVisible()
    await expect(
      page.getByText(format(status.xp), { exact: true }).first(),
    ).toBeVisible()
    const meStreaks = await streakStyles(page, 'main')
    expect(meStreaks.filter(Boolean).length).toBeGreaterThan(0)
    await assertAvatarRows(page, 'main section[aria-labelledby="me-name"]', 1)

    const meShot = path.join(OUT_DIR, viewport.name, 'me.png')
    await page.screenshot({
      path: meShot,
      fullPage: false,
      animations: 'disabled',
    })
    report.artifacts = {
      ...(report.artifacts as Record<string, string>),
      [`${viewport.name}/me.png`]: path.relative(REPO_ROOT, meShot),
    }
    pageReport.me = { streaks: meStreaks.filter(Boolean) }

    expect(errors.console).toEqual([])
    expect(errors.page).toEqual([])
    pageReport.consoleErrors = errors.console
    pageReport.pageErrors = errors.page
    viewports[viewport.name] = pageReport
    await context.close()
  }

  const after = await fetchSnapshot(request, token)
  expect(signature(after)).toBe(signature(before))
  report.after = signature(after)
  report.viewports = viewports
  const reportPath = path.join(OUT_DIR, 'report.json')
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8')
  expect(fs.existsSync(reportPath)).toBeTruthy()
})
