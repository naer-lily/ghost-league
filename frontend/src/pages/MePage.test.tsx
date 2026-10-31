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

  it('renders one player row, a flat stat trio, a small ring and my rank row', async () => {
    vi.stubGlobal('fetch', mockSnapshot())

    renderMe()

    const header = await screen.findByTestId('player-header')
    expect(header.children).toHaveLength(4)
    expect(screen.getAllByTestId('tier-icon')).toHaveLength(1)
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

    const week = screen.getByTestId('me-stat-week')
    const rank = screen.getByTestId('me-stat-rank')
    const embers = screen.getByTestId('me-stat-embers')
    expect(week).toHaveTextContent('本周')
    expect(week).toHaveTextContent('524 XP')
    expect(week.querySelectorAll('small')).toHaveLength(1)
    expect(week.querySelector('small')).toHaveTextContent('XP')
    expect(rank).toHaveTextContent('排名')
    expect(rank).toHaveTextContent('10')
    expect(embers).toHaveTextContent('余烬')
    expect(embers).toHaveTextContent('0')

    const ring = screen.getByRole('progressbar', { name: '今日 XP 目标' })
    expect(ring).toHaveAttribute('aria-valuenow', '100')
    expect(ring).toHaveStyle({ width: '68px', height: '68px' })

    const rankRow = screen.getByRole('link', {
      name: '我的榜单位置，第 10 名',
    })
    expect(rankRow).toHaveAttribute('href', '/league')
    expect(rankRow).toHaveTextContent('我的榜单位置')
    expect(rankRow).toHaveTextContent('10')

    expect(document.querySelectorAll('[class*="card"]')).toHaveLength(0)
    expect(document.body.textContent ?? '').not.toMatch(/连胜|连续|已打卡/)
  })
})
