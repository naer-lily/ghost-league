import { ArrowUp, CheckCircle2, Target, Trophy, Users } from 'lucide-react'
import type { CSSProperties } from 'react'
import { useHomeSnapshot } from '../api/queries'
import { AnimatedNumber } from '../components/AnimatedNumber'
import { Avatar } from '../components/Avatar'
import { GoalRing } from '../components/GoalRing'
import { PageAside } from '../components/PageAside'
import { PageError, PageLoading } from '../components/PageState'
import { StandingsBoard } from '../components/StandingsBoard'
import { StreakBadge } from '../components/StreakBadge'
import { TierIcon } from '../components/TierIcon'
import {
  buildHomeView,
  describeApiError,
  formatNumber,
  tierStyleVars,
  type HomeView,
} from '../lib/home'
import styles from './HomePage.module.css'

function Hero({ view }: { view: HomeView }) {
  const style = tierStyleVars(view.tier) as CSSProperties
  return (
    <section
      className={styles.hero}
      style={style}
      aria-labelledby="tier-heading"
    >
      <div className={styles.heroGlow} aria-hidden="true" />
      <div className={styles.heroTop}>
        <div className={styles.tierBlock}>
          <p className="eyebrow">
            <span className={styles.signal} aria-hidden="true" />
            本周
          </p>
          <h1 id="tier-heading" className={styles.tierName}>
            {view.tier.label}
          </h1>
          <p className={styles.groupLine}>{view.groupLabel}</p>
        </div>
        <TierIcon
          tier={view.tier.key}
          theme={view.iconTheme}
          size={70}
          decorative
        />
      </div>

      <div className={styles.identity}>
        <Avatar
          src={view.avatarUrl}
          name={view.displayName}
          size={48}
          loading="eager"
        />
        <div className={styles.identityCopy}>
          <p className={styles.name}>{view.displayName}</p>
          <p className={styles.identityMeta}>
            <Users size={12} aria-hidden="true" />
            {view.groupSize || '—'}
          </p>
        </div>
        <StreakBadge
          className={styles.heroStreak}
          value={view.streak}
          checkedIn={view.checkedIn}
          size="md"
        />
      </div>
    </section>
  )
}

function TodayCard({ view }: { view: HomeView }) {
  return (
    <section className={styles.statCard} aria-labelledby="today-heading">
      <div className={styles.statHead}>
        <div className={styles.statTitle}>
          <span className={styles.statIcon} aria-hidden="true">
            <Target size={17} />
          </span>
          <h2 id="today-heading">今日 XP</h2>
        </div>
        <span
          className={view.checkedIn ? styles.doneChip : styles.liveChip}
          aria-label={view.checkedIn ? '今日已完成' : '今日进行中'}
        >
          {view.checkedIn ? (
            <CheckCircle2 size={16} aria-hidden="true" />
          ) : (
            <Target size={16} aria-hidden="true" />
          )}
        </span>
      </div>
      <div className={styles.todayBody}>
        <GoalRing
          value={view.todayXp}
          goal={view.goalXp}
          color={view.tier.color}
          size={96}
          stroke={9}
        />
      </div>
    </section>
  )
}

function RankCard({ view }: { view: HomeView }) {
  return (
    <section className={styles.statCard} aria-labelledby="rank-heading">
      <div className={styles.statHead}>
        <div className={styles.statTitle}>
          <span className={styles.rankIcon} aria-hidden="true">
            <Trophy size={17} />
          </span>
          <h2 id="rank-heading">排名</h2>
        </div>
        <span className={styles.caption}>本周</span>
      </div>
      <div
        className={styles.rankLine}
        aria-label={`本周名次 第 ${view.rank ?? '—'} 名`}
      >
        <span className={styles.hash} aria-hidden="true">
          #
        </span>
        {view.rank === null ? (
          <span className={styles.rankEmpty}>—</span>
        ) : (
          <AnimatedNumber className={styles.rankNumber} value={view.rank} />
        )}
        <span className={styles.rankOf}>/{view.groupSize || '—'}</span>
      </div>
      <div className={styles.weekXp}>
        <AnimatedNumber value={view.weekXp} />
        <small>XP</small>
      </div>
      <div
        className={styles.miniBar}
        role="progressbar"
        aria-label="与小组第一的 XP 对比"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={view.rankPercent}
      >
        <span style={{ width: `${view.rankPercent}%` }} />
      </div>
      {view.nextRankXpGap !== null ? (
        <p className={styles.rankHelper}>
          <ArrowUp size={13} aria-hidden="true" />
          {formatNumber(view.nextRankXpGap)} XP
        </p>
      ) : null}
    </section>
  )
}

export function HomePage() {
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

  return (
    <div className={styles.page}>
      <div className={styles.column}>
        <Hero view={view} />
        <div className={styles.statsGrid}>
          <TodayCard view={view} />
          <RankCard view={view} />
        </div>
        <StandingsBoard view={view} onRefresh={() => void home.refetch()} />
      </div>
      <PageAside view={view} />
    </div>
  )
}
