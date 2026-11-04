import { Camera, Check, Flame, Gift } from 'lucide-react'
import { useRef, useState, type ChangeEvent } from 'react'
import {
  useClaimTaskChest,
  useCompleteTask,
  useRepairTask,
} from '../api/queries'
import type { ChestRewardType, TaskItem } from '../api/types'
import { describeApiError } from '../lib/home'
import { compressTaskProof } from '../lib/image'
import { formatTaskCountdown } from '../lib/time'
import { useUiStore } from '../store/useUiStore'
import styles from './TaskCard.module.css'

export interface ClaimedTaskChest {
  rewardType: ChestRewardType
  amount: number
  boostMinutes: number | null
}

interface TaskCardProps {
  task: TaskItem
  embersBalance: number
  now: Date
  onClaimed: (reward: ClaimedTaskChest, title: string) => void
}

function chestRewardLabel(task: TaskItem): string {
  if (task.chest_reward_type === 'boost') {
    return task.chest_boost_minutes
      ? `经验宝 ${task.chest_boost_minutes} 分钟`
      : '经验宝'
  }
  if (task.chest_amount) return `${task.chest_amount} 钻`
  return '已领取'
}

export function TaskCard({
  task,
  embersBalance,
  now,
  onClaimed,
}: TaskCardProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const uploadingRef = useRef(false)
  const [preparing, setPreparing] = useState(false)
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

  async function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || uploadingRef.current) return
    uploadingRef.current = true
    setPreparing(true)

    let upload = file
    try {
      upload = await compressTaskProof(file)
    } catch {
      upload = file
    } finally {
      setPreparing(false)
    }

    try {
      await completeTask.mutateAsync({ taskId: task.id, file: upload })
      notify('任务完成。')
    } catch (error) {
      notify(describeApiError(error), 'error')
    } finally {
      uploadingRef.current = false
      setPreparing(false)
    }
  }

  function onClaim() {
    claimChest.mutate(task.id, {
      onSuccess: (result) =>
        onClaimed(
          {
            rewardType:
              result.reward_type === 'boost' ? 'boost' : 'diamonds',
            amount: result.amount,
            boostMinutes: result.boost_minutes,
          },
          task.title,
        ),
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
          {task.description &&
          (task.source === 'daily_manual' || task.source === 'checkin') ? (
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
              disabled={preparing || completeTask.isPending}
            />
            <button
              type="button"
              className={styles.action}
              onClick={() => inputRef.current?.click()}
              disabled={preparing || completeTask.isPending}
            >
              <Camera size={16} aria-hidden="true" />
              {preparing
                ? '处理中…'
                : completeTask.isPending
                  ? '上传中…'
                  : '拍照完成'}
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
            {chestRewardLabel(task)}
          </span>
        ) : null}
      </div>
    </article>
  )
}

export default TaskCard
