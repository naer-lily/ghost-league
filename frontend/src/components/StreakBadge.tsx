import { Flame } from 'lucide-react'
import type { CSSProperties } from 'react'
import styles from './StreakBadge.module.css'

export type StreakBadgeSize = 'sm' | 'md' | 'lg'

export interface StreakBadgeProps {
  value: number
  checkedIn: boolean
  size?: StreakBadgeSize
  className?: string | undefined
  label?: string | undefined
}

const ICON_SIZE: Record<StreakBadgeSize, number> = {
  sm: 15,
  md: 20,
  lg: 26,
}

const ACTIVE_FLAME = '#ff9d1f'
const ACTIVE_NUMBER = '#fff8ef'
/* Both values are deliberately R=G=B so an incomplete day is strictly gray. */
const INACTIVE_FLAME = '#8c8c8c'
const INACTIVE_NUMBER = '#a6a6a6'

export function StreakBadge({
  value,
  checkedIn,
  size = 'md',
  className,
  label,
}: StreakBadgeProps) {
  const safeValue = Math.max(0, Math.trunc(value))
  const style = {
    '--streak-flame': checkedIn ? ACTIVE_FLAME : INACTIVE_FLAME,
    '--streak-number': checkedIn ? ACTIVE_NUMBER : INACTIVE_NUMBER,
  } as CSSProperties

  return (
    <span
      className={[styles.badge, styles[size], className]
        .filter(Boolean)
        .join(' ')}
      style={style}
      data-testid="streak-badge"
      data-checked={checkedIn ? 'true' : 'false'}
      aria-label={
        label ??
        `连续 ${safeValue} 天，${checkedIn ? '今天已打卡' : '今天未打卡'}`
      }
    >
      <Flame
        className={styles.flame}
        size={ICON_SIZE[size]}
        strokeWidth={1.8}
        fill="currentColor"
        style={{ color: checkedIn ? ACTIVE_FLAME : INACTIVE_FLAME }}
        aria-hidden="true"
      />
      <span
        className={styles.value}
        data-streak-value=""
        style={{ color: checkedIn ? ACTIVE_NUMBER : INACTIVE_NUMBER }}
        aria-hidden="true"
      >
        {safeValue}
      </span>
    </span>
  )
}
