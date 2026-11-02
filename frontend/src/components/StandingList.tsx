import type { StandingRow } from '../api/types'
import { formatNumber, formatPower } from '../lib/home'
import { Avatar } from './Avatar'
import { StreakBadge } from './StreakBadge'
import styles from './StandingsBoard.module.css'

interface StandingListProps {
  rows: StandingRow[]
  label: string
  className?: string
  showPower?: boolean
  /** Only the live group board asks for promotion/demotion zones. */
  showZones?: boolean
  groupSize?: number
  promotionQuota?: number
  demotionQuota?: number
  onOpenProfile?: (userId: string) => void
}

interface StandingRowViewProps {
  row: StandingRow
  index: number
  showPower: boolean
  showZones: boolean
  groupSize: number
  promotionQuota: number
  demotionQuota: number
  onOpenProfile?: ((userId: string) => void) | undefined
}

const MEDALS = ['gold', 'silver', 'bronze'] as const

interface ZoneView {
  label: '晋升' | '下降'
  tone: 'promote' | 'demote'
}

function quotaForSize(size: number): number {
  return size >= 2 ? Math.max(1, Math.floor((size * 3) / 10)) : 0
}

function zoneFor(
  row: StandingRow,
  showZones: boolean,
  groupSize: number,
  promotionQuota: number,
  demotionQuota: number,
): ZoneView | null {
  if (!showZones || groupSize < 2) return null
  // The server computes movement from the real tier and group size. Prefer
  // its flags so Bronze never shows 下降 and Diamond never shows 晋升.
  if (row.promoted === true) return { label: '晋升', tone: 'promote' }
  if (row.demoted === true) return { label: '下降', tone: 'demote' }
  if (typeof row.promoted === 'boolean' && typeof row.demoted === 'boolean') {
    return null
  }
  if (promotionQuota > 0 && row.rank <= promotionQuota) {
    return { label: '晋升', tone: 'promote' }
  }
  if (demotionQuota > 0 && row.rank > groupSize - demotionQuota) {
    return { label: '下降', tone: 'demote' }
  }
  return null
}

export function StandingRowView({
  row,
  index,
  showPower = true,
  showZones = false,
  groupSize,
  promotionQuota = 0,
  demotionQuota = 0,
  onOpenProfile,
}: StandingRowViewProps) {
  const rank = row.rank
  const medal = rank >= 1 && rank <= 3 ? MEDALS[rank - 1] : undefined
  const medalLabel =
    medal === 'gold' ? '金牌' : medal === 'silver' ? '银牌' : medal === 'bronze' ? '铜牌' : undefined
  const zone = zoneFor(
    row,
    showZones,
    groupSize,
    promotionQuota,
    demotionQuota,
  )

  return (
    <li
      className={[styles.row, row.is_me ? styles.me : '']
        .filter(Boolean)
        .join(' ')}
      data-me={row.is_me ? 'true' : 'false'}
      data-testid="standing-row"
      aria-label={`${row.display_name || '选手'}，第 ${rank} 名，${formatNumber(row.xp)} XP${row.is_me ? '，我的位置' : ''}${zone ? `，${zone.label}` : ''}`}
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
      {onOpenProfile ? (
        <button
          type="button"
          className={styles.avatarButton}
          aria-label={`查看 ${row.display_name || '选手'} 的资料`}
          data-testid="standing-avatar"
          onClick={() => onOpenProfile(row.user_id)}
        >
          <Avatar
            src={row.avatar_url}
            name={row.display_name}
            size={36}
            loading={index < 6 ? 'eager' : 'lazy'}
          />
        </button>
      ) : (
        <Avatar
          src={row.avatar_url}
          name={row.display_name}
          size={36}
          loading={index < 6 ? 'eager' : 'lazy'}
        />
      )}
      <div className={styles.member}>
        <p className={styles.name}>
          {row.display_name || '未命名选手'}
          {zone ? (
            <span
              className={styles.zone}
              data-zone={zone.tone}
              data-testid="standing-zone"
            >
              {zone.label}
            </span>
          ) : null}
        </p>
        <span className={styles.streakLine}>
          <StreakBadge
            value={row.streak}
            checkedIn={Boolean(row.checkin)}
            size="sm"
          />
          {showPower ? (
            <span className={styles.power} data-testid="standing-power">
              战力 {formatPower(row.power)}
            </span>
          ) : null}
        </span>
      </div>
      <p className={styles.xp} data-testid="standing-xp">
        {formatNumber(row.xp)}{' '}
        <small className={styles.xpUnit}>XP</small>
      </p>
    </li>
  )
}

export function StandingList({
  rows,
  label,
  className,
  showPower = true,
  showZones = false,
  groupSize = rows.length,
  promotionQuota,
  demotionQuota,
  onOpenProfile,
}: StandingListProps) {
  const size = groupSize
  const promote = promotionQuota ?? quotaForSize(size)
  const demote = demotionQuota ?? quotaForSize(size)
  return (
    <ol
      className={[styles.list, className].filter(Boolean).join(' ')}
      aria-label={label}
    >
      {rows.map((row, index) => (
        <StandingRowView
          key={row.user_id}
          row={row}
          index={index}
          showPower={showPower}
          showZones={showZones}
          groupSize={size}
          promotionQuota={promote}
          demotionQuota={demote}
          onOpenProfile={onOpenProfile}
        />
      ))}
    </ol>
  )
}
