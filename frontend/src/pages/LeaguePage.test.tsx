import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type { FriendSummary } from '../api/types'
import { formatNumber } from '../lib/home'
import { makeSnapshot } from '../test/fixtures'
import { LeaguePage } from './LeaguePage'

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

function mockApi(friends: FriendSummary[]) {
  const snapshot = makeSnapshot()
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/v1/me/friends/standings')) {
      return response({ week_start: '2026-10-26', members: friends })
    }
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
})
