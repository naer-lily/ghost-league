import { ApiError } from '../api/client'
import type {
  HomeSnapshot,
  LeagueGroup,
  StandingRow,
  Standings,
  Status,
} from '../api/types'

export interface TierMeta {
  key: string
  label: string
  order: number
  color: string
  second: string
  soft: string
}

const TIERS: Record<string, TierMeta> = {
  Bronze: {
    key: 'bronze',
    label: '青铜',
    order: 0,
    color: '#d08a5a',
    second: '#8a4c29',
    soft: 'rgba(208, 138, 90, 0.18)',
  },
  Silver: {
    key: 'silver',
    label: '白银',
    order: 1,
    color: '#cfd8e6',
    second: '#7e8aa3',
    soft: 'rgba(207, 216, 230, 0.16)',
  },
  Gold: {
    key: 'gold',
    label: '黄金',
    order: 2,
    color: '#ffd45c',
    second: '#c8861f',
    soft: 'rgba(255, 212, 92, 0.18)',
  },
  Sapphire: {
    key: 'sapphire',
    label: '蓝宝石',
    order: 3,
    color: '#4e9bff',
    second: '#2455b8',
    soft: 'rgba(78, 155, 255, 0.18)',
  },
  Ruby: {
    key: 'ruby',
    label: '红宝石',
    order: 4,
    color: '#ff5577',
    second: '#b81f46',
    soft: 'rgba(255, 85, 119, 0.18)',
  },
  Emerald: {
    key: 'emerald',
    label: '翡翠',
    order: 5,
    color: '#4be5ad',
    second: '#168c68',
    soft: 'rgba(75, 229, 173, 0.16)',
  },
  Amethyst: {
    key: 'amethyst',
    label: '紫水晶',
    order: 6,
    color: '#bf73ff',
    second: '#7430bf',
    soft: 'rgba(191, 115, 255, 0.18)',
  },
  Pearl: {
    key: 'pearl',
    label: '珍珠',
    order: 7,
    color: '#ffe9f6',
    second: '#c795bd',
    soft: 'rgba(255, 233, 246, 0.16)',
  },
  Obsidian: {
    key: 'obsidian',
    label: '黑曜石',
    order: 8,
    color: '#7b6bff',
    second: '#261a5f',
    soft: 'rgba(123, 107, 255, 0.2)',
  },
  Diamond: {
    key: 'diamond',
    label: '钻石',
    order: 9,
    color: '#8ff4ff',
    second: '#2f8da6',
    soft: 'rgba(143, 244, 255, 0.18)',
  },
}

const FALLBACK_TIER = TIERS.Bronze as TierMeta

export function tierMeta(tier: string | null | undefined): TierMeta {
  return (tier && TIERS[tier]) || FALLBACK_TIER
}

const numberFormat = new Intl.NumberFormat('zh-CN')

export function formatNumber(value: number): string {
  return numberFormat.format(Math.max(0, Math.trunc(value)))
}

function dateAtShanghai(iso: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null
  const date = new Date(`${iso}T00:00:00+08:00`)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatWeekStart(iso: string): string {
  const date = dateAtShanghai(iso)
  if (!date) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'long',
    day: 'numeric',
    timeZone: 'Asia/Shanghai',
  }).format(date)
}

export function formatSettlement(
  nextSettlementAt: string,
  now: Date = new Date(),
): string {
  const target = new Date(nextSettlementAt)
  if (Number.isNaN(target.getTime())) return '等待结算时间'
  const diff = target.getTime() - now.getTime()
  if (diff <= 0) return '等待结算'
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 60) return `${Math.max(1, minutes)} 分钟后结算`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时后结算`
  const days = Math.floor(hours / 24)
  return `${days} 天 ${hours % 24} 小时后结算`
}

export function formatSettlementShort(
  nextSettlementAt: string,
  now: Date = new Date(),
): string {
  const target = new Date(nextSettlementAt)
  if (Number.isNaN(target.getTime())) return '—'
  const diff = target.getTime() - now.getTime()
  if (diff <= 0) return '结算中'
  const minutes = Math.floor(diff / 60_000)
  if (minutes < 60) return `${Math.max(1, minutes)} 分`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时`
  const days = Math.floor(hours / 24)
  const rest = hours % 24
  return rest ? `${days} 天 ${rest} 小时` : `${days} 天`
}

export function groupLabel(group: LeagueGroup | null): string {
  if (!group) return '待分入小组'
  const suffix = `G${String(group.no).padStart(2, '0')}`
  return `${tierMeta(group.tier).label} · ${suffix}`
}

function rowFromStatus(
  profile: HomeSnapshot['profile'],
  status: Status,
): StandingRow {
  return {
    rank: status.rank ?? 0,
    user_id: profile.user_id,
    display_name: status.display_name || profile.display_name,
    avatar_url: status.avatar_url ?? profile.avatar_url,
    is_me: true,
    xp: status.xp,
    checkin: status.checkin,
    streak: status.streak.current,
    title: status.equipped_title ?? profile.equipped_title,
    frame: status.frame ?? profile.frame,
    frame_id: status.frame_id ?? null,
    backdrop: status.backdrop ?? profile.backdrop,
  }
}

function findSelfRow(
  standings: Standings,
  profile: HomeSnapshot['profile'],
  status: Status,
): StandingRow | null {
  const fromBoard = standings.standings.find((row) => row.is_me)
  if (fromBoard) return fromBoard
  if (!status.group || status.rank === null) return null
  return rowFromStatus(profile, status)
}

export interface HomeView {
  tier: TierMeta
  iconTheme: string
  displayName: string
  avatarUrl: string | null
  group: LeagueGroup | null
  groupLabel: string
  groupSize: number
  hasGroup: boolean
  emptyBoard: boolean
  todayXp: number
  goalXp: number
  todayRemaining: number
  todayRatio: number
  todayPercent: number
  checkedIn: boolean
  streak: number
  longestStreak: number
  weekXp: number
  rank: number | null
  leaderXp: number
  rankRatio: number
  rankPercent: number
  nextRankXpGap: number | null
  nextRank: number | null
  rows: StandingRow[]
  topThree: StandingRow[]
  selfRow: StandingRow | null
  selfInTopThree: boolean
  weekStartLabel: string
  settlementLabel: string
  embersBalance: number
  embersCap: number
}

export function buildHomeView(
  snapshot: HomeSnapshot,
  now: Date = new Date(),
): HomeView {
  const { profile, status, standings } = snapshot
  const tier = tierMeta(status.tier || profile.tier)
  const group = status.group ?? standings.group
  const todayXp = Math.max(0, Math.trunc(status.today_xp))
  const goalXp = Math.max(1, Math.trunc(status.required_xp) || 100)
  const todayRatio = Math.min(1, todayXp / goalXp)
  const checkedIn = Boolean(status.checkin)
  const topThree = standings.standings.slice(0, 3)
  const selfRow = findSelfRow(standings, profile, status)
  const leaderXp = Math.max(
    status.xp,
    ...standings.standings.map((row) => row.xp),
  )
  const rank = status.rank ?? selfRow?.rank ?? null
  const nextRank = rank !== null && rank > 1 ? rank - 1 : null
  const nextRankRow =
    nextRank !== null
      ? standings.standings.find((row) => row.rank === nextRank)
      : undefined
  const nextRankXpGap =
    nextRankRow && rank !== null
      ? Math.max(0, nextRankRow.xp - status.xp + 1)
      : null

  const todayRemaining = Math.max(0, goalXp - todayXp)
  const streak = Math.max(0, Math.trunc(status.streak.current))
  return {
    tier,
    iconTheme: status.icon_theme || profile.icon_theme || 'classic',
    displayName: status.display_name || profile.display_name,
    avatarUrl: status.avatar_url ?? profile.avatar_url,
    group,
    groupLabel: groupLabel(group),
    groupSize: Math.max(0, status.group_size || standings.group_size || 0),
    hasGroup: Boolean(group),
    emptyBoard: !group || standings.standings.length === 0,
    todayXp,
    goalXp,
    todayRemaining,
    todayRatio,
    todayPercent: Math.round(todayRatio * 100),
    checkedIn,
    streak,
    longestStreak: Math.max(0, Math.trunc(status.streak.longest)),
    weekXp: Math.max(0, Math.trunc(status.xp)),
    rank,
    leaderXp,
    rankRatio: leaderXp > 0 ? Math.min(1, status.xp / leaderXp) : 0,
    rankPercent:
      leaderXp > 0 ? Math.round(Math.min(1, status.xp / leaderXp) * 100) : 0,
    nextRankXpGap,
    nextRank,
    rows: standings.standings,
    topThree,
    selfRow,
    selfInTopThree: topThree.some((row) => row.is_me),
    weekStartLabel: formatWeekStart(status.week_start),
    settlementLabel: formatSettlement(status.next_settlement_at, now),
    embersBalance: Math.max(0, Math.trunc(status.embers.balance)),
    embersCap: Math.max(0, Math.trunc(status.embers.cap)),
  }
}

export function describeApiError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return error.message
    if (error.status === 401) return '登录已失效，请重新输入令牌。'
    if (error.status === 403) return '当前账号没有查看这些数据的权限。'
    if (error.status === 404) return '没有找到本周的联赛数据。'
    if (error.status >= 500) return '服务暂时不可用，请稍后重试。'
    return '数据没有加载出来，请重试。'
  }
  return '数据没有加载出来，请稍后重试。'
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}

export function tierStyleVars(tier: TierMeta): Record<string, string> {
  return {
    '--tier-color': tier.color,
    '--tier-second': tier.second,
    '--tier-soft': tier.soft,
  }
}
