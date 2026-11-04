import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type { Bet, RivalPlayer, RivalState } from '../api/types'
import { makeBetOptions, makeRecentXp, makeSnapshot } from '../test/fixtures'
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

function bet(overrides: Partial<Bet> = {}): Bet {
  return {
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
      weekly: bet(),
      daily: null,
      group: null,
    },
    bet_options: makeBetOptions(),
    projection: null,
    bet_windows: {
      weekly_locks_at: futureIso(4),
      daily_locks_at: futureIso(2),
      daily_settles_at: futureIso(3),
    },
    ...overrides,
  }
}

const PUBLIC_USER = {
  user_id: 'ch-rival',
  handle: null,
  display_name: '林间',
  avatar_url: null,
  activity_label: '绘画',
  tier: 'Bronze',
  group_id: 7,
  week_start: '2026-10-26',
  xp: 760,
  power: 980,
  rank: 4,
  group_size: 15,
  checkin: 'verified',
  streak: 2,
  equipped_title: null,
  frame: null,
  backdrop: null,
  badge_accent: null,
  is_following: false,
  following_count: 2,
  followers_count: 1,
  comparison: {
    viewer_id: 'naer-lily',
    target_id: 'ch-rival',
    viewer_xp: 524,
    target_xp: 760,
    viewer_rank: 10,
    target_rank: 4,
    viewer_group_size: 15,
    target_group_size: 15,
    xp_diff: -236,
    leader: 'them',
  },
  recent_xp: makeRecentXp({
    target: [0, 0, 189, 182, 178, 150, 61],
    viewer: [0, 0, 0, 0, 0, 0, 524],
  }),
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
  tasks?: unknown[]
  homeFails?: () => boolean
}

function mockApi(options: MockOptions = {}) {
  const snapshot = options.snapshot ?? makeSnapshot()
  const rival = options.rival ?? rivalState()
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (options.homeFails?.()) return response({ detail: 'unauthorized' }, 401)
    if (url.includes('/v1/me/tasks')) {
      return response({
        server_now: rival.server_now,
        tasks: options.tasks ?? [],
      })
    }
    if (url.includes('/v1/me/task-definitions')) {
      return response([])
    }
    if (url.includes('/v1/me/rival/candidates')) {
      return response({
        server_now: rival.server_now,
        week_start: rival.week_start,
        selection_open: rival.selection.open,
        candidates: options.candidates ?? [],
      })
    }
    if (url.includes('/v1/me/rival')) return response(rival)
    if (url.includes('/v1/me/bets')) {
      return response({
        server_now: rival.server_now,
        week_start: rival.week_start,
        day: rival.week_start,
        weekly: rival.bets.weekly,
        daily: rival.bets.daily,
        group: rival.bets.group,
        bets: rival.bets,
        bet_options: rival.bet_options,
        bet_windows: rival.bet_windows,
      })
    }
    if (url.includes('/v1/users/')) return response(PUBLIC_USER)
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

  it('shows the full duel card with weekly and daily surfaces on the home page', async () => {
    vi.stubGlobal('fetch', mockApi())

    renderHome()

    const card = await screen.findByTestId('rival-duel-card')
    expect(card).toHaveAttribute('data-variant', 'full')
    expect(card).toHaveTextContent('林间')
    expect(screen.getByTestId('rival-me-xp')).toHaveTextContent('524 XP')
    expect(screen.getByTestId('rival-rival-xp')).toHaveTextContent('760 XP')
    expect(screen.getByTestId('rival-gap')).toHaveTextContent('落后 236 XP')

    const today = within(card).getByTestId('rival-today-score')
    expect(today).toHaveTextContent('今日 我 129 XP')
    expect(today).toHaveTextContent('宿敌 120 XP')
    expect(screen.getByTestId('rival-week-countdown')).toBeVisible()
    expect(screen.getByTestId('rival-daily-countdown')).toBeVisible()

    expect(screen.getByTestId('rival-bet-status-周注')).toHaveTextContent(
      '周注 · 已下注',
    )
    expect(screen.getByTestId('rival-bet-target-weekly')).toHaveTextContent(
      '+0 XP',
    )
    expect(screen.getByTestId('rival-bet-odds-weekly')).toHaveTextContent(
      '×2.00',
    )
    expect(screen.getByTestId('rival-bet-status-日注')).toHaveTextContent(
      '日注 · 未下注',
    )
    expect(screen.getByRole('button', { name: '下注日注' })).toBeVisible()
    expect(
      screen.queryByRole('button', { name: '下注周注' }),
    ).not.toBeInTheDocument()
    expect(card).toHaveTextContent('战力')
    expect(
      screen.queryByTestId('rival-bet-status-组注'),
    ).not.toBeInTheDocument()
    expect(card).not.toHaveTextContent('组注')
    expect(card).not.toHaveTextContent('今日 +')

    expect(screen.queryByText('小组榜')).not.toBeInTheDocument()
    expect(screen.queryByText(/G01|我的组|组号/)).not.toBeInTheDocument()
    expect(screen.queryByText('本周追一个对手，实时对撞。')).not.toBeInTheDocument()
    expect(screen.getByTestId('player-tier')).toHaveTextContent('青铜')
    expect(screen.getByTestId('today-progress')).toBeVisible()
    expect(screen.queryByTestId('today-current-tier')).not.toBeInTheDocument()
  })

  it('opens a daily-only bet dialog from the daily surface', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', mockApi())

    renderHome()

    await user.click(await screen.findByRole('button', { name: '下注日注' }))
    const dialog = await screen.findByTestId('rival-bet-dialog')
    expect(within(dialog).queryByRole('tab')).not.toBeInTheDocument()
    expect(within(dialog).getByRole('tabpanel')).toHaveAttribute(
      'data-kind',
      'daily',
    )
    expect(
      within(dialog).getByText('押「今天我比宿敌多多少 XP」'),
    ).toBeInTheDocument()
    expect(within(dialog).getByTestId('rival-target-111')).toHaveTextContent(
      '×2.00',
    )
    expect(within(dialog).getByTestId('rival-target-111')).toHaveTextContent(
      '需要多 111 XP',
    )
    expect(within(dialog).getByTestId('rival-target-111')).toHaveTextContent(
      '预计总共 620 XP',
    )
    expect(within(dialog).queryByTestId('rival-target-0')).not.toBeInTheDocument()
    expect(within(dialog).getByTestId('rival-target-111')).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(within(dialog).getByTestId('rival-bet-target')).toHaveTextContent(
      '+111 XP',
    )
    expect(within(dialog).getByTestId('rival-bet-expected')).toHaveTextContent(
      '620 XP',
    )
    expect(within(dialog).getByTestId('rival-bet-odds')).toHaveTextContent(
      '×2.00',
    )
    expect(within(dialog).getByTestId('rival-bet-paid-input')).toHaveAttribute(
      'max',
      '100',
    )
    expect(
      within(dialog).queryByText(/目标不在服务端档位里/),
    ).not.toBeInTheDocument()
    expect(
      within(dialog).queryByText('押「我本周最终 XP 比宿敌高多少」'),
    ).not.toBeInTheDocument()
    expect(within(dialog).queryByText(/本周宿敌：/)).not.toBeInTheDocument()
    expect(within(dialog).queryByText(/每注自带/)).not.toBeInTheDocument()
    expect(within(dialog).queryByText(/本周剩余/)).not.toBeInTheDocument()
    expect(
      within(dialog).getByText('21:00 锁注 · 22:30 结算'),
    ).toBeInTheDocument()
  })

  it('opens a weekly-only bet dialog from the weekly surface', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      mockApi({
        rival: rivalState({
          bets: { weekly: null, daily: null, group: null },
        }),
      }),
    )

    renderHome()

    await user.click(await screen.findByRole('button', { name: '下注周注' }))
    const dialog = await screen.findByTestId('rival-bet-dialog')
    expect(within(dialog).queryByRole('tab')).not.toBeInTheDocument()
    expect(within(dialog).getByRole('tabpanel')).toHaveAttribute(
      'data-kind',
      'weekly',
    )
    expect(
      within(dialog).getByText('押「我本周最终 XP 比宿敌高多少」'),
    ).toBeInTheDocument()
    expect(
      within(dialog).queryByText('押「今天我比宿敌多多少 XP」'),
    ).not.toBeInTheDocument()
    expect(
      within(dialog).getByText('周一 23:59:59 截止 · 次周一结算'),
    ).toBeInTheDocument()
  })

  it('replaces the daily entry with the placed daily surface and keeps the weekly entry', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({
        rival: rivalState({
          bets: {
            weekly: null,
            daily: bet({
              id: 2,
              kind: 'daily',
              period_key: '2026-10-26',
              target_margin: 150,
              odds: 2,
              stake: 20,
              free_stake: 20,
              paid_stake: 0,
            }),
            group: null,
          },
        }),
      }),
    )

    renderHome()

    const daily = await screen.findByTestId('rival-bet-status-日注')
    expect(daily).toHaveTextContent('日注 · 已下注')
    expect(screen.getByTestId('rival-bet-target-daily')).toHaveTextContent(
      '+150 XP',
    )
    expect(screen.getByTestId('rival-bet-odds-daily')).toHaveTextContent(
      '×2.00',
    )
    expect(screen.getByTestId('rival-bet-stake-daily')).toHaveTextContent('20')
    expect(screen.getByTestId('rival-bet-return-daily')).toHaveTextContent('40')
    expect(
      screen.queryByRole('button', { name: '下注日注' }),
    ).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '下注周注' })).toBeVisible()
  })

  it('opens the rival public profile from the duel avatar and shows the week comparison', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', mockApi())

    renderHome()

    const card = await screen.findByTestId('rival-duel-card')
    const avatars = within(card).getAllByTestId('rival-avatar-profile')
    await user.click(avatars[1]!)

    const sheet = await screen.findByTestId('user-profile-sheet')
    expect(within(sheet).getByTestId('profile-recent-chart')).toBeVisible()
    expect(within(sheet).getByTestId('profile-recent-target')).toHaveAttribute(
      'points',
    )
    expect(within(sheet).getByTestId('profile-recent-viewer')).toHaveAttribute(
      'points',
    )
    expect(within(sheet).getByTestId('profile-follow')).toBeVisible()
    expect(within(sheet).queryByTestId('me-diamonds')).not.toBeInTheDocument()
    expect(within(sheet).queryByText('720')).not.toBeInTheDocument()
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

  it('shows the task section between today progress and the rival card', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({
        tasks: [
          {
            id: 'ti_1',
            source: 'daily_manual',
            title: '速写一张',
            description: '',
            difficulty: 2,
            chest_tier: 2,
            sort_order: 10,
            starts_at: '2026-11-04T00:00:00+08:00',
            ends_at: '2026-11-05T00:00:00+08:00',
            status: 'active',
            completed_at: null,
            chest_status: 'none',
            chest_amount: null,
            proof_url: null,
            progress: null,
          },
        ],
      }),
    )

    renderHome()

    const list = await screen.findByTestId('task-list')
    expect(list).toHaveTextContent('任务')
    expect(await screen.findByText('速写一张')).toBeInTheDocument()
    expect(list).toHaveTextContent(/还剩 \d+ 小时 \d+ 分/)
    expect(list).not.toHaveTextContent('截止 11/05')
    expect(within(list).getByRole('button', { name: /拍照完成/ })).toBeVisible()
    expect(within(list).getByRole('button', { name: '任务设置' })).toBeVisible()
    expect(screen.queryByText(/概率|机制|DSL/)).not.toBeInTheDocument()
  })

  it('sorts task cards on the client instead of trusting the API order', async () => {
    const task = (
      id: string,
      title: string,
      sortOrder: number,
      overrides: Record<string, unknown> = {},
    ) => ({
      id,
      source: 'daily_manual',
      title,
      description: '',
      difficulty: 1,
      chest_tier: 1,
      sort_order: sortOrder,
      starts_at: '2026-11-04T00:00:00+08:00',
      ends_at: '2026-11-05T00:00:00+08:00',
      status: 'active',
      completed_at: null,
      chest_status: 'none',
      chest_amount: null,
      proof_url: null,
      progress: null,
      ...overrides,
    })
    vi.stubGlobal(
      'fetch',
      mockApi({
        tasks: [
          task('ti_b', 'B', 20, {
            status: 'completed',
            chest_status: 'claimed',
          }),
          task('ti_d', 'D', 40, {
            status: 'completed',
            chest_status: 'available',
          }),
          task('ti_a', 'A', 10),
          task('ti_c', 'C', 30),
        ],
      }),
    )

    renderHome()

    const list = await screen.findByTestId('task-list')
    await screen.findByText('A')
    expect(
      within(list)
        .getAllByRole('heading', { level: 3 })
        .map((heading) => heading.textContent),
    ).toEqual(['A', 'C', 'D', 'B'])
  })

  it('updates the home task order after a settings drag reorder', async () => {
    const makeDefinition = (id: string, title: string, sortOrder: number) => ({
      id,
      user_id: 'owner',
      title,
      description: '',
      difficulty: 1,
      active: true,
      sort_order: sortOrder,
      created_at: '2026-11-04T10:00:00+08:00',
      updated_at: '2026-11-04T10:00:00+08:00',
    })
    const makeTask = (id: string, title: string, sortOrder: number) => ({
      id,
      source: 'daily_manual',
      title,
      description: '',
      difficulty: 1,
      chest_tier: 1,
      sort_order: sortOrder,
      starts_at: '2026-11-04T00:00:00+08:00',
      ends_at: '2026-11-05T00:00:00+08:00',
      status: 'active',
      completed_at: null,
      chest_status: 'none',
      chest_amount: null,
      proof_url: null,
      progress: null,
    })
    let definitions = [
      makeDefinition('td_a', 'A', 10),
      makeDefinition('td_b', 'B', 20),
    ]
    let tasks = [makeTask('ti_a', 'A', 10), makeTask('ti_b', 'B', 20)]
    const base = mockApi()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (
          url.endsWith('/v1/me/task-definitions/order') &&
          init?.method === 'PUT'
        ) {
          const ids = JSON.parse(String(init.body)).ids as string[]
          definitions = ids.map((id, index) => {
            const row = definitions.find((item) => item.id === id)!
            return { ...row, sort_order: (index + 1) * 10 }
          })
          const taskById = new Map(tasks.map((row) => [row.id, row]))
          tasks = ids.map((id, index) => ({
            ...taskById.get(id.replace('td_', 'ti_'))!,
            sort_order: (index + 1) * 10,
          }))
          return response(definitions)
        }
        if (url.endsWith('/v1/me/task-definitions')) {
          return response(definitions)
        }
        if (url.endsWith('/v1/me/tasks')) {
          return response({
            server_now: new Date().toISOString(),
            tasks,
          })
        }
        return base(input)
      }),
    )
    const rectSpy = vi
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockImplementation(function (this: HTMLElement) {
        const top = this.dataset.taskId === 'td_b' ? 58 : 0
        return {
          top,
          bottom: top + 50,
          height: 50,
          left: 0,
          right: 300,
          width: 300,
          x: 0,
          y: top,
          toJSON: () => undefined,
        } as DOMRect
      })

    renderHome()

    const list = await screen.findByTestId('task-list')
    await screen.findByText('A')
    const homeTitles = () =>
      Array.from(list.querySelectorAll('h3')).map(
        (heading) => heading.textContent ?? '',
      )
    expect(homeTitles()).toEqual(['A', 'B'])

    await userEvent.click(screen.getByRole('button', { name: '任务设置' }))
    const handle = await screen.findByRole('button', { name: '拖动排序 A' })
    fireEvent.pointerDown(handle, {
      pointerId: 1,
      pointerType: 'touch',
      isPrimary: true,
      button: 0,
      clientY: 20,
    })
    fireEvent.pointerMove(handle, {
      pointerId: 1,
      pointerType: 'touch',
      isPrimary: true,
      button: 0,
      clientY: 100,
    })
    fireEvent.pointerUp(handle, {
      pointerId: 1,
      pointerType: 'touch',
      isPrimary: true,
      button: 0,
      clientY: 100,
    })

    await waitFor(() => expect(homeTitles()).toEqual(['B', 'A']))
    rectSpy.mockRestore()
  })
})
