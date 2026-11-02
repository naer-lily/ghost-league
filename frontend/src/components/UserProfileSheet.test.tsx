import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type { UserSummary } from '../api/types'
import { UserProfileSheet } from './UserProfileSheet'

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

function selfSummary(): UserSummary {
  return {
    user_id: 'naer-lily',
    handle: 'naer-lily',
    display_name: '那尔',
    avatar_url: null,
    activity_label: '绘画',
    tier: 'Silver',
    group_id: 1,
    week_start: '2026-10-26',
    xp: 524,
    power: 1667,
    rank: 10,
    group_size: 15,
    checkin: 'verified',
    streak: 2,
    equipped_title: null,
    frame: null,
    backdrop: null,
    badge_accent: null,
    is_following: false,
    following_count: 2,
    followers_count: 3,
    comparison: null,
  }
}

function aiSummary(): UserSummary {
  return {
    ...selfSummary(),
    user_id: 'ch-kookouse',
    handle: null,
    display_name: 'Kookouse',
    activity_label: null,
  }
}

function renderSheet(userId = 'naer-lily') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { gcTime: 0, retry: false, refetchOnWindowFocus: false } },
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

  it('does not repeat a comparison block when viewing yourself', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response(selfSummary())))

    renderSheet()

    const sheet = await screen.findByTestId('user-profile-sheet')
    expect(await within(sheet).findByTestId('profile-xp')).toHaveTextContent(
      '524',
    )
    expect(within(sheet).queryByTestId('profile-comparison')).not.toBeInTheDocument()
    expect(within(sheet).getByTestId('profile-follow')).toBeVisible()
    expect(within(sheet).getByText('@naer-lily')).toBeVisible()
    expect(
      within(sheet).queryByText(
        '只展示公开的联赛信息；钻石、下注和其他私有数据不会出现在这里。',
      ),
    ).not.toBeInTheDocument()
  })

  it('does not expose an AI generated user id as a handle', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response(aiSummary())))

    renderSheet('ch-kookouse')

    const sheet = await screen.findByTestId('user-profile-sheet')
    expect(await within(sheet).findByTestId('profile-xp')).toHaveTextContent(
      '524',
    )
    expect(
      within(sheet).getByRole('heading', { name: 'Kookouse' }),
    ).toBeVisible()
    expect(within(sheet).queryByText('@ch-kookouse')).not.toBeInTheDocument()
    expect(within(sheet).getByTestId('profile-follow')).toBeVisible()
  })
})
