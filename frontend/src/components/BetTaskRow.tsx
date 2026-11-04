import { ChevronDown, ChevronUp } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { Bet, BetWindows } from '../api/types'
import {
  betReturn,
  betStatusText,
  clashBar,
  formatOdds,
  formatXp,
  type RivalBetTab,
} from '../lib/rival'
import { formatAbsoluteTime } from '../lib/time'
import styles from './BetTaskRow.module.css'

export interface BetSides {
  me: number
  rival: number
}

interface BetTaskRowProps {
  kind: RivalBetTab
  bet: Bet | null
  /** My XP for the row's window: today for daily, this week for weekly. */
  meXp: number
  /** The rival's XP for the row's window, before the target margin. */
  rivalXp: number
  windows: BetWindows
  locked: boolean
  expanded: boolean
  onToggle: () => void
  onOpenBets: (kind: RivalBetTab) => void
  /** Frozen values supplied by the caller (e.g. the settled weekly result). */
  snapshot?: BetSides | null
  /** Adds the simple gap before the weekly cluster. */
  firstWeekly?: boolean
}

const SNAPSHOT_PREFIX = 'gl.bet-task-row.v1'

function snapshotKey(kind: RivalBetTab, betId: number): string {
  return `${SNAPSHOT_PREFIX}.${kind}.${betId}`
}

/** Last real side values seen while the bet was still live. */
export function readBetSnapshot(
  kind: RivalBetTab,
  betId: number,
): BetSides | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(snapshotKey(kind, betId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<BetSides>
    if (
      typeof parsed.me === 'number' &&
      Number.isFinite(parsed.me) &&
      typeof parsed.rival === 'number' &&
      Number.isFinite(parsed.rival)
    ) {
      return { me: parsed.me, rival: parsed.rival }
    }
  } catch {
    return null
  }
  return null
}

function writeBetSnapshot(
  kind: RivalBetTab,
  betId: number,
  sides: BetSides,
): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(
      snapshotKey(kind, betId),
      JSON.stringify(sides),
    )
  } catch {
    // Private mode / quota errors must never break the row.
  }
}

export function formatBetDiff(diff: number): string {
  if (diff > 0) return `+${formatXp(diff)}`
  if (diff < 0) return `-${formatXp(-diff)}`
  return '0'
}

function settlementLabel(
  kind: RivalBetTab,
  bet: Bet,
  windows: BetWindows,
): string {
  if (bet.settled_at) return formatAbsoluteTime(bet.settled_at)
  if (kind === 'daily') return formatAbsoluteTime(windows.daily_settles_at)
  return '次周一结算'
}

function closedCopy(kind: RivalBetTab): string {
  return kind === 'daily' ? '今天的注已截止' : '本周的注已截止'
}

function toneClass(diff: number): string {
  if (diff > 0) return styles.ahead ?? ''
  if (diff < 0) return styles.behind ?? ''
  return styles.even ?? ''
}

function toneName(diff: number): 'ahead' | 'behind' | 'even' {
  if (diff > 0) return 'ahead'
  if (diff < 0) return 'behind'
  return 'even'
}

export function BetTaskRow({
  kind,
  bet,
  meXp,
  rivalXp,
  windows,
  locked,
  expanded,
  onToggle,
  onOpenBets,
  snapshot,
  firstWeekly,
}: BetTaskRowProps) {
  const label = kind === 'daily' ? '日注' : '周注'
  const target = bet?.target_margin ?? 0
  const live = { me: meXp, rival: rivalXp + target }
  const settled = Boolean(bet && bet.status !== 'placed')
  const lastLive = useRef<BetSides | null>(null)

  if (bet && !settled) lastLive.current = live

  const frozen: BetSides = settled && bet
    ? (snapshot ?? lastLive.current ?? readBetSnapshot(kind, bet.id) ?? live)
    : live

  useEffect(() => {
    if (!bet || bet.status !== 'placed') return
    writeBetSnapshot(kind, bet.id, {
      me: meXp,
      rival: rivalXp + target,
    })
  }, [bet?.id, bet?.status, kind, meXp, rivalXp, target])

  const rootClass = [styles.root, firstWeekly ? styles.firstWeekly : '']
    .filter(Boolean)
    .join(' ')

  if (!bet) {
    if (locked) {
      return (
        <article
          className={rootClass}
          data-testid={`bet-task-${kind}`}
          data-state="locked"
          data-kind={kind}
        >
          <div
            className={styles.lockedRow}
            data-testid={`bet-task-locked-${kind}`}
          >
            <span className={styles.lockedLabel}>{label}</span>
            <span className={styles.lockedCopy}>{closedCopy(kind)}</span>
          </div>
        </article>
      )
    }
    return (
      <article
        className={rootClass}
        data-testid={`bet-task-${kind}`}
        data-state="open"
        data-kind={kind}
      >
        <button
          type="button"
          className={styles.openRow}
          data-testid={`bet-task-open-${kind}`}
          onClick={() => onOpenBets(kind)}
        >
          {label}
        </button>
      </article>
    )
  }

  const diff =
    settled && bet.result_diff !== null
      ? bet.result_diff
      : frozen.me - frozen.rival
  const bar = clashBar(frozen.me, frozen.rival)
  const tone = toneName(diff)
  const status = settled ? betStatusText(bet) : null
  const gapCopy =
    diff > 0
      ? `领先 ${formatXp(diff)} XP`
      : diff < 0
        ? `落后 ${formatXp(-diff)} XP`
        : '双方持平'

  return (
    <article
      className={[rootClass, styles.placed].filter(Boolean).join(' ')}
      data-testid={`bet-task-${kind}`}
      data-state={settled ? 'settled' : 'placed'}
      data-kind={kind}
      data-tone={tone}
      data-frozen={settled ? 'true' : 'false'}
    >
      <button
        type="button"
        className={styles.placedButton}
        aria-expanded={expanded}
        aria-label={`${label}，我 ${formatXp(frozen.me)} XP，对方 ${formatXp(
          frozen.rival,
        )} XP，${gapCopy}${status ? `，${status}` : ''}`}
        data-testid={`bet-task-toggle-${kind}`}
        onClick={onToggle}
      >
        <span className={styles.xpRow}>
          <span className={styles.meXp} data-testid={`bet-task-me-${kind}`}>
            {formatXp(frozen.me)}
          </span>
          <span
            className={[styles.diff, toneClass(diff)].filter(Boolean).join(' ')}
            data-testid={`bet-task-diff-${kind}`}
            data-tone={tone}
          >
            {formatBetDiff(diff)}
          </span>
          <span
            className={styles.rivalXp}
            data-testid={`bet-task-rival-${kind}`}
          >
            {formatXp(frozen.rival)}
          </span>
        </span>

        <span
          className={styles.bar}
          role="img"
          aria-label={`我 ${formatXp(frozen.me)} XP，对方 ${formatXp(
            frozen.rival,
          )} XP`}
          data-testid={`bet-task-bar-${kind}`}
        >
          <span
            className={styles.barMe}
            style={{ width: `${bar.leftPercent}%` }}
            data-testid={`bet-task-bar-me-${kind}`}
          />
          <span
            className={styles.barRival}
            style={{ width: `${bar.rightPercent}%` }}
            data-testid={`bet-task-bar-rival-${kind}`}
          />
        </span>

        <span className={styles.meta}>
          {status ? (
            <span
              className={styles.result}
              data-testid={`bet-task-result-${kind}`}
            >
              {status}
            </span>
          ) : (
            <span className={styles.metaSpacer} />
          )}
          {expanded ? (
            <ChevronUp
              className={styles.chevron}
              size={14}
              aria-hidden="true"
            />
          ) : (
            <ChevronDown
              className={styles.chevron}
              size={14}
              aria-hidden="true"
            />
          )}
        </span>
      </button>

      {expanded ? (
        <dl
          className={styles.details}
          data-testid={`bet-task-details-${kind}`}
        >
          <div>
            <dt>本金</dt>
            <dd>
              {formatXp(bet.stake)} × {formatOdds(bet.odds)}
            </dd>
          </div>
          <div>
            <dt>目标</dt>
            <dd>+{formatXp(bet.target_margin)} XP</dd>
          </div>
          <div>
            <dt>总返</dt>
            <dd>{formatXp(betReturn(bet.stake, bet.odds))}</dd>
          </div>
          <div>
            <dt>结算时间</dt>
            <dd>{settlementLabel(kind, bet, windows)}</dd>
          </div>
        </dl>
      ) : null}
    </article>
  )
}

export default BetTaskRow
