import { expect, test, type APIRequestContext, type Browser } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const TOKEN_KEY = 'gl.token.v1'
const NEW_BASE = process.env.E2E_NEW_BASE_URL ?? 'http://127.0.0.1:4174'
const OLD_BASE = process.env.E2E_OLD_BASE_URL ?? ''
const FRONTEND_DIR = process.cwd()
const REPO_ROOT = path.resolve(FRONTEND_DIR, '..')
const OUT_DIR = path.join(REPO_ROOT, 'artifacts', 'frontend-iteration-1')

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
  tier: string
  today_xp: number
  xp: number
  rank: number | null
  group_size: number
  streak: { current: number }
}

interface StandingsPayload {
  group: { no: number; tier: string } | null
  group_size: number
  standings: Array<{
    rank: number
    display_name: string
    xp: number
    is_me: boolean
  }>
}

function signature(status: StatusPayload, standings: StandingsPayload): string {
  return JSON.stringify({
    user_id: status.user_id,
    today_xp: status.today_xp,
    xp: status.xp,
    rank: status.rank,
    streak: status.streak.current,
    top: standings.standings.slice(0, 3).map((row) => [row.rank, row.display_name, row.xp]),
    me: standings.standings.find((row) => row.is_me)?.xp ?? null,
    group: standings.group,
  })
}

async function fetchSnapshot(
  request: APIRequestContext,
  base: string,
  token: string,
): Promise<{ status: StatusPayload; standings: StandingsPayload }> {
  const headers = { Authorization: `Bearer ${token}` }
  const [statusResponse, standingsResponse] = await Promise.all([
    request.get(`${base}/v1/me/status`, { headers }),
    request.get(`${base}/v1/league/standings`, { headers }),
  ])
  expect(statusResponse.ok()).toBeTruthy()
  expect(standingsResponse.ok()).toBeTruthy()
  return {
    status: (await statusResponse.json()) as StatusPayload,
    standings: (await standingsResponse.json()) as StandingsPayload,
  }
}

interface PageChecks {
  overflow: number
  smallTargets: Array<{
    tag: string
    label: string
    width: number
    height: number
  }>
}

async function inspectPage(page: import('@playwright/test').Page): Promise<PageChecks> {
  return page.evaluate(() => {
    const overflow =
      Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) -
      window.innerWidth
    const selector =
      'a[href], button, [role="button"], [role="switch"], [role="radio"], input, select'
    const smallTargets = Array.from(
      document.querySelectorAll<HTMLElement>(selector),
    )
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
    return { overflow, smallTargets }
  })
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

async function makeComparison(
  browser: Browser,
  oldShot: string,
  newShot: string,
  output: string,
  width: number,
  height: number,
  viewportLabel: string,
): Promise<void> {
  const oldData = fs.readFileSync(oldShot).toString('base64')
  const newData = fs.readFileSync(newShot).toString('base64')
  const context = await browser.newContext({
    viewport: { width: width * 2 + 56, height: height + 120 },
    deviceScaleFactor: 1,
  })
  const page = await context.newPage()
  await page.setContent(`<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 18px 20px 22px;
    background: #0d171c;
    color: #fff;
    font-family: "Nunito", "Noto Sans CJK SC", "PingFang SC", system-ui, sans-serif;
  }
  h1 { margin: 0 0 14px; font-size: 15px; letter-spacing: .04em; color: #8fa6b2; font-weight: 800; }
  .row { display: flex; gap: 16px; align-items: flex-start; }
  figure { margin: 0; }
  figcaption { margin: 0 0 7px; color: #cfd8e6; font-size: 13px; font-weight: 800; }
  img { display: block; width: ${width}px; height: auto; border: 2px solid #37464f; border-radius: 14px; }
</style>
</head>
<body>
  <h1>同一账号 · 同一时刻 · ${viewportLabel} · 旧页面 / 新页面</h1>
  <div class="row">
    <figure><figcaption>旧页面 web/</figcaption><img alt="旧首页" src="data:image/png;base64,${oldData}" /></figure>
    <figure><figcaption>新页面 web-next/</figcaption><img alt="新首页" src="data:image/png;base64,${newData}" /></figure>
  </div>
</body>
</html>`)
  await page.screenshot({ path: output, fullPage: true, animations: 'disabled' })
  await context.close()
}

const token = readToken()
test.skip(!token, 'Set GHOST_LEAGUE_TOKEN or GHOST_LEAGUE_TOKEN_FILE to run live-data capture.')

test('home shows the same real numbers as web/ at 390 and 1440', async ({
  browser,
  request,
}) => {
  if (!token) return
  fs.mkdirSync(OUT_DIR, { recursive: true })

  const before = await fetchSnapshot(request, NEW_BASE, token)
  const status = before.status
  const standings = before.standings
  if (!standings.group || standings.standings.length === 0) {
    test.skip(true, 'This account has no group this week; live board capture needs one.')
    return
  }
  const topThree = standings.standings.slice(0, 3)
  const selfRow = standings.standings.find((row) => row.is_me)
  const tierLabel = TIER_LABELS[status.tier] ?? status.tier
  const viewportReports: Record<string, Record<string, unknown>> = {}
  const artifacts: Record<string, string> = {}
  const report: Record<string, unknown> = {
    generatedAt: new Date().toISOString(),
    bases: { new: NEW_BASE, old: OLD_BASE || null },
    expected: {
      user_id: status.user_id,
      display_name: status.display_name,
      tier: status.tier,
      tier_label: tierLabel,
      today_xp: status.today_xp,
      xp: status.xp,
      rank: status.rank,
      group_size: status.group_size,
      streak: status.streak.current,
      top_three: topThree.map((row) => ({
        rank: row.rank,
        name: row.display_name,
        xp: row.xp,
      })),
      me: selfRow ? { rank: selfRow.rank, xp: selfRow.xp } : null,
    },
    viewports: viewportReports,
    artifacts,
  }

  for (const viewport of [
    { width: 390, height: 844, name: '390' },
    { width: 1440, height: 900, name: '1440' },
  ]) {
    const context = await makeContext(browser, viewport, token)
    const page = await context.newPage()
    const consoleErrors: string[] = []
    const pageErrors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })
    page.on('pageerror', (error) => pageErrors.push(error.message))

    await page.goto(NEW_BASE, { waitUntil: 'networkidle' })
    await expect(page.getByRole('heading', { name: tierLabel })).toBeVisible()
    await expect(
      page.getByRole('heading', { name: '今日目标' }),
    ).toBeVisible()

    const todayCard = page.locator('section[aria-labelledby="today-heading"]')
    const rankCard = page.locator('section[aria-labelledby="rank-heading"]')
    await expect(
      todayCard.getByText(format(status.today_xp), { exact: true }),
    ).toBeVisible()
    await expect(
      rankCard.getByLabel(`本周名次 第 ${status.rank ?? '—'} 名`),
    ).toBeVisible()
    await expect(rankCard.getByText(format(status.xp), { exact: true })).toBeVisible()
    await expect(
      page.getByLabel(`连续 ${status.streak.current} 天`),
    ).toBeVisible()
    for (const row of topThree) {
      await expect(
        page.getByText(row.display_name, { exact: true }).first(),
      ).toBeVisible()
    }
    const self = page.locator('li[aria-label*="我的位置"]')
    await expect(self).toBeVisible()

    if (viewport.width === 390) {
      const selfBox = await self.boundingBox()
      const navBox = await page
        .locator('nav[aria-label="主导航"]')
        .last()
        .boundingBox()
      expect(selfBox).not.toBeNull()
      expect(navBox).not.toBeNull()
      if (selfBox && navBox) {
        expect(selfBox.y + selfBox.height).toBeLessThanOrEqual(navBox.y + 1)
      }
    }

    const checks = await inspectPage(page)
    expect(checks.overflow).toBeLessThanOrEqual(1)
    expect(checks.smallTargets).toEqual([])
    expect(consoleErrors).toEqual([])
    expect(pageErrors).toEqual([])

    const bodyText = await page.locator('body').innerText()
    const forbiddenTerms = ['主人', 'ghost', '模拟', '真人', 'ai']
    const forbiddenFound = forbiddenTerms.filter((term) =>
      bodyText.toLowerCase().includes(term),
    )
    expect(forbiddenFound).toEqual([])
    expect((await page.title()).toLowerCase()).not.toContain('ghost')

    const newShot = path.join(OUT_DIR, viewport.name, 'home.png')
    fs.mkdirSync(path.dirname(newShot), { recursive: true })
    await page.screenshot({ path: newShot, fullPage: false, animations: 'disabled' })

    viewportReports[viewport.name] = {
      new: {
        overflow: checks.overflow,
        small_targets: checks.smallTargets,
        console_errors: consoleErrors,
        page_errors: pageErrors,
        forbidden_terms: forbiddenFound,
      },
    }
    artifacts[`${viewport.name}/home.png`] = path.relative(REPO_ROOT, newShot)

    if (OLD_BASE) {
      const oldContext = await makeContext(browser, viewport, token)
      const oldPage = await oldContext.newPage()
      const oldConsoleErrors: string[] = []
      oldPage.on('console', (message) => {
        if (message.type() === 'error') oldConsoleErrors.push(message.text())
      })
      await oldPage.goto(OLD_BASE, { waitUntil: 'networkidle' })
      await expect(oldPage.locator('#app-shell')).toBeVisible()
      await expect(oldPage.locator('#tier-badge')).toHaveText(tierLabel)
      await expect(oldPage.locator('#today-seconds')).toHaveText(
        format(status.today_xp),
      )
      await expect(oldPage.locator('#week-rank')).toHaveText(
        String(status.rank ?? '—'),
      )
      await expect(oldPage.locator('#week-seconds')).toHaveText(
        format(status.xp),
      )
      await expect(oldPage.locator('#streak-number')).toHaveText(
        String(status.streak.current),
      )
      await expect(
        oldPage.getByText(topThree[0]?.display_name ?? '', { exact: true }).first(),
      ).toBeVisible()

      const oldShot = path.join(OUT_DIR, viewport.name, 'old-web.png')
      await oldPage.screenshot({
        path: oldShot,
        fullPage: false,
        animations: 'disabled',
      })
      const compareShot = path.join(OUT_DIR, 'compare', `${viewport.name}.png`)
      fs.mkdirSync(path.dirname(compareShot), { recursive: true })
      await makeComparison(
        browser,
        oldShot,
        newShot,
        compareShot,
        viewport.width,
        viewport.height,
        `${viewport.width}×${viewport.height}`,
      )
      viewportReports[viewport.name] = {
        ...viewportReports[viewport.name],
        old: { console_errors: oldConsoleErrors },
      }
      artifacts[`${viewport.name}/old-web.png`] = path.relative(
        REPO_ROOT,
        oldShot,
      )
      artifacts[`compare/${viewport.name}.png`] = path.relative(
        REPO_ROOT,
        compareShot,
      )
      await oldContext.close()
    }

    await context.close()
  }

  const after = await fetchSnapshot(request, NEW_BASE, token)
  expect(signature(after.status, after.standings)).toBe(
    signature(status, standings),
  )
  report.after = signature(after.status, after.standings)
  const reportPath = path.join(OUT_DIR, 'report.json')
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8')
  expect(fs.existsSync(reportPath)).toBeTruthy()
})
