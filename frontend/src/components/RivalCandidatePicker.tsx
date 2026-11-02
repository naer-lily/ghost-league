import type { UseQueryResult } from '@tanstack/react-query'
import { Check, RotateCcw, Swords } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { RivalCandidateList, RivalPlayer } from '../api/types'
import { describeApiError, formatPower, tierMeta } from '../lib/home'
import { formatXp } from '../lib/rival'
import { Avatar } from './Avatar'
import styles from './RivalCandidatePicker.module.css'

type CandidateFilter = 'above' | 'all' | 'cross'

const FILTERS: ReadonlyArray<{ id: CandidateFilter; label: string }> = [
  { id: 'above', label: '略高于我' },
  { id: 'all', label: '全部' },
  { id: 'cross', label: '跨组' },
]

function sortCandidates(
  candidates: RivalPlayer[],
  mePower: number,
): RivalPlayer[] {
  return [...candidates].sort((left, right) => {
    const leftGap = Math.abs(left.power - mePower)
    const rightGap = Math.abs(right.power - mePower)
    if (leftGap !== rightGap) return leftGap - rightGap
    if (left.power !== right.power) return right.power - left.power
    return left.user_id.localeCompare(right.user_id)
  })
}

interface RivalCandidatePickerProps {
  candidates: UseQueryResult<RivalCandidateList, Error>
  mePower: number
  currentRival: RivalPlayer | null
  locked: boolean
  selecting: boolean
  pendingId: string | undefined
  selectError: string | null
  onSelect: (candidate: RivalPlayer) => void
  /** Home renders a shorter list without the filter hint block. */
  compact?: boolean
}

/** Shared candidate list for the `/rival` page and the home page entry. */
export function RivalCandidatePicker({
  candidates,
  mePower,
  currentRival,
  locked,
  selecting,
  pendingId,
  selectError,
  onSelect,
  compact = false,
}: RivalCandidatePickerProps) {
  const [filter, setFilter] = useState<CandidateFilter>('above')
  const [visibleCount, setVisibleCount] = useState(compact ? 6 : 10)
  const list = candidates.data?.candidates ?? []

  const ordered = useMemo(
    () => sortCandidates(list, mePower),
    [list, mePower],
  )
  const above = useMemo(
    () =>
      ordered
        .filter((candidate) => candidate.power >= mePower)
        .sort((left, right) => left.power - right.power),
    [ordered, mePower],
  )
  const fallback = filter === 'above' && above.length === 0
  const visible = filter === 'above' ? (fallback ? ordered : above) : ordered
  const shown = visible.slice(0, visibleCount)

  return (
    <section
      className={[styles.panel, compact ? styles.compact : '']
        .filter(Boolean)
        .join(' ')}
      aria-label="宿敌候选区域"
    >
      {compact ? null : (
        <div className={styles.filterRow} role="group" aria-label="筛选宿敌候选">
          {FILTERS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={[
                styles.chip,
                filter === item.id ? styles.chipActive : '',
              ]
                .filter(Boolean)
                .join(' ')}
              aria-pressed={filter === item.id}
              onClick={() => {
                setFilter(item.id)
                setVisibleCount(10)
              }}
            >
              {item.id === 'above' ? (
                <Swords size={14} aria-hidden="true" />
              ) : null}
              {item.label}
            </button>
          ))}
        </div>
      )}

      {compact ? null : (
        <p className={styles.filterHint} data-testid="rival-filter-hint">
          {fallback
            ? '没有略高于你的候选，先显示全部跨组候选。'
            : filter === 'cross'
              ? '候选都来自其他小组，由本周分组实时生成。'
              : filter === 'above'
                ? '按战力差从小到大，优先追略高于你的对手。'
                : '按与你战力的差距从小到大排列。'}
        </p>
      )}

      {selectError ? (
        <p className={styles.errorNote} role="alert" data-testid="rival-select-error">
          {selectError}
        </p>
      ) : null}

      {locked ? (
        <p className={styles.lockNote}>周一 23:59 之后不能再选择或改选宿敌。</p>
      ) : null}

      {candidates.isPending ? (
        <div className={styles.candidateSkeleton} aria-busy="true">
          <span className="visually-hidden">正在读取宿敌候选…</span>
          {[0, 1, 2, 3].map((row) => (
            <span className={styles.skeletonRow} key={row} />
          ))}
        </div>
      ) : candidates.isError ? (
        <div className={styles.inlineState}>
          <p>{describeApiError(candidates.error)}</p>
          <button
            type="button"
            className="button button--secondary"
            onClick={() => void candidates.refetch()}
            disabled={candidates.isFetching}
          >
            <RotateCcw size={16} aria-hidden="true" />
            {candidates.isFetching ? '正在重试…' : '重试'}
          </button>
        </div>
      ) : visible.length === 0 ? (
        <div className={styles.inlineState}>
          <p>本周暂时没有可选的跨组候选。</p>
          <button
            type="button"
            className="button button--secondary"
            onClick={() => void candidates.refetch()}
          >
            刷新候选
          </button>
        </div>
      ) : (
        <ul className={styles.candidateList} aria-label="宿敌候选">
          {shown.map((candidate) => {
            const isCurrent = currentRival?.user_id === candidate.user_id
            const isPending = pendingId === candidate.user_id
            return (
              <li
                key={candidate.user_id}
                className={[
                  styles.candidate,
                  isCurrent ? styles.candidateCurrent : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                data-testid={`rival-candidate-${candidate.user_id}`}
              >
                <Avatar
                  src={candidate.avatar_url}
                  name={candidate.display_name}
                  size={44}
                />
                <div className={styles.candidateBody}>
                  <div className={styles.candidateTitle}>
                    <strong>{candidate.display_name}</strong>
                    {isCurrent ? (
                      <span className={styles.currentTag}>当前宿敌</span>
                    ) : null}
                  </div>
                  <p className={styles.candidateMeta}>
                    <span>段位 {tierMeta(candidate.tier).label}</span>
                    <span aria-hidden="true">·</span>
                    <span>战力 {formatPower(candidate.power)}</span>
                  </p>
                  <p className={styles.candidateXp}>
                    <span className={styles.weekXp}>
                      本周 {formatXp(candidate.week_xp)} XP
                    </span>
                    <span className={styles.todayXp}>
                      今日 +{formatXp(candidate.today_xp)} XP
                    </span>
                  </p>
                </div>
                <button
                  type="button"
                  className={styles.selectButton}
                  disabled={locked || selecting || isCurrent}
                  onClick={() => onSelect(candidate)}
                  aria-label={
                    isCurrent
                      ? `${candidate.display_name} 已经是本周宿敌`
                      : `选择 ${candidate.display_name} 作为本周宿敌`
                  }
                >
                  {isCurrent ? (
                    <>
                      <Check size={15} aria-hidden="true" />
                      当前
                    </>
                  ) : isPending ? (
                    '选择中…'
                  ) : (
                    '选择'
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {!candidates.isPending &&
      !candidates.isError &&
      visible.length > shown.length ? (
        <button
          type="button"
          className={styles.moreButton}
          onClick={() => setVisibleCount((count) => count + 10)}
        >
          显示更多候选（还有 {visible.length - shown.length} 个）
        </button>
      ) : null}
    </section>
  )
}
