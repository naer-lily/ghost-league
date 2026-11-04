import { expect, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const TOKEN_KEY = 'gl.token.v1'
const BASE = process.env.E2E_NEW_BASE_URL ?? 'http://127.0.0.1:4174'
const REPO_ROOT = path.resolve(process.cwd(), '..')
const OUT_DIR = path.join(REPO_ROOT, 'artifacts', 'ghost-user-profile')
const TARGET_ID = process.env.E2E_PROFILE_USER_ID
const TARGET_NAME = process.env.E2E_PROFILE_USER_NAME

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

const token = readToken()
test.skip(!token, 'Set GHOST_LEAGUE_TOKEN or GHOST_LEAGUE_TOKEN_FILE to run UI capture.')

for (const viewport of VIEWPORTS) {
  test(`opponent profile ${viewport.name}x${viewport.height}`, async ({
    browser,
  }) => {
    if (!token) throw new Error('missing token')
    fs.mkdirSync(OUT_DIR, { recursive: true })
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
    const page = await context.newPage()

    if (TARGET_ID) {
      await page.request.delete(`${BASE}/v1/me/follows/${TARGET_ID}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    }

    await page.goto(`${BASE}/league`)
    const board = page.getByRole('list', { name: '完整小组榜' })
    await expect(board).toBeVisible()
    const row = TARGET_NAME
      ? board.getByTestId('standing-row').filter({ hasText: TARGET_NAME }).first()
      : board
          .getByTestId('standing-row')
          .filter({ hasNotText: '我的位置' })
          .first()
    await expect(row).toBeVisible()
    const name =
      TARGET_NAME ??
      (await row.getAttribute('aria-label'))?.split('，')[0] ??
      ''
    expect(name.length).toBeGreaterThan(0)
    await row.getByTestId('standing-avatar').click()

    const sheet = page.getByTestId('user-profile-sheet')
    await expect(sheet).toBeVisible()
    await expect(sheet.getByRole('heading', { name })).toBeVisible()
    await expect(sheet.getByRole('button', { name: '返回' })).toBeVisible()
    await expect(sheet.getByTestId('profile-follow')).toBeEnabled()
    await expect(sheet.getByTestId('profile-power')).toBeVisible()
    await expect(sheet.getByTestId('profile-followers')).toBeVisible()
    await expect(sheet.getByTestId('profile-tier')).toBeVisible()
    await expect(sheet.getByTestId('profile-rank')).toBeVisible()

    const chart = sheet.getByTestId('profile-recent-chart')
    await expect(chart).toBeVisible()
    const targetPoints = await sheet
      .getByTestId('profile-recent-target')
      .getAttribute('points')
    const viewerPoints = await sheet
      .getByTestId('profile-recent-viewer')
      .getAttribute('points')
    expect(targetPoints?.trim().split(/\s+/)).toHaveLength(7)
    expect(viewerPoints?.trim().split(/\s+/)).toHaveLength(7)
    expect(targetPoints).not.toBe(viewerPoints)
    const lineColors = await chart.evaluate((svg) =>
      Array.from(svg.querySelectorAll('polyline')).map(
        (line) => getComputedStyle(line).stroke,
      ),
    )
    expect(lineColors).toContain('rgb(28, 176, 246)')
    expect(lineColors).toContain('rgb(138, 154, 163)')

    const follow = sheet.getByTestId('profile-follow')
    const wasFollowing = (await follow.getAttribute('aria-pressed')) === 'true'
    await follow.click()
    await expect(sheet.getByTestId('profile-follow')).toHaveAttribute(
      'aria-pressed',
      wasFollowing ? 'false' : 'true',
    )
    if (wasFollowing) {
      await sheet.getByTestId('profile-follow').click()
      await expect(sheet.getByTestId('profile-follow')).toHaveAttribute(
        'aria-pressed',
        'true',
      )
    }
    await expect(page.getByText('已关注。')).toBeHidden({ timeout: 5_000 })

    await expect(chart).toBeVisible()
    await page.screenshot({
      path: path.join(OUT_DIR, `opponent-profile-${viewport.name}.png`),
    })
    await context.close()
  })
}
