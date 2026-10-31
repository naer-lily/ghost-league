import { ChevronRight, Crown, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { StandingRow } from '../api/types'
import { formatNumber, type HomeView } from '../lib/home'
import { Avatar } from './Avatar'
import styles from './StandingsBoard.module.css'

interface RowProps {
  row: StandingRow
  index: number
}

function statusLine(row: StandingRow): string {
  const parts: string[] = []
  if (row.title) parts.push(row.title)
  parts.push(row.checkin ? '今日已完成' : '今日未完成')
  if (row.streak > 0) parts.push(`连续 ${row.streak} 天`)
  return parts.join(' · ')
}

function StandingRowView({ row, index }: RowProps) {
  const rank = row.rank
  const isMedal = rank >= 1 && rank <= 3
  const medalLabel = ['金牌', '银牌', '铜牌'][rank - 1]

  return (
    <li
      className={[styles.row, row.is_me ? styles.me : '']
        .filter(Boolean)
        .join(' ')}
      aria-label={`${row.display_name || '选手'}，第 ${rank} 名，${formatNumber(row.xp)} XP${row.is_me ? '，我的位置' : ''}`}
    >
      <span
        className={[styles.rank, isMedal ? styles[`rank${rank}`] : '']
          .filter(Boolean)
          .join(' ')}
        aria-label={isMedal ? medalLabel : undefined}
      >
        {rank === 1 ? (
          <Crown size={16} aria-hidden="true" />
        ) : (
          <span aria-hidden="true">{rank}</span>
        )}
      </span>
      <Avatar
        src={row.avatar_url}
        name={row.display_name}
        size={34}
        loading={index < 4 ? 'eager' : 'lazy'}
      />
      <div className={styles.member}>
        <p className={styles.name}>
          <span>{row.display_name || '未命名选手'}</span>
          {row.is_me ? <span className={styles.meTag}>我</span> : null}
        </p>
        <p className={styles.meta}>{statusLine(row)}</p>
      </div>
      <p className={styles.xp}>
        <span>{formatNumber(row.xp)}</span>
        <small>XP</small>
      </p>
    </li>
  )
}

interface StandingsBoardProps {
  view: HomeView
  onRefresh: () => void
}

export function StandingsBoard({ view, onRefresh }: StandingsBoardProps) {
  const showSelfSeparately = Boolean(view.selfRow && !view.selfInTopThree)

  return (
    <section className={styles.card} aria-labelledby="board-title">
      <div className={styles.head}>
        <div>
          <p className="eyebrow">我的小组</p>
          <h2 id="board-title">小组榜</h2>
        </div>
        <div className={styles.headMeta}>
          <span className={styles.count}>{view.groupSize || '—'} 人</span>
          <Link className={styles.more} to="/league">
            完整榜单
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
          <p className={styles.emptyBody}>
            {view.hasGroup
              ? '本组本周还没有可显示的成绩，稍后再来看看。'
              : '分组完成后，这里会显示前 3 名和你的位置。'}
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
          <ol className={styles.list} aria-label="小组榜前三名">
            {view.topThree.map((row, index) => (
              <StandingRowView key={row.user_id} row={row} index={index} />
            ))}
          </ol>

          {showSelfSeparately && view.selfRow ? (
            <>
              <div className={styles.divider} aria-hidden="true">
                <span>我的位置</span>
              </div>
              <ol className={styles.list} aria-label="我的小组位置">
                <StandingRowView row={view.selfRow} index={4} />
              </ol>
            </>
          ) : null}

          {view.selfInTopThree ? (
            <p className={styles.selfNote}>你的位置已在前三中高亮。</p>
          ) : null}
        </>
      )}
    </section>
  )
}
