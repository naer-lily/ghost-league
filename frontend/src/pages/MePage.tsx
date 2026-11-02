import {
  ChevronRight,
  Diamond,
  Sparkles,
  Trophy,
  Zap,
} from 'lucide-react'
import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { useHomeSnapshot } from '../api/queries'
import { AnimatedNumber } from '../components/AnimatedNumber'
import { GoalRing } from '../components/GoalRing'
import { PageError, PageLoading } from '../components/PageState'
import { PlayerHeader } from '../components/PlayerHeader'
import {
  buildHomeView,
  describeApiError,
  formatNumber,
  formatPower,
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
  const rankLabel = view.rank === null ? '—' : String(view.rank)
  const ringColor = view.checkedIn ? 'var(--green)' : view.tier.color

  return (
    <div className={styles.page}>
      <PlayerHeader view={view} />

      <div className={styles.stats} data-flat="true">
        <div className={styles.stat} data-testid="me-stat-week">
          <Zap className={styles.statIcon} size={18} aria-hidden="true" />
          <p className={styles.statValue}>
            <AnimatedNumber value={view.weekXp} /> <small>XP</small>
          </p>
          <p className={styles.statLabel}>本周</p>
        </div>

        <div className={styles.stat} data-testid="me-stat-rank">
          <Trophy
            className={`${styles.statIcon} ${styles.rankIcon}`}
            size={18}
            aria-hidden="true"
          />
          <p className={styles.statValue}>
            {view.rank === null ? (
              <span className={styles.empty}>—</span>
            ) : (
              <AnimatedNumber value={view.rank} />
            )}
            <small>/{view.groupSize || '—'}</small>
          </p>
          <p className={styles.statLabel}>排名</p>
        </div>

        <div className={styles.stat} data-testid="me-stat-embers">
          <Sparkles
            className={`${styles.statIcon} ${styles.emberIcon}`}
            size={18}
            aria-hidden="true"
          />
          <p className={styles.statValue}>
            <AnimatedNumber value={view.embersBalance} />
            <small>/{view.embersCap}</small>
          </p>
          <p className={styles.statLabel}>余烬</p>
        </div>
      </div>

      <Link
        className={styles.resourceRow}
        to="/shop"
        aria-label="打开星图，查看钻石、星图和战力"
        data-testid="me-resource-row"
      >
        <span className={styles.resource}>
          <Diamond
            className={`${styles.resourceIcon} ${styles.diamondIcon}`}
            size={16}
            aria-hidden="true"
          />
          <span className={styles.resourceText}>
            <small>钻石</small>
            <strong data-testid="me-diamonds">
              {formatNumber(view.diamonds)}
            </strong>
          </span>
        </span>
        <span className={styles.resource}>
          <Sparkles
            className={`${styles.resourceIcon} ${styles.starIcon}`}
            size={16}
            aria-hidden="true"
          />
          <span className={styles.resourceText}>
            <small>星图</small>
            <strong data-testid="me-stars">{formatNumber(view.starCount)}</strong>
          </span>
        </span>
        <span className={styles.resource}>
          <Zap
            className={`${styles.resourceIcon} ${styles.powerIcon}`}
            size={16}
            aria-hidden="true"
          />
          <span className={styles.resourceText}>
            <small>战力</small>
            <strong data-testid="me-power">{formatPower(view.power)}</strong>
          </span>
        </span>
        <ChevronRight
          className={styles.resourceChevron}
          size={16}
          aria-hidden="true"
        />
      </Link>

      <div className={styles.goal} style={style} data-flat="true">
        <GoalRing
          value={view.todayXp}
          goal={view.goalXp}
          color={ringColor}
          size={68}
          stroke={7}
        />
      </div>

      <Link
        className={styles.rankRow}
        to="/league"
        aria-label={`我的榜单位置，第 ${rankLabel} 名`}
      >
        <Trophy size={17} aria-hidden="true" />
        <span className={styles.rankLabel}>我的榜单位置</span>
        <span className={styles.rankValue}>
          {view.rank === null ? (
            <span className={styles.empty}>—</span>
          ) : (
            <AnimatedNumber value={view.rank} />
          )}
          <small>/{view.groupSize || '—'}</small>
        </span>
        <ChevronRight size={17} aria-hidden="true" />
      </Link>
    </div>
  )
}
