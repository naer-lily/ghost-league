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
  PlaceBetResult,
  RivalState,
} from '../api/types'
import { formatNumber } from '../lib/home'
import { makeBetOptions, makeSnapshot } from '../test/fixtures'
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
): BetsState {
  return {
    server_now: new Date().toISOString(),
    week_start: '2026-10-26',
    day: '2026-10-26',
    weekly: null,
    daily: null,
    group: existingGroupBet,
    bets: {
      weekly: null,
      daily: null,
      group: existingGroupBet,
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
}

function mockApi(friends: FriendSummary[], options: MockOptions = {}) {
  const snapshot = makeSnapshot()
  let bets =
    options.bets ?? makeBetsState(makeBetOptions({ group: null }))
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.includes('/v1/me/friends/standings')) {
      return response({ week_start: '2026-10-26', members: friends })
    }
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

  it('renders the full group board without a group size count', async () => {
    const snapshot = makeSnapshot()
    vi.stubGlobal('fetch', mockApi([]))

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

  it('shows the personal top-three group bet card only on the group tab', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      mockApi([], { bets: makeBetsState(makeBetOptions()) }),
    )

    renderLeague()

    const card = await screen.findByTestId('group-bet-card')
    expect(card).toHaveTextContent('押我本人在本组本周排名前三')
    expect(card).not.toHaveTextContent('我们组进前三')
    expect(within(card).getByTestId('group-bet-target-rank')).toHaveTextContent(
      '前三（第 3 名内）',
    )
    expect(within(card).getByTestId('group-bet-card-odds')).toHaveTextContent(
      '×2.00',
    )
    expect(card).toHaveTextContent('20')
    expect(card).toHaveTextContent('0–500 钻石')
    expect(screen.getByTestId('group-bet-open')).toHaveTextContent('下注组注')

    await user.click(screen.getByTestId('board-tab-friends'))
    expect(screen.queryByTestId('group-bet-card')).not.toBeInTheDocument()
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

  it('places a group bet with paid_stake and no stake field', async () => {
    const user = userEvent.setup()
    const betOptions = makeBetOptions()
    const placed = groupBet()
    let posted: Record<string, unknown> | null = null
    vi.stubGlobal(
      'fetch',
      mockApi([], {
        bets: makeBetsState(betOptions),
        place: (body) => {
          posted = body
          return {
            bet: placed,
            state: rivalStateFrom(makeBetsState(betOptions, placed)),
          }
        },
      }),
    )

    renderLeague()

    await user.click(await screen.findByTestId('group-bet-open'))
    const dialog = await screen.findByTestId('group-bet-dialog')
    expect(dialog).toHaveTextContent('押「我本人在本组本周排名前三」')
    const paidInput = within(dialog).getByTestId('group-bet-paid-input')
    expect(paidInput).toHaveValue(0)
    expect(within(dialog).getByTestId('group-bet-stake')).toHaveTextContent(
      '20',
    )
    expect(within(dialog).getByTestId('group-bet-payout')).toHaveTextContent(
      '40',
    )

    await user.clear(paidInput)
    await user.type(paidInput, '500')
    expect(within(dialog).getByTestId('group-bet-paid')).toHaveTextContent(
      '500',
    )
    expect(within(dialog).getByTestId('group-bet-stake')).toHaveTextContent(
      '520',
    )
    expect(within(dialog).getByTestId('group-bet-payout')).toHaveTextContent(
      '1,040',
    )

    await user.click(within(dialog).getByRole('button', { name: '确认下注' }))

    await waitFor(() =>
      expect(screen.queryByTestId('group-bet-dialog')).not.toBeInTheDocument(),
    )
    expect(await screen.findByTestId('group-bet-placed')).toHaveTextContent(
      '已下注',
    )
    expect(posted).toEqual({
      kind: 'group',
      paid_stake: 500,
      request_id: expect.any(String),
    })
    expect(posted).not.toHaveProperty('stake')
    expect(posted).not.toHaveProperty('target_margin')
  })
})
