import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
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
    defaultOptions: { queries: { gcTime: 0, refetchOnWindowFocus: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <LeaguePage />
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

describe('LeaguePage', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders every API row with bare ranks, medal colors and an unlabelled XP column', async () => {
    const snapshot = makeSnapshot()
    vi.stubGlobal('fetch', mockSnapshot(snapshot))

    renderLeague()

    const list = await screen.findByRole('list', { name: '完整小组榜' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows).toHaveLength(snapshot.standings.standings.length)
    expect(rows).toHaveLength(15)

    expect(screen.getByTestId('player-header').children).toHaveLength(4)
    expect(screen.getAllByTestId('tier-icon')).toHaveLength(1)

    const medalColors = [
      'rgb(255, 200, 0)',
      'rgb(207, 216, 230)',
      'rgb(208, 138, 90)',
    ]
    const medalNames = ['gold', 'silver', 'bronze']
    for (const [index, row] of rows.slice(0, 3).entries()) {
      const rank = within(row).getByTestId('standing-rank')
      expect(rank).toHaveAttribute('data-rank', String(index + 1))
      expect(rank).toHaveAttribute('data-medal', medalNames[index])
      expect(window.getComputedStyle(rank).color).toBe(medalColors[index])
    }
    for (const row of rows.slice(3)) {
      expect(within(row).getByTestId('standing-rank')).not.toHaveAttribute(
        'data-medal',
      )
    }

    const me = screen.getByRole('listitem', {
      name: /那尔，第 10 名.*我的位置/,
    })
    expect(me).toHaveAttribute('data-me', 'true')
    expect(within(me).getByTestId('streak-badge')).toBeInTheDocument()
    expect(within(me).getByTestId('standing-rank')).toHaveTextContent('10')

    for (const row of rows) {
      expect(within(row).getByTestId('streak-badge')).toBeInTheDocument()
      expect(within(row).queryByText('XP')).not.toBeInTheDocument()
      expect(row.textContent ?? '').not.toMatch(
        /XP|语言|今日已完成|今日未完成|连续|连胜|已打卡/,
      )
    }
    expect(screen.getAllByText('XP')).toHaveLength(1)

    expect(screen.getByLabelText(/结算倒计时/)).toBeInTheDocument()
    expect(screen.queryByText(/前三/)).not.toBeInTheDocument()
    expect(document.querySelectorAll('[class*="card"]')).toHaveLength(0)
  })
})
