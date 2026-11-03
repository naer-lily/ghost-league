import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type {
  Bet,
  BetsState,
  PlaceBetResult,
  RivalPlayer,
  RivalState,
} from '../api/types'
import { makeBetOptions } from '../test/fixtures'
import { RivalPage } from './RivalPage'

const HOUR = 3_600_000

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

function player(overrides: Partial<RivalPlayer> = {}): RivalPlayer {
  return {
    user_id: 'naer-lily',
    display_name: '那尔',
    avatar_url: null,
    group_no: 1,
    tier: 'Bronze',
    power: 654,
    week_xp: 524,
    today_xp: 129,
    ...overrides,
  }
}

function bet(overrides: Partial<Bet> = {}): Bet {
  return {
    id: 1,
    kind: 'weekly',
    period_key: '2026-11-02',
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

function futureIso(hours: number): string {
  return new Date(Date.now() + hours * HOUR).toISOString()
}

function makeState(overrides: Partial<RivalState> = {}): RivalState {
  return {
    server_now: new Date().toISOString(),
    week_start: '2026-11-02',
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
    bets: { weekly: null, daily: null, group: null },
    bet_options: makeBetOptions(),
    projection: {
      rival_week_estimate: 3400,
      weekly_target_max: 6800,
      daily_mu_me: 620.5,
      daily_sd_me: 180.2,
      daily_mu_rival: 510,
      daily_sd_rival: 150,
      daily_mu_diff: 110.5,
      daily_sigma_diff: 234.5,
      daily_target_margins: [1, 150, 300, 600],
    },
    bet_windows: {
      weekly_locks_at: futureIso(4),
      daily_locks_at: futureIso(2),
      daily_settles_at: futureIso(3),
    },
    ...overrides,
  }
}

function betsFrom(state: RivalState): BetsState {
  return {
    server_now: state.server_now,
    week_start: state.week_start,
    day: '2026-11-02',
    weekly: state.bets.weekly,
    daily: state.bets.daily,
    group: state.bets.group,
    bets: state.bets,
    bet_options: state.bet_options,
    bet_windows: state.bet_windows,
  }
}

interface MockOptions {
  state: RivalState
  candidates?: RivalPlayer[]
  select?: (body: Record<string, unknown>) => RivalState
  place?: (body: Record<string, unknown>) => PlaceBetResult
  placeError?: { status: number; payload: unknown }
}

function installApi(options: MockOptions) {
  const stateRef = { current: options.state }
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.includes('/v1/me/rival/candidates')) {
        return response({
          server_now: stateRef.current.server_now,
          week_start: stateRef.current.week_start,
          selection_open: stateRef.current.selection.open,
          candidates: options.candidates ?? [],
        })
      }
      if (url.includes('/v1/me/rival/select') && method === 'POST') {
        const body = JSON.parse(String(init?.body ?? '{}')) as Record<
          string,
          unknown
        >
        const next = options.select
          ? options.select(body)
          : stateRef.current
        stateRef.current = next
        return response(next)
      }
      if (url.includes('/v1/me/rival') && method === 'GET') {
        return response(stateRef.current)
      }
      if (url.includes('/v1/me/bets') && method === 'POST') {
        if (options.placeError) {
          return response(
            options.placeError.payload,
            options.placeError.status,
          )
        }
        const body = JSON.parse(String(init?.body ?? '{}')) as Record<
          string,
          unknown
        >
        const result = options.place?.(body)
        if (!result) return response({ detail: 'not configured' }, 500)
        stateRef.current = result.state
        return response(result)
      }
      if (url.includes('/v1/me/bets')) {
        return response(betsFrom(stateRef.current))
      }
      return response({ detail: 'not found' }, 404)
    },
  )
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, stateRef }
}

function renderRivalPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { gcTime: 0, refetchOnWindowFocus: false, retry: false },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <RivalPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const CANDIDATES: RivalPlayer[] = [
  player({
    user_id: 'ch-mid',
    display_name: '清风与梦',
    group_no: 7,
    power: 900,
    week_xp: 620,
    today_xp: 80,
  }),
  player({
    user_id: 'ch-strong',
    display_name: '星河尽头',
    group_no: 3,
    power: 1200,
    week_xp: 900,
    today_xp: 140,
  }),
  player({
    user_id: 'ch-low',
    display_name: '低战力',
    group_no: 9,
    power: 300,
    week_xp: 90,
    today_xp: 10,
  }),
]

describe('RivalPage', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('defaults to slightly stronger candidates, can switch filters, and enters the duel after selecting', async () => {
    const user = userEvent.setup()
    const noRival = makeState({
      selection: {
        open: true,
        locks_at: futureIso(4),
        auto_select_at: futureIso(28),
        mode: null,
      },
      rival: null,
      projection: null,
    })
    const duel = makeState()
    const { fetchMock } = installApi({
      state: noRival,
      candidates: CANDIDATES,
      select: (body) => {
        expect(body.rival_id).toBe('ch-mid')
        expect(typeof body.request_id).toBe('string')
        return duel
      },
    })

    renderRivalPage()

    expect(
      await screen.findByRole('heading', {
        name: '选一个本周要追的宿敌',
      }),
    ).toBeInTheDocument()
    expect(await screen.findByText('清风与梦')).toBeInTheDocument()
    expect(screen.getByText('星河尽头')).toBeInTheDocument()
    expect(screen.queryByText('低战力')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '全部' }))
    expect(await screen.findByText('低战力')).toBeInTheDocument()

    await user.click(
      screen.getByRole('button', {
        name: '选择 清风与梦 作为本周宿敌',
      }),
    )

    expect(
      await screen.findByRole('heading', { name: '宿敌对抗' }),
    ).toBeInTheDocument()
    expect(screen.getByTestId('rival-me-xp')).toHaveTextContent('524 XP')
    expect(screen.getByTestId('rival-rival-xp')).toHaveTextContent('760 XP')
    expect(screen.getByTestId('rival-gap')).toHaveTextContent('落后 236 XP')
    expect(screen.getByTestId('rival-bet-status-周注')).toHaveTextContent(
      '周注 · 未下注',
    )
    const post = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input).includes('/v1/me/rival/select') &&
        init?.method === 'POST',
    )
    expect(post).toBeTruthy()
  })

  it('falls back to all candidates when nobody is stronger', async () => {
    const noRival = makeState({
      rival: null,
      projection: null,
    })
    installApi({
      state: noRival,
      candidates: [
        player({
          user_id: 'ch-low',
          display_name: '低战力',
          power: 300,
          group_no: 9,
        }),
        player({
          user_id: 'ch-lower',
          display_name: '更低战力',
          power: 120,
          group_no: 11,
        }),
      ],
    })

    renderRivalPage()

    expect(await screen.findByText('低战力')).toBeInTheDocument()
    expect(screen.getByText('更低战力')).toBeInTheDocument()
    expect(screen.getByTestId('rival-filter-hint')).toHaveTextContent(
      '没有略高于你的候选，先显示全部跨组候选。',
    )
  })

  it('shows a real locked empty state and retries without inventing a rival', async () => {
    const user = userEvent.setup()
    const locked = makeState({
      selection: {
        open: false,
        locks_at: futureIso(-1),
        auto_select_at: futureIso(-2),
        mode: null,
      },
      rival: null,
      projection: null,
    })
    const { fetchMock } = installApi({ state: locked })

    renderRivalPage()

    expect(
      await screen.findByRole('heading', { name: '本周宿敌已锁定' }),
    ).toBeInTheDocument()
    expect(screen.queryByText(/0\s*:\s*0/)).not.toBeInTheDocument()
    expect(screen.queryByText('宿敌对抗')).not.toBeInTheDocument()

    const before = fetchMock.mock.calls.filter(([input]) =>
      String(input).includes('/v1/me/rival'),
    ).length
    await user.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => {
      const after = fetchMock.mock.calls.filter(([input]) =>
        String(input).includes('/v1/me/rival'),
      ).length
      expect(after).toBeGreaterThan(before)
    })
  })

  it('shows the lock note and hides reselect once the window is closed', async () => {
    const lockedDuel = makeState({
      selection: {
        open: false,
        locks_at: futureIso(-1),
        auto_select_at: futureIso(-2),
        mode: 'manual',
      },
    })
    installApi({ state: lockedDuel })

    renderRivalPage()

    expect(
      await screen.findByRole('heading', { name: '宿敌对抗' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText('宿敌已锁定，本周不可更换'),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: '改选' }),
    ).not.toBeInTheDocument()
  })

  it('renders a 50/50 collision bar when both sides have zero XP', async () => {
    const zero = makeState({
      me: player({ week_xp: 0, today_xp: 0 }),
      rival: player({
        user_id: 'ch-rival',
        display_name: '林间',
        group_no: 7,
        power: 980,
        week_xp: 0,
        today_xp: 0,
      }),
    })
    installApi({ state: zero })

    renderRivalPage()

    expect(
      await screen.findByRole('heading', { name: '宿敌对抗' }),
    ).toBeInTheDocument()
    expect(screen.getByTestId('rival-clash-me')).toHaveStyle({ width: '50%' })
    expect(screen.getByTestId('rival-clash-rival')).toHaveStyle({
      width: '50%',
    })
    expect(screen.getByTestId('rival-gap')).toHaveTextContent('双方持平')
    expect(document.body.textContent ?? '').not.toMatch(/0\s*:\s*0/)
  })

  it('shows both today XP values above the bet surfaces', async () => {
    installApi({ state: makeState() })

    renderRivalPage()

    const today = await screen.findByTestId('rival-today-score')
    expect(today).toHaveTextContent('今日 我 129 XP')
    expect(today).toHaveTextContent('宿敌 120 XP')
    expect(screen.getByTestId('rival-today-me')).toHaveTextContent(
      '今日 我 129 XP',
    )
    expect(screen.getByTestId('rival-today-rival')).toHaveTextContent(
      '宿敌 120 XP',
    )
    expect(screen.getByRole('button', { name: '下注周注' })).toBeVisible()
    expect(screen.getByRole('button', { name: '下注日注' })).toBeVisible()
    expect(screen.queryByText(/今日 \+/)).not.toBeInTheDocument()
  })

  it('replaces the daily bet entry with the current daily surface once placed', async () => {
    installApi({
      state: makeState({
        bets: {
          weekly: null,
          daily: bet({
            id: 2,
            kind: 'daily',
            period_key: '2026-11-02',
            target_margin: 150,
            odds: 2,
            stake: 20,
            free_stake: 20,
            paid_stake: 0,
          }),
          group: null,
        },
      }),
    })

    renderRivalPage()

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

  it('opens the weekly-only bet dialog from the weekly surface', async () => {
    const user = userEvent.setup()
    installApi({ state: makeState() })

    renderRivalPage()

    await user.click(await screen.findByRole('button', { name: '下注周注' }))
    const dialog = await screen.findByTestId('rival-bet-dialog')
    expect(
      within(dialog).getByRole('heading', { name: '下注' }),
    ).toBeInTheDocument()
    expect(within(dialog).queryByRole('tab')).not.toBeInTheDocument()
    expect(within(dialog).getByRole('tabpanel')).toHaveAttribute(
      'data-kind',
      'weekly',
    )

    expect(within(dialog).getByTestId('rival-target-0')).toHaveTextContent(
      '+0 XP',
    )
    expect(within(dialog).getByTestId('rival-target-150')).toHaveTextContent(
      '赔率 ×1.50',
    )
    expect(within(dialog).getByTestId('rival-target-300')).toHaveTextContent(
      '+300 XP',
    )
    expect(within(dialog).getByTestId('rival-bet-target')).toHaveTextContent(
      '+0 XP',
    )
    expect(within(dialog).getByTestId('rival-bet-odds')).toHaveTextContent(
      '×1.20',
    )
    expect(within(dialog).getByTestId('rival-bet-payout')).toHaveTextContent(
      '24',
    )
    expect(within(dialog).queryByText(/本周剩余/)).not.toBeInTheDocument()
    expect(within(dialog).queryByText(/日注锁注/)).not.toBeInTheDocument()
    expect(
      within(dialog).getByText('周一 23:59:59 截止 · 次周一结算'),
    ).toBeInTheDocument()

    await user.click(within(dialog).getByTestId('rival-target-300'))
    expect(within(dialog).getByTestId('rival-bet-target')).toHaveTextContent(
      '+300 XP',
    )
    expect(within(dialog).getByTestId('rival-bet-odds')).toHaveTextContent(
      '×2.00',
    )
  })

  it('lets the weekly bet use paid stakes 0 and 500 with server odds', async () => {
    const user = userEvent.setup()
    installApi({ state: makeState() })

    renderRivalPage()

    await user.click(await screen.findByRole('button', { name: '下注周注' }))
    const dialog = await screen.findByTestId('rival-bet-dialog')
    const paidInput = within(dialog).getByTestId('rival-bet-paid-input')

    expect(paidInput).toHaveValue(0)
    expect(within(dialog).getByTestId('rival-bet-paid')).toHaveTextContent('0')
    expect(within(dialog).getByTestId('rival-bet-free')).toHaveTextContent(
      '20',
    )
    expect(within(dialog).getByTestId('rival-bet-stake')).toHaveTextContent(
      '20',
    )
    expect(within(dialog).getByTestId('rival-bet-payout')).toHaveTextContent(
      '24',
    )

    await user.clear(paidInput)
    await user.type(paidInput, '500')
    expect(paidInput).toHaveValue(500)
    expect(within(dialog).getByTestId('rival-bet-paid')).toHaveTextContent(
      '500',
    )
    expect(within(dialog).getByTestId('rival-bet-stake')).toHaveTextContent(
      '520',
    )
    expect(within(dialog).getByTestId('rival-bet-payout')).toHaveTextContent(
      '624',
    )
    expect(within(dialog).getByTestId('rival-bet-paid-range')).toHaveValue(
      '500',
    )

    await user.click(within(dialog).getByTestId('rival-target-600'))
    expect(within(dialog).getByTestId('rival-bet-odds')).toHaveTextContent(
      '×3.20',
    )
    expect(within(dialog).getByTestId('rival-bet-payout')).toHaveTextContent(
      '1,664',
    )
  })

  it('selects the daily target from the server target_options', async () => {
    const user = userEvent.setup()
    installApi({ state: makeState() })

    renderRivalPage()

    await user.click(await screen.findByRole('button', { name: '下注日注' }))
    const dialog = await screen.findByTestId('rival-bet-dialog')
    expect(within(dialog).queryByRole('tab')).not.toBeInTheDocument()
    expect(within(dialog).getByRole('tabpanel')).toHaveAttribute(
      'data-kind',
      'daily',
    )

    expect(within(dialog).getByTestId('rival-target-1')).toHaveTextContent(
      '+1 XP',
    )
    expect(within(dialog).getByTestId('rival-target-1')).toHaveTextContent(
      '预计 510 XP',
    )
    expect(within(dialog).getByTestId('rival-target-150')).toHaveTextContent(
      '+150 XP',
    )
    expect(within(dialog).getByTestId('rival-target-150')).toHaveTextContent(
      '预计 660 XP',
    )
    expect(within(dialog).getByTestId('rival-target-300')).toHaveTextContent(
      '赔率 ×3.10',
    )
    expect(within(dialog).getByTestId('rival-target-300')).toHaveTextContent(
      '预计 810 XP',
    )
    expect(within(dialog).getByTestId('rival-target-600')).toBeInTheDocument()
    expect(within(dialog).queryByTestId('rival-target-0')).toBeNull()
    expect(within(dialog).getByTestId('rival-bet-paid-input')).toBeVisible()
    expect(within(dialog).getByTestId('rival-bet-stake')).toHaveTextContent(
      '20',
    )

    await user.click(within(dialog).getByTestId('rival-target-300'))
    expect(within(dialog).getByTestId('rival-bet-target')).toHaveTextContent(
      '+300 XP',
    )
    expect(within(dialog).getByTestId('rival-bet-expected')).toHaveTextContent(
      '810 XP',
    )
    expect(within(dialog).getByTestId('rival-bet-odds')).toHaveTextContent(
      '×3.10',
    )
  })

  it('defaults the daily target to the first positive server tier', async () => {
    const user = userEvent.setup()
    installApi({ state: makeState() })

    renderRivalPage()

    await user.click(await screen.findByRole('button', { name: '下注日注' }))
    const dialog = await screen.findByTestId('rival-bet-dialog')
    expect(within(dialog).queryByRole('tab')).not.toBeInTheDocument()
    expect(within(dialog).getByRole('tabpanel')).toHaveAttribute(
      'data-kind',
      'daily',
    )

    expect(within(dialog).queryByTestId('rival-target-0')).toBeNull()
    expect(within(dialog).getByTestId('rival-target-1')).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(within(dialog).getByTestId('rival-bet-target')).toHaveTextContent(
      '+1 XP',
    )
    expect(within(dialog).getByTestId('rival-bet-expected')).toHaveTextContent(
      '510 XP',
    )
    expect(within(dialog).getByTestId('rival-bet-odds')).toHaveTextContent(
      '×1.20',
    )
    expect(
      within(dialog).queryByText('目标不在服务端档位里，请从上面的档位里选一个。'),
    ).not.toBeInTheDocument()
    expect(
      within(dialog).getByRole('button', { name: '确认下注' }),
    ).toBeEnabled()
  })

  it('shows the closed daily surface after 21:00 without a bet entry', async () => {
    const closed = makeState({
      bet_windows: {
        weekly_locks_at: futureIso(4),
        daily_locks_at: futureIso(-1),
        daily_settles_at: futureIso(1),
      },
    })
    installApi({ state: closed })

    renderRivalPage()

    const daily = await screen.findByTestId('rival-bet-status-日注')
    expect(daily).toHaveTextContent('日注 · 已截止')
    expect(daily).toHaveTextContent('今天的注已截止')
    expect(
      screen.queryByRole('button', { name: '下注日注' }),
    ).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '下注周注' })).toBeVisible()
  })

  it('shows the closed weekly surface after the weekly lock without a bet entry', async () => {
    const closed = makeState({
      bet_windows: {
        weekly_locks_at: futureIso(-1),
        daily_locks_at: futureIso(2),
        daily_settles_at: futureIso(3),
      },
    })
    installApi({ state: closed })

    renderRivalPage()

    const weekly = await screen.findByTestId('rival-bet-status-周注')
    expect(weekly).toHaveTextContent('周注 · 已截止')
    expect(weekly).toHaveTextContent('本周的注已截止')
    expect(
      screen.queryByRole('button', { name: '下注周注' }),
    ).not.toBeInTheDocument()
  })

  it('places a weekly bet with paid_stake and no stake field', async () => {
    const user = userEvent.setup()
    const initial = makeState()
    const placed = bet({
      stake: 100,
      paid_stake: 80,
      target_margin: 150,
      odds: 1.5,
    })
    const nextState = makeState({
      bets: { weekly: placed, daily: null, group: null },
    })
    let posted: Record<string, unknown> | null = null
    const { fetchMock } = installApi({
      state: initial,
      place: (body) => {
        posted = body
        return { bet: placed, state: nextState }
      },
    })

    renderRivalPage()

    await user.click(await screen.findByRole('button', { name: '下注周注' }))
    const dialog = await screen.findByTestId('rival-bet-dialog')
    await user.click(within(dialog).getByTestId('rival-target-150'))
    const paidInput = within(dialog).getByTestId('rival-bet-paid-input')
    await user.clear(paidInput)
    await user.type(paidInput, '80')
    expect(within(dialog).getByTestId('rival-bet-stake')).toHaveTextContent(
      '100',
    )
    expect(within(dialog).getByTestId('rival-bet-payout')).toHaveTextContent(
      '150',
    )

    await user.click(within(dialog).getByRole('button', { name: '确认下注' }))

    await waitFor(() =>
      expect(
        screen.queryByTestId('rival-bet-dialog'),
      ).not.toBeInTheDocument(),
    )
    expect(await screen.findByTestId('rival-bet-status-周注')).toHaveTextContent(
      '周注 · 已下注',
    )
    expect(posted).toEqual({
      kind: 'weekly',
      target_margin: 150,
      paid_stake: 80,
      request_id: expect.any(String),
    })
    expect(posted).not.toHaveProperty('stake')
    const post = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input).includes('/v1/me/bets') && init?.method === 'POST',
    )
    expect(post).toBeTruthy()
  })

  it('shows a readable 409 reason and keeps the dialog open', async () => {
    const user = userEvent.setup()
    installApi({
      state: makeState(),
      placeError: {
        status: 409,
        payload: {
          detail: { code: 'already_placed', message: '本期已经下注' },
        },
      },
    })

    renderRivalPage()

    await user.click(await screen.findByRole('button', { name: '下注周注' }))
    const dialog = await screen.findByTestId('rival-bet-dialog')
    await user.click(
      within(dialog).getByRole('button', { name: '确认下注' }),
    )

    expect(await screen.findByTestId('rival-bet-error')).toHaveTextContent(
      '本期已经下过注了，下个周期再来。',
    )
    expect(screen.getByTestId('rival-bet-dialog')).toBeInTheDocument()
  })
})
