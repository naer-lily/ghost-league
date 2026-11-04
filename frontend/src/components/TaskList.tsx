import * as Dialog from '@radix-ui/react-dialog'
import { Gift, Settings, X } from 'lucide-react'
import { useState } from 'react'
import { useTasks } from '../api/queries'
import { TaskCard } from './TaskCard'
import styles from './TaskList.module.css'

interface TaskListProps {
  embersBalance: number
  onOpenSettings: () => void
}

interface ClaimedChest {
  amount: number
  title: string
}

export function TaskList({ embersBalance, onOpenSettings }: TaskListProps) {
  const tasks = useTasks()
  const [claimed, setClaimed] = useState<ClaimedChest | null>(null)
  const items = tasks.data?.tasks ?? []

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
          {items.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              embersBalance={embersBalance}
              onClaimed={(amount, title) => setClaimed({ amount, title })}
            />
          ))}
        </div>
      )}

      <Dialog.Root
        open={claimed !== null}
        onOpenChange={(open) => {
          if (!open) setClaimed(null)
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className={styles.overlay} />
          <Dialog.Content className={styles.dialog} data-testid="task-chest-dialog">
            <Dialog.Title className={styles.dialogTitle}>宝箱</Dialog.Title>
            <Dialog.Description className="visually-hidden">
              {claimed?.title ?? '任务'}的宝箱奖励
            </Dialog.Description>
            <span className={styles.dialogIcon} aria-hidden="true">
              <Gift size={30} />
            </span>
            <p className={styles.dialogAmount} data-testid="task-chest-amount">
              +{claimed?.amount ?? 0} 钻石
            </p>
            <Dialog.Close asChild>
              <button type="button" className="button button--primary button--full">
                收下
              </button>
            </Dialog.Close>
            <Dialog.Close asChild>
              <button type="button" className={styles.close} aria-label="关闭宝箱">
                <X size={18} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </section>
  )
}

export default TaskList
