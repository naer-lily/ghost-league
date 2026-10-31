import {
  CheckCircle2,
  Flame,
  Sparkles,
  Target,
  Trophy,
  Users,
  Zap,
} from 'lucide-react'
import type { CSSProperties } from 'react'
import { useHomeSnapshot } from '../api/queries'
import { AnimatedNumber } from '../components/AnimatedNumber'
import { Avatar } from '../components/Avatar'
import { GoalRing } from '../components/GoalRing'
import { PageError, PageLoading } from '../components/PageState'
import { StreakBadge } from '../components/StreakBadge'
import { TierIcon } from '../components/TierIcon'
import {
  buildHomeView,
  describeApiError,
  tierStyleVars,
} from '../lib/home'
import styles from './MePage.module.css'

export function MePage() {
  const home = useHomeSnapshot()

  if (home.isPending) return <PageLoading />

  if (home.isError) {
    return (
      <PageError
        message={describeApiError(home.error)}
        retrying={home.isFetching}
        onRetry={() => void home.refetch()}
      />
    )
  }

  if (!home.data) return <PageLoading />

  const view = buildHomeView(home.data)
  const style = tierStyleVars(view.tier) as CSSProperties

  return (
    <div className={styles.page}>
      <section
        className={styles.profile}
        style={style}
        aria-labelledby="me-name"
      >
        <div className={styles.glow} aria-hidden="true" />
        <div className={styles.identity}>
          <Avatar
            src={view.avatarUrl}
            name={view.displayName}
            size={78}
            loading="eager"
          />
          <div className={styles.identityCopy}>
            <h1 id="me-name" className={styles.name}>
              {view.displayName}
            </h1>
            <p className={styles.groupLine}>
              <Users size={12} aria-hidden="true" />
              {view.groupLabel}
            </p>
          </div>
        </div>

        <div className={styles.tierLine}>
          <TierIcon tier={view.tier.key} theme={view.iconTheme} size={54} />
          <span className={styles.tierName}>{view.tier.label}</span>
          <StreakBadge
            className={styles.streak}
            value={view.streak}
            checkedIn={view.checkedIn}
            size="lg"
          />
        </div>
      </section>

      <div className={styles.stats}>
        <section className={styles.statCard} aria-labelledby="me-week">
          <span className={styles.statIcon} aria-hidden="true">
            <Zap size={17} />
          </span>
          <p id="me-week" className={styles.statValue}>
            <AnimatedNumber value={view.weekXp} />
            <small>XP</small>
          </p>
          <p className={styles.statLabel}>本周</p>
        </section>

        <section className={styles.statCard} aria-labelledby="me-rank">
          <span className={`${styles.statIcon} ${styles.rankIcon}`} aria-hidden="true">
            <Trophy size={17} />
          </span>
          <p id="me-rank" className={styles.statValue}>
            {view.rank === null ? (
              <span className={styles.empty}>—</span>
            ) : (
              <AnimatedNumber value={view.rank} />
            )}
            <small>/{view.groupSize || '—'}</small>
          </p>
          <p className={styles.statLabel}>排名</p>
        </section>

        <section className={styles.statCard} aria-labelledby="me-embers">
          <span className={`${styles.statIcon} ${styles.emberIcon}`} aria-hidden="true">
            <Sparkles size={17} />
          </span>
          <p id="me-embers" className={styles.statValue}>
            <AnimatedNumber value={view.embersBalance} />
            <small>/{view.embersCap}</small>
          </p>
          <p className={styles.statLabel}>余烬</p>
        </section>
      </div>

      <section className={styles.goalCard} aria-labelledby="me-goal">
        <div className={styles.goalHead}>
          <div className={styles.goalTitle}>
            <span className={styles.goalIcon} aria-hidden="true">
              <Target size={17} />
            </span>
            <h2 id="me-goal">今日 XP</h2>
          </div>
          <span
            className={view.checkedIn ? styles.doneChip : styles.liveChip}
            aria-label={view.checkedIn ? '今日已完成' : '今日进行中'}
          >
            {view.checkedIn ? (
              <CheckCircle2 size={16} aria-hidden="true" />
            ) : (
              <Flame size={16} aria-hidden="true" />
            )}
          </span>
        </div>
        <div className={styles.goalBody}>
          <GoalRing
            value={view.todayXp}
            goal={view.goalXp}
            color={view.tier.color}
            size={124}
          />
        </div>
      </section>
    </div>
  )
}
