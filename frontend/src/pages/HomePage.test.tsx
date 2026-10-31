import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import { makeSnapshot } from '../test/fixtures'
import { HomePage } from './HomePage'

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

function renderHome() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        gcTime: 0,
        refetchOnWindowFocus: false,
      },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <HomePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function mockSnapshot(snapshot = makeSnapshot()) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/v1/me/profile')) return response(snapshot.profile)
    if (url.includes('/v1/me/status')) return response(snapshot.status)
    if (url.includes('/v1/league/standings')) return response(snapshot.standings)
    return response({ detail: 'not found' }, 404)
  })
}

describe('HomePage real data', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the tier, today XP, rank, streak and top-three board', async () => {
    const snapshot = makeSnapshot()
    snapshot.standings.standings[0]!.avatar_url = '/avatars/ch-xkein'
    vi.stubGlobal('fetch', mockSnapshot(snapshot))

    renderHome()

    expect(await screen.findByText('小组榜')).toBeInTheDocument()
    expect(screen.getAllByText('青铜').length).toBeGreaterThan(0)
    expect(screen.getByText('129')).toBeInTheDocument()
    expect(screen.getByText('今日目标已完成')).toBeInTheDocument()
    expect(screen.getByLabelText('本周名次 第 10 名')).toBeInTheDocument()
    expect(screen.getAllByText('524').length).toBeGreaterThan(0)
    expect(screen.getByText('再得 225 XP 可超过第 9 名')).toBeInTheDocument()
    expect(screen.getByText('8,019')).toBeInTheDocument()
    expect(screen.getByText('@Xkein')).toBeInTheDocument()
    expect(screen.getByText('我的位置')).toBeInTheDocument()
    expect(screen.getAllByText('那尔').length).toBeGreaterThan(0)

    const leader = screen.getByRole('listitem', { name: /@Xkein，第 1 名/ })
    expect(within(leader).getByText('@', { exact: true })).toBeInTheDocument()
    expect(leader.querySelector('img')).not.toBeNull()
    for (const [name, initial] of [
      [/RogerRordo，第 2 名/, 'R'],
      [/RedMcro，第 3 名/, 'R'],
      [/那尔，第 10 名.*我的位置/, '那'],
    ] as const) {
      const row = screen.getByRole('listitem', { name })
      expect(within(row).getByText(initial, { exact: true })).toBeInTheDocument()
    }
    expect(screen.getByLabelText('连续 2 天')).toBeInTheDocument()
    expect(
      screen.getByRole('progressbar', { name: '今日 XP 目标' }),
    ).toHaveAttribute('aria-valuenow', '100')
    const calls = vi.mocked(fetch).mock.calls.map(([input]) => String(input))
    expect(calls).toContain('/v1/me/profile')
    expect(calls).toContain('/v1/me/status')
    expect(calls).toContain('/v1/league/standings')
  })

  it('shows an explicit empty state with no invented numbers', async () => {
    const empty = makeSnapshot({
      status: {
        group: null,
        group_id: null,
        group_size: 0,
        rank: null,
        xp: 0,
        today_xp: 0,
        checkin: null,
        streak: {
          current: 0,
          longest: 0,
          clean_current: 0,
          last_checked_date: null,
        },
      },
      standings: {
        group: null,
        group_id: null,
        group_size: 0,
        me: null,
        standings: [],
      },
    })
    vi.stubGlobal('fetch', mockSnapshot(empty))

    renderHome()

    expect(await screen.findByText('本周还没有小组')).toBeInTheDocument()
    expect(screen.getAllByText('待分入小组').length).toBeGreaterThan(0)
    expect(screen.getByLabelText('本周名次 第 — 名')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.getByText('从第一笔专注开始')).toBeInTheDocument()
  })

  it('shows the error state and retries into real data', async () => {
    let failing = true
    const snapshot = makeSnapshot()
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (failing) return response({ detail: 'unauthorized' }, 401)
      const url = String(input)
      if (url.includes('/v1/me/profile')) return response(snapshot.profile)
      if (url.includes('/v1/me/status')) return response(snapshot.status)
      return response(snapshot.standings)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderHome()

    expect(await screen.findByText('数据没有加载出来')).toBeInTheDocument()
    expect(
      screen.getByText('登录已失效，请重新输入令牌。'),
    ).toBeInTheDocument()
    expect(screen.queryByText('8,019')).not.toBeInTheDocument()

    failing = false
    await userEvent.click(screen.getByRole('button', { name: '重试' }))

    expect(await screen.findByText('8,019')).toBeInTheDocument()
    expect(screen.getByText('今日目标已完成')).toBeInTheDocument()
  })

  it('renders a loading state before the first snapshot arrives', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => undefined)),
    )

    renderHome()

    expect(screen.getByText('正在读取本周联赛…')).toBeInTheDocument()
    expect(screen.getByText('正在读取本周联赛…').closest('[aria-busy]')).not.toBeNull()
  })
})
