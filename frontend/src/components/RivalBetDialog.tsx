import * as Dialog from '@radix-ui/react-dialog'
import { Clock3, Diamond, X } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import {
  createRequestId,
  useBets,
  usePlaceBet,
  type PlaceBetVariables,
} from '../api/queries'
import type {
  Bet,
  BetWindows,
  RivalBetOption,
  RivalState,
} from '../api/types'
import {
  BET_TABS,
  betKindLabel,
  betReturn,
  betStatusText,
  dailyLocked,
  describeRivalError,
  formatOdds,
  formatXp,
  isPast,
  type RivalBetTab,
} from '../lib/rival'
import { useUiStore } from '../store/useUiStore'
import styles from './RivalBetDialog.module.css'

const DEFAULT_FREE_STAKE = 20
const DEFAULT_MAX_PAID = 500

interface TargetOptionButtonProps {
  margin: number
  odds: number
  selected: boolean
  disabled: boolean
  onSelect: () => void
}

function TargetOptionButton({
  margin,
  odds,
  selected,
  disabled,
  onSelect,
}: TargetOptionButtonProps) {
  return (
    <button
      type="button"
      className={[styles.option, selected ? styles.optionSelected : '']
        .filter(Boolean)
        .join(' ')}
      aria-pressed={selected}
      disabled={disabled}
      data-testid={`rival-target-${margin}`}
      onClick={onSelect}
    >
      <span className={styles.optionTitle}>+{formatXp(margin)} XP</span>
      <span className={styles.optionLine}>赔率 ×{formatOdds(odds)}</span>
    </button>
  )
}

interface PlacedBetProps {
  bet: Bet
}

function PlacedBet({ bet }: PlacedBetProps) {
  return (
    <div className={styles.placed} data-testid="rival-bet-placed">
      <div className={styles.placedHead}>
        <span className={styles.placedBadge}>{betStatusText(bet)}</span>
        <span className={styles.placedKind}>{betKindLabel(bet.kind)}</span>
      </div>
      <dl className={styles.placedGrid}>
        <div>
          <dt>目标</dt>
          <dd>+{formatXp(bet.target_margin)} XP</dd>
        </div>
        <div>
          <dt>赔率</dt>
          <dd>×{formatOdds(bet.odds)}</dd>
        </div>
        <div>
          <dt>自付</dt>
          <dd>{formatXp(bet.paid_stake)}</dd>
        </div>
        <div>
          <dt>免费</dt>
          <dd>{formatXp(bet.free_stake)}</dd>
        </div>
        <div>
          <dt>总本金</dt>
          <dd>{formatXp(bet.stake)}</dd>
        </div>
        <div>
          <dt>总返</dt>
          <dd>{formatXp(betReturn(bet.stake, bet.odds))}</dd>
        </div>
      </dl>
      {bet.kind === 'daily' ? (
        <p className={styles.placedCopy}>
          当天 {bet.period_key} · 21:00 锁注 · 22:30 结算
        </p>
      ) : (
        <p className={styles.placedCopy}>
          周期 {bet.period_key} · 周一 23:59:59 截止 · 次周一结算
        </p>
      )}
    </div>
  )
}

function closedCopy(
  kind: RivalBetTab,
  windows: BetWindows,
  now: Date,
): string | null {
  if (kind === 'daily') {
    return dailyLocked(windows, now) ? '今天的注已截止' : null
  }
  return isPast(windows.weekly_locks_at, now) ? '本周的注已截止' : null
}

interface RivalBetDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  state: RivalState
  now: Date
  /** Open on this tab; the rival page uses weekly. */
  initialTab?: RivalBetTab
  /** Lock the dialog to one kind, used by the home daily-only entry. */
  onlyKind?: RivalBetTab
}

export function RivalBetDialog({
  open,
  onOpenChange,
  state,
  now,
  initialTab,
  onlyKind,
}: RivalBetDialogProps) {
  const titleId = useId()
  const descriptionId = useId()
  const paidInputId = useId()
  const betsQuery = useBets(open)
  const placeBet = usePlaceBet()
  const notify = useUiStore((store) => store.notify)
  const [tab, setTab] = useState<RivalBetTab>(
    onlyKind ?? initialTab ?? 'weekly',
  )
  const [targets, setTargets] = useState<Record<RivalBetTab, number>>({
    weekly: 0,
    daily: 0,
  })
  const [paidStakes, setPaidStakes] = useState<Record<RivalBetTab, number>>({
    weekly: 0,
    daily: 0,
  })
  const [error, setError] = useState<string | null>(null)

  const tabs = onlyKind
    ? BET_TABS.filter((item) => item.kind === onlyKind)
    : BET_TABS

  useEffect(() => {
    if (!open) return
    setError(null)
    setTab(onlyKind ?? initialTab ?? 'weekly')
  }, [open, onlyKind, initialTab])

  const bets = betsQuery.data?.bets ?? state.bets
  const betOptions = betsQuery.data?.bet_options ?? state.bet_options
  const windows = betsQuery.data?.bet_windows ?? state.bet_windows
  const currentBet = bets[tab]
  const option: RivalBetOption | null = betOptions[tab]
  const closed = closedCopy(tab, windows, now)
  const optionTargets = option?.target_options ?? []
  const selectedTarget =
    optionTargets.find((entry) => entry.margin === targets[tab]) ??
    optionTargets[0] ??
    null

  useEffect(() => {
    if (!open || !option) return
    const first = option.target_options[0]
    if (!first) return
    setTargets((current) => {
      if (
        option.target_options.some((entry) => entry.margin === current[tab])
      ) {
        return current
      }
      return { ...current, [tab]: first.margin }
    })
  }, [open, tab, option])

  const freeStake = option?.free_stake ?? DEFAULT_FREE_STAKE
  const minPaid = option?.min_paid_stake ?? 0
  const maxPaid = option?.max_paid_stake ?? DEFAULT_MAX_PAID
  const paidStake = Math.min(Math.max(paidStakes[tab], minPaid), maxPaid)
  const totalStake = freeStake + paidStake
  const payout = selectedTarget ? betReturn(totalStake, selectedTarget.odds) : 0
  const submitDisabled =
    Boolean(currentBet) ||
    Boolean(closed) ||
    !option ||
    !selectedTarget ||
    placeBet.isPending

  function handleOpenChange(next: boolean) {
    if (!next) {
      setError(null)
      placeBet.reset()
    }
    onOpenChange(next)
  }

  function setPaid(value: number) {
    if (!Number.isFinite(value)) return
    const next = Math.min(Math.max(Math.trunc(value), minPaid), maxPaid)
    setPaidStakes((current) => ({ ...current, [tab]: next }))
  }

  async function handleSubmit() {
    if (submitDisabled || !selectedTarget) return
    setError(null)
    const variables: PlaceBetVariables = {
      kind: tab,
      paidStake,
      targetMargin: selectedTarget.margin,
      requestId: createRequestId(),
    }
    try {
      await placeBet.mutateAsync(variables)
      handleOpenChange(false)
      notify(`${betKindLabel(tab)}已下。`)
    } catch (submitError) {
      setError(describeRivalError(submitError))
    }
  }

  const submitLabel = currentBet
    ? '本期已下注'
    : closed
      ? closed
      : placeBet.isPending
        ? '提交中…'
        : '确认下注'

  const isDaily = tab === 'daily'
  const lockedTab = onlyKind ?? null

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={styles.content}
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
          data-testid="rival-bet-dialog"
        >
          <div className={styles.head}>
            <div>
              <Dialog.Title id={titleId} className={styles.title}>
                下注
              </Dialog.Title>
              <Dialog.Description
                id={descriptionId}
                className="visually-hidden"
              >
                下注对话框
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className={styles.close}
                aria-label="关闭下注对话框"
              >
                <X size={20} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </div>

          {lockedTab ? null : (
            <div className={styles.tabs} role="tablist" aria-label="下注类型">
              {tabs.map((item) => {
                const active = item.kind === tab
                const placed = Boolean(bets[item.kind])
                return (
                  <button
                    key={item.kind}
                    type="button"
                    role="tab"
                    id={`rival-bet-tab-${item.kind}`}
                    aria-selected={active}
                    aria-controls={`rival-bet-panel-${item.kind}`}
                    tabIndex={active ? 0 : -1}
                    className={[styles.tab, active ? styles.tabActive : '']
                      .filter(Boolean)
                      .join(' ')}
                    onClick={() => {
                      setTab(item.kind)
                      setError(null)
                    }}
                  >
                    <span>{item.label}</span>
                    {placed ? (
                      <span className={styles.tabDot} aria-label="已下注" />
                    ) : null}
                  </button>
                )
              })}
            </div>
          )}

          <div
            className={styles.panel}
            role="tabpanel"
            id={`rival-bet-panel-${tab}`}
            aria-labelledby={
              lockedTab ? undefined : `rival-bet-tab-${tab}`
            }
            data-kind={tab}
          >
            {betsQuery.isFetching ? (
              <p className={styles.sync} aria-live="polite">
                正在同步下注状态…
              </p>
            ) : null}

            <h3 className={styles.panelTitle}>
              {isDaily
                ? '押「今天我比宿敌多多少 XP」'
                : '押「我本周最终 XP 比宿敌高多少」'}
            </h3>

            {option ? (
              <>
                <div className={styles.options}>
                  {option.target_options.map((entry) => (
                    <TargetOptionButton
                      key={entry.margin}
                      margin={entry.margin}
                      odds={entry.odds}
                      selected={entry.margin === selectedTarget?.margin}
                      disabled={Boolean(currentBet) || Boolean(closed)}
                      onSelect={() => {
                        setTargets((current) => ({
                          ...current,
                          [tab]: entry.margin,
                        }))
                        setError(null)
                      }}
                    />
                  ))}
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
                      value={paidStake}
                      disabled={Boolean(currentBet) || Boolean(closed)}
                      aria-label="自付钻石"
                      data-testid="rival-bet-paid-input"
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
                    value={paidStake}
                    disabled={Boolean(currentBet) || Boolean(closed)}
                    aria-label="自付钻石滑杆"
                    data-testid="rival-bet-paid-range"
                    onChange={(event) => setPaid(Number(event.target.value))}
                  />
                  <dl className={styles.stakeGrid}>
                    <div>
                      <dt>自付</dt>
                      <dd data-testid="rival-bet-paid">
                        {formatXp(paidStake)}
                      </dd>
                    </div>
                    <div>
                      <dt>免费</dt>
                      <dd data-testid="rival-bet-free">
                        {formatXp(freeStake)}
                      </dd>
                    </div>
                    <div>
                      <dt>总本金</dt>
                      <dd data-testid="rival-bet-stake">
                        {formatXp(totalStake)}
                      </dd>
                    </div>
                  </dl>
                </div>

                <div className={styles.summary} data-testid="rival-bet-summary">
                  <div>
                    <span>目标</span>
                    <strong data-testid="rival-bet-target">
                      {selectedTarget
                        ? `+${formatXp(selectedTarget.margin)} XP`
                        : '—'}
                    </strong>
                  </div>
                  <div>
                    <span>赔率</span>
                    <strong data-testid="rival-bet-odds">
                      {selectedTarget
                        ? `×${formatOdds(selectedTarget.odds)}`
                        : '—'}
                    </strong>
                  </div>
                  <div>
                    <span>总返</span>
                    <strong data-testid="rival-bet-payout">
                      {selectedTarget ? formatXp(payout) : '—'}
                    </strong>
                  </div>
                </div>
              </>
            ) : (
              <p className={styles.hint} role="status">
                当前没有可用的下注档位。
              </p>
            )}

            <p className={styles.deadline}>
              <Clock3 size={14} aria-hidden="true" />
              {isDaily
                ? '21:00 锁注 · 22:30 结算'
                : '周一 23:59:59 截止 · 次周一结算'}
            </p>

            {currentBet ? <PlacedBet bet={currentBet} /> : null}

            {error ? (
              <p
                className={styles.error}
                role="alert"
                data-testid="rival-bet-error"
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
