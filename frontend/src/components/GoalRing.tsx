import { Target } from 'lucide-react'
import type { CSSProperties } from 'react'
import { AnimatedNumber } from './AnimatedNumber'
import { ProgressRing } from './ProgressRing'
import styles from './GoalRing.module.css'

interface GoalRingProps {
  value: number
  goal: number
  color?: string
  size?: number
  stroke?: number
}

export function GoalRing({
  value,
  goal,
  color = 'var(--green)',
  size = 106,
  stroke = 10,
}: GoalRingProps) {
  const style = {
    '--goal-size': `${size}px`,
  } as CSSProperties

  return (
    <ProgressRing
      value={value}
      max={goal}
      label="今日 XP 目标"
      size={size}
      stroke={stroke}
      color={color}
    >
      <span className={styles.content} style={style}>
        <span className={styles.number}>
          <AnimatedNumber value={value} />
          <small>XP</small>
        </span>
        <span className={styles.goal}>
          <Target size={Math.max(10, Math.round(size * 0.075))} aria-hidden="true" />
          <AnimatedNumber value={goal} />
        </span>
      </span>
    </ProgressRing>
  )
}
