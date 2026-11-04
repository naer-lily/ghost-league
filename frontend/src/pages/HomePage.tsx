import { ChevronDown, ChevronUp, RotateCcw, Swords } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import type { CSSProperties } from 'react'
import { useState } from 'react'
import {
  createRequestId,
  tasksQueryKey,
  useHomeSnapshot,
  useRival,
  useRivalCandidates,
  useSelectRival,
} from '../api/queries'
import type { RivalPlayer } from '../api/types'
import { PageError, PageLoading } from '../components/PageState'
import { PlayerHeader } from '../components/PlayerHeader'
import { PullToRefresh } from '../components/PullToRefresh'
import { RivalBetDialog } from '../components/RivalBetDialog'
import { RivalCandidatePicker } from '../components/RivalCandidatePicker'
import { RivalDuelCard } from '../components/RivalDuelCard'
import { TaskList } from '../components/TaskList'
import { TaskSettingsDialog } from '../components/TaskSettingsDialog'
import { TodayProgress } from '../components/TodayProgress'
import { UserProfileSheet } from '../components/UserProfileSheet'
import {
  buildHomeView,
  describeApiError,
  tierStyleVars,
} from '../lib/home'
import { describeRivalError, type RivalBetTab } from '../lib/rival'
import { useServerNow } from '../lib/useServerNow'
import { useUiStore } from '../store/useUiStore'
import styles from './HomePage.module.css'

export function HomePage() {
  const home = useHomeSnapshot()
  const rivalQuery = useRival()
  const selectMutation = useSelectRival()
  const queryClient = useQueryClient()
  const notify = useUiStore((state) => state.notify)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [dialogKind, setDialogKind] = useState<RivalBetTab | null>(null)
  const [profileId, setProfileId] = useState<string | null>(null)
  const [tasksSettingsOpen, setTasksSettingsOpen] = useState(false)

  const data = rivalQuery.data
  const now = useServerNow(data?.server_now, Boolean(data))
  const selectionOpen = Boolean(data?.selection.open)
  const hasRival = Boolean(data?.rival)
  const candidateEnabled = Boolean(
    data && selectionOpen && !hasRival && pickerOpen,
  )
  const candidates = useRivalCandidates(candidateEnabled)

  async function refresh() {
    const [homeResult, rivalResult] = await Promise.all([
      home.refetch(),
      rivalQuery.refetch(),
      queryClient.invalidateQueries({ queryKey: tasksQueryKey }),
    ])
    const error = homeResult.error ?? rivalResult.error
    if (error) {
      notify(describeApiError(error), 'error')
    } else {
      notify('联赛数据已刷新。')
    }
  }

  if (home.isPending) return <PageLoading />

  if (home.isError) {
    return (
      <PageError
        message={describeApiError(home.error)}
        retrying={home.isFetching}
        onRetry={() => {
          void home.refetch()
          void rivalQuery.refetch()
        }}
      />
    )
  }

  if (!home.data) return <PageLoading />

  const view = buildHomeView(home.data)
  const style = tierStyleVars(view.tier) as CSSProperties

  function handleSelect(candidate: RivalPlayer) {
    selectMutation.mutate(
      {
        rivalId: candidate.user_id,
        requestId: createRequestId(),
      },
      {
        onSuccess: () => {
          setPickerOpen(false)
          notify('宿敌已选定。')
        },
        onError: (error) => notify(describeRivalError(error), 'error'),
      },
    )
  }

  return (
    <PullToRefresh onRefresh={refresh}>
      <div className={styles.page}>
        <PlayerHeader view={view} />

        <div className={styles.today} style={style} data-flat="true">
          <TodayProgress
            todayXp={view.todayXp}
            todaySeconds={view.todaySeconds}
            updatedAt={view.todayUpdatedAt}
            tier={view.tier}
          />
        </div>

        <TaskList
          embersBalance={view.embersBalance}
          onOpenSettings={() => setTasksSettingsOpen(true)}
        />

        <section
          className={styles.rival}
          aria-labelledby="home-rival-title"
          data-testid="home-rival"
        >
          <div className={styles.rivalHead}>
            <h2 id="home-rival-title" className={styles.rivalTitle}>
              <span aria-hidden="true">
                <Swords size={18} />
              </span>
              宿敌
            </h2>
            {hasRival && selectionOpen ? (
              <button
                type="button"
                className={styles.rivalAction}
                onClick={() => {
                  selectMutation.reset()
                  setPickerOpen((open) => !open)
                }}
                aria-expanded={pickerOpen}
              >
                {pickerOpen ? (
                  <ChevronUp size={15} aria-hidden="true" />
                ) : (
                  <ChevronDown size={15} aria-hidden="true" />
                )}
                {pickerOpen ? '收起候选' : '改选'}
              </button>
            ) : null}
          </div>

          {rivalQuery.isPending ? (
            <div className={styles.rivalSkeleton} aria-busy="true">
              <span className="visually-hidden">正在读取宿敌数据…</span>
              <span className={styles.skeletonLine} />
              <span className={styles.skeletonBar} />
              <span className={styles.skeletonLine} />
            </div>
          ) : rivalQuery.isError ? (
            <div className={styles.rivalState} role="alert">
              <p>{describeApiError(rivalQuery.error)}</p>
              <button
                type="button"
                className="button button--secondary"
                onClick={() => void rivalQuery.refetch()}
                disabled={rivalQuery.isFetching}
              >
                <RotateCcw size={16} aria-hidden="true" />
                {rivalQuery.isFetching ? '正在重试…' : '重试'}
              </button>
            </div>
          ) : data?.rival ? (
            <>
              <RivalDuelCard
                state={data}
                now={now}
                variant="full"
                onOpenProfile={setProfileId}
                onOpenBets={(kind) => setDialogKind(kind)}
              />
              {pickerOpen && selectionOpen ? (
                <RivalCandidatePicker
                  candidates={candidates}
                  mePower={data.me.power}
                  currentRival={data.rival}
                  locked={!selectionOpen}
                  selecting={selectMutation.isPending}
                  pendingId={
                    selectMutation.isPending
                      ? selectMutation.variables?.rivalId
                      : undefined
                  }
                  selectError={
                    selectMutation.error
                      ? describeRivalError(selectMutation.error)
                      : null
                  }
                  onSelect={handleSelect}
                  compact
                />
              ) : null}
            </>
          ) : data && selectionOpen ? (
            <div className={styles.rivalEmpty} data-testid="home-rival-empty">
              <span className={styles.rivalEmptyIcon} aria-hidden="true">
                <Swords size={24} />
              </span>
              <div className={styles.rivalEmptyCopy}>
                <strong>还没有宿敌</strong>
                <p>选择一个对手，首页会直接显示双方进度和下注状态。</p>
              </div>
              <button
                type="button"
                className="button button--primary"
                onClick={() => setPickerOpen((open) => !open)}
                aria-expanded={pickerOpen}
              >
                {pickerOpen ? '收起候选' : '选择宿敌'}
              </button>
            </div>
          ) : (
            <div className={styles.rivalState} role="status">
              <p>本周宿敌选择已锁定，暂时没有匹配到宿敌。</p>
              <button
                type="button"
                className="button button--secondary"
                onClick={() => void rivalQuery.refetch()}
                disabled={rivalQuery.isFetching}
              >
                <RotateCcw size={16} aria-hidden="true" />
                重试
              </button>
            </div>
          )}

          {!hasRival && selectionOpen && pickerOpen ? (
            <RivalCandidatePicker
              candidates={candidates}
              mePower={data?.me.power ?? 0}
              currentRival={null}
              locked={!selectionOpen}
              selecting={selectMutation.isPending}
              pendingId={
                selectMutation.isPending
                  ? selectMutation.variables?.rivalId
                  : undefined
              }
              selectError={
                selectMutation.error
                  ? describeRivalError(selectMutation.error)
                  : null
              }
              onSelect={handleSelect}
              compact
            />
          ) : null}
        </section>
      </div>

      {data?.rival ? (
        <RivalBetDialog
          open={dialogKind !== null}
          onOpenChange={(open) => {
            if (!open) setDialogKind(null)
          }}
          state={data}
          now={now}
          onlyKind={dialogKind ?? undefined}
        />
      ) : null}

      <UserProfileSheet
        userId={profileId}
        onOpenChange={(open) => {
          if (!open) setProfileId(null)
        }}
      />

      <TaskSettingsDialog
        open={tasksSettingsOpen}
        onOpenChange={setTasksSettingsOpen}
      />
    </PullToRefresh>
  )
}
