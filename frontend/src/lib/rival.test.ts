import { describe, expect, it } from 'vitest'
import {
  BET_TABS,
  betReturn,
  betStatusText,
  clashBar,
  dailyLocked,
  formatCountdown,
  formatOdds,
  gapView,
  groupLocked,
  weekNumber,
  weeklyLocked,
} from './rival'
import type { Bet, BetWindows } from '../api/types'

const NOW = new Date('2026-11-02T20:00:00+08:00')

function windows(overrides: Partial<BetWindows> = {}): BetWindows {
  return {
    weekly_locks_at: '2026-11-02T23:59:59+08:00',
    daily_locks_at: '2026-11-03T21:00:00+08:00',
    daily_settles_at: '2026-11-03T22:30:00+08:00',
    ...overrides,
  }
}

function bet(overrides: Partial<Bet> = {}): Bet {
  return {
    id: 1,
    kind: 'weekly',
    period_key: '2026-11-02',
    rival_id: 'ch-rival',
    stake: 40,
    free_stake: 20,
    paid_stake: 20,
    target_margin: 0,
    odds: 2,
    status: 'placed',
    placed_at: '2026-11-02T20:00:00+08:00',
    locked_at: null,
    settled_at: null,
    payout: 0,
    result_diff: null,
    ...overrides,
  }
}

describe('rival helpers', () => {
  it('splits the collision bar by each side and falls back to 50/50', () => {
    expect(clashBar(0, 0)).toEqual({
      leftPercent: 50,
      rightPercent: 50,
      total: 0,
    })
    const split = clashBar(150, 450)
    expect(split.leftPercent).toBeCloseTo(25)
    expect(split.rightPercent).toBeCloseTo(75)
    expect(split.total).toBe(600)
    expect(clashBar(0, 10).leftPercent).toBe(0)
    expect(clashBar(10, 0).rightPercent).toBe(0)
  })

  it('describes lead, lag and ties without inventing a fixed target', () => {
    expect(gapView(760, 150)).toMatchObject({
      tone: 'ahead',
      amount: 610,
      label: '领先',
    })
    expect(gapView(150, 760)).toMatchObject({
      tone: 'behind',
      amount: 610,
      label: '落后',
    })
    expect(gapView(150, 150)).toMatchObject({
      tone: 'even',
      amount: 0,
      label: '双方持平',
    })
  })

  it('formats countdowns and treats elapsed windows as closed', () => {
    expect(
      formatCountdown('2026-11-02T21:12:00+08:00', NOW),
    ).toBe('1 小时 12 分')
    expect(
      formatCountdown('2026-11-06T08:00:00+08:00', NOW),
    ).toBe('3 天 12 小时')
    expect(formatCountdown('2026-11-02T19:00:00+08:00', NOW)).toBe(
      '已截止',
    )
    expect(formatCountdown('not-a-date', NOW)).toBe('—')
  })

  it('uses the ISO week of the Monday week start', () => {
    expect(weekNumber('2026-11-02')).toBe('第 45 周')
    expect(weekNumber('2026-12-28')).toBe('第 53 周')
    expect(weekNumber('bad')).toBe('本周')
  })

  it('knows the weekly and daily lock windows', () => {
    expect(weeklyLocked(windows(), NOW)).toBe(false)
    expect(dailyLocked(windows(), NOW)).toBe(false)
    expect(
      weeklyLocked(
        windows({ weekly_locks_at: '2026-11-02T19:00:00+08:00' }),
        NOW,
      ),
    ).toBe(true)
    expect(
      dailyLocked(
        windows({ daily_locks_at: '2026-11-02T19:00:00+08:00' }),
        NOW,
      ),
    ).toBe(true)
  })

  it('only exposes weekly/daily rival bet tabs', () => {
    expect(BET_TABS.map((tab) => tab.kind)).toEqual(['weekly', 'daily'])
    expect(BET_TABS.map((tab) => tab.label)).toEqual(['周注', '日注'])
  })

  it('shares the weekly lock with the group bet', () => {
    expect(groupLocked(windows(), NOW)).toBe(false)
    expect(
      groupLocked(
        windows({ weekly_locks_at: '2026-11-02T19:00:00+08:00' }),
        NOW,
      ),
    ).toBe(true)
  })

  it('uses server odds for returns and formats them', () => {
    expect(betReturn(20, 1.2)).toBe(24)
    expect(betReturn(520, 2)).toBe(1040)
    expect(formatOdds(2)).toBe('2.00')
    expect(formatOdds(1.375)).toBe('1.38')
  })

  it('reads bet status copy', () => {
    expect(betStatusText(null)).toBe('未下注')
    expect(betStatusText(bet())).toBe('已下注')
    expect(betStatusText(bet({ status: 'won', payout: 80 }))).toBe(
      '已赢 +80',
    )
    expect(betStatusText(bet({ status: 'lost' }))).toBe('已输')
    expect(betStatusText(bet({ status: 'void' }))).toBe('已退回')
  })
})
