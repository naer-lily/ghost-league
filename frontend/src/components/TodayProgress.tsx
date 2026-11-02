import { motion, useReducedMotion } from 'framer-motion'
import { Flame } from 'lucide-react'
import { type CSSProperties, useEffect, useState } from 'react'
import { tierStyleVars, type TierMeta } from '../lib/home'
import {
  buildTodayProgress,
  TODAY_GOAL_MAX_XP,
} from '../lib/todayProgress'
import { AnimatedNumber } from './AnimatedNumber'
import styles from './TodayProgress.module.css'

interface TodayProgressProps {
  todayXp: number
  todaySeconds: number
  updatedAt: string
  tier: TierMeta
  /** Fixed clock for deterministic tests; the app uses a live clock. */
  now?: Date
}

/** Re-renders while the page is open so the 10-minute fire window can expire. */
function useClock(fixed?: Date): Date {
  const [now, setNow] = useState(() => fixed ?? new Date())

  useEffect(() => {
    if (fixed) return
    const timer = window.setInterval(() => setNow(new Date()), 15_000)
    return () => window.clearInterval(timer)
  }, [fixed])

  return fixed ?? now
}

export function TodayProgress({
  todayXp,
  todaySeconds,
  updatedAt,
  tier,
  now: fixedNow,
}: TodayProgressProps) {
  const reducedMotion = useReducedMotion()
  const now = useClock(fixedNow)
  const view = buildTodayProgress(
    { todayXp, todaySeconds, updatedAt },
    now,
  )
  const style = tierStyleVars(tier) as CSSProperties

  return (
    <section
      className={styles.section}
      style={style}
      aria-labelledby="today-progress-title"
      data-testid="today-progress"
    >
      <div className={styles.head}>
        <div className={styles.titleRow}>
          <h2 id="today-progress-title" className={styles.title}>
            今日进度
          </h2>

          {view.updateLabel ? (
            <motion.span
              className={styles.recent}
              data-testid="recent-update"
              aria-label="最近 1 小时内有 XP 更新"
              initial={
                reducedMotion ? false : { opacity: 0, scale: 0.82, y: 2 }
              }
              animate={{ opacity: 1, scale: 1, y: 0 }}
              transition={
                reducedMotion
                  ? { duration: 0 }
                  : { type: 'spring', stiffness: 320, damping: 22 }
              }
            >
              <Flame
                size={12}
                strokeWidth={2.4}
                fill="currentColor"
                aria-hidden="true"
              />
              <span>{view.updateLabel}</span>
            </motion.span>
          ) : null}
        </div>

        <dl className={styles.stats}>
          <div className={styles.stat}>
            <dt>今日 XP</dt>
            <dd>
              <AnimatedNumber value={view.todayXp} />
              <small>XP</small>
            </dd>
          </div>
          <div className={styles.stat}>
            <dt>今日分钟</dt>
            <dd>
              <AnimatedNumber value={view.todayMinutes} />
              <small>分钟</small>
            </dd>
          </div>
        </dl>
      </div>

      <div className={styles.barArea}>
        <div
          className={styles.track}
          role="progressbar"
          aria-label="今日 XP 目标"
          aria-valuemin={0}
          aria-valuemax={TODAY_GOAL_MAX_XP}
          aria-valuenow={Math.min(TODAY_GOAL_MAX_XP, view.todayXp)}
          aria-valuetext={view.valueText}
          data-progress={view.progress.toFixed(4)}
        >
          <span className={styles.segments} aria-hidden="true">
            {view.tiers.map((tierItem) => (
              <span
                key={tierItem.minutes}
                className={styles.segment}
                data-state={tierItem.state}
              />
            ))}
          </span>

          <motion.span
            className={styles.fill}
            data-testid="today-progress-fill"
            initial={false}
            animate={{ width: `${view.progress * 100}%` }}
            transition={
              reducedMotion
                ? { duration: 0 }
                : { type: 'spring', stiffness: 88, damping: 18, mass: 0.7 }
            }
          >
            <span className={styles.fillSurface} aria-hidden="true">
              <span className={styles.sheen} />
            </span>
            <span
              className={styles.headGlow}
              data-empty={view.progress <= 0 ? 'true' : undefined}
              aria-hidden="true"
            />
          </motion.span>

          <span className={styles.ticks} aria-hidden="true">
            {view.tiers.map((tierItem) => (
              <span
                key={tierItem.minutes}
                className={styles.tick}
                data-state={tierItem.state}
                data-current={
                  tierItem.state === 'current' ? 'true' : undefined
                }
                style={{
                  left: `${
                    ((tierItem.index + 1) / view.tiers.length) * 100
                  }%`,
                }}
              >
                <span className={styles.tickDot} />
              </span>
            ))}
          </span>
        </div>

        <ol className={styles.tierGrid} aria-label="今日目标档位">
          {view.tiers.map((tierItem) => (
            <li
              key={tierItem.minutes}
              className={styles.tier}
              data-testid="today-tier"
              data-state={tierItem.state}
              data-minutes={tierItem.minutes}
            >
              <span className={styles.tierLabel}>
                <span className={styles.tierNumber}>{tierItem.minutes}</span>
                <span className={styles.tierUnit}>分钟</span>
              </span>
            </li>
          ))}
        </ol>
      </div>

      <div className={styles.footer}>
        <span
          className={styles.remaining}
          data-testid="today-remaining"
          data-complete={view.allComplete ? 'true' : undefined}
        >
          {view.allComplete
            ? '六档全部达成'
            : `还差 ${view.remainingXp} XP`}
        </span>
      </div>
    </section>
  )
}
