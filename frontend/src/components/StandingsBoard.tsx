import { ChevronRight, Trophy, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { HomeView } from '../lib/home'
import { AnimatedNumber } from './AnimatedNumber'
import { StandingList } from './StandingList'
import styles from './StandingsBoard.module.css'

interface StandingsBoardProps {
  view: HomeView
  onRefresh: () => void
}

const HOME_ROWS = 5

export function StandingsBoard({ view, onRefresh }: StandingsBoardProps) {
  const rows = view.rows.slice(0, HOME_ROWS)
  const rankLabel = view.rank === null ? '—' : String(view.rank)
  const rankAria =
    view.rank === null
      ? '本周名次 第 — 名'
      : `本周名次 第 ${view.rank} 名`

  return (
    <section
      className={styles.board}
      aria-labelledby="board-title"
      data-flat="true"
    >
      <div className={styles.head}>
        <div className={styles.title}>
          <span className={styles.titleIcon} aria-hidden="true">
            <Trophy size={18} />
          </span>
          <h2 id="board-title">小组榜</h2>
        </div>
        <div className={styles.meta}>
          <span className={styles.weekXp}>
            <AnimatedNumber value={view.weekXp} /> <small>XP</small>
          </span>
          <span
            className={styles.rankChip}
            data-testid="board-rank"
            aria-label={rankAria}
          >
            {rankLabel}
            <span>/{view.groupSize || '—'}</span>
          </span>
        </div>
      </div>

      {view.emptyBoard ? (
        <div className={styles.empty}>
          <span className={styles.emptyIcon} aria-hidden="true">
            <Users size={26} />
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
          <StandingList rows={rows} label="小组榜前五名" />
          <Link
            className={styles.more}
            to="/league"
            aria-label="查看完整小组榜"
          >
            完整榜单
            <ChevronRight size={16} aria-hidden="true" />
          </Link>
        </>
      )}
    </section>
  )
}
