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
    display_name: '那尔',
    avatar_url: null,
    activity_label: '绘画',
    tier: 'Silver',
    group_id: 1,
    week_start: '2026-10-26',
    xp: 524,
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

function renderSheet() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { gcTime: 0, retry: false, refetchOnWindowFocus: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <UserProfileSheet userId="naer-lily" onOpenChange={() => undefined} />
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
  })
})
