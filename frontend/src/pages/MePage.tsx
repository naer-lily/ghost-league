import {
  ChevronRight,
  Diamond,
  Flame,
  History,
  Package,
  Settings,
  Sparkles,
  Trophy,
  Zap,
} from 'lucide-react'
import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { useHomeSnapshot } from '../api/queries'
import { AnimatedNumber } from '../components/AnimatedNumber'
import { PageError, PageLoading } from '../components/PageState'
import { PlayerHeader } from '../components/PlayerHeader'
import { PullToRefresh } from '../components/PullToRefresh'
import { TierProgress } from '../components/TierProgress'
import {
  buildHomeView,
  describeApiError,
  formatNumber,
  formatPower,
  tierStyleVars,
} from '../lib/home'
import { useUiStore } from '../store/useUiStore'
import styles from './MePage.module.css'

export function MePage() {
  const home = useHomeSnapshot()
  const notify = useUiStore((state) => state.notify)
  const setSettingsOpen = useUiStore((state) => state.setSettingsOpen)

  async function refresh() {
    const result = await home.refetch()
    if (result.error) {
      notify(describeApiError(result.error), 'error')
    } else {
      notify('个人数据已刷新。')
    }
  }

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
    <PullToRefresh onRefresh={refresh}>
      <div className={styles.page} style={style}>
        <PlayerHeader view={view} diamonds={view.diamonds} />

        <TierProgress tierKey={view.tier.key} iconTheme={view.iconTheme} />

        <section className={styles.stats} aria-labelledby="me-week-title">
          <div className={styles.sectionHead}>
            <h2 id="me-week-title">本周数据</h2>
          </div>
          <div className={styles.statGrid}>
            <div className={styles.stat} data-testid="me-stat-week">
              <Zap className={styles.statIcon} size={18} aria-hidden="true" />
              <p className={styles.statValue}>
                <AnimatedNumber value={view.weekXp} /> <small>XP</small>
              </p>
              <p className={styles.statLabel}>本周 XP</p>
            </div>

            <div className={styles.stat} data-testid="me-stat-today">
              <Flame
                className={`${styles.statIcon} ${styles.todayIcon}`}
                size={18}
                aria-hidden="true"
              />
              <p className={styles.statValue}>
                <AnimatedNumber value={view.todayXp} /> <small>XP</small>
              </p>
              <p className={styles.statLabel}>今日 XP</p>
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
              </p>
              <p className={styles.statLabel}>本周排名</p>
            </div>
          </div>
        </section>

        <section className={styles.streak} aria-labelledby="me-streak-title">
          <div className={styles.sectionHead}>
            <h2 id="me-streak-title">连胜</h2>
          </div>
          <div className={styles.streakGrid}>
            <div className={styles.streakItem} data-testid="me-streak-current">
              <span className={styles.streakIcon} aria-hidden="true">
                <Flame size={18} />
              </span>
              <strong>{view.streak}</strong>
              <small>当前连胜</small>
            </div>
            <div className={styles.streakItem} data-testid="me-streak-longest">
              <span className={styles.streakIcon} aria-hidden="true">
                <Sparkles size={18} />
              </span>
              <strong>{view.longestStreak}</strong>
              <small>最长连胜</small>
            </div>
            <div className={styles.streakItem} data-testid="me-streak-checkin">
              <span className={styles.streakIcon} aria-hidden="true">
                <Trophy size={18} />
              </span>
              <strong>{view.checkedIn ? '已打卡' : '未打卡'}</strong>
              <small>今日状态</small>
            </div>
          </div>
        </section>

        <Link
          className={styles.resourceRow}
          to="/inventory"
          aria-label="打开物品栏，查看钻石、星星和战力"
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
              <small>星星</small>
              <strong data-testid="me-stars">
                {formatNumber(view.starCount)}
              </strong>
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

        <nav className={styles.menu} aria-label="我的菜单">
          <Link className={styles.menuItem} to="/inventory">
            <span className={styles.menuIcon} aria-hidden="true">
              <Package size={18} />
            </span>
            <span className={styles.menuLabel}>物品栏</span>
            <span className={styles.menuValue}>
              {formatNumber(view.starCount)} 颗星
            </span>
            <ChevronRight size={17} aria-hidden="true" />
          </Link>

          <Link className={styles.menuItem} to="/history">
            <span className={styles.menuIcon} aria-hidden="true">
              <History size={18} />
            </span>
            <span className={styles.menuLabel}>历史</span>
            <span className={styles.menuValue}>战绩与记录</span>
            <ChevronRight size={17} aria-hidden="true" />
          </Link>

          <button
            type="button"
            className={styles.menuItem}
            onClick={() => setSettingsOpen(true)}
          >
            <span className={styles.menuIcon} aria-hidden="true">
              <Settings size={18} />
            </span>
            <span className={styles.menuLabel}>设置</span>
            <span className={styles.menuValue}>声音、外观与账号</span>
            <ChevronRight size={17} aria-hidden="true" />
          </button>
        </nav>
      </div>
    </PullToRefresh>
  )
}
