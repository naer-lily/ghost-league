import { ApiError } from '../api/client'
import type { Bet, BetWindows, RivalOutcome } from '../api/types'

const numberFormat = new Intl.NumberFormat('zh-CN')

export function formatXp(value: number): string {
  return numberFormat.format(Math.max(0, Math.trunc(value)))
}

export interface ClashBar {
  leftPercent: number
  rightPercent: number
  total: number
}

/** Split the single collision bar by each side's share of the week XP. */
export function clashBar(myXp: number, rivalXp: number): ClashBar {
  const mine = Math.max(0, Number.isFinite(myXp) ? myXp : 0)
  const theirs = Math.max(0, Number.isFinite(rivalXp) ? rivalXp : 0)
  const total = mine + theirs
  if (total === 0) {
    return { leftPercent: 50, rightPercent: 50, total: 0 }
  }
  const leftPercent = (mine / total) * 100
  return { leftPercent, rightPercent: 100 - leftPercent, total }
}

export interface GapView {
  tone: 'ahead' | 'behind' | 'even'
  amount: number
  label: string
}

export function gapView(myXp: number, rivalXp: number): GapView {
  const amount = Math.abs(myXp - rivalXp)
  if (amount === 0) return { tone: 'even', amount: 0, label: '双方持平' }
  return myXp > rivalXp
    ? { tone: 'ahead', amount, label: '领先' }
    : { tone: 'behind', amount, label: '落后' }
}

export function outcomeLabel(outcome: RivalOutcome): string {
  if (outcome === 'win') return '胜'
  if (outcome === 'loss') return '负'
  return '平'
}

function dateFromIso(iso: string): Date | null {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date
}

export function isPast(iso: string, now: Date): boolean {
  const target = dateFromIso(iso)
  return target !== null && target.getTime() <= now.getTime()
}

/**
 * Compact countdown for the rival screen. Returns "已截止" once the window
 * has passed instead of inventing a negative timer.
 */
export function formatCountdown(iso: string, now: Date): string {
  const target = dateFromIso(iso)
  if (!target) return '—'
  const diff = target.getTime() - now.getTime()
  if (diff <= 0) return '已截止'

  const totalMinutes = Math.ceil(diff / 60_000)
  if (totalMinutes < 60) return `${totalMinutes} 分钟`
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  if (hours < 24) {
    return minutes ? `${hours} 小时 ${minutes} 分` : `${hours} 小时`
  }
  const days = Math.floor(hours / 24)
  const dayHours = hours % 24
  return dayHours ? `${days} 天 ${dayHours} 小时` : `${days} 天`
}

/** ISO-8601 week number for the Monday that starts the league week. */
export function weekNumber(weekStart: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(weekStart)
  if (!match) return '本周'
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const target = new Date(Date.UTC(year, month - 1, day))
  const dayNumber = target.getUTCDay() || 7
  target.setUTCDate(target.getUTCDate() + 4 - dayNumber)
  const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1))
  const week = Math.ceil(
    ((target.getTime() - yearStart.getTime()) / 86_400_000 + 1) / 7,
  )
  return `第 ${week} 周`
}

export type BetTab = 'weekly' | 'daily' | 'group'

export const BET_TABS: ReadonlyArray<{ kind: BetTab; label: string }> = [
  { kind: 'weekly', label: '周注' },
  { kind: 'daily', label: '日注' },
  { kind: 'group', label: '组注' },
]

export function betStatusText(bet: Bet | null | undefined): string {
  if (!bet) return '未下注'
  if (bet.status === 'placed') return '已下注'
  if (bet.status === 'won') return `已赢 +${formatXp(bet.payout)}`
  if (bet.status === 'lost') return '已输'
  return '已退回'
}

export function betStatusTone(
  bet: Bet | null | undefined,
): 'idle' | 'placed' | 'settled' {
  if (!bet) return 'idle'
  return bet.status === 'placed' ? 'placed' : 'settled'
}

export function betKindLabel(kind: BetTab): string {
  if (kind === 'weekly') return '周注'
  if (kind === 'daily') return '日注'
  return '组注'
}

export function betPeriodLabel(bet: Bet): string {
  if (bet.kind === 'daily') return `当天 ${bet.period_key}`
  return `本周 ${bet.period_key}`
}

export function weeklyLocked(windows: BetWindows, now: Date): boolean {
  return isPast(windows.weekly_locks_at, now)
}

export function dailyLocked(windows: BetWindows, now: Date): boolean {
  return isPast(windows.daily_locks_at, now)
}

export function dailyLine(
  projectionLines: Record<string, number> | undefined,
  target: number,
): number | null {
  if (!projectionLines) return null
  const value = projectionLines[String(target)]
  return typeof value === 'number' ? value : null
}

function errorCode(error: ApiError): string | null {
  const payload = error.detail
  if (!payload || typeof payload !== 'object') return null
  const direct = (payload as { code?: unknown }).code
  if (typeof direct === 'string') return direct
  const detail = (payload as { detail?: unknown }).detail
  if (detail && typeof detail === 'object') {
    const nested = (detail as { code?: unknown }).code
    if (typeof nested === 'string') return nested
  }
  return null
}

/** Player-facing copy for rival selection and bet failures. */
export function describeRivalError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return '请求没有完成，请稍后重试。'
  }
  if (error.status === 0) return error.message
  if (error.status === 401) return '登录已失效，请重新输入令牌。'
  if (error.status === 403) return '当前账号不能参与本周宿敌。'
  if (error.status === 404) return '这个候选已经不可选了，请刷新候选再试。'
  const code = errorCode(error)
  if (code === 'already_placed') return '本期已经下过注了，下个周期再来。'
  if (code === 'no_rival') return '本周还没有宿敌，暂时不能下注。'
  if (code === 'insufficient_diamonds') return '钻石不足，先补足自付部分再下注。'
  if (error.status === 409 || error.status === 422) {
    return error.message || '这个操作现在不能完成，请刷新后再试。'
  }
  if (error.status >= 500) return '服务暂时不可用，请稍后重试。'
  return error.message || '请求没有完成，请稍后重试。'
}
