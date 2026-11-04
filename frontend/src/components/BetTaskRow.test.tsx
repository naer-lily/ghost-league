import { render, screen, waitFor, within } from '@testing-library/react'
import type { ComponentProps } from 'react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Bet, BetWindows } from '../api/types'
import { BetTaskRow, readBetSnapshot } from './BetTaskRow'
import styles from './BetTaskRow.module.css'

function bet(overrides: Partial<Bet> = {}): Bet {
  return {
    id: 1,
    kind: 'daily',
    period_key: '2026-11-04',
    rival_id: 'ch-rival',
    stake: 120,
    free_stake: 20,
    paid_stake: 100,
    target_margin: 49,
    odds: 2,
    status: 'placed',
    placed_at: '2026-11-04T10:00:00+08:00',
    locked_at: null,
    settled_at: null,
    payout: 0,
    result_diff: null,
    ...overrides,
  }
}

const WINDOWS: BetWindows = {
  weekly_locks_at: '2026-11-09T23:59:59+08:00',
  daily_locks_at: '2026-11-04T21:00:00+08:00',
  daily_settles_at: '2026-11-04T22:30:00+08:00',
}

function renderRow(
  overrides: Partial<ComponentProps<typeof BetTaskRow>> = {},
) {
  const onOpenBets = vi.fn()
  const onToggle = vi.fn()
  const props: ComponentProps<typeof BetTaskRow> = {
    kind: 'daily',
    bet: null,
    meXp: 638,
    rivalXp: 540,
    windows: WINDOWS,
    locked: false,
    now: new Date('2026-11-04T12:00:00+08:00'),
    expanded: false,
    onToggle,
    onOpenBets,
    ...overrides,
  }
  const result = render(<BetTaskRow {...props} />)
  return { ...result, props, onOpenBets, onToggle }
}

describe('BetTaskRow', () => {
  it('renders an unbet row as one full-width button and opens the dialog', async () => {
    const { onOpenBets } = renderRow({ kind: 'weekly' })

    const button = screen.getByRole('button', { name: '周注' })
    expect(button).toBeVisible()
    expect(screen.getByTestId('bet-task-weekly')).toHaveAttribute(
      'data-state',
      'open',
    )
    expect(screen.getByTestId('bet-task-label-weekly')).toHaveTextContent('周注')
    const cutoff = screen.getByTestId('bet-task-cutoff-weekly')
    expect(cutoff).toHaveTextContent('还剩 131 小时 59 分')
    expect(cutoff).toHaveClass(styles.deadline ?? '')
    expect(button).toContainElement(cutoff)
    expect(button).toContainElement(
      screen.getByTestId('bet-task-label-weekly'),
    )
    expect(screen.queryByText(/点击下注/)).not.toBeInTheDocument()
    expect(screen.queryByText(/目标|赔率|本金|总返/)).not.toBeInTheDocument()

    await userEvent.click(button)
    expect(onOpenBets).toHaveBeenCalledWith('weekly')
  })

  it('shows the daily countdown on the open row', () => {
    renderRow({ kind: 'daily' })

    expect(screen.getByTestId('bet-task-label-daily')).toHaveTextContent('日注')
    expect(screen.getByTestId('bet-task-cutoff-daily')).toHaveTextContent(
      '还剩 9 小时 0 分',
    )
  })

  it('shows a locked row with its label and cutoff and no clickable button', () => {
    renderRow({
      kind: 'daily',
      locked: true,
      now: new Date('2026-11-04T21:30:00+08:00'),
    })

    expect(screen.getByTestId('bet-task-locked-daily')).toHaveTextContent('日注')
    const cutoff = screen.getByTestId('bet-task-cutoff-daily')
    expect(cutoff).toHaveTextContent('已到期')
    expect(cutoff).toHaveClass(styles.deadline ?? '')
    expect(
      screen.queryByTestId('bet-task-settle-daily'),
    ).not.toBeInTheDocument()
    expect(screen.queryByText('今天的注已截止')).not.toBeInTheDocument()
    expect(screen.queryByText('本周的注已截止')).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByText(/点击下注/)).not.toBeInTheDocument()
  })

  it('shows the label and daily settlement time above a placed XP row', () => {
    renderRow({ bet: bet(), meXp: 638, rivalXp: 540 })

    expect(screen.getByTestId('bet-task-daily')).toHaveAttribute(
      'data-state',
      'placed',
    )
    expect(screen.getByTestId('bet-task-label-daily')).toHaveTextContent('日注')
    const settlement = screen.getByTestId('bet-task-settle-daily')
    expect(settlement).toHaveTextContent('还剩 10 小时 30 分')
    expect(settlement).toHaveClass(styles.settlement ?? '')
    expect(screen.queryByTestId('bet-task-cutoff-daily')).not.toBeInTheDocument()
    expect(screen.queryByText('还剩 9 小时 0 分')).not.toBeInTheDocument()
    expect(screen.getByTestId('bet-task-me-daily')).toHaveTextContent('638')
    expect(screen.getByTestId('bet-task-rival-daily')).toHaveTextContent('589')
    expect(screen.getByTestId('bet-task-diff-daily')).toHaveTextContent('+49')
    expect(screen.getByTestId('bet-task-bar-daily')).toBeVisible()
  })

  it('settles a live weekly bet at the next Monday 00:05 from its period', () => {
    renderRow({
      kind: 'weekly',
      bet: bet({
        id: 2,
        kind: 'weekly',
        period_key: '2026-11-02',
      }),
    })

    expect(screen.getByTestId('bet-task-label-weekly')).toHaveTextContent('周注')
    expect(screen.getByTestId('bet-task-settle-weekly')).toHaveTextContent(
      '还剩 108 小时 5 分',
    )
    expect(
      screen.queryByTestId('bet-task-cutoff-weekly'),
    ).not.toBeInTheDocument()
  })

  it('uses the real settled clock instead of the window countdown', () => {
    renderRow({
      bet: bet({
        status: 'won',
        result_diff: 49,
        payout: 240,
        settled_at: '2026-11-04T22:41:00+08:00',
      }),
    })

    expect(screen.getByTestId('bet-task-settle-daily')).toHaveTextContent(
      '已结算',
    )
    expect(screen.queryByTestId('bet-task-cutoff-daily')).not.toBeInTheDocument()
    expect(screen.getByTestId('bet-task-result-daily')).toHaveTextContent(
      '已赢 +240',
    )
  })

  it('shows my XP, the opponent XP plus target, and a positive signed diff', () => {
    renderRow({ bet: bet() })

    expect(screen.getByTestId('bet-task-me-daily')).toHaveTextContent('638')
    expect(screen.getByTestId('bet-task-rival-daily')).toHaveTextContent('589')
    const diff = screen.getByTestId('bet-task-diff-daily')
    expect(diff).toHaveTextContent('+49')
    expect(diff).toHaveAttribute('data-tone', 'ahead')
    expect(diff).toHaveClass(styles.ahead ?? '')
    expect(screen.getByTestId('bet-task-bar-daily')).toBeVisible()
    expect(screen.queryByText(/目标|赔率|本金|总返/)).not.toBeInTheDocument()
  })

  it('uses the orange negative tone and the gray even tone without relying on color', () => {
    const { rerender, props } = renderRow({
      bet: bet(),
      meXp: 540,
      rivalXp: 638,
    })

    let diff = screen.getByTestId('bet-task-diff-daily')
    expect(diff).toHaveTextContent('-147')
    expect(diff).toHaveAttribute('data-tone', 'behind')
    expect(diff).toHaveClass(styles.behind ?? '')

    rerender(
      <BetTaskRow
        {...props}
        meXp={700}
        rivalXp={651}
      />,
    )

    diff = screen.getByTestId('bet-task-diff-daily')
    expect(diff).toHaveTextContent('0')
    expect(diff).toHaveAttribute('data-tone', 'even')
    expect(diff).toHaveClass(styles.even ?? '')
  })

  it('expands inline with only the stake/odds, target, return and settlement time', () => {
    renderRow({ bet: bet(), expanded: true })

    const details = screen.getByTestId('bet-task-details-daily')
    expect(details).toHaveTextContent('120 × 2.00')
    expect(details).toHaveTextContent('+49 XP')
    expect(details).toHaveTextContent('240')
    expect(details).toHaveTextContent('2026-11-04 22:30')
    expect(screen.queryByTestId('rival-bet-dialog')).not.toBeInTheDocument()
    expect(within(details).getByText('本金')).toBeVisible()
    expect(within(details).getByText('目标')).toBeVisible()
    expect(within(details).getByText('总返')).toBeVisible()
    expect(within(details).getByText('结算时间')).toBeVisible()
  })

  it('freezes the settled bar on the last live values and shows the result', () => {
    localStorage.clear()
    const settled = bet({
      status: 'won',
      result_diff: 49,
      payout: 240,
      settled_at: '2026-11-04T22:30:00+08:00',
    })
    const { rerender, props } = renderRow({
      bet: bet(),
      meXp: 638,
      rivalXp: 540,
    })

    expect(screen.getByTestId('bet-task-me-daily')).toHaveTextContent('638')

    rerender(
      <BetTaskRow
        {...props}
        bet={settled}
        meXp={9999}
        rivalXp={-400}
      />,
    )

    expect(screen.getByTestId('bet-task-daily')).toHaveAttribute(
      'data-state',
      'settled',
    )
    expect(screen.getByTestId('bet-task-daily')).toHaveAttribute(
      'data-frozen',
      'true',
    )
    expect(screen.getByTestId('bet-task-me-daily')).toHaveTextContent('638')
    expect(screen.getByTestId('bet-task-rival-daily')).toHaveTextContent('589')
    expect(screen.getByTestId('bet-task-diff-daily')).toHaveTextContent('+49')
    expect(screen.getByTestId('bet-task-result-daily')).toHaveTextContent(
      '已赢 +240',
    )
  })

  it('uses the caller supplied frozen sides when the weekly result is known', () => {
    localStorage.clear()
    renderRow({
      kind: 'weekly',
      bet: bet({
        id: 7,
        kind: 'weekly',
        status: 'lost',
        result_diff: -49,
        settled_at: '2026-11-09T00:05:00+08:00',
      }),
      meXp: 9000,
      rivalXp: 100,
      snapshot: { me: 638, rival: 687 },
    })

    expect(screen.getByTestId('bet-task-me-weekly')).toHaveTextContent('638')
    expect(screen.getByTestId('bet-task-rival-weekly')).toHaveTextContent('687')
    expect(screen.getByTestId('bet-task-diff-weekly')).toHaveTextContent('-49')
    expect(screen.getByTestId('bet-task-settle-weekly')).toHaveTextContent(
      '已结算',
    )
    expect(screen.getByTestId('bet-task-result-weekly')).toHaveTextContent(
      '已输',
    )
  })

  it('persists the last live sides so a remounted settled row stays frozen', async () => {
    localStorage.clear()
    const live = bet({ id: 11 })
    const first = renderRow({
      bet: live,
      meXp: 638,
      rivalXp: 540,
    })

    await waitFor(() =>
      expect(readBetSnapshot('daily', 11)).toEqual({ me: 638, rival: 589 }),
    )
    first.unmount()

    renderRow({
      bet: { ...live, status: 'won', result_diff: 49, payout: 240 },
      meXp: 700,
      rivalXp: 620,
    })

    expect(screen.getByTestId('bet-task-me-daily')).toHaveTextContent('638')
    expect(screen.getByTestId('bet-task-rival-daily')).toHaveTextContent('589')
  })
})
