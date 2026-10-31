import { Timer, Trophy, Users } from 'lucide-react'
import { useHomeSnapshot } from '../api/queries'
import { PageError, PageLoading } from '../components/PageState'
import { PlayerHeader } from '../components/PlayerHeader'
import { StandingList } from '../components/StandingList'
import {
  buildHomeView,
  describeApiError,
  formatSettlementShort,
} from '../lib/home'
import styles from './LeaguePage.module.css'

export function LeaguePage() {
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
  const rows = home.data.standings.standings

  return (
    <div className={styles.page}>
      <PlayerHeader view={view} />

      <div className={styles.groupBar} data-flat="true">
        <span className={styles.groupInfo}>
          <Users size={15} aria-hidden="true" />
          {rows.length || view.groupSize || 0}
        </span>
        <span
          className={styles.settle}
          aria-label={`结算倒计时：${view.settlementLabel}`}
        >
          <Timer size={15} aria-hidden="true" />
          {formatSettlementShort(home.data.status.next_settlement_at)}
        </span>
      </div>

      <section
        className={styles.board}
        aria-labelledby="league-board"
        data-flat="true"
      >
        <div className={styles.boardHead}>
          <div className={styles.boardTitle}>
            <span className={styles.boardIcon} aria-hidden="true">
              <Trophy size={18} />
            </span>
            <h2 id="league-board">小组榜</h2>
          </div>
          <span className={styles.unit}>XP</span>
        </div>

        {rows.length === 0 ? (
          <div className={styles.empty}>
            <span className={styles.emptyIcon} aria-hidden="true">
              <Users size={28} />
            </span>
            <p className={styles.emptyTitle}>
              {view.hasGroup ? '小组榜还没有成绩' : '本周还没有小组'}
            </p>
            <button
              type="button"
              className="button button--secondary"
              onClick={() => void home.refetch()}
            >
              刷新
            </button>
          </div>
        ) : (
          <StandingList rows={rows} label="完整小组榜" />
        )}
      </section>
    </div>
  )
}
