import { describe, expect, it } from 'vitest'
import {
  buildTodayProgress,
  isRecentlyUpdated,
  RECENT_UPDATE_WINDOW_MS,
  relativeUpdateLabel,
  TODAY_GOAL_TIERS,
} from './todayProgress'

const NOW = new Date('2026-10-31T09:10:00+08:00')
const RECENT = '2026-10-31T09:05:00+08:00'
const STALE = '2026-10-31T07:55:00+08:00'

function input(overrides: Partial<Parameters<typeof buildTodayProgress>[0]> = {}) {
  return {
    todayXp: 129,
    todaySeconds: 779,
    updatedAt: RECENT,
    ...overrides,
  }
}

describe('today goal tiers', () => {
  it('uses the six product tiers in minutes and XP', () => {
    expect(TODAY_GOAL_TIERS.map((tier) => tier.minutes)).toEqual([
      10, 30, 60, 120, 180, 240,
    ])
    expect(TODAY_GOAL_TIERS.map((tier) => tier.xp)).toEqual([
      100, 300, 600, 1200, 1800, 2400,
    ])
  })
})

describe('buildTodayProgress', () => {
  it('marks completed, current and future tiers and the XP gap', () => {
    const view = buildTodayProgress(input(), NOW)

    expect(view.todayXp).toBe(129)
    expect(view.todayMinutes).toBe(12)
    expect(view.completedCount).toBe(1)
    expect(view.currentIndex).toBe(1)
    expect(view.currentTier.minutes).toBe(30)
    expect(view.nextTier?.minutes).toBe(30)
    expect(view.remainingXp).toBe(171)
    expect(view.allComplete).toBe(false)
    expect(view.tiers.map((tier) => tier.state)).toEqual([
      'complete',
      'current',
      'future',
      'future',
      'future',
      'future',
    ])
    expect(view.progress).toBeCloseTo((1 + 29 / 200) / 6, 10)
    expect(view.percent).toBe(19)
    expect(view.valueText).toBe('129 XP')
    expect(view.updateLabel).toBe('5 分钟前更新')
  })

  it('treats an exact tier target as completed and advances the current tier', () => {
    const view = buildTodayProgress(
      input({ todayXp: 300, todaySeconds: 1800 }),
      NOW,
    )

    expect(view.completedCount).toBe(2)
    expect(view.currentTier.minutes).toBe(60)
    expect(view.remainingXp).toBe(300)
    expect(view.progress).toBeCloseTo(2 / 6, 10)
    expect(view.tiers[1]?.state).toBe('complete')
    expect(view.tiers[2]?.state).toBe('current')
  })

  it('starts on the first tier when there is no XP yet', () => {
    const view = buildTodayProgress(
      input({ todayXp: 0, todaySeconds: 0 }),
      NOW,
    )

    expect(view.currentIndex).toBe(0)
    expect(view.currentTier.minutes).toBe(10)
    expect(view.remainingXp).toBe(100)
    expect(view.progress).toBe(0)
    expect(view.percent).toBe(0)
    expect(view.tiers[0]?.state).toBe('current')
  })

  it('reports all six tiers complete without inventing a next tier', () => {
    const view = buildTodayProgress(
      input({ todayXp: 2500, todaySeconds: 15_000 }),
      NOW,
    )

    expect(view.allComplete).toBe(true)
    expect(view.completedCount).toBe(6)
    expect(view.currentIndex).toBe(5)
    expect(view.currentTier.minutes).toBe(240)
    expect(view.nextTier).toBeNull()
    expect(view.remainingXp).toBe(0)
    expect(view.progress).toBe(1)
    expect(view.tiers.every((tier) => tier.state === 'complete')).toBe(true)
    expect(view.valueText).toBe('2500 XP')
  })

  it('derives minutes by flooring today_seconds and clamps bad values', () => {
    expect(
      buildTodayProgress(input({ todaySeconds: 119 }), NOW).todayMinutes,
    ).toBe(1)
    expect(
      buildTodayProgress(input({ todaySeconds: 779 }), NOW).todayMinutes,
    ).toBe(12)
    expect(
      buildTodayProgress(
        input({ todayXp: -4, todaySeconds: -1 }),
        NOW,
      ),
    ).toMatchObject({ todayXp: 0, todayMinutes: 0 })
    expect(
      buildTodayProgress(
        input({ todayXp: Number.NaN, todaySeconds: Number.NaN }),
        NOW,
      ),
    ).toMatchObject({ todayXp: 0, todayMinutes: 0 })
  })
})

describe('isRecentlyUpdated', () => {
  it('uses a one-hour window and compares against the real timestamp', () => {
    expect(RECENT_UPDATE_WINDOW_MS).toBe(60 * 60 * 1000)
    expect(isRecentlyUpdated(RECENT, NOW)).toBe(true)
    expect(
      isRecentlyUpdated(
        new Date(NOW.getTime() - RECENT_UPDATE_WINDOW_MS + 1000).toISOString(),
        NOW,
      ),
    ).toBe(true)
    expect(
      isRecentlyUpdated(
        new Date(NOW.getTime() - RECENT_UPDATE_WINDOW_MS - 1000).toISOString(),
        NOW,
      ),
    ).toBe(false)
    expect(isRecentlyUpdated(STALE, NOW)).toBe(false)
  })

  it('rejects future, empty and invalid timestamps', () => {
    expect(isRecentlyUpdated('2026-10-31T09:20:00+08:00', NOW)).toBe(false)
    expect(isRecentlyUpdated('not-a-date', NOW)).toBe(false)
    expect(isRecentlyUpdated('', NOW)).toBe(false)
  })

  it('formats "刚刚更新" only inside the first minute', () => {
    expect(relativeUpdateLabel('2026-10-31T09:09:30+08:00', NOW)).toBe(
      '刚刚更新',
    )
    expect(relativeUpdateLabel('2026-10-31T09:05:00+08:00', NOW)).toBe(
      '5 分钟前更新',
    )
    expect(relativeUpdateLabel(STALE, NOW)).toBe('')
  })
})
