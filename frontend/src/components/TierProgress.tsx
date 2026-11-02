import type { CSSProperties } from 'react'
import { TIER_STAGES, tierStyleVars } from '../lib/home'
import { TierIcon } from './TierIcon'
import styles from './TierProgress.module.css'

interface TierProgressProps {
  tierKey: string
  iconTheme: string
}

/**
 * Horizontal promotion ladder. Completed and current tiers stay readable, the
 * immediate next tier is the nearby preview, and everything further ahead is
 * fogged with a question mark so later tier names are never revealed.
 */
export function TierProgress({ tierKey, iconTheme }: TierProgressProps) {
  const current =
    TIER_STAGES.find((stage) => stage.key === tierKey) ?? TIER_STAGES[0]!
  const style = tierStyleVars(current) as CSSProperties

  return (
    <section
      className={styles.section}
      style={style}
      aria-labelledby="tier-progress-title"
      data-testid="tier-progress"
    >
      <div className={styles.head}>
        <h2 id="tier-progress-title" className={styles.title}>
          段位进度
        </h2>
        <span className={styles.step}>
          第 {current.order + 1} / {TIER_STAGES.length} 阶段
        </span>
      </div>

      <ol className={styles.stages} aria-label="段位阶段">
        {TIER_STAGES.map((stage) => {
          const fogged = stage.order > current.order + 1
          const state = fogged
            ? 'fog'
            : stage.order < current.order
              ? 'complete'
              : stage.order === current.order
                ? 'current'
                : 'future'
          return (
            <li
              key={stage.key}
              className={styles.stage}
              data-state={state}
              data-testid="tier-stage"
              data-fogged={fogged ? 'true' : 'false'}
              aria-current={state === 'current' ? 'step' : undefined}
              aria-label={
                fogged
                  ? '未解锁的后续段位'
                  : `${stage.label}段位，${state === 'current' ? '当前阶段' : state === 'complete' ? '已完成' : '未到达'}`
              }
            >
              <span className={styles.node} aria-hidden="true">
                {fogged ? (
                  <>
                    <span className={styles.fogIcon}>
                      <TierIcon
                        tier={stage.key}
                        theme={iconTheme}
                        size={22}
                        decorative
                      />
                    </span>
                    <span className={styles.fogMark}>?</span>
                  </>
                ) : (
                  <TierIcon
                    tier={stage.key}
                    theme={iconTheme}
                    size={22}
                    decorative
                  />
                )}
              </span>
              <span className={styles.label}>
                {fogged ? '???' : stage.label}
              </span>
            </li>
          )
        })}
      </ol>

      <p className={styles.currentLine}>
        当前 <strong>{current.label}</strong>
        {current.order + 1 < TIER_STAGES.length
          ? `，下一阶段 ${TIER_STAGES[current.order + 1]!.label}`
          : '，已是最高段位'}
      </p>
    </section>
  )
}
