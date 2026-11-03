import { Clock3, Timer } from 'lucide-react'
import type { Bet, RivalState } from '../api/types'
import {
  betReturn,
  betStatusText,
  betStatusTone,
  clashBar,
  dailyLocked,
  formatCountdown,
  formatOdds,
  formatXp,
  gapView,
  weeklyLocked,
  type RivalBetTab,
} from '../lib/rival'
import { formatPower } from '../lib/home'
import { Avatar } from './Avatar'
import styles from './RivalDuelCard.module.css'

interface RivalDuelCardProps {
  state: RivalState
  now: Date
  onOpenBets: (kind: RivalBetTab) => void
  /** The home page uses the compact read-only body. */
  variant?: 'full' | 'summary'
  onOpenProfile?: (userId: string) => void
}

interface BetSurfaceProps {
  kind: RivalBetTab
  label: string
  bet: Bet | null
  closedCopy: string | null
  onOpenBets: (kind: RivalBetTab) => void
}

function BetSurface({
  kind,
  label,
  bet,
  closedCopy,
  onOpenBets,
}: BetSurfaceProps) {
  const status = bet ? betStatusText(bet) : closedCopy ? '已截止' : '未下注'
  return (
    <article
      className={[
        styles.betSurface,
        bet ? styles.betSurfacePlaced : '',
        !bet && closedCopy ? styles.betSurfaceClosed : '',
      ]
        .filter(Boolean)
        .join(' ')}
      data-testid={`rival-bet-status-${label}`}
      data-kind={kind}
    >
      <div className={styles.betSurfaceHead}>
        <span className={styles.betSurfaceKind}>{label}</span>
        <span className={styles.betSurfaceStatus}>
          {label} · {status}
        </span>
      </div>

      {bet ? (
        <>
          <dl className={styles.betSurfaceGrid}>
            <div>
              <dt>目标</dt>
              <dd data-testid={`rival-bet-target-${kind}`}>
                +{formatXp(bet.target_margin)} XP
              </dd>
            </div>
            <div>
              <dt>赔率</dt>
              <dd data-testid={`rival-bet-odds-${kind}`}>
                ×{formatOdds(bet.odds)}
              </dd>
            </div>
            <div>
              <dt>总本金</dt>
              <dd data-testid={`rival-bet-stake-${kind}`}>
                {formatXp(bet.stake)}
              </dd>
            </div>
            <div>
              <dt>总返</dt>
              <dd data-testid={`rival-bet-return-${kind}`}>
                {formatXp(betReturn(bet.stake, bet.odds))}
              </dd>
            </div>
          </dl>
          <p className={styles.betSurfaceNote}>
            {kind === 'daily'
              ? `当天 ${bet.period_key} · 21:00 锁注 · 22:30 结算`
              : `周期 ${bet.period_key} · 周一 23:59:59 截止 · 次周一结算`}
          </p>
        </>
      ) : closedCopy ? (
        <p className={styles.betSurfaceClosedCopy}>{closedCopy}</p>
      ) : (
        <button
          type="button"
          className={styles.betButton}
          onClick={() => onOpenBets(kind)}
        >
          {`下注${label}`}
        </button>
      )}
    </article>
  )
}

/**
 * The reusable duel body used by both `/rival` and the home page. The full
 * variant carries both weekly and daily XP, timers, and bet surfaces; the
 * `summary` variant remains a compact weekly-only fallback. Group bets live on
 * the league board.
 */
export function RivalDuelCard({
  state,
  now,
  onOpenBets,
  variant = 'full',
  onOpenProfile,
}: RivalDuelCardProps) {
  const rival = state.rival
  if (!rival) return null
  const me = state.me
  const summary = variant === 'summary'
  const bar = clashBar(me.week_xp, rival.week_xp)
  const gap = gapView(me.week_xp, rival.week_xp)
  const windows = state.bet_windows
  const dailyClosed = dailyLocked(windows, now)
  const weeklyClosed = weeklyLocked(windows, now)
  const weeklyClosedCopy = weeklyClosed ? '本周的注已截止' : null
  const dailyClosedCopy = dailyClosed ? '今天的注已截止' : null

  function avatar(src: string | null, name: string, userId: string) {
    const node = <Avatar src={src} name={name} size={48} />
    if (!onOpenProfile) return node
    return (
      <button
        type="button"
        className={styles.avatarButton}
        aria-label={`查看 ${name || '选手'} 的资料`}
        data-testid="rival-avatar-profile"
        onClick={() => onOpenProfile(userId)}
      >
        {node}
      </button>
    )
  }

  return (
    <section
      className={styles.card}
      aria-labelledby="rival-duel-title"
      data-testid="rival-duel-card"
      data-variant={variant}
    >
      <h2 id="rival-duel-title" className="visually-hidden">
        本周宿敌对撞
      </h2>

      <div className={styles.playerGrid}>
        <article className={[styles.playerCard, styles.playerMe].join(' ')}>
          <span className={styles.playerTag}>我</span>
          <div className={styles.avatarWrap}>
            {avatar(me.avatar_url, me.display_name, me.user_id)}
          </div>
          <p className={styles.playerName} title={me.display_name}>
            {me.display_name}
          </p>
          <p className={styles.playerXp} data-testid="rival-me-xp">
            {formatXp(me.week_xp)} <small>XP</small>
          </p>
          {summary ? null : (
            <p className={styles.playerPower}>战力 {formatPower(me.power)}</p>
          )}
        </article>

        <div className={styles.vsColumn} aria-hidden="true">
          <span className={styles.vs}>VS</span>
        </div>

        <article className={[styles.playerCard, styles.playerRival].join(' ')}>
          <span className={styles.playerTag}>宿敌</span>
          <div className={styles.avatarWrap}>
            {avatar(rival.avatar_url, rival.display_name, rival.user_id)}
          </div>
          <p className={styles.playerName} title={rival.display_name}>
            {rival.display_name}
          </p>
          <p className={styles.playerXp} data-testid="rival-rival-xp">
            {formatXp(rival.week_xp)} <small>XP</small>
          </p>
          {summary ? null : (
            <p className={styles.playerPower}>
              战力 {formatPower(rival.power)}
            </p>
          )}
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

      <div
        className={styles.timePanel}
        data-count={summary ? '1' : '2'}
      >
        {summary ? null : (
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
        )}
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

      {summary ? (
        <div className={styles.betBar}>
          <div
            className={styles.betStatuses}
            aria-label="今日下注状态"
          >
            <span
              className={[
                styles.betChip,
                betStatusTone(state.bets.daily) === 'placed'
                  ? styles.betChipDone
                  : '',
                betStatusTone(state.bets.daily) === 'settled'
                  ? styles.betChipSettled
                  : '',
              ]
                .filter(Boolean)
                .join(' ')}
              data-testid="rival-bet-status-日注"
            >
              日注 · {betStatusText(state.bets.daily)}
            </span>
          </div>
          <button
            type="button"
            className={styles.betButton}
            onClick={() => onOpenBets('daily')}
          >
            下注
          </button>
        </div>
      ) : (
        <>
          <div
            className={styles.todayScore}
            data-testid="rival-today-score"
            aria-label={`今日 XP：我 ${formatXp(me.today_xp)} XP，宿敌 ${formatXp(rival.today_xp)} XP`}
          >
            <span className={styles.todayMine} data-testid="rival-today-me">
              今日 我 {formatXp(me.today_xp)} XP
            </span>
            <span className={styles.todayRival} data-testid="rival-today-rival">
              宿敌 {formatXp(rival.today_xp)} XP
            </span>
          </div>

          <div className={styles.betSurfaces} aria-label="宿敌下注">
            <BetSurface
              kind="weekly"
              label="周注"
              bet={state.bets.weekly}
              closedCopy={weeklyClosedCopy}
              onOpenBets={onOpenBets}
            />
            <BetSurface
              kind="daily"
              label="日注"
              bet={state.bets.daily}
              closedCopy={dailyClosedCopy}
              onOpenBets={onOpenBets}
            />
          </div>
        </>
      )}
    </section>
  )
}
