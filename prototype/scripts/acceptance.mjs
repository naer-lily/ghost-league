import { chromium } from 'playwright'
import { execFileSync, spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const projectDir = path.resolve(here, '..')
const repoDir = path.resolve(projectDir, '..')
const outDir = path.join(repoDir, 'artifacts', 'prototype-v2')
const baseUrl = process.env.BASE_URL ?? 'http://127.0.0.1:4173'
const minTouch = 44

const V1_HOME_TEXT = { 390: 263, 1440: 318 }

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
const homeText = {}

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

async function toastText(page) {
  return page.locator('.toast').textContent().catch(() => null)
}

async function countHomeText(page) {
  return page.evaluate(() => {
    const text = document.body.innerText.replace(/\s+/g, '')
    return { length: [...text].length, text }
  })
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
      status: '.status-strip',
      banner: '.unit-banner',
      path: '.week-path',
      today: '.day-node--today',
      sprite: '.path-buddy .ember-sprite',
      nav: navSelector,
    },
    league: {
      topbar: '.topbar',
      hero: '.league-hero',
      countdown: '.countdown-pill',
      podium: '.podium',
      promotion: '.zone-bar--promotion',
      meRow: '.league-row--me',
      demotion: '.zone-bar--demotion',
      board: '.league-board',
      nav: navSelector,
    },
    embers: {
      topbar: '.topbar',
      hero: '.embers-hero',
      balance: '[data-testid="embers-balance"]',
      repairButton: '[data-testid="embers-repair-button"]',
      log: '.ember-log',
      nav: navSelector,
    },
    history: {
      topbar: '.topbar',
      board: '.history-board',
      weekRow: '.week-row',
      nav: navSelector,
    },
    me: {
      topbar: '.topbar',
      profile: '.profile-hero',
      avatar: '.profile-hero .avatar',
      stats: '.stat-quad',
      filter: '.collection .segmented',
      tile: '.collection-tile',
      settings: '[data-testid="settings-button"]',
      nav: navSelector,
    },
  }
}

function navSelectorFor(width) {
  return width >= 960 ? '.nav-rail__item' : '.bottom-nav__item'
}

async function recordPage(page, key, id, labelRef, width) {
  labelRef.label = `${key}:${id}`
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForTimeout(120)
  const overflow = await getOverflow(page)
  const touch = await auditTouch(page)
  await scanCopy(page, `${key}:${id}`)
  check(`${key} ${id} horizontal overflow`, overflow.scrollWidth <= overflow.clientWidth + 1, overflow)
  check(`${key} ${id} touch targets`, touch.violations.length === 0, touch)
  const rel = `${key}/${id}.png`
  await screenshot(page, rel)
  await fullScreenshot(page, `full/${key}-${id}.png`)
  return {
    screenshot: rel,
    fullScreenshot: `full/${key}-${id}.png`,
    overflow,
    touch,
    boxes: await getBoxes(page, selectorsFor(width)[id]),
  }
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
  const navSelector = navSelectorFor(width)
  const pages = {}
  const extras = {}

  await goto(page, baseUrl)

  const navLabels = await page.locator(navSelector).allTextContents()
  check(`${key} five tabs`, navLabels.length === 5, navLabels)

  const homeNodeCount = await page.locator('.day-node').count()
  const todayNodeText = await page.locator('[data-testid="day-node-today"]').textContent()
  const greeting = (await page.locator('.path-buddy__bubble').textContent())?.trim() ?? ''
  const statusPills = await page.locator('.status-pill').count()
  check(`${key} weekly path 7 nodes`, homeNodeCount === 7, { homeNodeCount })
  check(`${key} today node shows XP`, todayNodeText?.includes('110'), { todayNodeText })
  check(`${key} status strip has 3 resources`, statusPills === 3, { statusPills })
  check(`${key} greeting <= 8 chars`, [...greeting].length > 0 && [...greeting].length <= 8, { greeting })

  const homeTextResult = await countHomeText(page)
  const baseline = V1_HOME_TEXT[width]
  const reduction = baseline ? 1 - homeTextResult.length / baseline : 0
  homeText[key] = {
    v2: homeTextResult.length,
    v1: baseline,
    reduction: Number(reduction.toFixed(4)),
    text: homeTextResult.text,
  }
  check(`${key} home text reduced >= 40%`, reduction >= 0.4, homeText[key])

  pages.home = await recordPage(page, key, 'home', labelRef, width)

  // Refresh + sound
  labelRef.label = `${key}:refresh`
  await page.locator('[data-testid="refresh-button"]').click()
  const refreshDisabled = await page.locator('[data-testid="refresh-button"]').isDisabled()
  await page.waitForTimeout(720)
  const refreshToast = await toastText(page)
  check(`${key} refresh`, refreshDisabled && refreshToast === '已更新', { refreshDisabled, refreshToast })
  extras.refresh = { disabledDuring: refreshDisabled, toast: refreshToast }

  labelRef.label = `${key}:sound`
  const soundBefore = await page.locator('[data-testid="sound-button"]').getAttribute('aria-pressed')
  await page.locator('[data-testid="sound-button"]').click()
  await page.waitForTimeout(200)
  const soundAfter = await page.locator('[data-testid="sound-button"]').getAttribute('aria-pressed')
  const soundToast = await toastText(page)
  await page.locator('[data-testid="sound-button"]').click()
  await page.waitForTimeout(200)
  const soundRestored = await page.locator('[data-testid="sound-button"]').getAttribute('aria-pressed')
  check(`${key} sound toggle`, soundBefore === 'true' && soundAfter === 'false' && soundToast === '声音已关' && soundRestored === 'true', {
    soundBefore,
    soundAfter,
    soundToast,
    soundRestored,
  })
  extras.sound = { soundBefore, soundAfter, soundToast, soundRestored }

  // Today node detail + share + feed
  labelRef.label = `${key}:day-sheet`
  await page.locator('[data-testid="day-node-today"]').click()
  await page.waitForTimeout(350)
  const daySheetOpen = await page.locator('[data-testid="day-sheet"]').isVisible()
  const daySheetTitle = await page.locator('[data-testid="day-sheet"] .sheet__title').textContent()
  const daySheetTouch = await auditTouch(page, 'dialog')
  await scanCopy(page, `${key}:day-sheet`)
  await screenshot(page, `extra/${key}-day-sheet.png`)
  await page.locator('[data-testid="day-share-button"]').click()
  await page.waitForTimeout(220)
  const shareToast = await toastText(page)
  await page.locator('[data-testid="day-feed-button"]').click()
  await page.waitForTimeout(350)
  const feedOpen = await page.locator('[data-testid="feed-sheet"]').isVisible()
  const feedRows = await page.locator('[data-testid="feed-sheet"] .feed-row').count()
  await scanCopy(page, `${key}:feed-sheet`)
  await screenshot(page, `extra/${key}-feed.png`)
  await closeDialog(page)
  check(`${key} day detail sheet`, daySheetOpen && daySheetTitle?.includes('周四'), { daySheetOpen, daySheetTitle })
  check(`${key} day detail touch`, daySheetTouch.violations.length === 0, daySheetTouch)
  check(`${key} share action`, shareToast === '战绩卡已生成', { shareToast })
  check(`${key} all feed sheet`, feedOpen && feedRows >= 3, { feedOpen, feedRows })
  extras.daySheet = { open: daySheetOpen, title: daySheetTitle, touch: daySheetTouch, screenshot: `extra/${key}-day-sheet.png` }
  extras.feed = { open: feedOpen, rows: feedRows, screenshot: `extra/${key}-feed.png` }

  // Missed day detail and repair entry
  labelRef.label = `${key}:missed-day`
  await page.locator('.day-node--missed').click()
  await page.waitForTimeout(350)
  const missedOpen = await page.locator('[data-testid="day-sheet"]').isVisible()
  const missedRepair = await page.locator('[data-testid="day-repair-button"]').isVisible()
  const missedText = await page.locator('[data-testid="day-sheet"]').innerText()
  await scanCopy(page, `${key}:missed-day`)
  await screenshot(page, `extra/${key}-missed-sheet.png`)
  await closeDialog(page)
  check(`${key} missed node drilldown`, missedOpen && missedRepair && missedText.includes('断签'), {
    missedOpen,
    missedRepair,
  })
  extras.missedDay = { open: missedOpen, repair: missedRepair, screenshot: `extra/${key}-missed-sheet.png` }

  // Top streak opens the same repair sheet
  labelRef.label = `${key}:repair-sheet`
  await page.locator('[data-testid="status-streak"]').click()
  await page.waitForTimeout(350)
  const repairOpen = await page.locator('[data-testid="repair-sheet"]').isVisible()
  const repairOptions = await page.locator('[data-testid="repair-sheet"] [role="radio"]').count()
  const repairTouch = await auditTouch(page, 'dialog')
  await scanCopy(page, `${key}:repair-sheet`)
  await screenshot(page, `extra/${key}-repair.png`)
  await closeDialog(page)
  check(`${key} repair sheet`, repairOpen && repairOptions === 2, { repairOpen, repairOptions })
  check(`${key} repair sheet touch`, repairTouch.violations.length === 0, repairTouch)
  extras.repairSheet = { open: repairOpen, options: repairOptions, touch: repairTouch, screenshot: `extra/${key}-repair.png` }

  // Consume one ember by repairing the missed day.
  labelRef.label = `${key}:repair-flow`
  await page.locator('.day-node--missed').click()
  await page.waitForTimeout(300)
  await page.locator('[data-testid="day-repair-button"]').click()
  await page.waitForTimeout(400)
  const repairToast = await toastText(page)
  const embersAfter = (await page.locator('[data-testid="status-embers"]').textContent())?.trim()
  const missedAfter = await page.locator('.day-node--missed').count()
  const doneAfter = await page.locator('.day-node--done').count()
  check(
    `${key} repair consumes one ember`,
    repairToast === '火焰续上了。' && embersAfter === '0' && missedAfter === 0 && doneAfter === 3,
    { repairToast, embersAfter, missedAfter, doneAfter },
  )
  extras.repairFlow = { toast: repairToast, embersAfter, missedAfter, doneAfter }

  // Reset local state after the destructive action.
  await goto(page, baseUrl)

  // League
  await page.locator(navSelector, { hasText: '小组榜' }).click()
  await page.waitForTimeout(600)
  labelRef.label = `${key}:league`
  const podiumCount = await page.locator('[data-testid="podium-card"]').count()
  const rowCount = await page.locator('[data-testid="league-row"]').count()
  const meRow = await page.locator('.league-row--me').count()
  const promotionZone = await page.locator('.zone-bar--promotion').count()
  const demotionZone = await page.locator('.zone-bar--demotion').count()
  const countdown = (await page.locator('[data-testid="countdown"]').textContent())?.trim()
  check(`${key} league 15 entries`, podiumCount === 3 && rowCount === 12, { podiumCount, rowCount })
  check(`${key} league own row highlighted`, meRow === 1, { meRow })
  check(`${key} league zones`, promotionZone === 1 && demotionZone === 1, { promotionZone, demotionZone })
  check(`${key} countdown pill`, Boolean(countdown && countdown.length > 4), { countdown })
  pages.league = await recordPage(page, key, 'league', labelRef, width)

  // Tooltip: hover + escape
  labelRef.label = `${key}:tooltip`
  const leagueTip = page.getByRole('button', { name: '晋级与降级' })
  await leagueTip.hover()
  await page.waitForTimeout(280)
  const tooltipVisible = await page.getByRole('tooltip').isVisible().catch(() => false)
  const tooltipText = await page.getByRole('tooltip').textContent().catch(() => null)
  await scanCopy(page, `${key}:tooltip`)
  await screenshot(page, `extra/${key}-tooltip.png`)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(220)
  const tooltipClosed = !(await page.getByRole('tooltip').isVisible().catch(() => false))
  check(`${key} tooltip hover`, tooltipVisible, { tooltipText })
  check(`${key} tooltip escape`, tooltipClosed, null)
  extras.tooltip = { screenshot: `extra/${key}-tooltip.png`, text: tooltipText, visible: tooltipVisible, closed: tooltipClosed }

  // Friends board
  labelRef.label = `${key}:friends`
  await page.locator('.segmented__item', { hasText: '好友' }).click()
  await page.waitForTimeout(350)
  const friendsOpen = await page.locator('[data-testid="friends-board"]').isVisible()
  const friendRows = await page.locator('[data-testid="friends-board"] [data-testid="league-row"]').count()
  await scanCopy(page, `${key}:friends`)
  await screenshot(page, `extra/${key}-friends.png`)
  await page.locator('.segmented__item', { hasText: '小组' }).click()
  await page.waitForTimeout(300)
  check(`${key} friends board`, friendsOpen && friendRows === 8, { friendsOpen, friendRows })
  extras.friends = { open: friendsOpen, rows: friendRows, screenshot: `extra/${key}-friends.png` }

  // Member sheet, follow, escape and backdrop close
  labelRef.label = `${key}:member`
  await page.locator('[data-testid="league-row"]').nth(1).click()
  await page.waitForTimeout(350)
  const memberOpen = await page.locator('[data-testid="user-detail-sheet"]').isVisible()
  const memberTitle = await page.locator('[data-testid="user-detail-sheet"] .sheet__title').textContent()
  const memberTouch = await auditTouch(page, 'dialog')
  const followButton = page.locator('[data-testid="user-detail-sheet"]').getByRole('button', { name: '关注' })
  const followVisible = await followButton.isVisible().catch(() => false)
  if (followVisible) {
    await followButton.click()
    await page.waitForTimeout(250)
  }
  const followToast = followVisible ? await toastText(page) : null
  await scanCopy(page, `${key}:member`)
  await screenshot(page, `extra/${key}-member.png`)
  await closeDialog(page)
  const memberClosed = (await page.locator('[data-testid="user-detail-sheet"]').count()) === 0
  await page.locator('[data-testid="league-row"]').nth(1).click()
  await page.waitForTimeout(300)
  await page.mouse.click(10, 10)
  await page.waitForTimeout(300)
  const backdropClosed = (await page.locator('[data-testid="user-detail-sheet"]').count()) === 0
  check(`${key} member detail`, memberOpen && memberClosed && backdropClosed, { memberOpen, memberTitle, memberClosed, backdropClosed })
  check(`${key} member touch`, memberTouch.violations.length === 0, memberTouch)
  check(`${key} follow action`, followVisible && followToast === '已关注', { followVisible, followToast })
  extras.member = {
    open: memberOpen,
    title: memberTitle,
    closedByEscape: memberClosed,
    closedByBackdrop: backdropClosed,
    touch: memberTouch,
    followToast,
    screenshot: `extra/${key}-member.png`,
  }

  // Reload between sheets so transient toasts do not leak into page screenshots.
  await goto(page, baseUrl)

  // Embers
  await page.locator(navSelector, { hasText: '余烬' }).click()
  await page.waitForTimeout(500)
  labelRef.label = `${key}:embers`
  const balance = (await page.locator('[data-testid="embers-balance"]').textContent())?.trim()
  const logRows = await page.locator('.log-row').count()
  check(`${key} embers page`, balance === '1' && logRows >= 3, { balance, logRows })
  pages.embers = await recordPage(page, key, 'embers', labelRef, width)
  await page.locator('[data-testid="embers-repair-button"]').click()
  await page.waitForTimeout(350)
  const emberRepairOpen = await page.locator('[data-testid="repair-sheet"]').isVisible()
  await closeDialog(page)
  check(`${key} embers repair entry`, emberRepairOpen, { emberRepairOpen })

  // History normal + week detail
  await page.locator(navSelector, { hasText: '历史' }).click()
  await page.waitForTimeout(950)
  labelRef.label = `${key}:history`
  const weekRows = await page.locator('.week-row').count()
  check(`${key} history weeks`, weekRows === 4, { weekRows })
  pages.history = await recordPage(page, key, 'history', labelRef, width)
  await page.locator('.week-row').first().click()
  await page.waitForTimeout(350)
  const weekSheetOpen = await page.locator('[data-testid="week-sheet"]').isVisible()
  await scanCopy(page, `${key}:week-sheet`)
  await screenshot(page, `extra/${key}-week.png`)
  await closeDialog(page)
  check(`${key} week detail`, weekSheetOpen, { weekSheetOpen })
  extras.weekSheet = { open: weekSheetOpen, screenshot: `extra/${key}-week.png` }

  // Me
  await page.locator(navSelector, { hasText: '我的' }).click()
  await page.waitForTimeout(500)
  labelRef.label = `${key}:me`
  const statCells = await page.locator('.stat-cell').count()
  const profileVisible = await page.locator('.profile-hero').isVisible()
  check(`${key} profile + four stats`, profileVisible && statCells === 4, { profileVisible, statCells })
  pages.me = await recordPage(page, key, 'me', labelRef, width)

  // Collection filter + equip
  labelRef.label = `${key}:collection`
  await page.locator('.collection .segmented__item', { hasText: '勋章' }).click()
  await page.waitForTimeout(300)
  const filterGroups = await page.locator('.collection-group').count()
  const filterTitle = await page.locator('.collection-group__title').first().textContent()
  const badgeTiles = await page.locator('.collection-tile').count()
  await scanCopy(page, `${key}:collection-filter`)
  await screenshot(page, `extra/${key}-collection-filter.png`)
  await page.locator('.collection .segmented__item', { hasText: '边框' }).click()
  await page.waitForTimeout(250)
  const bronzeTile = page.getByRole('button', { name: '青铜框，可装备' })
  await bronzeTile.scrollIntoViewIfNeeded()
  await bronzeTile.click()
  await page.waitForTimeout(250)
  const equipToast = await toastText(page)
  const equippedPressed = await page.getByRole('button', { name: '青铜框，已装备' }).getAttribute('aria-pressed')
  check(`${key} collection filter`, filterGroups === 1 && filterTitle === '勋章' && badgeTiles === 5, {
    filterGroups,
    filterTitle,
    badgeTiles,
  })
  check(`${key} collection equip`, equipToast === '已装备 · 青铜框' && equippedPressed === 'true', {
    equipToast,
    equippedPressed,
  })
  extras.collection = {
    filterGroups,
    filterTitle,
    badgeTiles,
    equipToast,
    equippedPressed,
    screenshot: `extra/${key}-collection-filter.png`,
  }

  // Settings: sound / haptics / theme
  labelRef.label = `${key}:settings`
  await page.locator('[data-testid="settings-button"]').click()
  await page.waitForTimeout(350)
  const settingsOpen = await page.locator('[data-testid="settings-sheet"]').isVisible()
  const settingsTouch = await auditTouch(page, 'dialog')
  await screenshot(page, `extra/${key}-settings.png`)
  await scanCopy(page, `${key}:settings`)

  const soundSwitch = page.getByRole('switch', { name: '声音' })
  const soundSwitchBefore = await soundSwitch.getAttribute('aria-checked')
  await soundSwitch.click()
  await page.waitForTimeout(220)
  const soundSwitchAfter = await soundSwitch.getAttribute('aria-checked')
  const soundSwitchToast = await toastText(page)
  const soundTopAfter = await page.locator('[data-testid="sound-button"]').getAttribute('aria-pressed')
  await soundSwitch.click()
  await page.waitForTimeout(200)

  const hapticSwitch = page.getByRole('switch', { name: '轻触反馈' })
  const hapticBefore = await hapticSwitch.getAttribute('aria-checked')
  await hapticSwitch.click()
  await page.waitForTimeout(220)
  const hapticAfter = await hapticSwitch.getAttribute('aria-checked')
  const hapticToast = await toastText(page)
  await hapticSwitch.click()
  await page.waitForTimeout(200)

  await page.locator('.theme-option', { hasText: '线性' }).click()
  await page.waitForTimeout(200)
  const themeClassLine = await page.locator('.app').getAttribute('class')
  const navIconSelector = width >= 960 ? '.nav-rail__item svg' : '.bottom-nav__item svg'
  const lineStroke = await page.evaluate(
    (selector) => getComputedStyle(document.querySelector(selector)).strokeWidth,
    navIconSelector,
  )
  await page.locator('.theme-option', { hasText: '填色' }).click()
  await page.waitForTimeout(200)
  const solidFill = await page.evaluate(
    (selector) => getComputedStyle(document.querySelector(selector)).fillOpacity,
    navIconSelector,
  )
  await page.locator('.theme-option', { hasText: '圆润' }).click()
  await page.waitForTimeout(180)

  await page.getByRole('button', { name: '集成说明' }).click()
  await page.waitForTimeout(300)
  const integrationOpen = await page.locator('[data-testid="integration-sheet"]').isVisible()
  await scanCopy(page, `${key}:integration`)
  await screenshot(page, `extra/${key}-integration.png`)
  await closeDialog(page)
  await page.locator('[data-testid="settings-button"]').click()
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: '附近的人' }).click()
  await page.waitForTimeout(300)
  const nearbyOpen = await page.locator('[data-testid="nearby-sheet"]').isVisible()
  const nearbyRows = await page.locator('[data-testid="nearby-sheet"] .people-row').count()
  await scanCopy(page, `${key}:nearby`)
  await screenshot(page, `extra/${key}-nearby.png`)
  await closeDialog(page)

  check(`${key} settings sheet`, settingsOpen, { settingsOpen })
  check(`${key} settings touch`, settingsTouch.violations.length === 0, settingsTouch)
  check(`${key} integration + nearby`, integrationOpen && nearbyOpen && nearbyRows > 0, {
    integrationOpen,
    nearbyOpen,
    nearbyRows,
  })
  check(
    `${key} sound + haptics`,
    soundSwitchBefore === 'true' &&
      soundSwitchAfter === 'false' &&
      soundSwitchToast === '声音已关' &&
      soundTopAfter === 'false' &&
      hapticBefore === 'true' &&
      hapticAfter === 'false' &&
      hapticToast === '轻触反馈已关',
    { soundSwitchBefore, soundSwitchAfter, soundSwitchToast, soundTopAfter, hapticBefore, hapticAfter, hapticToast },
  )
  check(`${key} icon theme`, themeClassLine?.includes('icon-theme-line') && lineStroke === '1.4px' && solidFill === '0.42', {
    themeClassLine,
    lineStroke,
    solidFill,
  })
  extras.settings = { open: settingsOpen, touch: settingsTouch, screenshot: `extra/${key}-settings.png` }
  extras.integration = { open: integrationOpen, screenshot: `extra/${key}-integration.png` }
  extras.nearby = { open: nearbyOpen, rows: nearbyRows, screenshot: `extra/${key}-nearby.png` }
  extras.soundHaptics = {
    soundSwitchBefore,
    soundSwitchAfter,
    soundSwitchToast,
    soundTopAfter,
    hapticBefore,
    hapticAfter,
    hapticToast,
  }
  extras.iconTheme = { themeClassLine, lineStroke, solidFill }

  // Avatar upload + save inside edit sheet
  labelRef.label = `${key}:edit`
  await page.locator('[data-testid="edit-profile"]').click()
  await page.waitForTimeout(350)
  const editOpen = await page.locator('[data-testid="edit-sheet"]').isVisible()
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
  const avatarPreview = await page.locator('.edit-profile__preview').isVisible()
  await screenshot(page, `extra/${key}-edit.png`)
  await page.locator('[data-testid="save-profile"]').click()
  await page.waitForTimeout(700)
  const saveToast = await toastText(page)
  const editClosed = (await page.locator('[data-testid="edit-sheet"]').count()) === 0
  check(`${key} avatar preview + save`, editOpen && avatarPreview && saveToast === '已保存' && editClosed, {
    editOpen,
    avatarPreview,
    saveToast,
    editClosed,
  })
  extras.edit = { open: editOpen, preview: avatarPreview, saveToast, closed: editClosed, screenshot: `extra/${key}-edit.png` }

  // History empty + loading
  await goto(page, `${baseUrl}/?history=empty`)
  await page.locator(navSelector, { hasText: '历史' }).click()
  await page.waitForTimeout(950)
  const emptyVisible = await page.locator('.empty-state').isVisible()
  await scanCopy(page, `${key}:history-empty`)
  await screenshot(page, `extra/${key}-history-empty.png`)
  check(`${key} history empty`, emptyVisible, null)
  extras.historyEmpty = { visible: emptyVisible, screenshot: `extra/${key}-history-empty.png` }

  await goto(page, `${baseUrl}/?history=loading`)
  await page.locator(navSelector, { hasText: '历史' }).click()
  await page.waitForTimeout(220)
  const loadingVisible = await page.locator('.history-skeleton').isVisible()
  await scanCopy(page, `${key}:history-loading`)
  await screenshot(page, `extra/${key}-history-loading.png`)
  check(`${key} history loading`, loadingVisible, null)
  extras.historyLoading = { visible: loadingVisible, screenshot: `extra/${key}-history-loading.png` }

  // Logout + login
  labelRef.label = `${key}:logout`
  await goto(page, baseUrl)
  await page.locator(navSelector, { hasText: '我的' }).click()
  await page.waitForTimeout(450)
  await page.locator('[data-testid="settings-button"]').click()
  await page.waitForTimeout(300)
  await page.locator('[data-testid="logout-button"]').click()
  await page.waitForTimeout(300)
  const logoutSheet = await page.locator('[data-testid="logout-sheet"]').isVisible()
  await page.locator('[data-testid="logout-confirm"]').click()
  await page.waitForTimeout(400)
  const loginVisible = await page.locator('.login-card').isVisible()
  await scanCopy(page, `${key}:login`)
  await screenshot(page, `extra/${key}-login.png`)
  await page.getByRole('button', { name: '重新进入' }).click()
  await page.waitForTimeout(450)
  const reentered = await page.locator('[data-testid="home-page"]').isVisible()
  check(`${key} logout + login`, logoutSheet && loginVisible && reentered, { logoutSheet, loginVisible, reentered })
  extras.logout = { sheet: logoutSheet, loginVisible, reentered, screenshot: `extra/${key}-login.png` }

  await context.close()
  return { pages, extras }
}

async function runTouchAndMotion(browser) {
  const width = 390
  const height = 844
  const labelRef = { label: '390:touch' }
  const context = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 1,
    hasTouch: true,
    isMobile: true,
  })
  const page = await context.newPage()
  attachDiagnostics(page, labelRef)
  await goto(page, baseUrl)

  const result = {}
  const trigger = page.getByRole('button', { name: '连续 3 天' })
  await trigger.tap()
  await page.waitForTimeout(300)
  const repairOpen = await page.locator('[data-testid="repair-sheet"]').isVisible()
  const repairTouch = await auditTouch(page, 'dialog')
  await closeDialog(page)
  check('touch streak opens repair', repairOpen, { repairOpen })
  check('touch repair sheet targets', repairTouch.violations.length === 0, repairTouch)

  await page.locator('[data-testid="day-node-today"]').tap()
  await page.waitForTimeout(300)
  const dayOpen = await page.locator('[data-testid="day-sheet"]').isVisible()
  await closeDialog(page)
  check('touch node drilldown', dayOpen, { dayOpen })

  await page.locator('.bottom-nav__item', { hasText: '小组榜' }).click()
  await page.waitForTimeout(500)
  const tip = page.getByRole('button', { name: '晋级与降级' })
  await tip.tap()
  await page.waitForTimeout(280)
  const tipOpen = await page.getByRole('tooltip').isVisible().catch(() => false)
  await screenshot(page, 'extra/390-touch-tooltip.png')
  await tip.tap()
  await page.waitForTimeout(280)
  const tipClosed = !(await page.getByRole('tooltip').isVisible().catch(() => false))
  check('touch tooltip toggles', tipOpen && tipClosed, { tipOpen, tipClosed })
  result.tooltip = { open: tipOpen, closed: tipClosed }
  result.repair = { open: repairOpen, touch: repairTouch }
  await context.close()

  labelRef.label = '390:reduced-motion'
  const reducedContext = await browser.newContext({
    viewport: { width, height },
    deviceScaleFactor: 1,
    reducedMotion: 'reduce',
  })
  const reducedPage = await reducedContext.newPage()
  attachDiagnostics(reducedPage, labelRef)
  await goto(reducedPage, baseUrl)
  const reduced = await reducedPage.evaluate(() => ({
    media: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    emberAnimation: getComputedStyle(document.querySelector('.ember-sprite')).animationName,
    todayAnimation: getComputedStyle(document.querySelector('.day-node--today'), '::before').animationName,
    pageAnimation: getComputedStyle(document.querySelector('.page')).animationDuration,
  }))
  await scanCopy(reducedPage, '390:reduced-motion')
  await reducedPage.screenshot({ path: path.join(outDir, 'extra/390-reduced-motion.png') })
  screenshots.push('extra/390-reduced-motion.png')
  check(
    'reduced motion',
    reduced.media && reduced.emberAnimation === 'none' && reduced.todayAnimation === 'none' && reduced.pageAnimation === '0.001s',
    reduced,
  )
  result.reducedMotion = reduced
  await reducedContext.close()
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
  '主人',
  '去画一笔',
  '开始创作',
  '打卡按钮',
  '打卡',
  '多邻国',
  'duolingo',
  '30 人',
  '30人',
  '商店',
  '锦标赛',
  '用户',
  '系统',
  '算法',
  'channel',
  'ingest',
  'player_ref',
].map((term) => term.toLowerCase())

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
    forbiddenTerms.forEach((term) => {
      if (haystack.includes(term)) matches.push({ term, context: context.label })
    })
    pathPatterns.forEach((pattern, index) => {
      if (pattern.test(context.text)) matches.push({ pathPatternIndex: index, context: context.label })
    })
  }
  return matches
}

function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH
  for (const candidate of ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser']) {
    if (fs.existsSync(candidate)) return candidate
  }
  return undefined
}

const server = await ensureServer()
const chromePath = findChrome()
const browser = await chromium.launch({
  args: ['--no-sandbox'],
  ...(chromePath ? { executablePath: chromePath } : {}),
})

const report = {
  prototype: 'Ghost League v2 · Duolingo-close prototype',
  generatedAt: new Date().toISOString(),
  gitHead: getGitHead(),
  baseUrl,
  browser: `${browser.browserType().name()} ${browser.version()}`,
  startCommand: 'cd prototype && npm run dev -- --host 127.0.0.1 --port 4173',
  buildCommand: 'cd prototype && npm run build',
  e2eCommand: 'cd prototype && CHROME_PATH=/usr/bin/google-chrome npm run test:e2e',
  coordinateSpace: 'document',
  touchThreshold: minTouch,
  viewports: [
    { width: 390, height: 844, nav: 'bottom' },
    { width: 1440, height: 900, nav: 'rail' },
  ],
  homeText: {
    method: 'document.body.innerText, whitespace stripped',
    baseline: V1_HOME_TEXT,
    data: homeText,
  },
  screenshots,
  pages: {},
  extras: {},
  touch: {},
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
    '全部为本地 mock：刷新、分享、补签、关注、上传头像、保存资料、登录都没有网络请求。',
    '不实现 30 人小组规则；UI 只按 15 人组声称前 3 晋级/后 3 降级。',
    '历史空态与加载态通过 ?history=empty / ?history=loading 预览，没有额外界面开关。',
    '声音开关只切换状态与提示，不播放音频；触觉调用 navigator.vibrate（设备不支持时静默）。',
    '头像只在本机预览，不上传；分享不生成图片。',
    '15 人榜在 390×844 首屏需要滚动，完整榜单见 full/390-league.png。',
    '这是独立原型，不是生产 PWA；未修改 web/、ghost_league/、tests/。',
  ],
}

try {
  report.pages['390'] = await runViewport(browser, 390, 844)
  report.pages['1440'] = await runViewport(browser, 1440, 900)
  report.extras = {
    390: report.pages['390'].extras,
    1440: report.pages['1440'].extras,
  }
  report.touch = await runTouchAndMotion(browser)
} finally {
  await browser.close()
  if (server) server.kill('SIGTERM')
}

report.copy.contexts = copyContexts.map((context) => context.label)
report.copy.matches = copyMatches()
check('no console errors', consoleErrors.length === 0, consoleErrors)
check('no page errors', pageErrors.length === 0, pageErrors)
check('no forbidden copy', report.copy.matches.length === 0, report.copy.matches)
check(
  'home text reduction across viewports',
  Object.values(homeText).every((entry) => entry.v1 > 0 && entry.reduction >= 0.4),
  homeText,
)
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
  homeText: Object.fromEntries(
    Object.entries(homeText).map(([key, entry]) => [key, { v1: entry.v1, v2: entry.v2, reduction: entry.reduction }]),
  ),
  report: path.join(outDir, 'report.json'),
}

console.log(JSON.stringify(summary, null, 2))
if (failures.length > 0) {
  console.error(JSON.stringify(failures, null, 2))
  process.exitCode = 1
}
