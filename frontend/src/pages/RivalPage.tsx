import type { UseQueryResult } from '@tanstack/react-query'
import {
  ArrowLeft,
  Check,
  Clock3,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Swords,
  Timer,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import {
  createRequestId,
  useRival,
  useRivalCandidates,
  useSelectRival,
} from '../api/queries'
import type {
  RivalCandidateList,
  RivalPlayer,
  RivalState,
} from '../api/types'
import { Avatar } from '../components/Avatar'
import { PageError, PageLoading } from '../components/PageState'
import { RivalBetDialog } from '../components/RivalBetDialog'
import { describeApiError, formatPower } from '../lib/home'
import {
  betStatusText,
  betStatusTone,
  clashBar,
  dailyLocked,
  describeRivalError,
  formatCountdown,
  formatXp,
  gapView,
  weekNumber,
} from '../lib/rival'
import { useUiStore } from '../store/useUiStore'
import styles from './RivalPage.module.css'

function useViewNow(serverNow: string | undefined, active: boolean): Date {
  const [tick, setTick] = useState(() => Date.now())

  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setTick(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])

  return useMemo(() => {
    if (!serverNow) return new Date(tick)
    const server = new Date(serverNow).getTime()
    if (Number.isNaN(server)) return new Date(tick)
    return new Date(tick + (server - Date.now()))
  }, [tick, serverNow])
}

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

interface SelectionViewProps {
  state: RivalState
  candidates: UseQueryResult<RivalCandidateList, Error>
  now: Date
  currentRival: RivalPlayer | null
  selecting: boolean
  pendingId: string | undefined
  selectError: string | null
  onSelect: (candidate: RivalPlayer) => void
  onBack: () => void
}

function SelectionView({
  state,
  candidates,
  now,
  currentRival,
  selecting,
  pendingId,
  selectError,
  onSelect,
  onBack,
}: SelectionViewProps) {
  const [filter, setFilter] = useState<CandidateFilter>('above')
  const [visibleCount, setVisibleCount] = useState(10)
  const mePower = state.me.power
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

  const locked = !state.selection.open

  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div className={styles.headText}>
          <div className={styles.headRow}>
            {currentRival ? (
              <button
                type="button"
                className={styles.backButton}
                onClick={onBack}
                aria-label="返回宿敌对抗"
              >
                <ArrowLeft size={18} aria-hidden="true" />
              </button>
            ) : null}
            <p className={styles.eyebrow}>
              <Swords size={14} aria-hidden="true" />
              {weekNumber(state.week_start)}
            </p>
          </div>
          <h1 className={styles.title}>选一个本周要追的宿敌</h1>
          <p className={styles.sub} data-testid="rival-selection-window">
            {locked
              ? '本周宿敌选择已锁定'
              : `周一 23:59 截止 · 还剩 ${formatCountdown(state.selection.locks_at, now)}`}
          </p>
        </div>
        <span className={styles.lockPill}>
          {locked ? (
            <>
              <ShieldCheck size={14} aria-hidden="true" />
              已锁定
            </>
          ) : (
            <>
              <Clock3 size={14} aria-hidden="true" />
              {currentRival ? '可改选' : '选择开放'}
            </>
          )}
        </span>
      </header>

      <section className={styles.panel} aria-label="宿敌候选">
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

        <p className={styles.filterHint} data-testid="rival-filter-hint">
          {fallback
            ? '没有略高于你的候选，先显示全部跨组候选。'
            : filter === 'cross'
              ? '候选都来自其他小组，由本周分组实时生成。'
              : filter === 'above'
                ? '按战力差从小到大，优先追略高于你的对手。'
                : '按与你战力的差距从小到大排列。'}
        </p>

        {selectError ? (
          <p className={styles.errorNote} role="alert" data-testid="rival-select-error">
            {selectError}
          </p>
        ) : null}

        {locked ? (
          <p className={styles.lockNote}>
            周一 23:59 之后不能再选择或改选宿敌。
          </p>
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
                    size={46}
                  />
                  <div className={styles.candidateBody}>
                    <div className={styles.candidateTitle}>
                      <strong>{candidate.display_name}</strong>
                      {isCurrent ? (
                        <span className={styles.currentTag}>当前宿敌</span>
                      ) : null}
                    </div>
                    <p className={styles.candidateMeta}>
                      <span>组 {candidate.group_no ?? '—'}</span>
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

      <p className={styles.footNote}>
        选中的对手本周会和你一起出现在宿敌页；跨组配对不影响小组排名。
      </p>
    </div>
  )
}

interface DuelViewProps {
  state: RivalState
  now: Date
  onOpenBets: () => void
  onChangeRival: () => void
}

function DuelView({
  state,
  now,
  onOpenBets,
  onChangeRival,
}: DuelViewProps) {
  const rival = state.rival
  if (!rival) return null
  const me = state.me
  const bar = clashBar(me.week_xp, rival.week_xp)
  const gap = gapView(me.week_xp, rival.week_xp)
  const windows = state.bet_windows
  const dailyClosed = dailyLocked(windows, now)
  const bets = state.bets
  const statuses: ReadonlyArray<{ label: string; bet: typeof bets.weekly }> = [
    { label: '周注', bet: bets.weekly },
    { label: '日注', bet: bets.daily },
    { label: '组注', bet: bets.group },
  ]

  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div className={styles.headText}>
          <p className={styles.eyebrow}>
            <Swords size={14} aria-hidden="true" />
            {weekNumber(state.week_start)}
          </p>
          <h1 className={styles.title}>宿敌对抗</h1>
          <p className={styles.sub}>
            {state.selection.open
              ? '周一 23:59 前可以改选宿敌'
              : '宿敌已锁定，本周不可更换'}
          </p>
        </div>
        {state.selection.open ? (
          <button
            type="button"
            className={styles.changeButton}
            onClick={onChangeRival}
          >
            改选
          </button>
        ) : null}
      </header>

      <section className={styles.panel} aria-labelledby="rival-duel-title">
        <h2 id="rival-duel-title" className="visually-hidden">
          本周宿敌对撞
        </h2>

        <div className={styles.playerGrid}>
          <article className={[styles.playerCard, styles.playerMe].join(' ')}>
            <span className={styles.playerTag}>我</span>
            <div className={styles.avatarWrap}>
              <Avatar src={me.avatar_url} name={me.display_name} size={54} />
            </div>
            <p className={styles.playerName} title={me.display_name}>
              {me.display_name}
            </p>
            <p className={styles.playerXp} data-testid="rival-me-xp">
              {formatXp(me.week_xp)} <small>XP</small>
            </p>
            <p className={styles.playerToday}>今日 +{formatXp(me.today_xp)}</p>
            <p className={styles.playerPower}>
              战力 {formatPower(me.power)}
            </p>
          </article>

          <div className={styles.vsColumn} aria-hidden="true">
            <span className={styles.vs}>VS</span>
          </div>

          <article
            className={[styles.playerCard, styles.playerRival].join(' ')}
          >
            <span className={styles.playerTag}>宿敌</span>
            <div className={styles.avatarWrap}>
              <Avatar
                src={rival.avatar_url}
                name={rival.display_name}
                size={54}
              />
            </div>
            <p className={styles.playerName} title={rival.display_name}>
              {rival.display_name}
            </p>
            <p className={styles.playerXp} data-testid="rival-rival-xp">
              {formatXp(rival.week_xp)} <small>XP</small>
            </p>
            <p className={styles.playerToday}>
              今日 +{formatXp(rival.today_xp)}
            </p>
            <p className={styles.playerPower}>
              战力 {formatPower(rival.power)}
            </p>
          </article>
        </div>

        <div
          className={styles.clash}
          role="img"
          aria-label={`我本周 ${formatXp(me.week_xp)} XP，宿敌本周 ${formatXp(rival.week_xp)} XP`}
          data-testid="rival-clash"
        >
          <span
            className={styles.clashMe}
            style={{ width: `${bar.leftPercent}%` }}
            data-testid="rival-clash-me"
          />
          <span
            className={styles.clashRival}
            style={{ width: `${bar.rightPercent}%` }}
            data-testid="rival-clash-rival"
          />
          {bar.leftPercent > 0 && bar.leftPercent < 100 ? (
            <span
              className={styles.clashSpark}
              style={{ left: `${bar.leftPercent}%` }}
              aria-hidden="true"
            />
          ) : null}
        </div>
        <div className={styles.barLabels}>
          <span className={styles.barMine}>
            我 {bar.total === 0 ? '50' : Math.round(bar.leftPercent)}%
          </span>
          <span className={styles.barRival}>
            宿敌 {bar.total === 0 ? '50' : Math.round(bar.rightPercent)}%
          </span>
        </div>

        <p className={styles.gapLine} aria-live="polite" data-testid="rival-gap">
          {gap.tone === 'even' ? (
            <>双方持平</>
          ) : (
            <>
              {gap.label}{' '}
              <strong className={styles.gapValue}>
                {formatXp(gap.amount)} XP
              </strong>
            </>
          )}
        </p>

        <div className={styles.timePanel}>
          <div className={styles.timeItem}>
            <span className={styles.timeLabel}>
              <Timer size={14} aria-hidden="true" />
              本周剩余
            </span>
            <strong
              className={styles.timeValue}
              data-testid="rival-week-countdown"
            >
              {formatCountdown(windows.weekly_locks_at, now)}
            </strong>
          </div>
          <div className={styles.timeItem}>
            <span className={styles.timeLabel}>
              <Clock3 size={14} aria-hidden="true" />
              日注锁注
            </span>
            <strong
              className={styles.timeValue}
              data-testid="rival-daily-countdown"
            >
              {dailyClosed ? '今天的注已截止' : formatCountdown(windows.daily_locks_at, now)}
            </strong>
            <span className={styles.timeHint}>21:00 锁注 · 22:30 结算</span>
          </div>
        </div>

        <div className={styles.betBar}>
          <div className={styles.betStatuses} aria-label="本周下注状态">
            {statuses.map((entry) => (
              <span
                key={entry.label}
                className={[
                  styles.betChip,
                  betStatusTone(entry.bet) === 'placed'
                    ? styles.betChipDone
                    : '',
                  betStatusTone(entry.bet) === 'settled'
                    ? styles.betChipSettled
                    : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                data-testid={`rival-bet-status-${entry.label}`}
              >
                {entry.label} · {betStatusText(entry.bet)}
              </span>
            ))}
          </div>
          <button
            type="button"
            className={styles.betButton}
            onClick={onOpenBets}
          >
            下注
          </button>
        </div>
      </section>

      <p className={styles.footNote}>
        周结算只看双方最终本周 XP；对撞条只把当前差距显示成推挤。
      </p>
    </div>
  )
}

function LockedView({ onRetry }: { onRetry: () => void }) {
  return (
    <div className={styles.page}>
      <section className={styles.lockedPanel} role="status">
        <span className={styles.lockedIcon} aria-hidden="true">
          <ShieldAlert size={32} />
        </span>
        <p className="eyebrow">本周宿敌</p>
        <h1 className={styles.lockedTitle}>本周宿敌已锁定</h1>
        <p className={styles.lockedCopy}>
          选宿敌窗口已经关闭，本周没有匹配到宿敌。这里不会伪造对局或下注。
        </p>
        <button
          type="button"
          className="button button--primary"
          onClick={onRetry}
        >
          <RotateCcw size={17} aria-hidden="true" />
          重试
        </button>
      </section>
    </div>
  )
}

export function RivalPage() {
  const rivalQuery = useRival()
  const selectMutation = useSelectRival()
  const notify = useUiStore((state) => state.notify)
  const [showSelection, setShowSelection] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)

  const data = rivalQuery.data
  const now = useViewNow(data?.server_now, Boolean(data))
  const selectionOpen = Boolean(data?.selection.open)
  const candidateEnabled = Boolean(
    data && selectionOpen && (!data.rival || showSelection),
  )
  const candidates = useRivalCandidates(candidateEnabled)

  if (rivalQuery.isPending) return <PageLoading />

  if (rivalQuery.isError) {
    return (
      <PageError
        message={describeApiError(rivalQuery.error)}
        retrying={rivalQuery.isFetching}
        onRetry={() => void rivalQuery.refetch()}
      />
    )
  }

  if (!data) return <PageLoading />

  const selectError = selectMutation.error
    ? describeRivalError(selectMutation.error)
    : null

  function handleSelect(candidate: RivalPlayer) {
    selectMutation.mutate(
      {
        rivalId: candidate.user_id,
        requestId: createRequestId(),
      },
      {
        onSuccess: () => {
          setShowSelection(false)
          notify('宿敌已选定。')
        },
        onError: (error) => {
          notify(describeRivalError(error), 'error')
        },
      },
    )
  }

  if (data.rival && !showSelection) {
    return (
      <>
        <DuelView
          state={data}
          now={now}
          onOpenBets={() => setDialogOpen(true)}
          onChangeRival={() => {
            selectMutation.reset()
            setShowSelection(true)
          }}
        />
        <RivalBetDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          state={data}
          now={now}
        />
      </>
    )
  }

  if (selectionOpen) {
    return (
      <SelectionView
        state={data}
        candidates={candidates}
        now={now}
        currentRival={data.rival}
        selecting={selectMutation.isPending}
        pendingId={
          selectMutation.isPending
            ? selectMutation.variables?.rivalId
            : undefined
        }
        selectError={selectError}
        onSelect={handleSelect}
        onBack={() => setShowSelection(false)}
      />
    )
  }

  return <LockedView onRetry={() => void rivalQuery.refetch()} />
}
