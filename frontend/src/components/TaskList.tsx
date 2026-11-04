import { Settings } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTasks } from '../api/queries'
import type { TaskItem } from '../api/types'
import { useServerNow } from '../lib/useServerNow'
import { ChestOpenDialog } from './ChestOpenDialog'
import { TaskCard } from './TaskCard'
import styles from './TaskList.module.css'

interface TaskListProps {
  embersBalance: number
  onOpenSettings: () => void
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

export function sortTasksForDisplay(tasks: readonly TaskItem[]): TaskItem[] {
  return [...tasks].sort((left, right) => {
    const bucket = displayBucket(left) - displayBucket(right)
    if (bucket !== 0) return bucket
    if (left.ends_at !== right.ends_at) return left.ends_at < right.ends_at ? -1 : 1
    if (left.sort_order !== right.sort_order) {
      return left.sort_order - right.sort_order
    }
    if (left.id === right.id) return 0
    return left.id < right.id ? -1 : 1
  })
}

export function TaskList({ embersBalance, onOpenSettings }: TaskListProps) {
  const tasks = useTasks()
  const now = useServerNow(tasks.data?.server_now, Boolean(tasks.data))
  const [openedTask, setOpenedTask] = useState<TaskItem | null>(null)
  const items = useMemo(() => tasks.data?.tasks ?? [], [tasks.data])
  const ordered = useMemo(() => sortTasksForDisplay(items), [items])

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
      ) : items.length === 0 ? (
        <p className={styles.empty}>今天还没有任务。</p>
      ) : (
        <div className={styles.list}>
          {ordered.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              embersBalance={embersBalance}
              now={now}
              onOpenChest={setOpenedTask}
            />
          ))}
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
