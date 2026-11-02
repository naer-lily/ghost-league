import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type {
  Bet,
  BetOptions,
  BetsState,
  FriendSummary,
  GroupMarketOption,
  PlaceBetResult,
  RivalState,
} from '../api/types'
import { formatNumber } from '../lib/home'
import {
  makeBetOptions,
  makeGroupMarkets,
  makeSnapshot,
} from '../test/fixtures'
import { LeaguePage } from './LeaguePage'

const HOUR = 3_600_000

function futureIso(hours: number): string {
  return new Date(Date.now() + hours * HOUR).toISOString()
}

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

const PUBLIC_USER = {
  user_id: 'ch-kookouse',
  display_name: '@kookouse',
  avatar_url: null,
  activity_label: '绘画',
  tier: 'Silver',
  group_id: 1,
  week_start: '2026-10-26',
  xp: 4071,
  rank: 4,
  group_size: 15,
  checkin: 'verified',
  streak: 2,
  equipped_title: null,
  frame: null,
  backdrop: null,
  badge_accent: null,
  is_following: false,
  following_count: 1,
  followers_count: 0,
  comparison: {
    viewer_id: 'naer-lily',
    target_id: 'ch-kookouse',
    viewer_xp: 524,
    target_xp: 4071,
    viewer_rank: 10,
    target_rank: 4,
    viewer_group_size: 15,
    target_group_size: 15,
    xp_diff: -3547,
    leader: 'them',
  },
}

function renderLeague() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { gcTime: 0, retry: false, refetchOnWindowFocus: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <LeaguePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function friend(
  user_id: string,
  display_name: string,
  xp: number,
): FriendSummary {
  return {
    user_id,
    display_name,
    avatar_url: null,
    activity_label: '绘画',
    tier: 'Bronze',
    group_id: 2,
    week_start: '2026-10-26',
    xp,
    rank: 4,
    group_size: 15,
    checkin: 'verified',
    streak: 2,
    equipped_title: null,
    frame: null,
    backdrop: null,
    badge_accent: null,
    is_following: true,
    following_count: 2,
    followers_count: 0,
  }
}

function groupBet(overrides: Partial<Bet> = {}): Bet {
  return {
    id: 9,
    kind: 'group',
    period_key: '2026-10-26',
    rival_id: null,
    stake: 520,
    free_stake: 20,
    paid_stake: 500,
    market: 'top3',
    target_rank: 3,
    target_margin: 0,
    odds: 2,
    status: 'placed',
    placed_at: new Date().toISOString(),
    locked_at: null,
    settled_at: null,
    payout: 0,
    result_diff: null,
    group_id: 1,
    group_rank: null,
    ...overrides,
  }
}

function makeBetsState(
  betOptions: BetOptions,
  existingGroupBet: Bet | null = null,
  groups?: GroupMarketOption[],
): BetsState {
  const markets = groups ?? betOptions.group?.markets ?? []
  return {
    server_now: new Date().toISOString(),
    week_start: '2026-10-26',
    day: '2026-10-26',
    weekly: null,
    daily: null,
    group: existingGroupBet,
    groups: markets,
    bets: {
      weekly: null,
      daily: null,
      group: existingGroupBet,
      groups: markets,
    },
    bet_options: betOptions,
    bet_windows: {
      weekly_locks_at: futureIso(4),
      daily_locks_at: futureIso(2),
      daily_settles_at: futureIso(3),
    },
  }
}

function rivalStateFrom(bets: BetsState): RivalState {
  return {
    server_now: bets.server_now,
    week_start: bets.week_start,
    selection: {
      open: true,
      locks_at: bets.bet_windows.weekly_locks_at,
      auto_select_at: futureIso(28),
      mode: null,
    },
    me: {
      user_id: 'naer-lily',
      display_name: '那尔',
      avatar_url: null,
      group_no: 1,
      tier: 'Bronze',
      power: 1667,
      week_xp: 524,
      today_xp: 129,
    },
    rival: null,
    result: null,
    bets: bets.bets,
    bet_options: bets.bet_options,
    projection: null,
    bet_windows: bets.bet_windows,
  }
}

interface MockOptions {
  bets?: BetsState
  place?: (body: Record<string, unknown>) => PlaceBetResult
  snapshot?: ReturnType<typeof makeSnapshot>
}

function mockApi(friends: FriendSummary[], options: MockOptions = {}) {
  const snapshot = options.snapshot ?? makeSnapshot()
  let bets =
    options.bets ?? makeBetsState(makeBetOptions({ group: null }))
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.includes('/v1/me/friends/standings')) {
      return response({ week_start: '2026-10-26', members: friends })
    }
    if (url.includes('/v1/users/')) return response(PUBLIC_USER)
    if (url.includes('/v1/me/bets') && method === 'POST') {
      if (!options.place) return response({ detail: 'not configured' }, 500)
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<
        string,
        unknown
      >
      const result = options.place(body)
      bets = {
        ...bets,
        server_now: result.state.server_now,
        weekly: result.state.bets.weekly,
        daily: result.state.bets.daily,
        group: result.state.bets.group,
        groups: result.state.bets.groups ?? bets.groups ?? [],
        bets: result.state.bets,
        bet_options: result.state.bet_options,
        bet_windows: result.state.bet_windows,
      }
      return response(result)
    }
    if (url.includes('/v1/me/bets')) return response(bets)
    if (url.includes('/v1/me/profile')) return response(snapshot.profile)
    if (url.includes('/v1/me/status')) return response(snapshot.status)
    if (url.includes('/v1/league/standings')) return response(snapshot.standings)
    return response({ detail: 'not found' }, 404)
  })
}

describe('LeaguePage tabs', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the full group board with 4 promotion and 4 demotion zones', async () => {
    const snapshot = makeSnapshot({
      standings: {
        group: {
          id: 1,
          no: 1,
          tier: 'Silver',
          week_start: '2026-10-26',
          size: 15,
        },
      },
    })
    vi.stubGlobal('fetch', mockApi([], { snapshot }))

    renderLeague()

    const list = await screen.findByRole('list', { name: '完整小组榜' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows).toHaveLength(snapshot.standings.standings.length)
    expect(screen.getByTestId('board-tab-group')).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByTestId('board-tab-friends')).toHaveAttribute(
      'aria-selected',
      'false',
    )
    expect(screen.queryByLabelText('小组人数')).not.toBeInTheDocument()
    expect(screen.getByLabelText(/结算倒计时/)).toBeInTheDocument()
    expect(screen.queryByText('我的组')).not.toBeInTheDocument()
    expect(screen.queryByText(/G01|组号/)).not.toBeInTheDocument()

    for (const [index, row] of rows.entries()) {
      const zone = within(row).queryByTestId('standing-zone')
      if (index < 4) {
        expect(zone).toHaveTextContent('晋升')
      } else if (index >= rows.length - 4) {
        expect(zone).toHaveTextContent('下降')
      } else {
        expect(zone).not.toBeInTheDocument()
      }
    }

    const me = screen.getByRole('listitem', {
      name: /那尔，第 10 名.*我的位置/,
    })
    expect(me).toHaveAttribute('data-me', 'true')
    expect(within(me).getByTestId('standing-rank')).toHaveTextContent('10')
    for (const [index, row] of rows.entries()) {
      const power = snapshot.standings.standings[index]!.power
      expect(within(row).getByTestId('standing-power')).toHaveTextContent(
        `战力 ${power === null ? '—' : formatNumber(power)}`,
      )
    }
  })

  it('opens a public profile from a standings avatar', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', mockApi([]))

    renderLeague()

    const list = await screen.findByRole('list', { name: '完整小组榜' })
    const rows = within(list).getAllByRole('listitem')
    await user.click(within(rows[3]!).getByTestId('standing-avatar'))

    const sheet = await screen.findByTestId('user-profile-sheet')
    expect(
      within(sheet).getByRole('heading', { name: '@kookouse' }),
    ).toBeInTheDocument()
    expect(within(sheet).getByTestId('profile-comparison')).toHaveTextContent(
      '我和他的本周对比',
    )
    expect(within(sheet).getByTestId('profile-follow')).toBeVisible()
    expect(within(sheet).queryByText('720')).not.toBeInTheDocument()
  })

  it('shows only followed people in the friends board, ranked by XP', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi([
        friend('naer-lily', '那尔', 524),
        friend('friend-a', '阿岚', 900),
        friend('friend-b', '小满', 1200),
      ]),
    )

    renderLeague()
    await userEvent.click(await screen.findByTestId('board-tab-friends'))

    const list = await screen.findByRole('list', { name: '好友榜' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveAccessibleName(/小满，第 1 名/)
    expect(rows[1]).toHaveAccessibleName(/阿岚，第 2 名/)
    expect(screen.queryByText('那尔', { selector: 'p' })).not.toBeInTheDocument()
    expect(within(rows[0]!).queryByTestId('standing-power')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '好友榜' })).toBeVisible()
  })

  it('shows an honest empty state when there are no follows', async () => {
    vi.stubGlobal('fetch', mockApi([friend('naer-lily', '那尔', 524)]))

    renderLeague()
    await userEvent.click(await screen.findByTestId('board-tab-friends'))

    expect(await screen.findByTestId('friends-empty')).toHaveTextContent(
      '还没有关注的好友',
    )
    await waitFor(() =>
      expect(screen.queryByRole('list', { name: '好友榜' })).not.toBeInTheDocument(),
    )
  })

  it('shows three independent group markets only on the group tab', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      mockApi([], { bets: makeBetsState(makeBetOptions()) }),
    )

    renderLeague()

    const card = await screen.findByTestId('group-bet-card')
    expect(card).not.toHaveTextContent('小组总 XP')
    expect(card).not.toHaveTextContent('我本人在本组')
    for (const [market, label, odds] of [
      ['top3', '押前三', '×5.13'],
      ['promote', '押升段', '×4.19'],
      ['no_demote', '押不降段', '×1.62'],
    ] as const) {
      const panel = within(card).getByTestId(`group-market-${market}`)
      expect(within(panel).getByRole('heading', { name: label })).toBeVisible()
      expect(
        within(panel).getByTestId(`group-market-odds-${market}`),
      ).toHaveTextContent(odds)
      expect(
        within(panel).getByTestId(`group-market-taken-${market}`),
      ).toHaveTextContent('未下注')
      expect(
        within(panel).getByTestId(`group-bet-open-${market}`),
      ).toBeEnabled()
    }

    await user.click(screen.getByTestId('board-tab-friends'))
    expect(screen.queryByTestId('group-bet-card')).not.toBeInTheDocument()
  })

  it('only renders the markets the server allows for the tier', async () => {
    const betOptions = makeBetOptions({
      group: {
        target_rank: 3,
        target_margin: 0,
        min_paid_stake: 0,
        max_paid_stake: 500,
        free_stake: 20,
        odds: 5.13,
        markets: makeGroupMarkets().filter(
          (market) => market.market !== 'no_demote',
        ),
      },
    })
    vi.stubGlobal(
      'fetch',
      mockApi([], { bets: makeBetsState(betOptions) }),
    )

    renderLeague()

    const card = await screen.findByTestId('group-bet-card')
    expect(within(card).getByTestId('group-market-top3')).toBeInTheDocument()
    expect(within(card).getByTestId('group-market-promote')).toBeInTheDocument()
    expect(
      within(card).queryByTestId('group-market-no_demote'),
    ).not.toBeInTheDocument()
  })

  it('hides the group bet card when the server has no group option', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi([], {
        bets: makeBetsState(makeBetOptions({ group: null })),
      }),
    )

    renderLeague()

    await screen.findByRole('list', { name: '完整小组榜' })
    expect(screen.queryByTestId('group-bet-card')).not.toBeInTheDocument()
    expect(screen.queryByTestId('group-bet-open')).not.toBeInTheDocument()
  })

  it('places one group market with market + paid_stake and no stake field', async () => {
    const user = userEvent.setup()
    const betOptions = makeBetOptions()
    const placed = groupBet({ market: 'promote', target_rank: 4, odds: 4.19 })
    let posted: Record<string, unknown> | null = null
    const placedMarkets = makeGroupMarkets({
      promote: {
        can_place: false,
        reason: 'already_placed',
        status: 'placed',
        bet: placed,
      },
    })
    vi.stubGlobal(
      'fetch',
      mockApi([], {
        bets: makeBetsState(betOptions),
        place: (body) => {
          posted = body
          return {
            bet: placed,
            state: rivalStateFrom(
              makeBetsState(betOptions, placed, placedMarkets),
            ),
          }
        },
      }),
    )

    renderLeague()

    await user.click(await screen.findByTestId('group-bet-open-promote'))
    const dialog = await screen.findByTestId('group-bet-dialog')
    expect(dialog).toHaveAttribute('data-market', 'promote')
    expect(
      within(dialog).getByRole('heading', { name: '押升段' }),
    ).toBeInTheDocument()
    const paidInput = within(dialog).getByTestId('group-bet-paid-input')
    expect(paidInput).toHaveValue(0)
    expect(within(dialog).getByTestId('group-bet-stake')).toHaveTextContent(
      '20',
    )

    await user.clear(paidInput)
    await user.type(paidInput, '500')
    expect(within(dialog).getByTestId('group-bet-paid')).toHaveTextContent(
      '500',
    )
    expect(within(dialog).getByTestId('group-bet-payout')).toHaveTextContent(
      '2,179',
    )

    await user.click(within(dialog).getByRole('button', { name: '确认下注' }))

    await waitFor(() =>
      expect(screen.queryByTestId('group-bet-dialog')).not.toBeInTheDocument(),
    )
    const promote = await screen.findByTestId('group-market-promote')
    expect(within(promote).getByTestId('group-bet-placed')).toHaveTextContent(
      '已下注',
    )
    expect(
      within(await screen.findByTestId('group-market-top3')).getByTestId(
        'group-market-taken-top3',
      ),
    ).toHaveTextContent('未下注')
    expect(posted).toEqual({
      kind: 'group',
      market: 'promote',
      paid_stake: 500,
      request_id: expect.any(String),
    })
    expect(posted).not.toHaveProperty('stake')
    expect(posted).not.toHaveProperty('target_margin')
  })
})
