import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type { FeedItem, FriendSummary, UserSummary } from '../api/types'
import { makeSnapshot } from '../test/fixtures'
import { LeaguePage } from './LeaguePage'

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

function friendSummary(following: boolean): FriendSummary {
  return {
    user_id: 'friend-a',
    handle: 'friend-a',
    display_name: '阿岚',
    avatar_url: null,
    activity_label: '画画',
    tier: 'Silver',
    group_id: 2,
    week_start: '2026-10-26',
    xp: 900,
    power: 450,
    rank: 4,
    group_size: 15,
    checkin: 'verified',
    streak: 6,
    equipped_title: '点火',
    frame: null,
    backdrop: null,
    badge_accent: null,
    is_following: following,
    following_count: 3,
    followers_count: following ? 1 : 0,
  }
}

function publicProfile(following: boolean): UserSummary {
  return {
    ...friendSummary(following),
    comparison: {
      viewer_id: 'naer-lily',
      target_id: 'friend-a',
      viewer_xp: 524,
      target_xp: 900,
      viewer_rank: 10,
      target_rank: 4,
      viewer_group_size: 15,
      target_group_size: 15,
      xp_diff: -376,
      leader: 'them',
    },
  }
}

const FEED_ITEM: FeedItem = {
  id: 1,
  kind: 'checkin',
  day: '2026-11-02',
  body: '今天点着了 900 XP',
  author: {
    id: 'friend-a',
    name: '阿岚',
    title: '点火',
    frame: null,
    avatar_url: null,
  },
  reactions: [{ emoji: '盯', count: 2, mine: false }],
  tags: [{ tag: '稳', count: 1 }],
  created_at: '2026-11-02T22:00:00+08:00',
}

function renderLeague() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { gcTime: 0, retry: false, refetchOnWindowFocus: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <LeaguePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('League feed and public profile', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('opens a public profile from the feed and updates the friends board', async () => {
    const user = userEvent.setup()
    const snapshot = makeSnapshot()
    let followed = false
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        const method = init?.method ?? 'GET'
        if (url.includes('/v1/me/friends/standings')) {
          return response({
            week_start: '2026-10-26',
            members: followed ? [friendSummary(true)] : [],
          })
        }
        if (url.includes('/v1/league/feed')) {
          return response({
            week_start: '2026-10-26',
            generated_at: new Date().toISOString(),
            items: [FEED_ITEM],
          })
        }
        if (url.includes('/v1/users/friend-a')) {
          return response(publicProfile(followed))
        }
        if (url.includes('/v1/me/follows/friend-a')) {
          if (method === 'POST') {
            followed = true
            return response(friendSummary(true))
          }
          if (method === 'DELETE') {
            followed = false
            return response(null, 204)
          }
        }
        if (url.includes('/v1/me/bets')) {
          return response({
            server_now: new Date().toISOString(),
            week_start: '2026-10-26',
            day: '2026-11-02',
            weekly: null,
            daily: null,
            group: null,
            bets: { weekly: null, daily: null, group: null },
            bet_options: { weekly: null, daily: null, group: null },
            bet_windows: {
              weekly_locks_at: '2026-11-02T23:59:59+08:00',
              daily_locks_at: '2026-11-02T21:00:00+08:00',
              daily_settles_at: '2026-11-02T22:30:00+08:00',
            },
          })
        }
        if (url.includes('/v1/me/profile')) return response(snapshot.profile)
        if (url.includes('/v1/me/status')) return response(snapshot.status)
        if (url.includes('/v1/league/standings')) return response(snapshot.standings)
        return response({ detail: 'not found' }, 404)
      },
    )
    vi.stubGlobal('fetch', fetchMock)

    renderLeague()
    await screen.findByRole('list', { name: '完整小组榜' })

    await user.click(screen.getByTestId('board-tab-feed'))
    const feed = await screen.findByTestId('league-feed')
    expect(within(feed).getByTestId('feed-author')).toHaveTextContent('阿岚')
    expect(feed).toHaveTextContent('今天点着了 900 XP')
    expect(feed).toHaveTextContent('盯')
    expect(feed).toHaveTextContent('#稳')

    await user.click(within(feed).getByTestId('feed-item'))
    const sheet = await screen.findByTestId('user-profile-sheet')
    expect(within(sheet).getByTestId('profile-xp')).toHaveTextContent('900')
    expect(within(sheet).getByTestId('profile-power')).toHaveTextContent('450')
    expect(within(sheet).getByTestId('profile-rank')).toHaveTextContent(
      '第 4 / 15 名',
    )
    expect(within(sheet).getByTestId('profile-streak')).toHaveTextContent('6')
    expect(within(sheet).getByTestId('profile-following')).toHaveTextContent('3')
    expect(within(sheet).getByTestId('profile-followers')).toHaveTextContent('0')
    expect(within(sheet).queryByText('720')).not.toBeInTheDocument()
    const comparison = within(sheet).getByTestId('profile-comparison')
    expect(within(comparison).getByTestId('profile-comparison-me')).toHaveTextContent(
      '524',
    )
    expect(
      within(comparison).getByTestId('profile-comparison-them'),
    ).toHaveTextContent('900')
    expect(
      within(comparison).getByTestId('profile-comparison-diff'),
    ).toHaveTextContent('-376')
    expect(
      within(comparison).getByTestId('profile-comparison-leader'),
    ).toHaveTextContent('阿岚领先 376 XP')

    const followButton = within(sheet).getByTestId('profile-follow')
    expect(followButton).toHaveAttribute('aria-pressed', 'false')
    await user.click(followButton)
    await waitFor(() =>
      expect(within(sheet).getByTestId('profile-follow')).toHaveAttribute(
        'aria-pressed',
        'true',
      ),
    )
    expect(within(sheet).getByTestId('profile-followers')).toHaveTextContent('1')
    expect(followed).toBe(true)

    await user.click(
      within(sheet).getByRole('button', { name: '关闭选手资料' }),
    )
    await waitFor(() =>
      expect(screen.queryByTestId('user-profile-sheet')).not.toBeInTheDocument(),
    )

    await user.click(screen.getByTestId('board-tab-friends'))
    const friends = await screen.findByRole('list', { name: '好友榜' })
    expect(within(friends).getByText('阿岚')).toBeVisible()

    await user.click(screen.getByTestId('board-tab-feed'))
    await user.click(await screen.findByTestId('feed-item'))
    const reopened = await screen.findByTestId('user-profile-sheet')
    const followedButton = within(reopened).getByTestId('profile-follow')
    expect(followedButton).toHaveAttribute('aria-pressed', 'true')
    await user.click(followedButton)
    await waitFor(() =>
      expect(within(reopened).getByTestId('profile-follow')).toHaveAttribute(
        'aria-pressed',
        'false',
      ),
    )
    expect(followed).toBe(false)

    await user.click(
      within(reopened).getByRole('button', { name: '关闭选手资料' }),
    )
    await user.click(screen.getByTestId('board-tab-friends'))
    expect(await screen.findByTestId('friends-empty')).toHaveTextContent(
      '还没有关注的好友',
    )
  })
})
