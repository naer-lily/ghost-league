import { AlertTriangle, Flame, Gem, RotateCcw, Sparkles, Trophy } from 'lucide-react'
import type { CSSProperties } from 'react'
import { useHomeSnapshot } from '../api/queries'
import { AnimatedNumber } from '../components/AnimatedNumber'
import { Avatar } from '../components/Avatar'
import { PageAside } from '../components/PageAside'
import { ProgressRing } from '../components/ProgressRing'
import { StandingsBoard } from '../components/StandingsBoard'
import {
  buildHomeView,
  describeApiError,
  formatNumber,
  tierStyleVars,
  type HomeView,
} from '../lib/home'
import styles from './HomePage.module.css'

function HomeSkeleton() {
  return (
    <div className={styles.page} aria-busy="true">
      <span className="visually-hidden">正在读取本周联赛…</span>
      <div className={styles.column}>
        <div className={`${styles.hero} ${styles.skeletonHero}`} />
        <div className={styles.statsGrid}>
          <div className={styles.skeletonCard} />
          <div className={styles.skeletonCard} />
        </div>
        <div className={styles.skeletonBoard} />
      </div>
    </div>
  )
}

function HomeError({
  message,
  retrying,
  onRetry,
}: {
  message: string
  retrying: boolean
  onRetry: () => void
}) {
  return (
    <div className={styles.page}>
      <div className={styles.column}>
        <section className={styles.errorCard} role="alert">
          <span className={styles.errorIcon} aria-hidden="true">
            <AlertTriangle size={30} />
          </span>
          <p className="eyebrow">本周数据</p>
          <h1>数据没有加载出来</h1>
          <p>{message}</p>
          <p className={styles.errorHint}>
            不会显示占位数字；恢复连接后再读取真实数据。
          </p>
          <button
            type="button"
            className="button button--primary"
            onClick={onRetry}
            disabled={retrying}
          >
            <RotateCcw size={18} aria-hidden="true" />
            {retrying ? '正在重试…' : '重试'}
          </button>
        </section>
      </div>
    </div>
  )
}

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
            本周段位
          </p>
          <h1 id="tier-heading" className={styles.tierName}>
            {view.tier.label}
          </h1>
          <p className={styles.groupLine}>{view.groupLabel}</p>
        </div>
        <span className={styles.gem} aria-hidden="true">
          <Gem size={40} />
        </span>
      </div>

      <div className={styles.identity}>
        <Avatar
          src={view.avatarUrl}
          name={view.displayName}
          size={52}
          loading="eager"
        />
        <div className={styles.identityCopy}>
          <p className={styles.name}>{view.displayName}</p>
          <p className={styles.identityMeta}>
            {view.activityLabel}
            {view.equippedTitle ? ` · ${view.equippedTitle}` : ''}
          </p>
        </div>
        <div className={styles.streak} aria-label={`连续 ${view.streak} 天`}>
          <Flame size={22} className={styles.flame} aria-hidden="true" />
          <span className={styles.streakNumber}>
            <AnimatedNumber value={view.streak} />
            <small>天</small>
          </span>
          <span className={styles.streakLabel}>连胜</span>
        </div>
      </div>
      <p className={styles.streakCopy}>{view.streakCopy}</p>
    </section>
  )
}

function TodayCard({ view }: { view: HomeView }) {
  return (
    <section className={styles.statCard} aria-labelledby="today-heading">
      <div className={styles.statHead}>
        <div>
          <p className="eyebrow">今日 XP</p>
          <h2 id="today-heading">今日目标</h2>
        </div>
        <span
          className={view.checkedIn ? styles.doneChip : styles.liveChip}
        >
          {view.checkedIn ? '已完成' : '进行中'}
        </span>
      </div>
      <div className={styles.todayBody}>
        <ProgressRing
          value={view.todayXp}
          max={view.goalXp}
          label="今日 XP 目标"
          size={90}
          stroke={9}
          color={view.tier.color}
        >
          <span className={styles.ringNumber}>
            <AnimatedNumber value={view.todayXp} />
            <small>XP</small>
          </span>
          <span className={styles.ringGoal}>目标 {formatNumber(view.goalXp)}</span>
        </ProgressRing>
        <div className={styles.todayCopy}>
          <p className={styles.statStrong}>{view.todayStatusText}</p>
          <p className={styles.statMuted}>{view.todayDetail}</p>
        </div>
      </div>
    </section>
  )
}

function RankCard({ view }: { view: HomeView }) {
  return (
    <section className={styles.statCard} aria-labelledby="rank-heading">
      <div className={styles.statHead}>
        <div>
          <p className="eyebrow">本周名次</p>
          <h2 id="rank-heading">小组排名</h2>
        </div>
        <Trophy size={19} className={styles.rankIcon} aria-hidden="true" />
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
        <span className={styles.rankOf}>
          /{view.groupSize || '—'}
        </span>
      </div>
      <p className={styles.rankCaption}>小组当前排名</p>
      <div className={styles.weekXp}>
        <AnimatedNumber value={view.weekXp} />
        <small>XP</small>
      </div>
      <p className={styles.rankCaption}>本周累计</p>
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
      <p className={styles.rankHelper}>{view.rankHelper}</p>
    </section>
  )
}

export function HomePage() {
  const home = useHomeSnapshot()

  if (home.isPending) return <HomeSkeleton />

  if (home.isError) {
    return (
      <HomeError
        message={describeApiError(home.error)}
        retrying={home.isFetching}
        onRetry={() => void home.refetch()}
      />
    )
  }

  if (!home.data) return <HomeSkeleton />

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
        <p className={styles.footnote}>
          <Sparkles size={13} aria-hidden="true" />
          数据来自本周联赛快照，每 30 秒自动更新。
        </p>
      </div>
      <PageAside view={view} />
    </div>
  )
}
