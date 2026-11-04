import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type { UserSummary } from '../api/types'
import { makeRecentXp } from '../test/fixtures'
import { UserProfileSheet } from './UserProfileSheet'

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

function makeSummary(overrides: Partial<UserSummary> = {}): UserSummary {
  return {
    user_id: 'friend-a',
    handle: 'friend-a',
    display_name: '阿岚',
    avatar_url: null,
    activity_label: '画画',
    tier: 'Silver',
    group_id: 2,
    week_start: '2026-11-02',
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
    is_following: false,
    following_count: 3,
    followers_count: 0,
    comparison: null,
    recent_xp: makeRecentXp({
      target: [0, 0, 189, 182, 178, 150, 441],
      viewer: [0, 0, 0, 0, 0, 0, 521],
    }),
    ...overrides,
  }
}

function selfSummary(): UserSummary {
  return makeSummary({
    user_id: 'naer-lily',
    handle: 'naer-lily',
    display_name: '那尔',
    xp: 524,
    power: 1667,
    rank: 10,
    equipped_title: null,
    following_count: 2,
    followers_count: 3,
    recent_xp: makeRecentXp({
      target: [0, 0, 0, 0, 0, 0, 524],
      viewer: [0, 0, 0, 0, 0, 0, 524],
    }),
  })
}

function handlelessSummary(): UserSummary {
  return makeSummary({
    user_id: 'ch-kookouse',
    handle: null,
    display_name: 'Kookouse',
    activity_label: null,
    recent_xp: makeRecentXp({
      target: [0, 0, 0, 0, 0, 0, 0],
      viewer: [0, 0, 0, 0, 0, 0, 0],
    }),
  })
}

function renderSheet(userId = 'friend-a') {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { gcTime: 0, retry: false, refetchOnWindowFocus: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <UserProfileSheet userId={userId} onOpenChange={() => undefined} />
    </QueryClientProvider>,
  )
}

describe('UserProfileSheet', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders a full-screen profile with both recent XP lines', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response(makeSummary())))

    renderSheet()

    const sheet = await screen.findByTestId('user-profile-sheet')
    expect(
      await within(sheet).findByRole('heading', { name: '阿岚' }),
    ).toBeVisible()
    expect(within(sheet).getByRole('button', { name: '返回' })).toBeVisible()
    expect(
      within(sheet).queryByRole('button', { name: '关闭选手资料' }),
    ).not.toBeInTheDocument()
    expect(within(sheet).getByTestId('profile-handle')).toHaveTextContent(
      '@friend-a',
    )
    expect(within(sheet).getByText('@friend-a')).toBeVisible()
    expect(within(sheet).getByTestId('profile-xp')).toHaveTextContent('900')
    expect(within(sheet).getByTestId('profile-power')).toHaveTextContent('450')
    expect(within(sheet).getByTestId('profile-following')).toHaveTextContent('3')
    expect(within(sheet).getByTestId('profile-followers')).toHaveTextContent('0')

    const chart = within(sheet).getByTestId('profile-recent-chart')
    expect(chart).toBeVisible()
    expect(within(sheet).getByText('最近 7 天')).toBeVisible()
    expect(within(sheet).getByText('每天 XP')).toBeVisible()
    expect(within(chart).getByText('550')).toBeVisible()
    expect(within(chart).getByText('367')).toBeVisible()
    expect(within(chart).getByText('183')).toBeVisible()
    expect(within(chart).getByText('0')).toBeVisible()
    for (const label of ['四', '五', '六', '日', '一', '二', '三']) {
      expect(within(chart).getByText(label)).toBeVisible()
    }
    const targetLine = within(sheet).getByTestId('profile-recent-target')
    const viewerLine = within(sheet).getByTestId('profile-recent-viewer')
    expect(targetLine).toHaveAttribute('points')
    expect(viewerLine).toHaveAttribute('points')
    expect(targetLine.getAttribute('points')).not.toBe(
      viewerLine.getAttribute('points'),
    )
    expect(chart.querySelectorAll('circle')).toHaveLength(14)
    expect(within(sheet).getByText('1,140 XP')).toBeVisible()
    expect(within(sheet).getByText('521 XP')).toBeVisible()

    expect(within(sheet).getByTestId('profile-streak')).toHaveTextContent('6')
    expect(within(sheet).getByTestId('profile-rank')).toHaveTextContent(
      '第 4 / 15 名',
    )
    expect(within(sheet).getByTestId('profile-tier')).toHaveTextContent('白银')
    expect(within(sheet).getByTestId('profile-loadout')).toHaveTextContent(
      '称号 · 点火',
    )
    expect(within(sheet).getByTestId('profile-follow')).toBeEnabled()
  })

  it('follows from the profile button and updates the follower count', async () => {
    const user = userEvent.setup()
    const initial = makeSummary()
    let following = false
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === 'POST') following = true
        return response(
          following
            ? { ...initial, is_following: true, followers_count: 1 }
            : initial,
        )
      },
    )
    vi.stubGlobal('fetch', fetchMock)

    renderSheet()

    const sheet = await screen.findByTestId('user-profile-sheet')
    const button = await within(sheet).findByTestId('profile-follow')
    expect(button).toBeEnabled()
    expect(button).toHaveAttribute('aria-pressed', 'false')
    expect(button).toHaveTextContent('关注')

    await user.click(button)

    await waitFor(() =>
      expect(within(sheet).getByTestId('profile-follow')).toHaveAttribute(
        'aria-pressed',
        'true',
      ),
    )
    expect(within(sheet).getByTestId('profile-follow')).toHaveTextContent(
      '已关注',
    )
    expect(within(sheet).getByTestId('profile-followers')).toHaveTextContent('1')
    expect(fetchMock).toHaveBeenCalledWith(
      '/v1/me/follows/friend-a',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('omits the handle row without identity wording when handle is missing', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response(handlelessSummary())))

    renderSheet('ch-kookouse')

    const sheet = await screen.findByTestId('user-profile-sheet')
    expect(
      await within(sheet).findByRole('heading', { name: 'Kookouse' }),
    ).toBeVisible()
    expect(within(sheet).queryByTestId('profile-handle')).not.toBeInTheDocument()
    expect(within(sheet).queryByText('@ch-kookouse')).not.toBeInTheDocument()
    for (const word of ['AI 选手', 'AI', '机器人', '人机', 'Channel', 'provider']) {
      expect(within(sheet).queryByText(word, { exact: false })).toBeNull()
    }
    expect(within(sheet).getByTestId('profile-follow')).toBeVisible()
  })

  it('shows a zeroed chart and omits empty equipment and power data', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        response(
          makeSummary({
            power: null,
            rank: null,
            group_size: 0,
            streak: 0,
            equipped_title: null,
            frame: null,
            backdrop: null,
            badge_accent: null,
            recent_xp: makeRecentXp({
              target: [0, 0, 0, 0, 0, 0, 0],
              viewer: [0, 0, 0, 0, 0, 0, 0],
            }),
          }),
        ),
      ),
    )

    renderSheet()

    const sheet = await screen.findByTestId('user-profile-sheet')
    expect(await within(sheet).findByTestId('profile-power')).toHaveTextContent(
      '—',
    )
    expect(within(sheet).getByTestId('profile-rank')).toHaveTextContent('—')
    expect(within(sheet).getByTestId('profile-streak')).toHaveTextContent('0')
    expect(within(sheet).queryByTestId('profile-loadout')).not.toBeInTheDocument()
    const chart = within(sheet).getByTestId('profile-recent-chart')
    expect(within(chart).getByText('100')).toBeVisible()
    expect(within(chart).getByText('0')).toBeVisible()
    expect(within(sheet).getAllByText('0 XP')).toHaveLength(2)
    expect(within(sheet).getByTestId('profile-recent-target')).toHaveAttribute(
      'points',
    )
    expect(within(sheet).getByTestId('profile-recent-viewer')).toHaveAttribute(
      'points',
    )
  })

  it('keeps both lines identical when viewing yourself', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response(selfSummary())))

    renderSheet('naer-lily')

    const sheet = await screen.findByTestId('user-profile-sheet')
    const targetLine = await within(sheet).findByTestId('profile-recent-target')
    const viewerLine = within(sheet).getByTestId('profile-recent-viewer')
    expect(targetLine.getAttribute('points')).toBe(
      viewerLine.getAttribute('points'),
    )
    expect(within(sheet).getByText('@naer-lily')).toBeVisible()
  })
})
