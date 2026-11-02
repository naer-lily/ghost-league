import * as Dialog from '@radix-ui/react-dialog'
import { Clock3, Diamond, X } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { createRequestId, usePlaceBet } from '../api/queries'
import type { Bet, BetWindows, GroupBetOption } from '../api/types'
import {
  betReturn,
  betStatusText,
  describeRivalError,
  formatCountdown,
  formatOdds,
  formatXp,
  groupLocked,
} from '../lib/rival'
import { useUiStore } from '../store/useUiStore'
import styles from './RivalBetDialog.module.css'

interface GroupBetDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  option: GroupBetOption
  bet: Bet | null
  windows: BetWindows
  now: Date
}

export function GroupBetDialog({
  open,
  onOpenChange,
  option,
  bet,
  windows,
  now,
}: GroupBetDialogProps) {
  const titleId = useId()
  const descriptionId = useId()
  const paidInputId = useId()
  const placeBet = usePlaceBet()
  const notify = useUiStore((store) => store.notify)
  const [paidStake, setPaidStake] = useState(option.min_paid_stake)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setError(null)
      setPaidStake(option.min_paid_stake)
    }
  }, [open, option.min_paid_stake])

  const minPaid = option.min_paid_stake
  const maxPaid = option.max_paid_stake
  const freeStake = option.free_stake
  const paid = Math.min(Math.max(paidStake, minPaid), maxPaid)
  const totalStake = freeStake + paid
  const payout = betReturn(totalStake, option.odds)
  const closed = groupLocked(windows, now)
  const submitDisabled = Boolean(bet) || closed || placeBet.isPending

  function handleOpenChange(next: boolean) {
    if (!next) {
      setError(null)
      placeBet.reset()
    }
    onOpenChange(next)
  }

  function setPaid(value: number) {
    if (!Number.isFinite(value)) return
    setPaidStake(Math.min(Math.max(Math.trunc(value), minPaid), maxPaid))
  }

  async function handleSubmit() {
    if (submitDisabled) return
    setError(null)
    try {
      await placeBet.mutateAsync({
        kind: 'group',
        paidStake: paid,
        requestId: createRequestId(),
      })
      handleOpenChange(false)
      notify('组注已下。')
    } catch (submitError) {
      setError(describeRivalError(submitError))
    }
  }

  const submitLabel = bet
    ? '本周已下注'
    : closed
      ? '本周的注已截止'
      : placeBet.isPending
        ? '提交中…'
        : '确认下注'

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={styles.content}
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
          data-testid="group-bet-dialog"
        >
          <div className={styles.head}>
            <div>
              <Dialog.Title id={titleId} className={styles.title}>
                组注
              </Dialog.Title>
              <Dialog.Description
                id={descriptionId}
                className={styles.description}
              >
                押我本人在本组本周排名前三。只看个人本周 XP 排名，和小组总 XP
                无关；每注自带 {freeStake} 免费本金。
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className={styles.close}
                aria-label="关闭组注对话框"
              >
                <X size={20} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </div>

          <div className={styles.panel}>
            <h3 className={styles.panelTitle}>
              押「我本人在本组本周排名前三」
            </h3>
            <div className={styles.summary}>
              <div>
                <span>目标名次</span>
                <strong>前三</strong>
              </div>
              <div>
                <span>赔率</span>
                <strong>×{formatOdds(option.odds)}</strong>
              </div>
              <div>
                <span>免费本金</span>
                <strong>{formatXp(freeStake)}</strong>
              </div>
            </div>

            <div className={styles.stakeBox}>
              <div className={styles.stakeHead}>
                <label htmlFor={paidInputId}>自付钻石</label>
                <span>
                  {minPaid}–{maxPaid}
                </span>
              </div>
              <div className={styles.stakeRow}>
                <input
                  id={paidInputId}
                  className={styles.stakeInput}
                  type="number"
                  inputMode="numeric"
                  min={minPaid}
                  max={maxPaid}
                  step={1}
                  value={paid}
                  disabled={Boolean(bet) || closed}
                  aria-label="自付钻石"
                  data-testid="group-bet-paid-input"
                  onChange={(event) => setPaid(Number(event.target.value))}
                />
                <span className={styles.unit}>钻石</span>
              </div>
              <input
                className={styles.stakeRange}
                type="range"
                min={minPaid}
                max={maxPaid}
                step={1}
                value={paid}
                disabled={Boolean(bet) || closed}
                aria-label="自付钻石滑杆"
                data-testid="group-bet-paid-range"
                onChange={(event) => setPaid(Number(event.target.value))}
              />
              <dl className={styles.stakeGrid}>
                <div>
                  <dt>自付</dt>
                  <dd data-testid="group-bet-paid">{formatXp(paid)}</dd>
                </div>
                <div>
                  <dt>免费</dt>
                  <dd data-testid="group-bet-free">{formatXp(freeStake)}</dd>
                </div>
                <div>
                  <dt>总本金</dt>
                  <dd data-testid="group-bet-stake">{formatXp(totalStake)}</dd>
                </div>
              </dl>
            </div>

            <div className={styles.summary} data-testid="group-bet-summary">
              <div>
                <span>目标名次</span>
                <strong>前三</strong>
              </div>
              <div>
                <span>赔率</span>
                <strong data-testid="group-bet-odds">
                  ×{formatOdds(option.odds)}
                </strong>
              </div>
              <div>
                <span>总返</span>
                <strong data-testid="group-bet-payout">
                  {formatXp(payout)}
                </strong>
              </div>
            </div>

            <p className={styles.deadline}>
              <Clock3 size={14} aria-hidden="true" />
              周一 23:59:59 截止 · 次周一结算
            </p>
            <p className={styles.note}>
              本周剩余 {formatCountdown(windows.weekly_locks_at, now)}
            </p>

            {bet ? (
              <p className={styles.closed} role="status">
                本周组注{betStatusText(bet)}，不能重复提交。
              </p>
            ) : null}

            {closed ? (
              <p className={styles.closed} role="status">
                本周的注已截止
              </p>
            ) : null}

            {error ? (
              <p
                className={styles.error}
                role="alert"
                data-testid="group-bet-error"
              >
                {error}
              </p>
            ) : null}

            <button
              type="button"
              className={styles.submit}
              disabled={submitDisabled}
              onClick={() => void handleSubmit()}
            >
              <Diamond size={17} aria-hidden="true" />
              {submitLabel}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
