import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { tierMeta } from '../lib/home'
import { TodayProgress } from './TodayProgress'

const NOW = new Date('2026-10-31T09:10:00+08:00')
const RECENT = '2026-10-31T09:05:00+08:00'
const STALE = '2026-10-31T07:55:00+08:00'

function renderProgress(overrides: {
  todayXp?: number
  todaySeconds?: number
  updatedAt?: string
  now?: Date
} = {}) {
  return render(
    <TodayProgress
      todayXp={overrides.todayXp ?? 129}
      todaySeconds={overrides.todaySeconds ?? 779}
      updatedAt={overrides.updatedAt ?? RECENT}
      tier={tierMeta('Bronze')}
      now={overrides.now ?? NOW}
    />,
  )
}

describe('TodayProgress', () => {
  it('renders six tiers, XP/minutes stats and a real relative update label', () => {
    renderProgress()

    expect(screen.getByRole('heading', { name: '今日进度' })).toBeVisible()
    expect(screen.getByText('今日 XP')).toBeVisible()
    expect(screen.getByText('今日分钟')).toBeVisible()
    expect(screen.getByText('129')).toBeVisible()
    expect(screen.getByText('12')).toBeVisible()
    expect(screen.queryByTestId('today-current-tier')).not.toBeInTheDocument()
    expect(screen.getByTestId('today-remaining')).toHaveTextContent(
      '还差 171 XP',
    )

    const tiers = screen.getAllByTestId('today-tier')
    expect(tiers).toHaveLength(6)
    expect(tiers.map((tier) => tier.textContent)).toEqual([
      '10分钟',
      '30分钟',
      '60分钟',
      '120分钟',
      '180分钟',
      '240分钟',
    ])
    expect(tiers.map((tier) => tier.getAttribute('data-state'))).toEqual([
      'complete',
      'current',
      'future',
      'future',
      'future',
      'future',
    ])

    const marker = screen.getByTestId('recent-update')
    expect(marker).toHaveTextContent('5 分钟前更新')
    expect(marker).toHaveAttribute('aria-label', '最近 1 小时内有 XP 更新')

    const bar = screen.getByRole('progressbar', { name: '今日 XP 目标' })
    expect(bar).toHaveAttribute('aria-valuemin', '0')
    expect(bar).toHaveAttribute('aria-valuemax', '2400')
    expect(bar).toHaveAttribute('aria-valuenow', '129')
    expect(bar).toHaveAttribute('aria-valuetext', '129 XP，还差 171 XP')
    expect(bar).toHaveAttribute('data-progress', '0.1908')
    expect(screen.getByTestId('today-progress-fill')).toBeInTheDocument()
    expect(document.querySelectorAll('[class*="card"]')).toHaveLength(0)
  })

  it('uses "刚刚更新" only inside the first minute', () => {
    renderProgress({ updatedAt: '2026-10-31T09:09:40+08:00' })

    expect(screen.getByTestId('recent-update')).toHaveTextContent('刚刚更新')
  })

  it('hides the marker when the real last activity is over one hour old', () => {
    renderProgress({ updatedAt: STALE })

    expect(screen.queryByTestId('recent-update')).not.toBeInTheDocument()
    expect(screen.getByText('还差 171 XP')).toBeVisible()
  })

  it('never fakes freshness when the API has no activity timestamp', () => {
    renderProgress({ updatedAt: '' })

    expect(screen.queryByTestId('recent-update')).not.toBeInTheDocument()
  })

  it('recomputes the relative label from the polling timestamp', () => {
    const { rerender } = renderProgress({
      todayXp: 100,
      todaySeconds: 600,
      updatedAt: STALE,
    })
    expect(screen.queryByTestId('recent-update')).not.toBeInTheDocument()

    rerender(
      <TodayProgress
        todayXp={129}
        todaySeconds={779}
        updatedAt="2026-10-31T09:05:00+08:00"
        tier={tierMeta('Bronze')}
        now={NOW}
      />,
    )
    expect(screen.getByTestId('recent-update')).toHaveTextContent('5 分钟前更新')

    rerender(
      <TodayProgress
        todayXp={129}
        todaySeconds={779}
        updatedAt="2026-10-31T09:05:00+08:00"
        tier={tierMeta('Bronze')}
        now={new Date('2026-10-31T10:06:00+08:00')}
      />,
    )
    expect(screen.queryByTestId('recent-update')).not.toBeInTheDocument()
  })

  it('starts at tier one with zero progress', () => {
    renderProgress({ todayXp: 0, todaySeconds: 0 })

    expect(screen.getByTestId('today-remaining')).toHaveTextContent(
      '还差 100 XP',
    )
    const bar = screen.getByRole('progressbar', { name: '今日 XP 目标' })
    expect(bar).toHaveAttribute('aria-valuenow', '0')
    expect(bar).toHaveAttribute('data-progress', '0.0000')
    expect(screen.getAllByTestId('today-tier')[0]).toHaveAttribute(
      'data-state',
      'current',
    )
  })

  it('shows an all-complete state without inventing another tier', () => {
    renderProgress({ todayXp: 2500, todaySeconds: 15_000 })

    expect(screen.getByTestId('today-remaining')).toHaveTextContent(
      '六档全部达成',
    )
    const bar = screen.getByRole('progressbar', { name: '今日 XP 目标' })
    expect(bar).toHaveAttribute('aria-valuenow', '2400')
    expect(bar).toHaveAttribute('data-progress', '1.0000')
    expect(
      screen
        .getAllByTestId('today-tier')
        .every((tier) => tier.getAttribute('data-state') === 'complete'),
    ).toBe(true)
  })
})
