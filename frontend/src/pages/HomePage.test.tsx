import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type { RivalPlayer, RivalState } from '../api/types'
import { makeSnapshot } from '../test/fixtures'
import { HomePage } from './HomePage'

const HOUR = 3_600_000

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

function futureIso(hours: number): string {
  return new Date(Date.now() + hours * HOUR).toISOString()
}

function player(overrides: Partial<RivalPlayer> = {}): RivalPlayer {
  return {
    user_id: 'naer-lily',
    display_name: '那尔',
    avatar_url: null,
    group_no: 1,
    tier: 'Bronze',
    power: 1667,
    week_xp: 524,
    today_xp: 129,
    ...overrides,
  }
}

function rivalState(overrides: Partial<RivalState> = {}): RivalState {
  return {
    server_now: new Date().toISOString(),
    week_start: '2026-10-26',
    selection: {
      open: true,
      locks_at: futureIso(4),
      auto_select_at: futureIso(28),
      mode: null,
    },
    me: player(),
    rival: player({
      user_id: 'ch-rival',
      display_name: '林间',
      group_no: 7,
      power: 980,
      week_xp: 760,
      today_xp: 120,
    }),
    result: null,
    bets: {
      weekly: {
        id: 1,
        kind: 'weekly',
        period_key: '2026-10-26',
        rival_id: 'ch-rival',
        stake: 40,
        free_stake: 20,
        paid_stake: 20,
        target_margin: 0,
        odds: 2,
        status: 'placed',
        placed_at: new Date().toISOString(),
        locked_at: null,
        settled_at: null,
        payout: 0,
        result_diff: null,
      },
      daily: null,
      group: null,
    },
    projection: null,
    bet_windows: {
      weekly_locks_at: futureIso(4),
      daily_locks_at: futureIso(2),
      daily_settles_at: futureIso(3),
    },
    ...overrides,
  }
}

function renderHome() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { gcTime: 0, retry: false, refetchOnWindowFocus: false },
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

interface MockOptions {
  snapshot?: ReturnType<typeof makeSnapshot>
  rival?: RivalState
  candidates?: RivalPlayer[]
  homeFails?: () => boolean
}

function mockApi(options: MockOptions = {}) {
  const snapshot = options.snapshot ?? makeSnapshot()
  const rival = options.rival ?? rivalState()
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (options.homeFails?.()) return response({ detail: 'unauthorized' }, 401)
    if (url.includes('/v1/me/rival/candidates')) {
      return response({
        server_now: rival.server_now,
        week_start: rival.week_start,
        selection_open: rival.selection.open,
        candidates: options.candidates ?? [],
      })
    }
    if (url.includes('/v1/me/rival')) return response(rival)
    if (url.includes('/v1/me/profile')) return response(snapshot.profile)
    if (url.includes('/v1/me/status')) return response(snapshot.status)
    if (url.includes('/v1/league/standings')) return response(snapshot.standings)
    return response({ detail: 'not found' }, 404)
  })
}

describe('HomePage rework', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the duel card and drops the home group board and group label', async () => {
    vi.stubGlobal('fetch', mockApi())

    renderHome()

    const card = await screen.findByTestId('rival-duel-card')
    expect(card).toHaveTextContent('林间')
    expect(screen.getByTestId('rival-me-xp')).toHaveTextContent('524 XP')
    expect(screen.getByTestId('rival-rival-xp')).toHaveTextContent('760 XP')
    expect(screen.getByTestId('rival-gap')).toHaveTextContent('落后 236 XP')
    expect(screen.getByTestId('rival-bet-status-周注')).toHaveTextContent(
      '周注 · 已下注',
    )
    expect(screen.getByRole('button', { name: '下注' })).toBeVisible()

    expect(screen.queryByText('小组榜')).not.toBeInTheDocument()
    expect(screen.queryByText(/G01|我的组|组号/)).not.toBeInTheDocument()
    expect(screen.queryByText('本周追一个对手，实时对撞。')).not.toBeInTheDocument()
    expect(screen.getByTestId('player-tier')).toHaveTextContent('青铜')
    expect(screen.getByTestId('today-progress')).toBeVisible()
    expect(screen.queryByTestId('today-current-tier')).not.toBeInTheDocument()
  })

  it('shows an inline selection entry when no rival is selected', async () => {
    const rival = rivalState({ rival: null })
    const candidates = [player({ user_id: 'ch-mid', display_name: '清风与梦' })]
    vi.stubGlobal('fetch', mockApi({ rival, candidates }))

    renderHome()

    expect(await screen.findByText('还没有宿敌')).toBeInTheDocument()
    expect(screen.queryByText('本周追一个对手，实时对撞。')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '选择宿敌' }))

    expect(await screen.findByText('清风与梦')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /选择 清风与梦 作为本周宿敌/ })).toBeVisible()
  })

  it('uses the real last activity timestamp for the update marker', async () => {
    const snapshot = makeSnapshot({
      status: { last_activity_at: '2026-10-31T09:06:34+08:00' },
    })
    vi.stubGlobal('fetch', mockApi({ snapshot }))

    renderHome()

    await screen.findByTestId('today-progress')
    expect(screen.queryByTestId('recent-update')).not.toBeInTheDocument()
  })

  it('shows home errors with a real retry path', async () => {
    let failing = true
    vi.stubGlobal('fetch', mockApi({ homeFails: () => failing }))

    renderHome()

    expect(await screen.findByText('数据没有加载出来')).toBeInTheDocument()
    expect(screen.getByText('登录已失效，请重新输入令牌。')).toBeInTheDocument()

    failing = false
    await userEvent.click(screen.getByRole('button', { name: '重试' }))

    expect(await screen.findByTestId('rival-duel-card')).toBeInTheDocument()
  })

  it('renders a loading state before the first snapshot arrives', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => undefined)),
    )

    renderHome()

    expect(screen.getByText('正在读取本周联赛…')).toBeInTheDocument()
  })

  it('wraps the page in a pull-to-refresh container', async () => {
    vi.stubGlobal('fetch', mockApi())

    renderHome()

    await waitFor(() =>
      expect(screen.getByTestId('pull-to-refresh')).toBeInTheDocument(),
    )
  })
})
