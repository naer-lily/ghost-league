import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import { makeSnapshot } from '../test/fixtures'
import { AppShell } from './AppShell'

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

function renderShell() {
  const snapshot = makeSnapshot()
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/v1/me/profile')) return response(snapshot.profile)
    if (url.includes('/v1/me/status')) return response(snapshot.status)
    if (url.includes('/v1/league/standings')) return response(snapshot.standings)
    return response({ detail: 'not found' }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { gcTime: 0, refetchOnWindowFocus: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={['/']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <AppShell />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AppShell navigation', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows icon-only navigation with accessible labels and an active block', () => {
    renderShell()

    const navs = Array.from(
      document.querySelectorAll<HTMLElement>('nav[aria-label="主导航"]'),
    )
    expect(navs).toHaveLength(2)

    const bottom = navs[1]!
    const bottomLinks = within(bottom).getAllByRole('link')
    expect(bottomLinks).toHaveLength(5)
    for (const link of bottomLinks) {
      expect(link.textContent).toBe('')
      expect(link.getAttribute('aria-label')).toBeTruthy()
      expect(link.querySelector('svg')).not.toBeNull()
    }
    expect(bottomLinks[0]).toHaveAttribute('aria-current', 'page')

    for (const link of document.querySelectorAll<HTMLAnchorElement>(
      'nav[aria-label="主导航"] a',
    )) {
      expect(link.textContent).toBe('')
      expect(link.getAttribute('aria-label')).toBeTruthy()
    }
  })

  it('shows the gem balance as an icon and number in the top bar', async () => {
    renderShell()

    const gems = await screen.findByLabelText('宝石 128')
    expect(gems).toHaveAttribute('data-testid', 'gem-balance')
    expect(gems).toHaveTextContent('128')
    expect(gems.textContent).not.toMatch(/宝石/)
    expect(gems.querySelector('svg')).not.toBeNull()
  })
})
