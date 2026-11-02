import * as Dialog from '@radix-ui/react-dialog'
import { Clock3, Diamond, X } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { createRequestId, usePlaceBet } from '../api/queries'
import type { BetWindows, GroupMarketOption } from '../api/types'
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
  option: GroupMarketOption
  windows: BetWindows
  now: Date
}

export function GroupBetDialog({
  open,
  onOpenChange,
  option,
  windows,
  now,
}: GroupBetDialogProps) {
  const titleId = useId()
  const descriptionId = useId()
  const paidInputId = useId()
  const placeBet = usePlaceBet()
  const notify = useUiStore((store) => store.notify)
  const [paidStake, setPaidStake] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setError(null)
      setPaidStake(0)
    }
  }, [open])

  const minPaid = 0
  const maxPaid = 500
  const freeStake = 20
  const paid = Math.min(Math.max(paidStake, minPaid), maxPaid)
  const totalStake = freeStake + paid
  const odds = option.odds ?? 0
  const payout = betReturn(totalStake, odds)
  const closed = groupLocked(windows, now)
  const bet = option.bet
  const submitDisabled = Boolean(bet) || closed || !option.can_place || placeBet.isPending

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
        market: option.market,
        paidStake: paid,
        requestId: createRequestId(),
      })
      handleOpenChange(false)
      notify(`${option.label}已下。`)
    } catch (submitError) {
      setError(describeRivalError(submitError))
    }
  }

  const submitLabel = bet
    ? '本期已下注'
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
          data-market={option.market}
        >
          <div className={styles.head}>
            <div>
              <Dialog.Title id={titleId} className={styles.title}>
                {option.label}
              </Dialog.Title>
              <Dialog.Description
                id={descriptionId}
                className="visually-hidden"
              >
                {option.label}，赔率以服务端为准。
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className={styles.close}
                aria-label={`关闭${option.label}对话框`}
              >
                <X size={20} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </div>

          <div className={styles.panel}>
            <div className={styles.summary}>
              <div>
                <span>赔率</span>
                <strong data-testid="group-bet-odds">
                  ×{formatOdds(odds)}
                </strong>
              </div>
              <div>
                <span>免费本金</span>
                <strong>{formatXp(freeStake)}</strong>
              </div>
              <div>
                <span>状态</span>
                <strong>{bet ? betStatusText(bet) : '未下注'}</strong>
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
                <span>盘口</span>
                <strong>{option.label}</strong>
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
                {option.label}
                {betStatusText(bet)}，不能重复提交。
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
