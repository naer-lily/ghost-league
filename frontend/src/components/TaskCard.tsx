import { Camera, Check, Flame, Gift } from 'lucide-react'
import { useRef, type ChangeEvent } from 'react'
import {
  useClaimTaskChest,
  useCompleteTask,
  useRepairTask,
} from '../api/queries'
import type { TaskItem } from '../api/types'
import { describeApiError } from '../lib/home'
import { formatTaskCountdown } from '../lib/time'
import { useUiStore } from '../store/useUiStore'
import styles from './TaskCard.module.css'

interface TaskCardProps {
  task: TaskItem
  embersBalance: number
  now: Date
  onClaimed: (amount: number, title: string) => void
}

export function TaskCard({
  task,
  embersBalance,
  now,
  onClaimed,
}: TaskCardProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const completeTask = useCompleteTask()
  const claimChest = useClaimTaskChest()
  const repairTask = useRepairTask()
  const notify = useUiStore((state) => state.notify)

  const manualActive = task.source === 'daily_manual' && task.status === 'active'
  const repairActive =
    task.source === 'repair' && task.status === 'active' && task.missed_date
  const dslActive = task.source !== 'daily_manual' && task.status === 'active'
  const chestAvailable =
    task.status === 'completed' && task.chest_status === 'available'
  const chestClaimed =
    task.status === 'completed' && task.chest_status === 'claimed'
  const canRepair = embersBalance >= 1
  const remaining = formatTaskCountdown(task.ends_at, now)

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    completeTask.mutate(
      { taskId: task.id, file },
      {
        onSuccess: () => notify('任务完成。'),
        onError: (error) => notify(describeApiError(error), 'error'),
      },
    )
  }

  function onClaim() {
    claimChest.mutate(task.id, {
      onSuccess: (result) => onClaimed(result.amount, task.title),
      onError: (error) => notify(describeApiError(error), 'error'),
    })
  }

  function onRepair() {
    if (!task.missed_date || !canRepair) return
    repairTask.mutate(
      { date: task.missed_date },
      {
        onSuccess: () => notify('补上了。'),
        onError: (error) => notify(describeApiError(error), 'error'),
      },
    )
  }

  return (
    <article className={styles.card} data-testid={`task-card-${task.source}`}>
      <div className={styles.body}>
        <div className={styles.copy}>
          <h3 className={styles.title}>{task.title}</h3>
          {task.description && task.source === 'daily_manual' ? (
            <p className={styles.description}>{task.description}</p>
          ) : null}
          <p className={styles.deadline}>{remaining}</p>
        </div>

        {manualActive ? (
          <>
            <input
              ref={inputRef}
              className={styles.fileInput}
              type="file"
              accept="image/*"
              capture="environment"
              aria-label={`上传${task.title}的照片`}
              onChange={onFileChange}
            />
            <button
              type="button"
              className={styles.action}
              onClick={() => inputRef.current?.click()}
              disabled={completeTask.isPending}
            >
              <Camera size={16} aria-hidden="true" />
              {completeTask.isPending ? '上传中…' : '拍照完成'}
            </button>
          </>
        ) : repairActive ? (
          <button
            type="button"
            className={styles.action}
            onClick={onRepair}
            disabled={repairTask.isPending || !canRepair}
          >
            <Flame size={16} aria-hidden="true" />
            {repairTask.isPending
              ? '补录中…'
              : canRepair
                ? '用余烬补'
                : '还差一枚余烬'}
          </button>
        ) : dslActive && task.progress ? (
          <p className={styles.progress} data-testid="task-progress">
            {task.progress.current} / {task.progress.target}
            {task.source === 'weekend' ? ' XP' : ''}
          </p>
        ) : chestAvailable ? (
          <button
            type="button"
            className={styles.chest}
            onClick={onClaim}
            disabled={claimChest.isPending}
            aria-label={`领取${task.title}的宝箱`}
          >
            <Gift size={17} aria-hidden="true" />
            {claimChest.isPending ? '领取中…' : '宝箱'}
          </button>
        ) : chestClaimed ? (
          <span className={styles.claimed} data-testid="task-claimed">
            <Check size={15} aria-hidden="true" />
            已领取{task.chest_amount ? ` ${task.chest_amount} 钻` : ''}
          </span>
        ) : null}
      </div>
    </article>
  )
}

export default TaskCard
