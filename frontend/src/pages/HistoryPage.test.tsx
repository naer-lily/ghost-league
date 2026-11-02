import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type { HistoryItem } from '../api/types'
import { formatAbsoluteTime } from '../lib/time'
import { HistoryPage } from './HistoryPage'

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString()
}

function historyItem(
  id: string,
  type: HistoryItem['type'],
  overrides: Partial<HistoryItem> = {},
): HistoryItem {
  return {
    id,
    type,
    at: minutesAgo(10),
    title: '标题',
    body: '正文',
    data: {},
    ...overrides,
  }
}

const ITEMS: HistoryItem[] = [
  historyItem('checkin:2026-11-02', 'checkin', {
    at: minutesAgo(5),
    title: '打卡',
    body: '画画 · 画了一张速写',
    data: { date: '2026-11-02', domain: '画画', content: '画了一张速写' },
  }),
  historyItem('bet:1', 'bet', {
    at: minutesAgo(20),
    title: '下注',
    body: '周注 · 目标 +150 XP · 赔率 ×2 · 已赢 · 派彩 600',
  }),
  historyItem('group_bet:2', 'group_bet', {
    at: minutesAgo(30),
    title: '押升段',
    body: '组内第 3 名 · 赔率 ×4.19 · 已赢 · 派彩 440',
    data: { market: 'promote', market_label: '押升段', target_rank: 4 },
  }),
  historyItem('rival:2026-10-19', 'rival', {
    at: minutesAgo(60),
    title: '宿敌',
    body: '我 1,200 XP · 宿敌 900 XP · 获胜 · 奖励 120 钻石',
  }),
  historyItem('star:star-1', 'star', {
    at: minutesAgo(120),
    title: '星星',
    body: '霜蓝 · 蓝白星 · 耀星',
  }),
  historyItem('week:2026-10-19', 'week', {
    at: minutesAgo(180),
    title: '周结算',
    body: 'Bronze · 第 3 名 · 4,200 XP · 晋级 · 干净打卡 5 天',
  }),
]

function historyPayload(items: HistoryItem[]) {
  return {
    user_id: 'naer-lily',
    generated_at: new Date().toISOString(),
    limit: 100,
    items,
  }
}

function renderHistory() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { gcTime: 0, retry: false, refetchOnWindowFocus: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <HistoryPage />
    </QueryClientProvider>,
  )
}

describe('HistoryPage', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the timeline with relative and absolute times', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => response(historyPayload(ITEMS))),
    )

    renderHistory()

    const list = await screen.findByRole('list', { name: '历史时间线' })
    const rows = within(list).getAllByTestId('history-item')
    expect(rows).toHaveLength(6)
    expect(screen.getByTestId('history-count')).toHaveTextContent('全部 6 条')
    expect(rows[0]).toHaveTextContent('画画 · 画了一张速写')
    expect(rows[0]).toHaveTextContent('5 分钟前')
    expect(rows[0]).toHaveTextContent(formatAbsoluteTime(ITEMS[0]!.at))
    expect(rows[0]).not.toHaveTextContent(ITEMS[0]!.at)
    expect(rows[2]).toHaveTextContent('押升段')
    expect(within(rows[2]!).getByTestId('history-market')).toHaveTextContent(
      '升段',
    )
    expect(screen.queryByText('还没有历史记录')).not.toBeInTheDocument()
  })

  it('filters by chip and treats group bets as bets', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => response(historyPayload(ITEMS))),
    )

    renderHistory()
    await screen.findByRole('list', { name: '历史时间线' })

    await user.click(screen.getByTestId('history-filter-checkin'))
    expect(screen.getByTestId('history-count')).toHaveTextContent(
      '打卡 1 条 / 全部 6 条',
    )
    expect(screen.getAllByTestId('history-item')).toHaveLength(1)
    expect(screen.getByTestId('history-filter-checkin')).toHaveAttribute(
      'aria-pressed',
      'true',
    )

    await user.click(screen.getByTestId('history-filter-bet'))
    expect(screen.getByTestId('history-count')).toHaveTextContent(
      '下注 2 条 / 全部 6 条',
    )
    expect(screen.getAllByTestId('history-item')).toHaveLength(2)

    await user.click(screen.getByTestId('history-filter-star'))
    expect(screen.getByTestId('history-count')).toHaveTextContent(
      '星星 1 条 / 全部 6 条',
    )
    expect(screen.getAllByTestId('history-item')).toHaveLength(1)
  })

  it('shows a real empty state without sample records', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => response(historyPayload([]))),
    )

    renderHistory()

    expect(await screen.findByTestId('history-empty')).toHaveTextContent(
      '还没有历史记录',
    )
    expect(screen.getByTestId('history-count')).toHaveTextContent('全部 0 条')
    expect(screen.queryByTestId('history-item')).not.toBeInTheDocument()
  })

  it('shows the error and retries the real request', async () => {
    const user = userEvent.setup()
    let calls = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        calls += 1
        if (calls <= 2) return response({ detail: '服务暂时不可用' }, 500)
        return response(historyPayload(ITEMS))
      }),
    )

    renderHistory()

    expect(
      await screen.findByRole('alert', {}, { timeout: 3_000 }),
    ).toHaveTextContent('服务暂时不可用')
    await user.click(screen.getByRole('button', { name: '重试' }))

    await waitFor(() =>
      expect(screen.getByRole('list', { name: '历史时间线' })).toBeVisible(),
    )
    expect(screen.getAllByTestId('history-item')).toHaveLength(6)
  })
})
