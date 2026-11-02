import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import { useUiStore } from '../store/useUiStore'
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
    useUiStore.setState({ settingsOpen: false })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows five icon-only nav entries with the inventory label', () => {
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
    expect(bottomLinks.map((link) => link.getAttribute('aria-label'))).toEqual([
      '首页',
      '小组',
      '物品栏',
      '历史',
      '我的',
    ])
    expect(bottomLinks.map((link) => link.getAttribute('href'))).toEqual([
      '/',
      '/league',
      '/inventory',
      '/history',
      '/me',
    ])
    expect(
      within(bottom).queryByRole('link', { name: '宿敌' }),
    ).not.toBeInTheDocument()
    expect(
      within(bottom).queryByRole('link', { name: '星图' }),
    ).not.toBeInTheDocument()
  })

  it('keeps only diamonds and the avatar in the top bar', async () => {
    renderShell()

    const diamonds = await screen.findByLabelText('钻石 720')
    expect(diamonds).toHaveAttribute('data-testid', 'diamond-balance')
    expect(diamonds).toHaveAttribute('href', '/inventory')
    expect(diamonds).toHaveTextContent('720')
    expect(diamonds.textContent).not.toMatch(/钻石/)
    expect(diamonds.querySelector('svg')).not.toBeNull()
    expect(screen.queryByTestId('gem-balance')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('打开设置')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('开启声音')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('关闭声音')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('刷新联赛数据')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '个人页' })).toHaveAttribute(
      'href',
      '/me',
    )
  })

  it('keeps the settings description hidden', async () => {
    useUiStore.setState({ settingsOpen: true })
    renderShell()

    const dialog = await screen.findByRole('dialog', { name: '设置' })
    expect(
      screen.queryByText(
        '音量、外观和账号都在这里；这些选项沿用现有账号能力。',
      ),
    ).not.toBeInTheDocument()
    const descriptionId = dialog.getAttribute('aria-describedby')
    expect(descriptionId).toBeTruthy()
    const description = document.getElementById(descriptionId!)
    expect(description).toHaveTextContent('设置对话框')
    expect(description).toHaveClass('visually-hidden')
  })
})
