import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import { makeSnapshot } from '../test/fixtures'
import { MePage } from './MePage'

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

function renderMe() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { gcTime: 0, refetchOnWindowFocus: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <MePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function mockSnapshot(snapshot = makeSnapshot()) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/v1/me/profile')) return response(snapshot.profile)
    if (url.includes('/v1/me/status')) return response(snapshot.status)
    if (url.includes('/v1/league/standings')) return response(snapshot.standings)
    return response({ detail: 'not found' }, 404)
  })
}

describe('MePage', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the profile, old tier icon, streak and compact stats', async () => {
    vi.stubGlobal('fetch', mockSnapshot())

    renderMe()

    expect(await screen.findByRole('heading', { name: '那尔' })).toBeInTheDocument()
    expect(screen.getByTestId('tier-icon')).toBeInTheDocument()
    expect(
      screen.getByTestId('tier-icon').querySelector('img')?.getAttribute('src'),
    ).toBe('/assets/tiers/material/bronze.png')
    expect(
      screen
        .getAllByTestId('streak-badge')
        .some(
          (badge) =>
            badge.getAttribute('aria-label') === '连续 2 天，今天已打卡',
        ),
    ).toBe(true)
    expect(screen.getByText('本周')).toBeInTheDocument()
    expect(screen.getByText('排名')).toBeInTheDocument()
    expect(screen.getByText('余烬')).toBeInTheDocument()
    expect(
      screen.getByRole('progressbar', { name: '今日 XP 目标' }),
    ).toHaveAttribute('aria-valuenow', '100')
    expect(document.body.textContent ?? '').not.toMatch(/连胜|连续|已打卡/)
  })
})
