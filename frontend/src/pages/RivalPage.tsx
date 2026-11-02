import {
  ArrowLeft,
  Clock3,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Swords,
} from 'lucide-react'
import { useState } from 'react'
import {
  createRequestId,
  useRival,
  useRivalCandidates,
  useSelectRival,
} from '../api/queries'
import type { RivalPlayer } from '../api/types'
import { PageError, PageLoading } from '../components/PageState'
import { RivalBetDialog } from '../components/RivalBetDialog'
import { RivalCandidatePicker } from '../components/RivalCandidatePicker'
import { RivalDuelCard } from '../components/RivalDuelCard'
import { UserProfileSheet } from '../components/UserProfileSheet'
import { describeApiError } from '../lib/home'
import {
  describeRivalError,
  formatCountdown,
  weekNumber,
} from '../lib/rival'
import { useServerNow } from '../lib/useServerNow'
import { useUiStore } from '../store/useUiStore'
import styles from './RivalPage.module.css'

function SelectionView({
  data,
  picker,
  onSelect,
  onBack,
  selecting,
  pendingId,
  selectError,
}: {
  data: NonNullable<ReturnType<typeof useRival>['data']>
  picker: ReturnType<typeof useRivalCandidates>
  onSelect: (candidate: RivalPlayer) => void
  onBack: () => void
  selecting: boolean
  pendingId: string | undefined
  selectError: string | null
}) {
  const now = useServerNow(data.server_now, true)
  const currentRival = data.rival
  const locked = !data.selection.open

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
              {weekNumber(data.week_start)}
            </p>
          </div>
          <h1 className={styles.title}>选一个本周要追的宿敌</h1>
          <p className={styles.sub} data-testid="rival-selection-window">
            {locked
              ? '本周宿敌选择已锁定'
              : `周一 23:59 截止 · 还剩 ${formatCountdown(data.selection.locks_at, now)}`}
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

      <RivalCandidatePicker
        candidates={picker}
        mePower={data.me.power}
        currentRival={currentRival}
        locked={locked}
        selecting={selecting}
        pendingId={pendingId}
        selectError={selectError}
        onSelect={onSelect}
      />

      <p className={styles.footNote}>
        选中的对手本周会和你一起出现在宿敌页；跨组配对不影响小组排名。
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
  const [profileId, setProfileId] = useState<string | null>(null)

  const data = rivalQuery.data
  const selectionOpen = Boolean(data?.selection.open)
  const candidateEnabled = Boolean(
    data && selectionOpen && (!data.rival || showSelection),
  )
  const candidates = useRivalCandidates(candidateEnabled)
  const now = useServerNow(data?.server_now, Boolean(data))

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
        <div className={styles.page}>
          <header className={styles.head}>
            <div className={styles.headText}>
              <p className={styles.eyebrow}>
                <Swords size={14} aria-hidden="true" />
                {weekNumber(data.week_start)}
              </p>
              <h1 className={styles.title}>宿敌对抗</h1>
              <p className={styles.sub}>
                {data.selection.open
                  ? '周一 23:59 前可以改选宿敌'
                  : '宿敌已锁定，本周不可更换'}
              </p>
            </div>
            {data.selection.open ? (
              <button
                type="button"
                className={styles.changeButton}
                onClick={() => {
                  selectMutation.reset()
                  setShowSelection(true)
                }}
              >
                改选
              </button>
            ) : null}
          </header>

          <RivalDuelCard
            state={data}
            now={now}
            onOpenProfile={setProfileId}
            onOpenBets={() => setDialogOpen(true)}
          />

          <p className={styles.footNote}>
            周结算只看双方最终本周 XP；对撞条只把当前差距显示成推挤。
          </p>
        </div>
        <RivalBetDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          state={data}
          now={now}
          initialTab="weekly"
        />
        <UserProfileSheet
          userId={profileId}
          onOpenChange={(open) => {
            if (!open) setProfileId(null)
          }}
        />
      </>
    )
  }

  if (selectionOpen) {
    return (
      <SelectionView
        data={data}
        picker={candidates}
        onSelect={handleSelect}
        onBack={() => setShowSelection(false)}
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
      />
    )
  }

  return <LockedView onRetry={() => void rivalQuery.refetch()} />
}
