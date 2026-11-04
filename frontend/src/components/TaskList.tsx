import { Settings } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTasks } from '../api/queries'
import type { Bet, BetWindows, RivalState, TaskItem } from '../api/types'
import { useServerNow } from '../lib/useServerNow'
import { dailyLocked, weeklyLocked, type RivalBetTab } from '../lib/rival'
import { BetTaskRow, type BetSides } from './BetTaskRow'
import { ChestOpenDialog } from './ChestOpenDialog'
import { TaskCard } from './TaskCard'
import styles from './TaskList.module.css'

interface TaskListProps {
  embersBalance: number
  onOpenSettings: () => void
  rivalState?: RivalState | null
  onOpenBets?: (kind: RivalBetTab) => void
}

interface BetRowData {
  kind: RivalBetTab
  bet: Bet | null
  meXp: number
  rivalXp: number
  locked: boolean
  locksAt: string
  windows: BetWindows
}

type OrderedEntry =
  | {
      type: 'task'
      key: string
      task: TaskItem
      sink: number
      cluster: number
      atMs: number
      order: number
    }
  | {
      type: 'bet'
      key: string
      row: BetRowData
      sink: number
      cluster: number
      atMs: number
      order: number
    }

function displayBucket(task: TaskItem): number {
  if (
    task.status === 'active' ||
    (task.status === 'completed' && task.chest_status === 'available')
  ) {
    return 0
  }
  return 1
}

function timestamp(value: string): number {
  const parsed = new Date(value).getTime()
  return Number.isNaN(parsed) ? 0 : parsed
}

function weekEndMs(weekStart: string | null | undefined): number | null {
  if (!weekStart) return null
  const start = timestamp(`${weekStart}T00:00:00+08:00`)
  if (start === 0) return null
  return start + 7 * 86_400_000
}

function taskCluster(task: TaskItem, endMs: number | null): number {
  if (task.source === 'weekly_chain') return 1
  if (endMs !== null && timestamp(task.ends_at) >= endMs) return 1
  return 0
}

function buildBetRows(
  state: RivalState | null | undefined,
  now: Date,
): BetRowData[] {
  if (!state?.rival) return []
  const windows = state.bet_windows
  return [
    {
      kind: 'daily',
      bet: state.bets.daily,
      meXp: state.me.today_xp,
      rivalXp: state.rival.today_xp,
      locked: dailyLocked(windows, now),
      locksAt: windows.daily_locks_at,
      windows,
    },
    {
      kind: 'weekly',
      bet: state.bets.weekly,
      meXp: state.me.week_xp,
      rivalXp: state.rival.week_xp,
      locked: weeklyLocked(windows, now),
      locksAt: windows.weekly_locks_at,
      windows,
    },
  ]
}

function buildOrderedEntries(
  tasks: readonly TaskItem[],
  betRows: readonly BetRowData[],
  weekStart: string | null | undefined,
): OrderedEntry[] {
  const endMs = weekEndMs(weekStart)
  const entries: OrderedEntry[] = [
    ...tasks.map<OrderedEntry>((task) => ({
      type: 'task',
      key: `task:${task.id}`,
      task,
      sink: displayBucket(task),
      cluster: taskCluster(task, endMs),
      atMs: timestamp(task.ends_at),
      order: task.sort_order,
    })),
    ...betRows.map<OrderedEntry>((row) => ({
      type: 'bet',
      key: `bet:${row.kind}:${row.bet?.id ?? 'none'}`,
      row,
      sink: 0,
      cluster: row.kind === 'weekly' ? 1 : 0,
      atMs: timestamp(row.locksAt),
      order: row.kind === 'weekly' ? 1 : 0,
    })),
  ]

  return entries.sort((left, right) => {
    if (left.sink !== right.sink) return left.sink - right.sink
    if (left.cluster !== right.cluster) return left.cluster - right.cluster
    if (left.atMs !== right.atMs) return left.atMs - right.atMs
    if (left.order !== right.order) return left.order - right.order
    if (left.key === right.key) return 0
    return left.key < right.key ? -1 : 1
  })
}

function frozenSnapshot(
  state: RivalState | null | undefined,
  row: BetRowData,
): BetSides | null {
  if (!state || !row.bet || row.bet.status === 'placed') return null
  if (
    row.kind === 'weekly' &&
    state.result &&
    state.result.week_start === row.bet.period_key
  ) {
    return { me: state.result.my_xp, rival: state.result.rival_xp }
  }
  return null
}

export function TaskList({
  embersBalance,
  onOpenSettings,
  rivalState,
  onOpenBets,
}: TaskListProps) {
  const tasks = useTasks()
  const now = useServerNow(tasks.data?.server_now, Boolean(tasks.data))
  const [openedTask, setOpenedTask] = useState<TaskItem | null>(null)
  const [expandedBet, setExpandedBet] = useState<{
    kind: RivalBetTab
    id: number
  } | null>(null)
  const items = useMemo(() => tasks.data?.tasks ?? [], [tasks.data])
  const betRows = useMemo(
    () => (onOpenBets ? buildBetRows(rivalState, now) : []),
    [onOpenBets, rivalState, now],
  )
  const ordered = useMemo(
    () => buildOrderedEntries(items, betRows, rivalState?.week_start),
    [betRows, items, rivalState?.week_start],
  )
  const firstWeeklyIndex = ordered.findIndex(
    (entry) => entry.cluster === 1 && entry.sink === 0,
  )

  function toggleBet(kind: RivalBetTab, id: number) {
    setExpandedBet((current) =>
      current && current.kind === kind && current.id === id
        ? null
        : { kind, id },
    )
  }

  return (
    <section className={styles.section} aria-labelledby="home-tasks-title" data-testid="task-list">
      <div className={styles.head}>
        <h2 id="home-tasks-title" className={styles.title}>
          任务
        </h2>
        <button
          type="button"
          className={styles.settings}
          onClick={onOpenSettings}
          aria-label="任务设置"
        >
          <Settings size={15} aria-hidden="true" />
          设置
        </button>
      </div>

      {tasks.isPending ? (
        <div className={styles.skeleton} aria-busy="true">
          <span className="visually-hidden">正在读取任务…</span>
          <span />
        </div>
      ) : tasks.isError ? (
        <p className={styles.empty}>任务暂时没加载出来。</p>
      ) : ordered.length === 0 ? (
        <p className={styles.empty}>今天还没有任务。</p>
      ) : (
        <div className={styles.list}>
          {ordered.map((entry, index) => {
            const addsGap = index === firstWeeklyIndex && firstWeeklyIndex > 0
            return (
              <div
                key={entry.key}
                className={[styles.entry, addsGap ? styles.weeklyStart : '']
                  .filter(Boolean)
                  .join(' ')}
                data-entry-kind={entry.type}
                data-list-gap={addsGap ? 'true' : undefined}
              >
                {entry.type === 'bet' ? (
                  <BetTaskRow
                    kind={entry.row.kind}
                    bet={entry.row.bet}
                    meXp={entry.row.meXp}
                    rivalXp={entry.row.rivalXp}
                    windows={entry.row.windows}
                    locked={entry.row.locked}
                    expanded={
                      entry.row.bet !== null &&
                      expandedBet?.kind === entry.row.kind &&
                      expandedBet.id === entry.row.bet.id
                    }
                    snapshot={frozenSnapshot(rivalState, entry.row)}
                    onToggle={() => {
                      if (entry.row.bet) {
                        toggleBet(entry.row.kind, entry.row.bet.id)
                      }
                    }}
                    onOpenBets={(kind) => onOpenBets?.(kind)}
                  />
                ) : (
                  <TaskCard
                    task={entry.task}
                    embersBalance={embersBalance}
                    now={now}
                    onOpenChest={setOpenedTask}
                  />
                )}
              </div>
            )
          })}
        </div>
      )}

      {openedTask ? (
        <ChestOpenDialog
          key={openedTask.id}
          task={openedTask}
          onClose={() => setOpenedTask(null)}
        />
      ) : null}
    </section>
  )
}

export default TaskList
