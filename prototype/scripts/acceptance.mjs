import { chromium } from 'playwright'
import { execFileSync, spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const projectDir = path.resolve(here, '..')
const repoDir = path.resolve(projectDir, '..')
const outDir = path.join(repoDir, 'artifacts', 'prototype')
const baseUrl = process.env.BASE_URL ?? 'http://127.0.0.1:4173'
const minTouch = 44

for (const dir of ['390', '1440', 'extra', 'full']) {
  fs.mkdirSync(path.join(outDir, dir), { recursive: true })
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const failures = []
const checks = []
const consoleErrors = []
const pageErrors = []
const screenshots = []
const copyContexts = []

function check(name, ok, detail) {
  checks.push({ name, ok: Boolean(ok), detail })
  if (!ok) failures.push({ name, detail })
}

function attachDiagnostics(page, labelRef) {
  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push({ context: labelRef.label, text: message.text() })
    }
  })
  page.on('pageerror', (error) => {
    pageErrors.push({ context: labelRef.label, text: error.message })
  })
}

async function serverIsUp() {
  try {
    const response = await fetch(baseUrl)
    return response.ok
  } catch {
    return false
  }
}

async function ensureServer() {
  if (await serverIsUp()) return null
  const child = spawn('npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', '4173'], {
    cwd: projectDir,
    stdio: 'ignore',
  })
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await sleep(500)
    if (await serverIsUp()) return child
  }
  throw new Error(`dev server did not start at ${baseUrl}`)
}

async function goto(page, url) {
  await page.goto(url, { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)
}

async function screenshot(page, relPath, options = {}) {
  const file = path.join(outDir, relPath)
  await page.screenshot({ path: file, ...options })
  screenshots.push(relPath.split(path.sep).join('/'))
  return relPath
}

async function fullScreenshot(page, relPath) {
  const handle = await page.addStyleTag({
    content: '.bottom-nav{position:static !important}.toast{display:none !important}',
  })
  await page.screenshot({ path: path.join(outDir, relPath), fullPage: true })
  screenshots.push(relPath.split(path.sep).join('/'))
  await handle.evaluate((element) => element.remove())
}

async function scanCopy(page, label) {
  const text = await page.evaluate(() => document.body.innerText)
  copyContexts.push({ label, text })
}

async function getOverflow(page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    bodyScrollWidth: document.body.scrollWidth,
  }))
}

async function auditTouch(page, scope = 'page') {
  return page.evaluate(
    ({ scope, minTouch }) => {
      const root = scope === 'dialog' ? document.querySelector('dialog[open]') : document
      if (!root) return { count: 0, minWidth: 0, minHeight: 0, violations: [] }
      const selector =
        'button, a[href], input, [role="button"], [role="switch"], [role="radio"], [role="tab"]'
      const nodes = [...root.querySelectorAll(selector)]
      const visible = []
      for (const element of nodes) {
        if (element.closest('.visually-hidden')) continue
        if (element.closest('dialog:not([open])')) continue
        const style = getComputedStyle(element)
        if (style.display === 'none' || style.visibility === 'hidden') continue
        const rect = element.getBoundingClientRect()
        if (rect.width <= 0 || rect.height <= 0) continue
        visible.push({ element, rect })
      }
      const violations = []
      let minWidth = Infinity
      let minHeight = Infinity
      const describe = (element) => {
        const classes =
          typeof element.className === 'string'
            ? element.className.trim().split(/\s+/).slice(0, 2).join('.')
            : ''
        const label = element.getAttribute('aria-label') || (element.textContent || '').trim().slice(0, 24)
        return `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ''}${
          classes ? `.${classes}` : ''
        }${label ? ` [${label}]` : ''}`
      }
      for (const { element, rect } of visible) {
        minWidth = Math.min(minWidth, rect.width)
        minHeight = Math.min(minHeight, rect.height)
        if (rect.width < minTouch || rect.height < minTouch) {
          violations.push({
            element: describe(element),
            width: Math.round(rect.width * 10) / 10,
            height: Math.round(rect.height * 10) / 10,
          })
        }
      }
      return {
        count: visible.length,
        minWidth: visible.length ? Math.round(minWidth * 10) / 10 : 0,
        minHeight: visible.length ? Math.round(minHeight * 10) / 10 : 0,
        violations,
      }
    },
    { scope, minTouch },
  )
}

async function getBoxes(page, selectors) {
  return page.evaluate((selectors) => {
    const pick = (selector) => {
      for (const element of document.querySelectorAll(selector)) {
        const style = getComputedStyle(element)
        if (style.display === 'none' || style.visibility === 'hidden') continue
        const rect = element.getBoundingClientRect()
        if (rect.width <= 0 || rect.height <= 0) continue
        return {
          x: Math.round(rect.x + window.scrollX),
          y: Math.round(rect.y + window.scrollY),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        }
      }
      return null
    }
    const result = {}
    for (const [key, selector] of Object.entries(selectors)) result[key] = pick(selector)
    return result
  }, selectors)
}

async function closeDialog(page) {
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)
}

const pageDefs = [
  ['home', '首页'],
  ['league', '小组榜'],
  ['embers', '余烬'],
  ['history', '历史'],
  ['me', '我的'],
]

function selectorsFor(width) {
  const navSelector = width >= 960 ? '.nav-rail' : '.bottom-nav'
  return {
    home: {
      topbar: '.topbar',
      hero: '.home-hero',
      ring: '.xp-ring',
      checkin: '.checkin-state',
      shareButton: '[data-testid="share-button"]',
      statTile: width >= 960 ? '.stat-grid--desktop .stat-tile' : '.stat-grid--mobile .stat-tile',
      groupCard: '.group-card',
      feedCard: '.feed-card',
      nav: navSelector,
    },
    league: {
      topbar: '.topbar',
      controls: '.league-controls',
      hero: '.league-hero',
      countdown: '.countdown',
      podium: '.podium',
      promotionDivider: '.zone-divider--promotion',
      meRow: '.league-row--me',
      demotionDivider: '.zone-divider--demotion',
      demotionRow: '.league-row--demotion',
      board: '.league-board',
      nav: navSelector,
    },
    embers: {
      topbar: '.topbar',
      hero: '.embers-hero',
      balance: '[data-testid="embers-balance"]',
      repairButton: '[data-testid="embers-repair-button"]',
      earnCard: '.earn-card',
      logCard: '.ember-log',
      nav: navSelector,
    },
    history: {
      topbar: '.topbar',
      summary: '.history-summary',
      weekRow: '.week-row',
      board: '.history-board',
      nav: navSelector,
    },
    me: {
      topbar: '.topbar',
      profileCard: '.profile-card',
      avatar: '.profile-card .avatar',
      saveButton: '[data-testid="save-profile"]',
      stats: '.profile-stats',
      collectionFilter: '.collection .segmented',
      collectionTile: '.collection-tile',
      settingsCard: '.settings-card',
      soundSwitch: '.switch[aria-label="声音"]',
      logoutButton: '[data-testid="logout-button"]',
      nav: navSelector,
    },
  }
}

function navSelectorFor(width) {
  return width >= 960 ? '.nav-rail__item' : '.bottom-nav__item'
}

async function runViewport(browser, width, height) {
  const key = String(width)
  const labelRef = { label: `${key}:boot` }
  const context = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 1,
  })
  const page = await context.newPage()
  attachDiagnostics(page, labelRef)
  const pages = {}
  const extras = {}
  const navSelector = navSelectorFor(width)

  await goto(page, baseUrl)

  for (const [id, label] of pageDefs) {
    if (id !== 'home') {
      await page.locator(navSelector, { hasText: label }).click()
      await page.waitForTimeout(900)
    }
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.waitForTimeout(120)
    labelRef.label = `${key}:${id}`
    const overflow = await getOverflow(page)
    const touch = await auditTouch(page)
    await scanCopy(page, `${key}:${id}`)
    check(`${key} ${id} horizontal overflow`, overflow.scrollWidth <= overflow.clientWidth + 1, overflow)
    check(`${key} ${id} touch targets`, touch.violations.length === 0, touch)
    const rel = `${key}/${id}.png`
    await screenshot(page, rel)
    const fullRel = `full/${key}-${id}.png`
    await fullScreenshot(page, fullRel)
    pages[id] = {
      screenshot: rel,
      fullScreenshot: fullRel,
      overflow,
      touch,
      boxes: await getBoxes(page, selectorsFor(width)[id]),
    }
  }

  // Home tooltip
  labelRef.label = `${key}:tooltip`
  await page.locator(navSelector, { hasText: '首页' }).click()
  await page.waitForTimeout(400)
  const weekTip = page.getByRole('button', { name: '本周计算规则' })
  await weekTip.hover()
  await page.waitForTimeout(250)
  const hoverTooltip = await page.getByRole('tooltip').isVisible().catch(() => false)
  const tooltipText = await page.getByRole('tooltip').textContent().catch(() => null)
  await scanCopy(page, `${key}:tooltip`)
  await screenshot(page, `extra/${key}-tooltip.png`)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(200)
  const escClosed = !(await page.getByRole('tooltip').isVisible().catch(() => false))
  check(`${key} tooltip hover`, hoverTooltip, tooltipText)
  check(`${key} tooltip escape`, escClosed, null)
  extras.tooltip = { screenshot: `extra/${key}-tooltip.png`, text: tooltipText, hoverTooltip, escClosed }

  // All-feed sheet
  labelRef.label = `${key}:feed-sheet`
  await page.getByRole('button', { name: '查看全部动态' }).click()
  await page.waitForTimeout(350)
  const feedSheetOpen = await page.locator('[data-testid="feed-sheet"]').isVisible()
  const feedRows = await page.locator('[data-testid="feed-sheet"] .feed-item').count()
  await scanCopy(page, `${key}:feed-sheet`)
  await screenshot(page, `extra/${key}-feed-sheet.png`)
  await closeDialog(page)
  check(`${key} feed sheet`, feedSheetOpen && feedRows >= 3, { feedRows })
  extras.feedSheet = { screenshot: `extra/${key}-feed-sheet.png`, open: feedSheetOpen, rows: feedRows }

  // League row detail
  labelRef.label = `${key}:user-sheet`
  await page.locator(navSelector, { hasText: '小组榜' }).click()
  await page.waitForTimeout(500)
  await page.locator('.league-row').nth(4).click()
  await page.waitForTimeout(350)
  const userSheetOpen = await page.locator('[data-testid="user-detail-sheet"]').isVisible()
  const userSheetTitle = await page.locator('[data-testid="user-detail-sheet"] .sheet__title').textContent()
  const userSheetTouch = await auditTouch(page, 'dialog')
  await scanCopy(page, `${key}:user-sheet`)
  await screenshot(page, `extra/${key}-user-sheet.png`)
  await closeDialog(page)
  const userSheetClosed = (await page.locator('[data-testid="user-detail-sheet"]').count()) === 0
  check(`${key} user sheet`, userSheetOpen && userSheetClosed, { userSheetOpen, userSheetClosed })
  check(`${key} user sheet touch targets`, userSheetTouch.violations.length === 0, userSheetTouch)
  extras.userSheet = {
    screenshot: `extra/${key}-user-sheet.png`,
    title: userSheetTitle,
    open: userSheetOpen,
    closedByEscape: userSheetClosed,
    touch: userSheetTouch,
  }

  // Repair sheet
  labelRef.label = `${key}:repair-sheet`
  await page.locator(navSelector, { hasText: '首页' }).click()
  await page.waitForTimeout(400)
  await page.locator('[data-testid="repair-button"]').click()
  await page.waitForTimeout(350)
  const repairOpen = await page.locator('[data-testid="repair-sheet"]').isVisible()
  const repairOptions = await page.locator('[data-testid="repair-sheet"] [role="radio"]').count()
  const repairEnabled = !(await page.locator('[data-testid="repair-confirm"]').isDisabled())
  const repairTouch = await auditTouch(page, 'dialog')
  await scanCopy(page, `${key}:repair-sheet`)
  await screenshot(page, `extra/${key}-repair.png`)
  await closeDialog(page)
  check(`${key} repair sheet`, repairOpen && repairOptions >= 1 && repairEnabled, {
    repairOptions,
    repairEnabled,
  })
  check(`${key} repair sheet touch targets`, repairTouch.violations.length === 0, repairTouch)
  extras.repairSheet = {
    screenshot: `extra/${key}-repair.png`,
    open: repairOpen,
    options: repairOptions,
    confirmEnabled: repairEnabled,
    touch: repairTouch,
  }

  // History empty + loading
  labelRef.label = `${key}:history-empty`
  await goto(page, `${baseUrl}/?history=empty`)
  await page.locator(navSelector, { hasText: '历史' }).click()
  await page.waitForTimeout(900)
  const emptyVisible = await page.locator('.empty-state').isVisible()
  const emptyTitle = await page.locator('.empty-state__title').textContent().catch(() => null)
  const emptySummary = await page.locator('.history-summary').innerText()
  await scanCopy(page, `${key}:history-empty`)
  await screenshot(page, `extra/${key}-history-empty.png`)
  check(`${key} history empty`, emptyVisible, { emptyTitle, summary: emptySummary.slice(0, 40) })
  extras.historyEmpty = {
    screenshot: `extra/${key}-history-empty.png`,
    visible: emptyVisible,
    title: emptyTitle,
  }

  labelRef.label = `${key}:history-loading`
  await goto(page, `${baseUrl}/?history=loading`)
  await page.locator(navSelector, { hasText: '历史' }).click()
  await page.waitForTimeout(350)
  const loadingVisible = await page.locator('.history-skeleton').isVisible()
  await scanCopy(page, `${key}:history-loading`)
  await screenshot(page, `extra/${key}-history-loading.png`)
  check(`${key} history loading`, loadingVisible, null)
  extras.historyLoading = { screenshot: `extra/${key}-history-loading.png`, visible: loadingVisible }

  // Week detail
  labelRef.label = `${key}:week-sheet`
  await goto(page, baseUrl)
  await page.locator(navSelector, { hasText: '历史' }).click()
  await page.waitForTimeout(900)
  await page.locator('.week-row').first().click()
  await page.waitForTimeout(350)
  const weekSheetOpen = await page.locator('[data-testid="week-sheet"]').isVisible()
  await scanCopy(page, `${key}:week-sheet`)
  await screenshot(page, `extra/${key}-week-sheet.png`)
  await closeDialog(page)
  check(`${key} week detail`, weekSheetOpen, null)
  extras.weekSheet = { screenshot: `extra/${key}-week-sheet.png`, open: weekSheetOpen }

  // Collection + settings sheets
  labelRef.label = `${key}:me-extra`
  await page.locator(navSelector, { hasText: '我的' }).click()
  await page.waitForTimeout(500)
  await page.locator('.collection').scrollIntoViewIfNeeded()
  await page.waitForTimeout(200)
  await scanCopy(page, `${key}:me-collection`)
  await screenshot(page, `extra/${key}-me-collection.png`)
  await page.locator('.collection .segmented__item', { hasText: '勋章' }).click()
  await page.waitForTimeout(250)
  const filterGroups = await page.locator('.collection-group').count()
  const filterTitle = await page.locator('.collection-group__title').first().textContent()
  await scanCopy(page, `${key}:collection-filter`)
  await screenshot(page, `extra/${key}-collection-filter.png`)
  check(`${key} collection filter`, filterGroups === 1 && filterTitle === '勋章', {
    filterGroups,
    filterTitle,
  })
  extras.collectionFilter = {
    screenshot: `extra/${key}-collection-filter.png`,
    groups: filterGroups,
    title: filterTitle,
  }
  await page.locator('.collection .segmented__item', { hasText: '全部' }).click()
  await page.waitForTimeout(150)

  await page.getByRole('button', { name: '集成说明' }).click()
  await page.waitForTimeout(300)
  const integrationOpen = await page.locator('[data-testid="integration-sheet"]').isVisible()
  await scanCopy(page, `${key}:integration-sheet`)
  await screenshot(page, `extra/${key}-integration.png`)
  await page.getByRole('button', { name: '知道了' }).click()
  await page.waitForTimeout(250)
  await page.getByRole('button', { name: '附近的人' }).click()
  await page.waitForTimeout(300)
  const nearbyOpen = await page.locator('[data-testid="nearby-sheet"]').isVisible()
  const nearbyRows = await page.locator('[data-testid="nearby-sheet"] .people-row').count()
  await scanCopy(page, `${key}:nearby-sheet`)
  await screenshot(page, `extra/${key}-nearby.png`)
  await closeDialog(page)
  check(`${key} integration + nearby`, integrationOpen && nearbyOpen && nearbyRows > 0, {
    integrationOpen,
    nearbyOpen,
    nearbyRows,
  })
  extras.integration = { screenshot: `extra/${key}-integration.png`, open: integrationOpen }
  extras.nearby = { screenshot: `extra/${key}-nearby.png`, open: nearbyOpen, rows: nearbyRows }

  await context.close()
  return { pages, extras }
}

async function runInteractions(browser) {
  const width = 390
  const height = 844
  const labelRef = { label: '390:interactions' }
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 })
  const page = await context.newPage()
  attachDiagnostics(page, labelRef)
  const result = {}

  await goto(page, baseUrl)

  // Tooltip: hover, focus, Escape, Enter toggle, click-through
  labelRef.label = '390:tooltip-behaviour'
  const weekTip = page.getByRole('button', { name: '本周计算规则' })
  await weekTip.hover()
  await page.waitForTimeout(250)
  const hoverOpen = await page.getByRole('tooltip').isVisible().catch(() => false)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(200)
  const hoverEscClosed = !(await page.getByRole('tooltip').isVisible().catch(() => false))
  const streakTip = page.getByRole('button', { name: '火焰与补签' })
  await streakTip.focus()
  await page.waitForTimeout(250)
  const focusOpen = await page.getByRole('tooltip').isVisible().catch(() => false)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(200)
  const focusReturned = await page.evaluate(() => document.activeElement?.getAttribute('aria-label'))
  await page.keyboard.press('Enter')
  await page.waitForTimeout(250)
  const enterOpen = await page.getByRole('tooltip').isVisible().catch(() => false)
  await page.keyboard.press('Enter')
  await page.waitForTimeout(250)
  const enterClosed = !(await page.getByRole('tooltip').isVisible().catch(() => false))
  await weekTip.hover()
  await page.waitForTimeout(250)
  await page.locator('[data-testid="share-button"]').click()
  await page.waitForTimeout(250)
  const clickThroughToast = await page.locator('.toast').textContent().catch(() => null)
  const tooltipAfterClick = !(await page.getByRole('tooltip').isVisible().catch(() => false))
  check('tooltip hover + escape', hoverOpen && hoverEscClosed, { hoverOpen, hoverEscClosed })
  check('tooltip focus + keyboard toggle', focusOpen && enterOpen && enterClosed, {
    focusOpen,
    focusReturned,
    enterOpen,
    enterClosed,
  })
  check('tooltip does not block click', Boolean(clickThroughToast) && tooltipAfterClick, {
    clickThroughToast,
    tooltipAfterClick,
  })
  result.tooltip = {
    hoverOpen,
    hoverEscClosed,
    focusOpen,
    focusReturned,
    enterOpen,
    enterClosed,
    clickThroughToast,
    tooltipAfterClick,
  }

  // Refresh
  labelRef.label = '390:refresh'
  await goto(page, baseUrl)
  await page.locator('[data-testid="refresh-button"]').click()
  const refreshDisabled = await page.locator('[data-testid="refresh-button"]').isDisabled()
  await page.waitForTimeout(700)
  const refreshToast = await page.locator('.toast').textContent().catch(() => null)
  await page.screenshot({ path: path.join(outDir, 'extra/390-refresh-toast.png') })
  screenshots.push('extra/390-refresh-toast.png')
  check('refresh 600ms + toast', refreshDisabled && refreshToast === '已更新', {
    refreshDisabled,
    refreshToast,
  })
  result.refresh = { disabledDuring: refreshDisabled, toast: refreshToast }

  // Share
  await page.locator('[data-testid="share-button"]').click()
  await page.waitForTimeout(200)
  const shareToast = await page.locator('.toast').textContent().catch(() => null)
  check('share toast', shareToast === '战绩卡已生成', { shareToast })
  result.share = { toast: shareToast }

  // Repair flow
  labelRef.label = '390:repair-flow'
  await page.locator('[data-testid="repair-button"]').click()
  await page.waitForTimeout(300)
  const repairOptions = await page.locator('[data-testid="repair-sheet"] [role="radio"]').count()
  const repairEnabledBefore = !(await page.locator('[data-testid="repair-confirm"]').isDisabled())
  await page.locator('[data-testid="repair-confirm"]').click()
  await page.waitForTimeout(350)
  const repairToast = await page.locator('.toast').textContent().catch(() => null)
  await page.locator('.bottom-nav__item', { hasText: '余烬' }).click()
  await page.waitForTimeout(400)
  const balanceAfter = await page.locator('[data-testid="embers-balance"]').textContent()
  await page.locator('.bottom-nav__item', { hasText: '首页' }).click()
  await page.waitForTimeout(400)
  await page.locator('[data-testid="repair-button"]').click()
  await page.waitForTimeout(300)
  const repairDisabledAfter = await page.locator('[data-testid="repair-confirm"]').isDisabled()
  await closeDialog(page)
  check(
    'repair consumes one ember',
    repairOptions === 2 &&
      repairEnabledBefore &&
      repairToast === '补签成功。火焰续上了。' &&
      balanceAfter === '0' &&
      repairDisabledAfter,
    { repairOptions, repairEnabledBefore, repairToast, balanceAfter, repairDisabledAfter },
  )
  result.repair = {
    options: repairOptions,
    enabledBefore: repairEnabledBefore,
    toast: repairToast,
    balanceAfter,
    disabledAfter: repairDisabledAfter,
  }

  // User detail + escape + backdrop
  labelRef.label = '390:user-detail'
  await page.locator('.bottom-nav__item', { hasText: '小组榜' }).click()
  await page.waitForTimeout(500)
  await page.locator('.league-row').nth(4).click()
  await page.waitForTimeout(300)
  const sheetTitle = await page.locator('[data-testid="user-detail-sheet"] .sheet__title').textContent()
  const dialogCount = await page.locator('dialog[open]').count()
  await page.keyboard.press('Escape')
  await page.waitForTimeout(300)
  const escClosed = (await page.locator('[data-testid="user-detail-sheet"]').count()) === 0
  await page.locator('.league-row').nth(4).click()
  await page.waitForTimeout(300)
  await page.mouse.click(10, 10)
  await page.waitForTimeout(300)
  const backdropClosed = (await page.locator('[data-testid="user-detail-sheet"]').count()) === 0
  check('user detail sheet close paths', dialogCount === 1 && escClosed && backdropClosed, {
    sheetTitle,
    escClosed,
    backdropClosed,
  })
  result.userDetail = { title: sheetTitle, escClosed, backdropClosed }

  // Collection filter + equip
  labelRef.label = '390:collection'
  await page.locator('.bottom-nav__item', { hasText: '我的' }).click()
  await page.waitForTimeout(500)
  await page.locator('.collection').scrollIntoViewIfNeeded()
  await page.locator('.collection .segmented__item', { hasText: '勋章' }).click()
  await page.waitForTimeout(200)
  const badgeGroups = await page.locator('.collection-group').count()
  const badgeTitle = await page.locator('.collection-group__title').first().textContent()
  await page.locator('.collection .segmented__item', { hasText: '全部' }).click()
  await page.waitForTimeout(200)
  const bronzeTile = page.getByRole('button', { name: '青铜框，可装备' })
  await bronzeTile.scrollIntoViewIfNeeded()
  await bronzeTile.click()
  await page.waitForTimeout(250)
  const equipToast = await page.locator('.toast').textContent().catch(() => null)
  const equippedPressed = await page.getByRole('button', { name: '青铜框，已装备' }).getAttribute('aria-pressed')
  check('collection filter + equip', badgeGroups === 1 && badgeTitle === '勋章' && equippedPressed === 'true', {
    badgeGroups,
    badgeTitle,
    equipToast,
    equippedPressed,
  })
  result.collection = { badgeGroups, badgeTitle, equipToast, equippedPressed }

  // Sound + haptics
  labelRef.label = '390:sound-haptics'
  await page.locator('.profile-card').scrollIntoViewIfNeeded()
  await page.locator('[data-testid="sound-button"]').click()
  await page.waitForTimeout(200)
  const soundPressed = await page.locator('[data-testid="sound-button"]').getAttribute('aria-pressed')
  const soundToast = await page.locator('.toast').textContent().catch(() => null)
  const soundSwitch = page.getByRole('switch', { name: '声音' })
  await soundSwitch.scrollIntoViewIfNeeded()
  const soundSwitchState = await soundSwitch.getAttribute('aria-checked')
  await soundSwitch.click()
  await page.waitForTimeout(200)
  const soundSwitchBack = await soundSwitch.getAttribute('aria-checked')
  const soundBackPressed = await page.locator('[data-testid="sound-button"]').getAttribute('aria-pressed')
  const hapticSwitch = page.getByRole('switch', { name: '轻触反馈' })
  await hapticSwitch.scrollIntoViewIfNeeded()
  const hapticBefore = await hapticSwitch.getAttribute('aria-checked')
  await hapticSwitch.click()
  await page.waitForTimeout(200)
  const hapticAfter = await hapticSwitch.getAttribute('aria-checked')
  const hapticToast = await page.locator('.toast').textContent().catch(() => null)
  check(
    'sound + haptics switches',
    soundPressed === 'false' &&
      soundToast === '声音已关' &&
      soundSwitchState === 'false' &&
      soundSwitchBack === 'true' &&
      soundBackPressed === 'true' &&
      hapticBefore === 'true' &&
      hapticAfter === 'false' &&
      hapticToast === '轻触反馈已关',
    { soundPressed, soundToast, soundSwitchState, soundSwitchBack, soundBackPressed, hapticBefore, hapticAfter, hapticToast },
  )
  result.soundHaptics = {
    soundPressed,
    soundToast,
    soundSwitchState,
    soundSwitchBack,
    soundBackPressed,
    hapticBefore,
    hapticAfter,
    hapticToast,
  }

  // Icon theme
  labelRef.label = '390:icon-theme'
  await page.locator('.theme-option', { hasText: '线性' }).click()
  await page.waitForTimeout(250)
  const themeClass = await page.locator('.app').getAttribute('class')
  const lineStroke = await page.evaluate(() =>
    getComputedStyle(document.querySelector('.bottom-nav__item svg')).strokeWidth,
  )
  await page.locator('.theme-option', { hasText: '填色' }).click()
  await page.waitForTimeout(250)
  const solidFill = await page.evaluate(() =>
    getComputedStyle(document.querySelector('.bottom-nav__item svg')).fillOpacity,
  )
  await page.locator('.theme-option', { hasText: '圆润' }).click()
  await page.waitForTimeout(200)
  check('icon theme switch', themeClass.includes('icon-theme-line') && lineStroke === '1.4px' && solidFill === '0.42', {
    themeClass,
    lineStroke,
    solidFill,
  })
  result.iconTheme = { themeClass, lineStroke, solidFill }

  // Avatar preview + save profile
  labelRef.label = '390:avatar'
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR42mP8z8BQz0AEYBxVSFUAANsABf8lS9sAAAAASUVORK5CYII=',
    'base64',
  )
  await page.locator('[data-testid="avatar-input"]').setInputFiles({
    name: 'avatar.png',
    mimeType: 'image/png',
    buffer: png,
  })
  await page.waitForTimeout(300)
  const previewVisible = await page.locator('.profile-card__preview').isVisible()
  await page.locator('[data-testid="save-profile"]').click()
  await page.waitForTimeout(700)
  const saveToast = await page.locator('.toast').textContent().catch(() => null)
  const previewGone = (await page.locator('.profile-card__preview').count()) === 0
  check('avatar preview + save', previewVisible && saveToast === '已保存' && previewGone, {
    previewVisible,
    saveToast,
    previewGone,
  })
  result.avatar = { previewVisible, saveToast, previewGone }

  // Logout + login
  labelRef.label = '390:logout'
  await page.locator('[data-testid="logout-button"]').scrollIntoViewIfNeeded()
  await page.locator('[data-testid="logout-button"]').click()
  await page.waitForTimeout(300)
  const logoutSheet = await page.locator('[data-testid="logout-sheet"]').isVisible()
  await page.locator('[data-testid="logout-confirm"]').click()
  await page.waitForTimeout(400)
  const loginVisible = await page.locator('.login-card').isVisible()
  await scanCopy(page, '390:login')
  await screenshot(page, 'extra/390-login.png')
  await page.getByRole('button', { name: '重新进入' }).click()
  await page.waitForTimeout(400)
  const reentered = await page.locator('[data-testid="home-page"]').isVisible()
  check('logout + login', logoutSheet && loginVisible && reentered, {
    logoutSheet,
    loginVisible,
    reentered,
  })
  result.logout = { sheet: logoutSheet, loginVisible, reentered }

  await context.close()

  // Reduced motion context
  labelRef.label = '390:reduced-motion'
  const reducedContext = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 1,
    reducedMotion: 'reduce',
  })
  const reducedPage = await reducedContext.newPage()
  attachDiagnostics(reducedPage, labelRef)
  await goto(reducedPage, baseUrl)
  await reducedPage.waitForTimeout(150)
  const reduced = await reducedPage.evaluate(() => ({
    score: document.querySelector('.xp-ring__score')?.textContent,
    ringTransition: getComputedStyle(document.querySelector('.xp-ring__progress')).transitionDuration,
    pageAnimation: getComputedStyle(document.querySelector('.page')).animationDuration,
    media: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  }))
  await scanCopy(reducedPage, '390:reduced-motion')
  await reducedPage.screenshot({ path: path.join(outDir, 'extra/390-reduced-motion.png') })
  screenshots.push('extra/390-reduced-motion.png')
  check(
    'reduced motion',
    reduced.media && reduced.score.includes('110') && reduced.ringTransition === '0.001s',
    reduced,
  )
  result.reducedMotion = reduced
  await reducedContext.close()

  // Touch context
  labelRef.label = '390:touch-tooltip'
  const touchContext = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 1,
    hasTouch: true,
    isMobile: true,
  })
  const touchPage = await touchContext.newPage()
  attachDiagnostics(touchPage, labelRef)
  await goto(touchPage, baseUrl)
  const touchTrigger = touchPage.getByRole('button', { name: '本周计算规则' })
  await touchTrigger.tap()
  await touchPage.waitForTimeout(250)
  const tapOpen = await touchPage.getByRole('tooltip').isVisible().catch(() => false)
  await touchPage.screenshot({ path: path.join(outDir, 'extra/390-touch-tooltip.png') })
  screenshots.push('extra/390-touch-tooltip.png')
  await touchTrigger.tap()
  await touchPage.waitForTimeout(250)
  const tapClosed = !(await touchPage.getByRole('tooltip').isVisible().catch(() => false))
  check('tooltip touch tap toggles', tapOpen && tapClosed, { tapOpen, tapClosed })
  result.touchTooltip = { tapOpen, tapClosed }
  await touchContext.close()

  return result
}

function getGitHead() {
  try {
    return execFileSync('git', ['rev-parse', '--short', 'HEAD'], {
      cwd: repoDir,
      encoding: 'utf8',
    }).trim()
  } catch {
    return 'unknown'
  }
}

const forbiddenTerms = [
  '5Li75Lq6',
  '5Y6755S75LiA56yU',
  '55S75LiA56yU',
  '5omT5Y2h5oyJ6ZKu',
  '5byA5aeL5Yib5L2c',
  '5aSa6YK75Zu9',
  'ZHVvbGluZ28=',
  '5bm954G1',
  '5Lqh6ICF',
  '5Yal55WM',
  '6L2s5LiW',
  '54G16a2C',
  '6Zi06Ze0',
  '55So5oi3',
  '5oKo',
  '57O757uf',
  '5pyN5Yqh5Zmo',
  '5o6l5Y+j',
  '5pWw5o2u5bqT',
  '566X5rOV',
  '5qOA5rWL5Yiw',
  '5ZCM5q2l5aSx6LSl',
  '6K+356iN5ZCO',
  '6K+36YeN6K+V',
  '5a6d5a6d',
  '5qOS5qOS',
  '56yo6JuL',
  '6I+c6bif',
  '5bqf54mp',
  '5Yqg5rK5',
  '5Yay6bit',
  '5oGt5Zac5oKo',
  '5oSf6LCi5oKo55qE5L2/55So',
  '6K6p5oiR5Lus5LiA6LW3',
  '6LWL6IO9',
  '6Zet546v',
  '5omT6YCg',
  '5py65Zmo5Lq6',
  '5qih5ouf',
  '55yf5Lq6',
  'Y2hhbm5lbA==',
  'aW5nZXN0',
  'cGxheWVyX3JlZg==',
  'Z2hvc3Q=',
].map((encoded) => Buffer.from(encoded, 'base64').toString('utf8'))

const pathPatterns = [
  new RegExp(`/${'Users'}/`),
  new RegExp(`/${'home'}/`),
  new RegExp(`/${'root'}/`),
  new RegExp(`/${'opt'}/`),
  new RegExp(`[A-Za-z]:\\\\${'Users'}\\\\`),
]

function copyMatches() {
  const matches = []
  for (const context of copyContexts) {
    const haystack = context.text.toLowerCase()
    forbiddenTerms.forEach((term, index) => {
      if (haystack.includes(term.toLowerCase())) {
        matches.push({ termIndex: index, context: context.label })
      }
    })
    pathPatterns.forEach((pattern, index) => {
      if (pattern.test(context.text)) {
        matches.push({ pathPatternIndex: index, context: context.label })
      }
    })
  }
  return matches
}

const server = await ensureServer()
const browser = await chromium.launch({
  args: ['--no-sandbox'],
  ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
})

const report = {
  prototype: '点火联赛 · 交互原型',
  generatedAt: new Date().toISOString(),
  gitHead: getGitHead(),
  baseUrl,
  browser: `${browser.browserType().name()} ${browser.version()}`,
  startCommand: 'cd prototype && npm run dev -- --host 127.0.0.1 --port 4173',
  e2eCommand: 'cd prototype && npm run test:e2e',
  coordinateSpace: 'document',
  touchThreshold: minTouch,
  viewports: [
    { width: 390, height: 844, nav: 'bottom' },
    { width: 1440, height: 900, nav: 'rail' },
  ],
  screenshots,
  pages: {},
  extras: {},
  interactions: {},
  checks,
  failures,
  consoleErrors,
  pageErrors,
  copy: {
    termsChecked: forbiddenTerms.length,
    contexts: copyContexts.map((context) => context.label),
    matches: [],
  },
  knownGaps: [
    '15 人小组榜单在 1440×900 首屏不能全部铺开，需要滚动；完整列表见 full/1440-league.png。',
    '不实现 30 人小组规则，UI 只声称 15 人。',
    '不接后端：刷新、分享、补签、上传头像、保存资料、关注、登录均为本地 mock。',
    '历史空态与加载态通过 ?history=empty / ?history=loading 预览，没有额外的界面开关。',
    '集成说明、附近的人、余烬流水为 mock 数据；没有真实令牌、位置或网络请求。',
    '声音开关只切换状态与提示，不播放音频资源。',
    '联赛是一级 Tab，按规格不设返回按钮；成员详情的关闭按钮 / Esc / 遮罩承担返回。',
    '图标主题只改变图标描边与填充，不改变信息架构。',
    '没有 4 Tab 合并、等级进度条、商店、锦标赛或创作入口。',
    '这是独立原型，不是生产 PWA；未修改现有应用、Python 包或测试目录。',
  ],
}

try {
  report.pages['390'] = await runViewport(browser, 390, 844)
  report.pages['1440'] = await runViewport(browser, 1440, 900)
  report.extras = { '390': report.pages['390'].extras, '1440': report.pages['1440'].extras }
  report.interactions = await runInteractions(browser)
} finally {
  await browser.close()
  if (server) server.kill('SIGTERM')
}

report.copy.contexts = copyContexts.map((context) => context.label)
report.copy.matches = copyMatches()
check('no console errors', consoleErrors.length === 0, consoleErrors)
check('no page errors', pageErrors.length === 0, pageErrors)
check('no forbidden copy', report.copy.matches.length === 0, report.copy.matches)
report.checks = checks
report.failures = failures

fs.writeFileSync(path.join(outDir, 'report.json'), `${JSON.stringify(report, null, 2)}\n`)

const summary = {
  screenshots: screenshots.length,
  checks: checks.length,
  failures: failures.length,
  consoleErrors: consoleErrors.length,
  pageErrors: pageErrors.length,
  copyMatches: report.copy.matches.length,
  report: path.join(outDir, 'report.json'),
}

console.log(JSON.stringify(summary, null, 2))
if (failures.length > 0) {
  console.error(JSON.stringify(failures, null, 2))
  process.exitCode = 1
}
