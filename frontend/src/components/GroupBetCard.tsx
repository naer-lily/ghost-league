import { Clock3, Diamond, Trophy } from 'lucide-react'
import { useState } from 'react'
import { useBets } from '../api/queries'
import type { GroupMarket, GroupMarketOption } from '../api/types'
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

function PlacedGroupBet({ option }: { option: GroupMarketOption }) {
  const bet = option.bet
  if (!bet) return null
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
        <span className={styles.placedTitle}>{option.label}</span>
      </div>
      <dl className={styles.placedGrid}>
        <div>
          <dt>赔率</dt>
          <dd>×{formatOdds(bet.odds)}</dd>
        </div>
        <div>
          <dt>自付</dt>
          <dd>{formatXp(bet.paid_stake)}</dd>
        </div>
        <div>
          <dt>总返</dt>
          <dd>{formatXp(betReturn(bet.stake, bet.odds))}</dd>
        </div>
      </dl>
      {bet.group_rank !== null && bet.group_rank !== undefined ? (
        <p className={styles.placedCopy}>结算名次：本组第 {bet.group_rank} 名</p>
      ) : null}
    </div>
  )
}

function MarketArticle({
  option,
  closed,
  onOpen,
}: {
  option: GroupMarketOption
  closed: boolean
  onOpen: () => void
}) {
  const placed = Boolean(option.bet)
  const disabled = placed || closed || !option.can_place
  return (
    <article
      className={styles.market}
      data-testid={`group-market-${option.market}`}
      data-market={option.market}
    >
      <div className={styles.marketHead}>
        <h3 className={styles.title}>{option.label}</h3>
      </div>

      <dl className={styles.stats}>
        <div>
          <dt>赔率</dt>
          <dd data-testid={`group-market-odds-${option.market}`}>
            {option.odds === null ? '—' : `×${formatOdds(option.odds)}`}
          </dd>
        </div>
      </dl>

      <PlacedGroupBet option={option} />

      {placed ? null : (
        <button
          type="button"
          className={styles.button}
          disabled={disabled}
          data-testid={`group-bet-open-${option.market}`}
          aria-label={`${option.label}下注`}
          onClick={onOpen}
        >
          <Diamond size={16} aria-hidden="true" />
          {closed ? '本周已截止' : '下注'}
        </button>
      )}
    </article>
  )
}

/**
 * Three independent group markets (`top3` / `promote` / `no_demote`). The
 * server decides which markets exist for the tier and supplies each odds;
 * the card only renders them side by side and submits one market per request.
 */
export function GroupBetCard() {
  const betsQuery = useBets(true)
  const data = betsQuery.data
  const now = useServerNow(data?.server_now, Boolean(data))
  const [activeMarket, setActiveMarket] = useState<GroupMarket | null>(null)

  if (!data) return null

  const markets = (
    data.bets.groups ??
    data.groups ??
    data.bet_options.group?.markets ??
    []
  ).filter((market) => market.available !== false)
  if (markets.length === 0) return null

  const closed = groupLocked(data.bet_windows, now)
  const active = markets.find((item) => item.market === activeMarket) ?? null

  return (
    <section
      className={styles.card}
      aria-label="组注"
      data-testid="group-bet-card"
    >
      <div className={styles.head}>
        <span className={styles.icon} aria-hidden="true">
          <Trophy size={18} />
        </span>
        <div className={styles.headText}>
          <h2 className="visually-hidden">组注</h2>
        </div>
      </div>

      <div className={styles.markets}>
        {markets.map((option) => (
          <MarketArticle
            key={option.market}
            option={option}
            closed={closed}
            onOpen={() => setActiveMarket(option.market)}
          />
        ))}
      </div>

      {closed ? null : (
        <p className={styles.deadline}>
          <Clock3 size={14} aria-hidden="true" />
          周一 23:59:59 截止 · 剩余{' '}
          {formatCountdown(data.bet_windows.weekly_locks_at, now)}
        </p>
      )}

      {active ? (
        <GroupBetDialog
          open
          onOpenChange={(open) => {
            if (!open) setActiveMarket(null)
          }}
          option={active}
          windows={data.bet_windows}
          now={now}
        />
      ) : null}
    </section>
  )
}
