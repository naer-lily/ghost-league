import { Clock3, Diamond, Trophy } from 'lucide-react'
import { useState } from 'react'
import { useBets } from '../api/queries'
import type { Bet, GroupBetOption } from '../api/types'
import {
  betReturn,
  betStatusText,
  betStatusTone,
  formatCountdown,
  formatOdds,
  formatXp,
  groupLocked,
} from '../lib/rival'
import { useServerNow } from '../lib/useServerNow'
import { GroupBetDialog } from './GroupBetDialog'
import styles from './GroupBetCard.module.css'

interface PlacedGroupBetProps {
  bet: Bet
  option: GroupBetOption
}

function PlacedGroupBet({ bet, option }: PlacedGroupBetProps) {
  return (
    <div className={styles.placed} data-testid="group-bet-placed">
      <div className={styles.placedHead}>
        <span
          className={[
            styles.badge,
            betStatusTone(bet) === 'placed' ? styles.badgePlaced : '',
          ]
            .filter(Boolean)
            .join(' ')}
        >
          {betStatusText(bet)}
        </span>
        <span className={styles.placedTitle}>我本人在本组本周排名前三</span>
      </div>
      <dl className={styles.placedGrid}>
        <div>
          <dt>目标名次</dt>
          <dd>前三</dd>
        </div>
        <div>
          <dt>赔率</dt>
          <dd>×{formatOdds(bet.odds)}</dd>
        </div>
        <div>
          <dt>自付</dt>
          <dd>{formatXp(bet.paid_stake)}</dd>
        </div>
        <div>
          <dt>免费</dt>
          <dd>{formatXp(bet.free_stake)}</dd>
        </div>
        <div>
          <dt>总本金</dt>
          <dd>{formatXp(bet.stake)}</dd>
        </div>
        <div>
          <dt>总返</dt>
          <dd>{formatXp(betReturn(bet.stake, option.odds))}</dd>
        </div>
      </dl>
      <p className={styles.placedCopy}>
        周期 {bet.period_key} · 周一 23:59:59 截止 · 次周一结算
      </p>
      {bet.group_rank !== null && bet.group_rank !== undefined ? (
        <p className={styles.placedCopy}>
          结算名次：本组第 {bet.group_rank} 名
        </p>
      ) : null}
    </div>
  )
}

/**
 * Personal top-three group bet entry. It lives on the league group board, not
 * on the rival duel card, and only renders when the server provides a group
 * option for this player.
 */
export function GroupBetCard() {
  const betsQuery = useBets(true)
  const data = betsQuery.data
  const now = useServerNow(data?.server_now, Boolean(data))
  const [dialogOpen, setDialogOpen] = useState(false)

  if (!data) return null

  const option = data.bet_options.group
  if (!option) return null

  const bet = data.bets.group
  const closed = groupLocked(data.bet_windows, now)

  return (
    <section
      className={styles.card}
      aria-labelledby="group-bet-title"
      data-testid="group-bet-card"
    >
      <div className={styles.head}>
        <span className={styles.icon} aria-hidden="true">
          <Trophy size={18} />
        </span>
        <div className={styles.headText}>
          <h2 id="group-bet-title" className={styles.title}>
            押我本人在本组本周排名前三
          </h2>
          <p className={styles.copy}>
            只看你自己在本组的本周 XP 排名，小组总 XP 不参与判定。
          </p>
        </div>
        <span className={styles.chip}>组注</span>
      </div>

      <dl className={styles.stats}>
        <div>
          <dt>目标名次</dt>
          <dd data-testid="group-bet-target-rank">
            前三（第 {option.target_rank} 名内）
          </dd>
        </div>
        <div>
          <dt>赔率</dt>
          <dd data-testid="group-bet-card-odds">
            ×{formatOdds(option.odds)}
          </dd>
        </div>
        <div>
          <dt>免费本金</dt>
          <dd>{formatXp(option.free_stake)}</dd>
        </div>
        <div>
          <dt>自付范围</dt>
          <dd>
            {option.min_paid_stake}–{option.max_paid_stake} 钻石
          </dd>
        </div>
      </dl>

      {bet ? <PlacedGroupBet bet={bet} option={option} /> : null}

      <div className={styles.actions}>
        {bet ? null : (
          <button
            type="button"
            className={styles.button}
            disabled={closed}
            data-testid="group-bet-open"
            onClick={() => setDialogOpen(true)}
          >
            <Diamond size={16} aria-hidden="true" />
            {closed ? '本周的注已截止' : '下注组注'}
          </button>
        )}
        <p className={styles.deadline}>
          <Clock3 size={14} aria-hidden="true" />
          {closed
            ? '本周组注已截止'
            : `周一 23:59:59 截止 · 剩余 ${formatCountdown(data.bet_windows.weekly_locks_at, now)}`}
        </p>
      </div>

      <GroupBetDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        option={option}
        bet={bet}
        windows={data.bet_windows}
        now={now}
      />
    </section>
  )
}
