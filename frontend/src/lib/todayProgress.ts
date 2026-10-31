/**
 * Today's six goal tiers. The API only exposes accumulated XP/seconds, so every
 * value here is either a constant product rule or derived from a real field.
 * 1 XP = 6 seconds, therefore 10 minutes = 100 XP.
 */
export interface TodayGoalTier {
  readonly minutes: number
  readonly xp: number
}

export const TODAY_GOAL_TIERS: readonly TodayGoalTier[] = [
  { minutes: 10, xp: 100 },
  { minutes: 30, xp: 300 },
  { minutes: 60, xp: 600 },
  { minutes: 120, xp: 1200 },
  { minutes: 180, xp: 1800 },
  { minutes: 240, xp: 2400 },
]

export const TODAY_GOAL_MAX_XP = TODAY_GOAL_TIERS[TODAY_GOAL_TIERS.length - 1]!.xp

/** The fire marker is only for a recent status update, never permanent. */
export const RECENT_UPDATE_WINDOW_MS = 10 * 60 * 1000

export type TodayTierState = 'complete' | 'current' | 'future'

export interface TodayProgressTier extends TodayGoalTier {
  index: number
  state: TodayTierState
}

export interface TodayProgressInput {
  todayXp: number
  todaySeconds: number
  updatedAt: string
}

export interface TodayProgressView {
  todayXp: number
  todayMinutes: number
  updatedAt: string
  tiers: TodayProgressTier[]
  completedCount: number
  currentIndex: number
  currentTier: TodayProgressTier
  nextTier: TodayProgressTier | null
  remainingXp: number
  /** 0..1 over six equal-width segments (completed tiers + progress in current). */
  progress: number
  percent: number
  allComplete: boolean
  recentlyUpdated: boolean
  valueText: string
}

function nonNegativeInteger(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.trunc(value))
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(1, Math.max(0, value))
}

/**
 * `status.updated_at` is the API's current status timestamp. It is compared
 * directly with `now` for the 0–10 minute fire window; the component freezes
 * the timestamp until XP actually changes so a polling refresh cannot make the
 * marker permanent.
 */
export function isRecentlyUpdated(
  updatedAt: string,
  now: Date = new Date(),
  windowMs: number = RECENT_UPDATE_WINDOW_MS,
): boolean {
  const updated = new Date(updatedAt)
  const time = updated.getTime()
  if (Number.isNaN(time)) return false
  const delta = now.getTime() - time
  return delta >= 0 && delta <= windowMs
}

export function buildTodayProgress(
  input: TodayProgressInput,
  now: Date = new Date(),
): TodayProgressView {
  const todayXp = nonNegativeInteger(input.todayXp)
  const todayMinutes = Math.floor(
    nonNegativeInteger(input.todaySeconds) / 60,
  )
  const updatedAt = input.updatedAt

  const completedCount = TODAY_GOAL_TIERS.filter(
    (tier) => todayXp >= tier.xp,
  ).length
  const allComplete = completedCount === TODAY_GOAL_TIERS.length
  // First unreached tier; once every tier is reached, the last tier remains the
  // displayed "current" milestone and its distance is zero.
  const currentIndex = allComplete
    ? TODAY_GOAL_TIERS.length - 1
    : completedCount

  const tiers: TodayProgressTier[] = TODAY_GOAL_TIERS.map((tier, index) => {
    const reached = todayXp >= tier.xp
    return {
      ...tier,
      index,
      state: reached ? 'complete' : index === currentIndex ? 'current' : 'future',
    }
  })

  const currentTier = tiers[currentIndex]!
  const previousTargetXp =
    currentIndex > 0 ? tiers[currentIndex - 1]!.xp : 0
  const withinCurrentTier = allComplete
    ? 0
    : clamp01(
        (todayXp - previousTargetXp) / (currentTier.xp - previousTargetXp),
      )
  const progress = allComplete
    ? 1
    : clamp01((completedCount + withinCurrentTier) / tiers.length)
  const remainingXp = allComplete
    ? 0
    : Math.max(0, currentTier.xp - todayXp)
  const nextTier = allComplete ? null : currentTier

  const valueText = allComplete
    ? `${todayXp} XP，六档目标全部达成`
    : `${todayXp} XP，第 ${currentIndex + 1} 档 ${currentTier.minutes} 分钟，还差 ${remainingXp} XP`

  return {
    todayXp,
    todayMinutes,
    updatedAt,
    tiers,
    completedCount,
    currentIndex,
    currentTier,
    nextTier,
    remainingXp,
    progress,
    percent: Math.round(progress * 100),
    allComplete,
    recentlyUpdated: isRecentlyUpdated(updatedAt, now),
    valueText,
  }
}
