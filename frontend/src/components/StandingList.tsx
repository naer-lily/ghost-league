import { Crown } from 'lucide-react'
import type { StandingRow } from '../api/types'
import { formatNumber } from '../lib/home'
import { Avatar } from './Avatar'
import { StreakBadge } from './StreakBadge'
import styles from './StandingsBoard.module.css'

interface StandingListProps {
  rows: StandingRow[]
  label: string
  className?: string
}

interface StandingRowViewProps {
  row: StandingRow
  index: number
}

export function StandingRowView({ row, index }: StandingRowViewProps) {
  const rank = row.rank
  const isMedal = rank >= 1 && rank <= 3
  const medalLabel = ['金牌', '银牌', '铜牌'][rank - 1]

  return (
    <li
      className={[styles.row, row.is_me ? styles.me : '']
        .filter(Boolean)
        .join(' ')}
      data-me={row.is_me ? 'true' : 'false'}
      aria-label={`${row.display_name || '选手'}，第 ${rank} 名，${formatNumber(row.xp)} XP${row.is_me ? '，我的位置' : ''}`}
    >
      <span
        className={[styles.rank, isMedal ? styles[`rank${rank}`] : '']
          .filter(Boolean)
          .join(' ')}
        aria-label={isMedal ? medalLabel : undefined}
      >
        {rank === 1 ? (
          <Crown size={16} aria-hidden="true" />
        ) : (
          <span aria-hidden="true">{rank}</span>
        )}
      </span>
      <Avatar
        src={row.avatar_url}
        name={row.display_name}
        size={36}
        loading={index < 6 ? 'eager' : 'lazy'}
      />
      <div className={styles.member}>
        <p className={styles.name}>
          <span>{row.display_name || '未命名选手'}</span>
          {row.is_me ? <span className={styles.meTag}>我</span> : null}
        </p>
        <span className={styles.streakLine}>
          <StreakBadge
            value={row.streak}
            checkedIn={Boolean(row.checkin)}
            size="sm"
          />
        </span>
      </div>
      <p className={styles.xp}>
        <span>{formatNumber(row.xp)}</span>
        <small>XP</small>
      </p>
    </li>
  )
}

export function StandingList({ rows, label, className }: StandingListProps) {
  return (
    <ol
      className={[styles.list, className].filter(Boolean).join(' ')}
      aria-label={label}
    >
      {rows.map((row, index) => (
        <StandingRowView key={row.user_id} row={row} index={index} />
      ))}
    </ol>
  )
}
