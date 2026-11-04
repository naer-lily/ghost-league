import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'

const APP_URL = 'http://127.0.0.1:4174/'
const SHOTS = path.join(process.cwd(), '..', 'artifacts', 'bet-task-rows')
fs.mkdirSync(SHOTS, { recursive: true })

interface BetLike {
  id: number
  kind: 'daily' | 'weekly'
  period_key: string
  rival_id: string
  stake: number
  free_stake: number
  paid_stake: number
  target_margin: number
  odds: number
  status: 'placed' | 'won' | 'lost' | 'void'
  placed_at: string
  locked_at: string | null
  settled_at: string | null
  payout: number
  result_diff: number | null
}

interface RivalStateLike {
  server_now: string
  week_start: string
  selection: Record<string, unknown>
  me: Record<string, unknown>
  rival: Record<string, unknown>
  result: Record<string, unknown> | null
  bets: {
    weekly: BetLike | null
    daily: BetLike | null
    group: null
  }
  bet_options: Record<string, unknown>
  projection: null
  bet_windows: Record<string, string>
}

interface MockState {
  serverNow: string
  rivalState: RivalStateLike
  tasks: Array<Record<string, unknown>>
}

const WEEK_START = '2026-11-02'

function player(
  userId: string,
  name: string,
  weekXp: number,
  todayXp: number,
  power: number,
): Record<string, unknown> {
  return {
    user_id: userId,
    display_name: name,
    avatar_url: null,
    group_no: 1,
    tier: 'Bronze',
    power,
    week_xp: weekXp,
    today_xp: todayXp,
  }
}

function makeBet(
  overrides: Partial<BetLike> & Pick<BetLike, 'id' | 'kind'>,
): BetLike {
  return {
    period_key: overrides.kind === 'daily' ? '2026-11-04' : WEEK_START,
    rival_id: 'ch-rival',
    stake: 120,
    free_stake: 20,
    paid_stake: 100,
    target_margin: 0,
    odds: 2,
    status: 'placed',
    placed_at: '2026-11-04T10:00:00+08:00',
    locked_at: null,
    settled_at: null,
    payout: 0,
    result_diff: null,
    ...overrides,
  }
}

function makeRivalState(
  serverNow: string,
  daily: BetLike | null,
  weekly: BetLike | null,
): RivalStateLike {
  return {
    server_now: serverNow,
    week_start: WEEK_START,
    selection: {
      open: false,
      locks_at: '2026-11-02T23:59:59+08:00',
      auto_select_at: '2026-11-03T09:00:00+08:00',
      mode: 'manual',
    },
    me: player('naer-lily', '那尔', 823, 638, 1667),
    rival: player('ch-rival', '林间', 589, 540, 980),
    result: null,
    bets: { weekly, daily, group: null },
    bet_options: {
      weekly: {
        target_options: [{ margin: 0, odds: 2, expected_xp: 823 }],
        min_target_margin: 0,
        max_target_margin: 600,
        min_paid_stake: 0,
        max_paid_stake: 500,
        free_stake: 20,
        reference: 589,
      },
      daily: {
        target_options: [{ margin: 49, odds: 2, expected_xp: 638 }],
        min_target_margin: 49,
        max_target_margin: 308,
        min_paid_stake: 0,
        max_paid_stake: 100,
        free_stake: 20,
        reference: 49,
      },
      group: null,
    },
    projection: null,
    bet_windows: {
      weekly_locks_at: '2026-11-02T23:59:59+08:00',
      daily_locks_at: '2026-11-04T21:00:00+08:00',
      daily_settles_at: '2026-11-04T22:30:00+08:00',
    },
  }
}

function makeTasks(): Array<Record<string, unknown>> {
  const base = {
    description: '',
    difficulty: 1,
    chest_tier: 1,
    chest_pool: 'daily_1',
    missed_date: null,
    completed_at: null,
    chest_amount: null,
    chest_reward_type: 'diamonds',
    chest_boost_minutes: null,
    chest_star: null,
    proof_url: null,
    progress: null,
  }
  return [
    {
      ...base,
      id: 'ti_checkin',
      source: 'checkin',
      title: '每日打卡',
      description: '画满 10 分钟，开个小宝箱。',
      sort_order: 0,
      starts_at: '2026-11-02T00:00:00+08:00',
      ends_at: '2026-11-05T00:00:00+08:00',
      status: 'active',
      chest_status: 'none',
    },
    {
      ...base,
      id: 'ti_weekly',
      source: 'weekly_chain',
      title: '本周 1000 XP',
      chest_pool: 'weekly_chain_1',
      sort_order: 10,
      starts_at: '2026-11-02T00:00:00+08:00',
      ends_at: '2026-11-09T00:00:00+08:00',
      status: 'active',
      chest_status: 'none',
      progress: { current: 400, target: 1000 },
    },
    {
      ...base,
      id: 'ti_done',
      source: 'daily_manual',
      title: '速写一张',
      difficulty: 2,
      chest_tier: 2,
      sort_order: 1,
      starts_at: '2026-11-02T00:00:00+08:00',
      ends_at: '2026-11-05T00:00:00+08:00',
      status: 'completed',
      completed_at: '2026-11-04T09:00:00+08:00',
      chest_status: 'claimed',
      chest_amount: 7,
    },
  ]
}

function makeSnapshot(state: MockState): Record<string, unknown> {
  const me = state.rivalState.me as {
    user_id: string
    display_name: string
    tier: string
  }
  return {
    profile: {
      user_id: me.user_id,
      display_name: me.display_name,
      avatar_url: null,
      activity_label: '绘画',
      icon_theme: 'material',
      tier: me.tier,
      group_id: 1,
      group_no: 1,
      joined_week: WEEK_START,
      week_start: WEEK_START,
      equipped_title: null,
      frame: null,
      backdrop: null,
      badge_accent: null,
      updated_at: state.serverNow,
    },
    status: {
      user_id: me.user_id,
      display_name: me.display_name,
      avatar_url: null,
      activity_label: '绘画',
      icon_theme: 'material',
      tier: me.tier,
      group: {
        id: 1,
        no: 1,
        tier: me.tier,
        week_start: WEEK_START,
        size: 15,
      },
      group_id: 1,
      group_size: 15,
      week_start: WEEK_START,
      seconds: 3149,
      xp: 823,
      rank: 3,
      power: 1667,
      power_percentile: 0.625,
      power_updated_at: state.serverNow,
      power_provisional: false,
      today_seconds: 779,
      today_xp: 638,
      last_activity_at: state.serverNow,
      required_xp: 100,
      checkin: 'verified',
      streak: {
        current: 2,
        longest: 2,
        clean_current: 2,
        last_checked_date: '2026-11-04',
      },
      embers: { balance: 1, cap: 3, earned_this_week: 0 },
      gems: 128,
      diamonds: 720,
      diamond_cap: 1000,
      diamond_cap_level: 0,
      diamond_excess: 0,
      diamond_boost: {
        expires_at: null,
        remaining_seconds: 0,
        multiplier: 1,
      },
      inventory: { star: 0, seasonal_star: 0, ember: 0 },
      stars: [],
      equipped_title: null,
      equipped_title_id: null,
      frame: null,
      frame_id: null,
      backdrop: null,
      badge_accent: null,
      next_settlement_at: '2026-11-09T00:00:00+08:00',
      updated_at: state.serverNow,
    },
    standings: {
      week_start: WEEK_START,
      group: {
        id: 1,
        no: 1,
        tier: 'Bronze',
        week_start: WEEK_START,
        size: 15,
      },
      group_id: 1,
      group_size: 15,
      promotion_quota: 4,
      demotion_quota: 4,
      me: { rank: 3, xp: 823 },
      standings: [
        {
          rank: 1,
          user_id: 'ch-one',
          display_name: '夜航',
          avatar_url: null,
          is_me: false,
          xp: 1200,
          power: 1500,
          checkin: 'verified',
          streak: 2,
          title: null,
          frame: null,
          frame_id: null,
          backdrop: null,
        },
        {
          rank: 2,
          user_id: 'ch-two',
          display_name: '第九名',
          avatar_url: null,
          is_me: false,
          xp: 980,
          power: 1400,
          checkin: 'verified',
          streak: 1,
          title: null,
          frame: null,
          frame_id: null,
          backdrop: null,
        },
        {
          rank: 3,
          user_id: me.user_id,
          display_name: me.display_name,
          avatar_url: null,
          is_me: true,
          xp: 823,
          power: 1667,
          checkin: 'verified',
          streak: 2,
          title: null,
          frame: null,
          frame_id: null,
          backdrop: null,
        },
      ],
    },
  }
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function installMockApi(page: Page, state: MockState) {
  await page.route('**/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/v1/me/tasks') {
      await fulfillJson(route, {
        server_now: state.serverNow,
        tasks: state.tasks,
      })
      return
    }
    if (path === '/v1/me/rival') {
      await fulfillJson(route, state.rivalState)
      return
    }
    if (path === '/v1/me/bets') {
      await fulfillJson(route, {
        server_now: state.serverNow,
        week_start: WEEK_START,
        day: '2026-11-04',
        weekly: state.rivalState.bets.weekly,
        daily: state.rivalState.bets.daily,
        group: null,
        bets: state.rivalState.bets,
        bet_options: state.rivalState.bet_options,
        bet_windows: state.rivalState.bet_windows,
      })
      return
    }
    if (path === '/v1/me/profile') {
      const snapshot = makeSnapshot(state)
      await fulfillJson(route, snapshot.profile)
      return
    }
    if (path === '/v1/me/status') {
      const snapshot = makeSnapshot(state)
      await fulfillJson(route, snapshot.status)
      return
    }
    if (path === '/v1/league/standings') {
      const snapshot = makeSnapshot(state)
      await fulfillJson(route, snapshot.standings)
      return
    }
    if (path === '/v1/me/rival/candidates') {
      await fulfillJson(route, {
        server_now: state.serverNow,
        week_start: WEEK_START,
        selection_open: false,
        candidates: [],
      })
      return
    }
    await fulfillJson(route, { detail: 'not found' }, 404)
  })
  await page.route('**/favicon.ico', (route) => route.fulfill({ status: 204 }))
}

async function openHome(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('gl.token.v1', 'e2e-token')
  })
  await page.goto(APP_URL)
  await expect(page.getByTestId('task-list')).toBeVisible()
}

async function expectNoHorizontalOverflow(page: Page) {
  const width = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }))
  expect(width.scroll).toBeLessThanOrEqual(width.client + 1)
}

function trackConsoleErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

test.use({ viewport: { width: 390, height: 844 } })

test('unbet rows are full-width buttons without overflow', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  const state: MockState = {
    serverNow: '2026-11-02T12:00:00+08:00',
    rivalState: makeRivalState('2026-11-02T12:00:00+08:00', null, null),
    tasks: makeTasks(),
  }
  await installMockApi(page, state)
  await openHome(page)

  const daily = page.getByTestId('bet-task-open-daily')
  const weekly = page.getByTestId('bet-task-open-weekly')
  await expect(daily).toHaveText('日注')
  await expect(weekly).toHaveText('周注')
  await expect(page.getByText('点击下注')).toHaveCount(0)
  await expect(page.getByTestId('bet-task-daily')).toHaveAttribute(
    'data-state',
    'open',
  )
  await page.getByTestId('task-list').scrollIntoViewIfNeeded()
  await expectNoHorizontalOverflow(page)
  await page.screenshot({
    path: `${SHOTS}/01-unbet-buttons-390x844.png`,
  })
  expect(errors).toEqual([])
})

test('placed rows show live XP, signed diff and inline expansion', async ({
  page,
}) => {
  const errors = trackConsoleErrors(page)
  const serverNow = '2026-11-04T12:00:00+08:00'
  const daily = makeBet({
    id: 1,
    kind: 'daily',
    target_margin: 49,
  })
  const weekly = makeBet({
    id: 2,
    kind: 'weekly',
    target_margin: 0,
  })
  const state: MockState = {
    serverNow,
    rivalState: makeRivalState(serverNow, daily, weekly),
    tasks: makeTasks(),
  }
  await installMockApi(page, state)
  await openHome(page)

  const dailyRow = page.getByTestId('bet-task-daily')
  const weeklyRow = page.getByTestId('bet-task-weekly')
  await expect(dailyRow).toHaveAttribute('data-state', 'placed')
  await expect(dailyRow.getByTestId('bet-task-me-daily')).toHaveText('638')
  await expect(dailyRow.getByTestId('bet-task-rival-daily')).toHaveText('589')
  await expect(dailyRow.getByTestId('bet-task-diff-daily')).toHaveText('+49')
  await expect(dailyRow.getByTestId('bet-task-diff-daily')).toHaveAttribute(
    'data-tone',
    'ahead',
  )
  await expect(weeklyRow.getByTestId('bet-task-me-weekly')).toHaveText('823')
  await expect(weeklyRow.getByTestId('bet-task-rival-weekly')).toHaveText('589')
  await expect(weeklyRow.getByTestId('bet-task-diff-weekly')).toHaveText('+234')
  await expect(dailyRow).not.toContainText('目标')
  await expect(dailyRow).not.toContainText('本金')
  await page.getByTestId('task-list').scrollIntoViewIfNeeded()
  await expectNoHorizontalOverflow(page)
  await page.screenshot({
    path: `${SHOTS}/02-placed-bars-390x844.png`,
  })

  await dailyRow.getByTestId('bet-task-toggle-daily').click()
  await expect(page.getByTestId('bet-task-details-daily')).toBeVisible()
  await expect(page.getByTestId('bet-task-details-daily')).toContainText(
    '120 × 2.00',
  )
  await expect(page.getByTestId('bet-task-details-daily')).toContainText(
    '+49 XP',
  )
  await expect(page.getByTestId('bet-task-details-daily')).toContainText('240')
  await expectNoHorizontalOverflow(page)
  await page.screenshot({
    path: `${SHOTS}/03-daily-expanded-390x844.png`,
  })

  await weeklyRow.getByTestId('bet-task-toggle-weekly').click()
  await expect(page.getByTestId('bet-task-details-weekly')).toBeVisible()
  await expect(page.getByTestId('bet-task-details-daily')).toHaveCount(0)
  await page.screenshot({
    path: `${SHOTS}/04-weekly-expanded-390x844.png`,
  })

  await weeklyRow.getByTestId('bet-task-toggle-weekly').click()
  await expect(page.getByTestId('bet-task-details-weekly')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('settled rows keep the result and a frozen bar', async ({ page }) => {
  const errors = trackConsoleErrors(page)
  const serverNow = '2026-11-04T23:00:00+08:00'
  const daily = makeBet({
    id: 31,
    kind: 'daily',
    target_margin: 49,
    status: 'won',
    payout: 240,
    result_diff: 49,
    settled_at: '2026-11-04T22:30:00+08:00',
  })
  const weekly = makeBet({
    id: 32,
    kind: 'weekly',
    target_margin: 0,
  })
  const state: MockState = {
    serverNow,
    rivalState: makeRivalState(serverNow, daily, weekly),
    tasks: makeTasks(),
  }
  await installMockApi(page, state)
  await openHome(page)

  const dailyRow = page.getByTestId('bet-task-daily')
  await expect(dailyRow).toHaveAttribute('data-state', 'settled')
  await expect(dailyRow).toHaveAttribute('data-frozen', 'true')
  await expect(dailyRow.getByTestId('bet-task-result-daily')).toHaveText(
    '已赢 +240',
  )
  await expect(dailyRow.getByTestId('bet-task-me-daily')).toHaveText('638')
  await expect(dailyRow.getByTestId('bet-task-diff-daily')).toHaveText('+49')
  await expect(page.getByTestId('bet-task-weekly')).toHaveAttribute(
    'data-state',
    'placed',
  )
  await page.getByTestId('task-list').scrollIntoViewIfNeeded()
  await expectNoHorizontalOverflow(page)
  await page.screenshot({
    path: `${SHOTS}/05-settled-390x844.png`,
  })
  expect(errors).toEqual([])
})
