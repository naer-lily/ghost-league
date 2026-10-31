import { describe, expect, it } from 'vitest'
import { ApiError } from '../api/client'
import { makeSnapshot } from '../test/fixtures'
import {
  buildHomeView,
  describeApiError,
  formatNumber,
  formatSettlement,
  formatSettlementShort,
  formatWeekStart,
  groupLabel,
  tierMeta,
} from './home'

describe('home mapping', () => {
  it('maps the real API snapshot into the home numbers', () => {
    const view = buildHomeView(
      makeSnapshot(),
      new Date('2026-10-31T09:00:00+08:00'),
    )

    expect(view.tier.label).toBe('青铜')
    expect(view.groupLabel).toBe('青铜 · G01')
    expect(view.displayName).toBe('那尔')
    expect(view.todayXp).toBe(129)
    expect(view.goalXp).toBe(100)
    expect(view.todayPercent).toBe(100)
    expect(view.todayRemaining).toBe(0)
    expect(view.checkedIn).toBe(true)
    expect(view.weekXp).toBe(524)
    expect(view.rank).toBe(10)
    expect(view.groupSize).toBe(15)
    expect(view.streak).toBe(2)
    expect(view.gems).toBe(128)
    expect(view.topThree.map((row) => row.display_name)).toEqual([
      '@Xkein',
      'RogerRordo',
      'RedMcro',
    ])
    expect(view.selfRow?.user_id).toBe('naer-lily')
    expect(view.selfInTopThree).toBe(false)
    expect(view.nextRankXpGap).toBe(225)
    expect(view.nextRank).toBe(9)
    expect(view.leaderXp).toBe(8019)
    expect(view.weekStartLabel).toBe('10月26日')
    expect(view.settlementLabel).toBe('1 天 15 小时后结算')
  })

  it('keeps an honest empty state when no group is assigned', () => {
    const snapshot = makeSnapshot({
      status: {
        group: null,
        group_id: null,
        group_size: 0,
        rank: null,
        xp: 0,
        today_xp: 0,
        checkin: null,
        streak: {
          current: 0,
          longest: 0,
          clean_current: 0,
          last_checked_date: null,
        },
      },
      standings: {
        group: null,
        group_id: null,
        group_size: 0,
        me: null,
        standings: [],
      },
    })

    const view = buildHomeView(snapshot)

    expect(view.emptyBoard).toBe(true)
    expect(view.hasGroup).toBe(false)
    expect(view.rank).toBeNull()
    expect(view.topThree).toEqual([])
    expect(view.selfRow).toBeNull()
    expect(view.groupLabel).toBe('待分入小组')
  })

  it('uses the board row when the current player is in the top three', () => {
    const snapshot = makeSnapshot({
      status: { rank: 1, xp: 8019 },
      standings: {
        me: { rank: 1, xp: 8019 },
        standings: [
          {
            rank: 1,
            user_id: 'naer-lily',
            display_name: '那尔',
            avatar_url: null,
            is_me: true,
            xp: 8019,
            checkin: 'verified',
            streak: 2,
            title: '小丑',
            frame: '余烬',
            frame_id: 'frame_ember',
            backdrop: null,
          },
        ],
      },
    })

    const view = buildHomeView(snapshot)

    expect(view.selfInTopThree).toBe(true)
    expect(view.selfRow?.xp).toBe(8019)
    expect(view.nextRank).toBeNull()
    expect(view.nextRankXpGap).toBeNull()
  })

  it('derives the self row from status when the board omits it', () => {
    const snapshot = makeSnapshot({ standings: { standings: [] } })
    const view = buildHomeView(snapshot)

    expect(view.emptyBoard).toBe(true)
    expect(view.selfRow?.rank).toBe(10)
    expect(view.selfRow?.display_name).toBe('那尔')
  })
})

describe('formatting', () => {
  it('formats numbers and week starts for zh-CN', () => {
    expect(formatNumber(8019)).toBe('8,019')
    expect(formatWeekStart('2026-10-26')).toBe('10月26日')
    expect(groupLabel(null)).toBe('待分入小组')
  })

  it('formats settlement windows without inventing data', () => {
    const now = new Date('2026-10-31T09:00:00+08:00')
    expect(formatSettlement('2026-11-02T00:00:00+08:00', now)).toBe(
      '1 天 15 小时后结算',
    )
    expect(formatSettlement('2026-10-31T09:40:00+08:00', now)).toBe(
      '40 分钟后结算',
    )
    expect(formatSettlement('2026-10-31T08:00:00+08:00', now)).toBe('等待结算')
    expect(formatSettlement('not-a-date', now)).toBe('等待结算时间')
    expect(formatSettlementShort('2026-11-02T00:00:00+08:00', now)).toBe(
      '1 天 15 小时',
    )
    expect(formatSettlementShort('2026-10-31T09:40:00+08:00', now)).toBe(
      '40 分',
    )
    expect(formatSettlementShort('2026-10-31T08:00:00+08:00', now)).toBe(
      '结算中',
    )
  })

  it('falls back to the bronze tier for unknown values', () => {
    expect(tierMeta('Diamond').label).toBe('钻石')
    expect(tierMeta('Unknown').label).toBe('青铜')
    expect(tierMeta(undefined).label).toBe('青铜')
  })
})

describe('error copy', () => {
  it('maps authentication and service failures to readable copy', () => {
    expect(describeApiError(new ApiError('nope', 401))).toBe(
      '登录已失效，请重新输入令牌。',
    )
    expect(describeApiError(new ApiError('nope', 500))).toBe(
      '服务暂时不可用，请稍后重试。',
    )
    expect(describeApiError(new ApiError('网络连接失败，请检查网络后重试。', 0))).toBe(
      '网络连接失败，请检查网络后重试。',
    )
    expect(describeApiError(new Error('boom'))).toBe(
      '数据没有加载出来，请稍后重试。',
    )
  })
})
