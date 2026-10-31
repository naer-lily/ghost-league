import { ChevronRight, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { HomeView } from '../lib/home'
import { StandingList } from './StandingList'
import styles from './StandingsBoard.module.css'

interface StandingsBoardProps {
  view: HomeView
  onRefresh: () => void
}

export function StandingsBoard({ view, onRefresh }: StandingsBoardProps) {
  const showSelfSeparately = Boolean(view.selfRow && !view.selfInTopThree)

  return (
    <section className={styles.card} aria-labelledby="board-title">
      <div className={styles.head}>
        <div className={styles.title}>
          <span className={styles.headIcon} aria-hidden="true">
            <Users size={18} />
          </span>
          <div>
            <p className="eyebrow">小组</p>
            <h2 id="board-title">小组榜</h2>
          </div>
        </div>
        <div className={styles.headMeta}>
          <span className={styles.count}>{view.groupSize || '—'}</span>
          <Link className={styles.more} to="/league" aria-label="完整小组榜">
            全部
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
        </div>
      </div>

      {view.emptyBoard ? (
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
            onClick={onRefresh}
          >
            刷新
          </button>
        </div>
      ) : (
        <>
          <StandingList rows={view.topThree} label="小组榜前三名" />

          {showSelfSeparately && view.selfRow ? (
            <>
              <div className={styles.divider} aria-hidden="true">
                <span>我的位置</span>
              </div>
              <StandingList rows={[view.selfRow]} label="我的小组位置" />
            </>
          ) : null}
        </>
      )}
    </section>
  )
}
