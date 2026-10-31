import { motion, useReducedMotion } from 'framer-motion'
import type { ReactNode } from 'react'
import styles from './ProgressRing.module.css'

interface ProgressRingProps {
  value: number
  max: number
  label: string
  color?: string
  size?: number
  stroke?: number
  children: ReactNode
}

export function ProgressRing({
  value,
  max,
  label,
  color = 'var(--green)',
  size = 128,
  stroke = 11,
  children,
}: ProgressRingProps) {
  const reducedMotion = useReducedMotion()
  const safeMax = Math.max(1, max)
  const ratio = Math.min(1, Math.max(0, value / safeMax))
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference * (1 - ratio)

  return (
    <div
      className={styles.wrap}
      style={{ width: size, height: size }}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={safeMax}
      aria-valuenow={Math.min(safeMax, Math.max(0, value))}
      aria-valuetext={`${value} / ${safeMax} XP`}
    >
      <svg
        className={styles.svg}
        viewBox={`0 0 ${size} ${size}`}
        aria-hidden="true"
      >
        <circle
          className={styles.track}
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={stroke}
        />
        <motion.circle
          className={styles.progress}
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={stroke}
          strokeDasharray={circumference}
          initial={false}
          animate={{ strokeDashoffset: offset }}
          transition={
            reducedMotion
              ? { duration: 0 }
              : { type: 'spring', stiffness: 90, damping: 18, mass: 0.7 }
          }
          style={{ stroke: color }}
        />
      </svg>
      <div className={styles.center}>{children}</div>
    </div>
  )
}
