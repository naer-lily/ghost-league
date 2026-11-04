import * as Dialog from '@radix-ui/react-dialog'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { Diamond, Flame, Star, X } from 'lucide-react'
import { useId, useRef, useState } from 'react'
import { useClaimTaskChest } from '../api/queries'
import type { TaskChestResult, TaskItem } from '../api/types'
import { describeApiError } from '../lib/home'
import styles from './ChestOpenDialog.module.css'

/** Keep the opening beat visible even when the API answers immediately. */
const MIN_OPEN_MS = 650

type Phase = 'idle' | 'opening' | 'revealed'

interface ChestOpenDialogProps {
  task: TaskItem
  onClose: () => void
}

function rewardText(result: TaskChestResult): string {
  if (result.reward_type === 'star') {
    return result.star ? `星星：${result.star.name}` : '星星'
  }
  if (result.reward_type === 'boost') {
    return result.boost_minutes
      ? `经验宝 ${result.boost_minutes} 分钟`
      : '经验宝'
  }
  return `${result.amount} 钻`
}

function RewardIcon({ result }: { result: TaskChestResult }) {
  if (result.reward_type === 'star') return <Star size={26} aria-hidden="true" />
  if (result.reward_type === 'boost') {
    return <Flame size={26} aria-hidden="true" />
  }
  return <Diamond size={26} aria-hidden="true" />
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

export function ChestOpenDialog({ task, onClose }: ChestOpenDialogProps) {
  const titleId = useId()
  const descriptionId = useId()
  const claimChest = useClaimTaskChest()
  const reducedMotion = useReducedMotion()
  const [phase, setPhase] = useState<Phase>('idle')
  const [result, setResult] = useState<TaskChestResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inFlightRef = useRef(false)

  const opening = phase === 'opening'
  const revealed = phase === 'revealed' && result !== null

  function handleOpenChange(next: boolean) {
    if (next) return
    // Do not dismiss while the real claim request is in flight.
    if (opening) return
    onClose()
  }

  async function handleOpen() {
    if (opening || inFlightRef.current) return
    inFlightRef.current = true
    setError(null)
    setResult(null)
    setPhase('opening')
    const startedAt = Date.now()
    try {
      const claimed = await claimChest.mutateAsync(task.id)
      if (!reducedMotion) {
        const remaining = MIN_OPEN_MS - (Date.now() - startedAt)
        if (remaining > 0) await wait(remaining)
      }
      setResult(claimed)
      setPhase('revealed')
    } catch (submitError) {
      setResult(null)
      setPhase('idle')
      setError(describeApiError(submitError))
    } finally {
      inFlightRef.current = false
    }
  }

  return (
    <Dialog.Root open onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={styles.dialog}
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
          data-testid="chest-open-dialog"
          data-phase={phase}
        >
          <div className={styles.head}>
            <div>
              <Dialog.Title id={titleId} className={styles.eyebrow}>
                宝箱
              </Dialog.Title>
              <Dialog.Description id={descriptionId} className="visually-hidden">
                任务「{task.title}」的宝箱
              </Dialog.Description>
            </div>
            {opening ? null : (
              <Dialog.Close asChild>
                <button
                  type="button"
                  className={styles.close}
                  aria-label="关闭宝箱"
                >
                  <X size={18} aria-hidden="true" />
                </button>
              </Dialog.Close>
            )}
          </div>

          <h2 className={styles.taskTitle}>{task.title}</h2>

          <div
            className={styles.stage}
            data-testid="chest-art"
            data-state={revealed ? 'revealed' : 'closed'}
            aria-hidden="true"
          >
            {revealed && !reducedMotion ? (
              <motion.span
                className={styles.glow}
                data-testid="chest-glow"
                initial={{ opacity: 0, scale: 0.4 }}
                animate={{
                  opacity: [0, 0.8, 0.2],
                  scale: [0.4, 1.5, 2],
                }}
                transition={{ duration: 0.7, ease: 'easeOut' }}
              />
            ) : null}

            <motion.div
              className={styles.chest}
              animate={
                opening && !reducedMotion
                  ? {
                      x: [0, -2.5, 2.5, -1.5, 1.5, 0],
                      rotate: [0, -1.2, 1.2, -0.7, 0.7, 0],
                    }
                  : { x: 0, rotate: 0 }
              }
              transition={
                opening && !reducedMotion
                  ? {
                      duration: 0.6,
                      repeat: Infinity,
                      ease: 'easeInOut',
                    }
                  : { duration: 0.2 }
              }
            >
              <motion.div
                className={styles.lid}
                data-testid="chest-lid"
                data-open={revealed ? 'true' : 'false'}
                animate={
                  revealed
                    ? { rotate: -26, y: -9 }
                    : { rotate: 0, y: 0 }
                }
                transition={
                  reducedMotion
                    ? { duration: 0 }
                    : { duration: 0.7, ease: [0.22, 1, 0.36, 1] }
                }
              >
                <span className={styles.lidBand} />
                <span className={styles.lidLock} />
              </motion.div>
              <div className={styles.base}>
                <span className={styles.baseBand} />
                <span className={styles.baseLock} />
              </div>
            </motion.div>
          </div>

          <AnimatePresence initial={false}>
            {revealed && result ? (
              <motion.div
                key="reward"
                className={styles.reward}
                data-testid="chest-reward"
                role="status"
                initial={
                  reducedMotion
                    ? { opacity: 0 }
                    : { opacity: 0, scale: 0.7, y: 10 }
                }
                animate={{ opacity: 1, scale: 1, y: 0 }}
                transition={
                  reducedMotion
                    ? { duration: 0.18 }
                    : { duration: 0.7, ease: [0.22, 1, 0.36, 1] }
                }
              >
                <span
                  className={styles.rewardIcon}
                  data-reward={result.reward_type}
                >
                  <RewardIcon result={result} />
                </span>
                <span className={styles.rewardLabel}>{rewardText(result)}</span>
              </motion.div>
            ) : null}
          </AnimatePresence>

          {revealed ? (
            <div className={styles.revealActions}>
              <p className={styles.revealHint}>奖励已到账。</p>
              <Dialog.Close asChild>
                <button type="button" className={styles.primary}>
                  收下
                </button>
              </Dialog.Close>
            </div>
          ) : (
            <div className={styles.actions}>
              <p className={styles.hint}>
                {opening ? '正在开启…' : '开启后奖励立刻到账。'}
              </p>
              {error ? (
                <p
                  className={styles.error}
                  role="alert"
                  data-testid="chest-open-error"
                >
                  {error}
                </p>
              ) : null}
              <div className={styles.buttons}>
                <button
                  type="button"
                  className={styles.secondary}
                  onClick={onClose}
                  disabled={opening}
                >
                  取消
                </button>
                <button
                  type="button"
                  className={styles.primary}
                  onClick={() => void handleOpen()}
                  disabled={opening}
                >
                  {opening ? '开启中…' : '开启'}
                </button>
              </div>
            </div>
          )}

          {/* TODO: add chest opening sound when the audio slice lands. */}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export default ChestOpenDialog
