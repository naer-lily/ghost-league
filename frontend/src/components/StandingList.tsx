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

const MEDALS = ['gold', 'silver', 'bronze'] as const

export function StandingRowView({ row, index }: StandingRowViewProps) {
  const rank = row.rank
  const medal = rank >= 1 && rank <= 3 ? MEDALS[rank - 1] : undefined
  const medalLabel =
    medal === 'gold' ? '金牌' : medal === 'silver' ? '银牌' : medal === 'bronze' ? '铜牌' : undefined

  return (
    <li
      className={[styles.row, row.is_me ? styles.me : '']
        .filter(Boolean)
        .join(' ')}
      data-me={row.is_me ? 'true' : 'false'}
      data-testid="standing-row"
      aria-label={`${row.display_name || '选手'}，第 ${rank} 名，${formatNumber(row.xp)} XP${row.is_me ? '，我的位置' : ''}`}
    >
      <span
        className={styles.rank}
        data-testid="standing-rank"
        data-rank={rank}
        data-medal={medal}
        aria-label={medalLabel}
      >
        {rank}
      </span>
      <Avatar
        src={row.avatar_url}
        name={row.display_name}
        size={36}
        loading={index < 6 ? 'eager' : 'lazy'}
      />
      <div className={styles.member}>
        <p className={styles.name}>{row.display_name || '未命名选手'}</p>
        <span className={styles.streakLine}>
          <StreakBadge
            value={row.streak}
            checkedIn={Boolean(row.checkin)}
            size="sm"
          />
        </span>
      </div>
      <p className={styles.xp} data-testid="standing-xp">
        {formatNumber(row.xp)}
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
