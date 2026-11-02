import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import { makeSnapshot } from '../test/fixtures'
import { useUiStore } from '../store/useUiStore'
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

describe('MePage rework', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    useUiStore.setState({ settingsOpen: false })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders diamonds, streak, weekly stats, horizontal tiers and menu entries', async () => {
    vi.stubGlobal('fetch', mockSnapshot())

    renderMe()

    const header = await screen.findByTestId('player-header')
    expect(header.children).toHaveLength(5)
    expect(screen.getByTestId('player-diamonds')).toHaveTextContent('720')
    expect(screen.getByTestId('player-tier')).toHaveTextContent('青铜')
    expect(screen.getByTestId('player-tier')).not.toHaveTextContent('G01')
    expect(screen.getByTestId('streak-badge')).toHaveTextContent('2')

    const stages = screen.getAllByTestId('tier-stage')
    expect(stages).toHaveLength(10)
    expect(stages[0]).toHaveAttribute('data-state', 'current')
    expect(stages[0]).toHaveAttribute('aria-current', 'step')
    expect(stages[1]).toHaveAttribute('data-state', 'future')
    expect(screen.getByTestId('tier-progress')).toHaveTextContent('第 1 / 10 阶段')

    const week = screen.getByTestId('me-stat-week')
    const today = screen.getByTestId('me-stat-today')
    const rank = screen.getByTestId('me-stat-rank')
    expect(week).toHaveTextContent('本周 XP')
    expect(week).toHaveTextContent('524')
    expect(today).toHaveTextContent('今日 XP')
    expect(today).toHaveTextContent('129')
    expect(rank).toHaveTextContent('本周排名')
    expect(rank).toHaveTextContent('10')
    expect(rank).not.toHaveTextContent('/15')

    expect(screen.getByTestId('me-streak-current')).toHaveTextContent('2')
    expect(screen.getByTestId('me-streak-longest')).toHaveTextContent('2')
    expect(screen.getByTestId('me-streak-checkin')).toHaveTextContent('已打卡')

    const resources = screen.getByTestId('me-resource-row')
    expect(resources).toHaveAttribute('href', '/inventory')
    expect(resources).toHaveTextContent('钻石')
    expect(resources).toHaveTextContent('星星')
    expect(resources).not.toHaveTextContent('星图')
    expect(within(resources).getByTestId('me-diamonds')).toHaveTextContent('720')
    expect(within(resources).getByTestId('me-stars')).toHaveTextContent('1')
    expect(within(resources).getByTestId('me-power')).toHaveTextContent('1,667')

    expect(
      screen.queryByRole('link', { name: '我的榜单位置，第 10 名' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByText(/G01|我的组|组号/)).not.toBeInTheDocument()
    expect(screen.getByTestId('pull-to-refresh')).toBeInTheDocument()

    const menu = screen.getByRole('navigation', { name: '我的菜单' })
    expect(within(menu).getByRole('link', { name: /物品栏/ })).toHaveAttribute(
      'href',
      '/inventory',
    )
    expect(within(menu).getByRole('link', { name: /历史/ })).toHaveAttribute(
      'href',
      '/history',
    )
  })

  it('opens the existing settings dialog from the Me menu', async () => {
    vi.stubGlobal('fetch', mockSnapshot())
    renderMe()

    await screen.findByTestId('player-header')
    await userEvent.click(screen.getByRole('button', { name: /设置/ }))
    expect(useUiStore.getState().settingsOpen).toBe(true)
  })
})
