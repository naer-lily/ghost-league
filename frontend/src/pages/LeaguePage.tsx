import { Timer, Users } from 'lucide-react'
import type { CSSProperties } from 'react'
import { useHomeSnapshot } from '../api/queries'
import { PageError, PageLoading } from '../components/PageState'
import { StandingList } from '../components/StandingList'
import { TierIcon } from '../components/TierIcon'
import {
  buildHomeView,
  describeApiError,
  formatSettlementShort,
  tierStyleVars,
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
  const style = tierStyleVars(view.tier) as CSSProperties

  return (
    <div className={styles.page}>
      <section
        className={styles.header}
        style={style}
        aria-labelledby="league-tier"
      >
        <div className={styles.glow} aria-hidden="true" />
        <TierIcon tier={view.tier.key} theme={view.iconTheme} size={88} />
        <div className={styles.headerCopy}>
          <p className="eyebrow">小组</p>
          <h1 id="league-tier" className={styles.tierName}>
            {view.tier.label}
          </h1>
          <p className={styles.groupLine}>{view.groupLabel}</p>
        </div>
        <p
          className={styles.settle}
          aria-label={`结算倒计时：${view.settlementLabel}`}
        >
          <Timer size={15} aria-hidden="true" />
          {formatSettlementShort(home.data.status.next_settlement_at)}
        </p>
      </section>

      <section className={styles.board} aria-labelledby="league-board">
        <div className={styles.boardHead}>
          <div className={styles.boardTitle}>
            <span className={styles.boardIcon} aria-hidden="true">
              <Users size={18} />
            </span>
            <div>
              <p className="eyebrow">本组</p>
              <h2 id="league-board">小组榜</h2>
            </div>
          </div>
          <span className={styles.count}>{rows.length}</span>
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
