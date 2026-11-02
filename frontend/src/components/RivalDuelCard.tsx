import { Clock3, Timer } from 'lucide-react'
import type { RivalState } from '../api/types'
import {
  betStatusText,
  betStatusTone,
  clashBar,
  dailyLocked,
  formatCountdown,
  formatXp,
  gapView,
} from '../lib/rival'
import { formatPower } from '../lib/home'
import { Avatar } from './Avatar'
import styles from './RivalDuelCard.module.css'

interface RivalDuelCardProps {
  state: RivalState
  now: Date
  onOpenBets: () => void
  showTimers?: boolean
}

/**
 * The reusable duel body used by both `/rival` and the home page. It renders
 * only values from `RivalState`; the home variant is visually denser but keeps
 * the same clash bar, gap and weekly/daily/group bet statuses.
 */
export function RivalDuelCard({
  state,
  now,
  onOpenBets,
  showTimers = true,
}: RivalDuelCardProps) {
  const rival = state.rival
  if (!rival) return null
  const me = state.me
  const bar = clashBar(me.week_xp, rival.week_xp)
  const gap = gapView(me.week_xp, rival.week_xp)
  const windows = state.bet_windows
  const dailyClosed = dailyLocked(windows, now)
  const statuses: ReadonlyArray<{ label: string; bet: typeof state.bets.weekly }> = [
    { label: '周注', bet: state.bets.weekly },
    { label: '日注', bet: state.bets.daily },
    { label: '组注', bet: state.bets.group },
  ]

  return (
    <section
      className={styles.card}
      aria-labelledby="rival-duel-title"
      data-testid="rival-duel-card"
    >
      <h2 id="rival-duel-title" className="visually-hidden">
        本周宿敌对撞
      </h2>

      <div className={styles.playerGrid}>
        <article className={[styles.playerCard, styles.playerMe].join(' ')}>
          <span className={styles.playerTag}>我</span>
          <div className={styles.avatarWrap}>
            <Avatar src={me.avatar_url} name={me.display_name} size={48} />
          </div>
          <p className={styles.playerName} title={me.display_name}>
            {me.display_name}
          </p>
          <p className={styles.playerXp} data-testid="rival-me-xp">
            {formatXp(me.week_xp)} <small>XP</small>
          </p>
          <p className={styles.playerToday}>今日 +{formatXp(me.today_xp)}</p>
          <p className={styles.playerPower}>战力 {formatPower(me.power)}</p>
        </article>

        <div className={styles.vsColumn} aria-hidden="true">
          <span className={styles.vs}>VS</span>
        </div>

        <article className={[styles.playerCard, styles.playerRival].join(' ')}>
          <span className={styles.playerTag}>宿敌</span>
          <div className={styles.avatarWrap}>
            <Avatar
              src={rival.avatar_url}
              name={rival.display_name}
              size={48}
            />
          </div>
          <p className={styles.playerName} title={rival.display_name}>
            {rival.display_name}
          </p>
          <p className={styles.playerXp} data-testid="rival-rival-xp">
            {formatXp(rival.week_xp)} <small>XP</small>
          </p>
          <p className={styles.playerToday}>今日 +{formatXp(rival.today_xp)}</p>
          <p className={styles.playerPower}>战力 {formatPower(rival.power)}</p>
        </article>
      </div>

      <div
        className={styles.clash}
        role="img"
        aria-label={`我本周 ${formatXp(me.week_xp)} XP，宿敌本周 ${formatXp(rival.week_xp)} XP`}
        data-testid="rival-clash"
      >
        <span
          className={styles.clashMe}
          style={{ width: `${bar.leftPercent}%` }}
          data-testid="rival-clash-me"
        />
        <span
          className={styles.clashRival}
          style={{ width: `${bar.rightPercent}%` }}
          data-testid="rival-clash-rival"
        />
        {bar.leftPercent > 0 && bar.leftPercent < 100 ? (
          <span
            className={styles.clashSpark}
            style={{ left: `${bar.leftPercent}%` }}
            aria-hidden="true"
          />
        ) : null}
      </div>
      <div className={styles.barLabels}>
        <span className={styles.barMine}>
          我 {bar.total === 0 ? '50' : Math.round(bar.leftPercent)}%
        </span>
        <span className={styles.barRival}>
          宿敌 {bar.total === 0 ? '50' : Math.round(bar.rightPercent)}%
        </span>
      </div>

      <p className={styles.gapLine} aria-live="polite" data-testid="rival-gap">
        {gap.tone === 'even' ? (
          <>双方持平</>
        ) : (
          <>
            {gap.label}{' '}
            <strong className={styles.gapValue}>
              {formatXp(gap.amount)} XP
            </strong>
          </>
        )}
      </p>

      {showTimers ? (
        <div className={styles.timePanel}>
          <div className={styles.timeItem}>
            <span className={styles.timeLabel}>
              <Timer size={14} aria-hidden="true" />
              本周剩余
            </span>
            <strong
              className={styles.timeValue}
              data-testid="rival-week-countdown"
            >
              {formatCountdown(windows.weekly_locks_at, now)}
            </strong>
          </div>
          <div className={styles.timeItem}>
            <span className={styles.timeLabel}>
              <Clock3 size={14} aria-hidden="true" />
              日注锁注
            </span>
            <strong
              className={styles.timeValue}
              data-testid="rival-daily-countdown"
            >
              {dailyClosed
                ? '今天的注已截止'
                : formatCountdown(windows.daily_locks_at, now)}
            </strong>
            <span className={styles.timeHint}>21:00 锁注 · 22:30 结算</span>
          </div>
        </div>
      ) : null}

      <div className={styles.betBar}>
        <div className={styles.betStatuses} aria-label="本周下注状态">
          {statuses.map((entry) => (
            <span
              key={entry.label}
              className={[
                styles.betChip,
                betStatusTone(entry.bet) === 'placed'
                  ? styles.betChipDone
                  : '',
                betStatusTone(entry.bet) === 'settled'
                  ? styles.betChipSettled
                  : '',
              ]
                .filter(Boolean)
                .join(' ')}
              data-testid={`rival-bet-status-${entry.label}`}
            >
              {entry.label} · {betStatusText(entry.bet)}
            </span>
          ))}
        </div>
        <button type="button" className={styles.betButton} onClick={onOpenBets}>
          下注
        </button>
      </div>
    </section>
  )
}
