import * as Dialog from '@radix-ui/react-dialog'
import { Clock3, Diamond, X } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import {
  createRequestId,
  useBets,
  usePlaceBet,
  type PlaceBetVariables,
} from '../api/queries'
import type { Bet, BetWindows, RivalState } from '../api/types'
import {
  BET_TABS,
  betKindLabel,
  betStatusText,
  dailyLine,
  dailyLocked,
  describeRivalError,
  formatCountdown,
  formatXp,
  isPast,
  type BetTab,
} from '../lib/rival'
import { useUiStore } from '../store/useUiStore'
import styles from './RivalBetDialog.module.css'

const WEEKLY_STAKES = [20, 40, 60] as const
const DAILY_TARGETS = [50, 150, 300] as const
const DAILY_PAYOUTS: Record<number, number> = { 50: 30, 150: 50, 300: 80 }

function freeStake(stake: number): number {
  return Math.min(20, stake)
}

function paidStake(stake: number): number {
  return stake - freeStake(stake)
}

function payout(stake: number): number {
  return stake * 2
}

interface StakeOptionProps {
  stake: number
  selected: boolean
  disabled: boolean
  onSelect: () => void
}

function StakeOption({
  stake,
  selected,
  disabled,
  onSelect,
}: StakeOptionProps) {
  return (
    <button
      type="button"
      className={[
        styles.option,
        selected ? styles.optionSelected : '',
      ]
        .filter(Boolean)
        .join(' ')}
      aria-pressed={selected}
      disabled={disabled}
      onClick={onSelect}
    >
      <span className={styles.optionTitle}>押 {stake}</span>
      <span className={styles.optionLine}>自付 {paidStake(stake)}</span>
      <span className={styles.optionReturn}>总返 {payout(stake)}</span>
    </button>
  )
}

interface DailyOptionProps {
  target: number
  selected: boolean
  disabled: boolean
  line: number | null
  onSelect: () => void
}

function DailyOption({
  target,
  selected,
  disabled,
  line,
  onSelect,
}: DailyOptionProps) {
  return (
    <button
      type="button"
      className={[
        styles.option,
        selected ? styles.optionSelected : '',
      ]
        .filter(Boolean)
        .join(' ')}
      aria-pressed={selected}
      disabled={disabled}
      onClick={onSelect}
    >
      <span className={styles.optionTitle}>+{target} XP</span>
      <span className={styles.optionLine}>
        预计线 {line === null ? '—' : formatXp(line)} XP
      </span>
      <span className={styles.optionReturn}>
        总返 {DAILY_PAYOUTS[target] ?? 0}
      </span>
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
        <span className={styles.placedBadge}>
          {betStatusText(bet)}
        </span>
        <span className={styles.placedKind}>{betKindLabel(bet.kind)}</span>
      </div>
      <dl className={styles.placedGrid}>
        <div>
          <dt>本金</dt>
          <dd>{formatXp(bet.stake)}</dd>
        </div>
        <div>
          <dt>免费</dt>
          <dd>{formatXp(bet.free_stake)}</dd>
        </div>
        <div>
          <dt>自付</dt>
          <dd>{formatXp(bet.paid_stake)}</dd>
        </div>
        <div>
          <dt>总返</dt>
          <dd>{formatXp(Math.round(bet.stake * bet.odds))}</dd>
        </div>
      </dl>
      {bet.kind === 'daily' ? (
        <p className={styles.placedCopy}>
          目标 +{formatXp(bet.target_margin)} XP · 09:00 锁注 · 10:30 结算
        </p>
      ) : (
        <p className={styles.placedCopy}>
          周期 {bet.period_key} · 周一 23:59 截止 · 次周一结算
        </p>
      )}
      <p className={styles.placedCopy}>本周期已经下过，不能重复提交。</p>
    </div>
  )
}

function closedCopy(kind: BetTab, windows: BetWindows, now: Date): string | null {
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
}

export function RivalBetDialog({
  open,
  onOpenChange,
  state,
  now,
}: RivalBetDialogProps) {
  const titleId = useId()
  const descriptionId = useId()
  const betsQuery = useBets(open)
  const placeBet = usePlaceBet()
  const notify = useUiStore((store) => store.notify)
  const [tab, setTab] = useState<BetTab>('weekly')
  const [weeklyStake, setWeeklyStake] = useState(20)
  const [dailyTarget, setDailyTarget] = useState(50)
  const [groupStake, setGroupStake] = useState(20)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) setError(null)
  }, [open])

  const bets = betsQuery.data?.bets ?? state.bets
  const windows = betsQuery.data?.bet_windows ?? state.bet_windows
  const projection = state.projection
  const currentBet = bets[tab]
  const closed = closedCopy(tab, windows, now)
  const submitDisabled =
    Boolean(currentBet) || Boolean(closed) || placeBet.isPending

  function handleOpenChange(next: boolean) {
    if (!next) {
      setError(null)
      placeBet.reset()
    }
    onOpenChange(next)
  }

  async function handleSubmit() {
    if (submitDisabled) return
    setError(null)
    const requestId = createRequestId()
    let variables: PlaceBetVariables
    if (tab === 'daily') {
      variables = {
        kind: 'daily',
        targetMargin: dailyTarget,
        requestId,
      }
    } else if (tab === 'weekly') {
      variables = { kind: 'weekly', stake: weeklyStake, requestId }
    } else {
      variables = { kind: 'group', stake: groupStake, requestId }
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
        : tab === 'daily'
          ? '押 20 下注'
          : `押 ${tab === 'weekly' ? weeklyStake : groupStake} 下注`

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
                className={styles.description}
              >
                本周宿敌：{state.rival?.display_name ?? '—'}。每注自带 20
                免费本金，只按自付部分扣钻石。
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

          <div
            className={styles.tabs}
            role="tablist"
            aria-label="下注类型"
          >
            {BET_TABS.map((item) => {
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
                  className={[
                    styles.tab,
                    active ? styles.tabActive : '',
                  ]
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

          <div
            className={styles.panel}
            role="tabpanel"
            id={`rival-bet-panel-${tab}`}
            aria-labelledby={`rival-bet-tab-${tab}`}
          >
            {betsQuery.isFetching ? (
              <p className={styles.sync} aria-live="polite">
                正在同步下注状态…
              </p>
            ) : null}

            {tab === 'weekly' ? (
              <>
                <h3 className={styles.panelTitle}>押「我本周 XP 高于宿敌」</h3>
                <div className={styles.projection}>
                  <span>预计达成线</span>
                  <strong data-testid="rival-weekly-line">
                    {projection
                      ? `${formatXp(projection.week_line)} XP`
                      : '—'}
                  </strong>
                </div>
                <div className={styles.options}>
                  {WEEKLY_STAKES.map((stake) => (
                    <StakeOption
                      key={stake}
                      stake={stake}
                      selected={weeklyStake === stake}
                      disabled={Boolean(currentBet) || Boolean(closed)}
                      onSelect={() => setWeeklyStake(stake)}
                    />
                  ))}
                </div>
                <p className={styles.deadline}>
                  <Clock3 size={14} aria-hidden="true" />
                  周一 23:59 截止 · 总返 2 倍
                </p>
              </>
            ) : null}

            {tab === 'daily' ? (
              <>
                <h3 className={styles.panelTitle}>押「今天我比宿敌多多少 XP」</h3>
                <p className={styles.targetCopy}>
                  固定本金 20 · 免费 20 · 自付 0
                </p>
                <div className={styles.options}>
                  {DAILY_TARGETS.map((target) => (
                    <DailyOption
                      key={target}
                      target={target}
                      selected={dailyTarget === target}
                      disabled={Boolean(currentBet) || Boolean(closed)}
                      line={dailyLine(projection?.daily_lines, target)}
                      onSelect={() => setDailyTarget(target)}
                    />
                  ))}
                </div>
                <p className={styles.deadline}>
                  <Clock3 size={14} aria-hidden="true" />
                  09:00 锁注 · 10:30 结算
                </p>
              </>
            ) : null}

            {tab === 'group' ? (
              <>
                <h3 className={styles.panelTitle}>
                  押「我们组本周在本 tier 进前三」
                </h3>
                <p className={styles.targetCopy}>
                  与个人宿敌注分开记录，可以同时存在。
                </p>
                <div className={styles.options}>
                  {WEEKLY_STAKES.map((stake) => (
                    <StakeOption
                      key={stake}
                      stake={stake}
                      selected={groupStake === stake}
                      disabled={Boolean(currentBet) || Boolean(closed)}
                      onSelect={() => setGroupStake(stake)}
                    />
                  ))}
                </div>
                <p className={styles.deadline}>
                  <Clock3 size={14} aria-hidden="true" />
                  周一 23:59 截止 · 总返 2 倍
                </p>
              </>
            ) : null}

            {currentBet ? <PlacedBet bet={currentBet} /> : null}

            {closed ? (
              <p className={styles.closed} role="status">
                {closed}
              </p>
            ) : null}

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

            <p className={styles.note}>
              免费 20 只覆盖这一注的前 20：押 20 自付 0、押 40 自付 20、押
              60 自付 40。
            </p>
            <p className={styles.note}>
              本周剩余 {formatCountdown(windows.weekly_locks_at, now)} · 日注锁注{' '}
              {formatCountdown(windows.daily_locks_at, now)}
            </p>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
