import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type { TaskItem } from '../api/types'
import { TaskList } from './TaskList'

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

function makeTask(overrides: Partial<TaskItem> = {}): TaskItem {
  return {
    id: 'ti_1',
    source: 'daily_manual',
    title: '速写一张',
    description: '',
    difficulty: 2,
    chest_tier: 2,
    starts_at: '2026-11-04T00:00:00+08:00',
    ends_at: '2026-11-05T00:00:00+08:00',
    status: 'active',
    completed_at: null,
    chest_status: 'none',
    chest_amount: null,
    proof_url: null,
    progress: null,
    ...overrides,
  }
}

function renderList(onOpenSettings = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { gcTime: 0, retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
  return {
    onOpenSettings,
    ...render(
      <QueryClientProvider client={queryClient}>
        <TaskList onOpenSettings={onOpenSettings} />
      </QueryClientProvider>,
    ),
  }
}

describe('TaskList', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('uploads a photo, then claims the chest and shows the diamond dialog', async () => {
    let task = makeTask()
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/chest')) {
        return response({ amount: 7, balance: 1007, duplicate: false })
      }
      if (url.includes('/complete')) {
        task = makeTask({
          status: 'completed',
          completed_at: '2026-11-04T12:30:00+08:00',
          chest_status: 'available',
          proof_url: '/v1/me/tasks/ti_1/proof',
        })
        return response({ task })
      }
      if (url.endsWith('/v1/me/tasks')) {
        return response({ server_now: '2026-11-04T12:00:00+08:00', tasks: [task] })
      }
      return response({ detail: 'not found' }, 404)
    })
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal('fetch', fetchMock)

    const { container } = renderList()
    expect(await screen.findByText('速写一张')).toBeInTheDocument()
    expect(screen.getByText('截止 11/05 00:00')).toBeInTheDocument()

    const input = container.querySelector('input[type="file"]')
    expect(input).not.toBeNull()
    const file = new File(['image-bytes'], 'proof.png', { type: 'image/png' })
    fireEvent.change(input as HTMLInputElement, { target: { files: [file] } })

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/v1/me/tasks/ti_1/complete'),
        expect.anything(),
      ),
    )

    const chest = await screen.findByRole('button', {
      name: '领取速写一张的宝箱',
    })
    await userEvent.click(chest)

    const dialog = await screen.findByTestId('task-chest-dialog')
    expect(within(dialog).getByTestId('task-chest-amount')).toHaveTextContent(
      '+7 钻石',
    )
    expect(screen.queryByText(/概率|机制|DSL/)).not.toBeInTheDocument()
  })

  it('shows weekend progress without an action button', async () => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/v1/me/tasks')) {
          return response({
            server_now: '2026-11-01T12:00:00+08:00',
            tasks: [
              makeTask({
                id: 'ti_weekend',
                source: 'weekend',
                title: '周末 · 1000 XP',
                description: '周六周日累计 1000 XP。',
                difficulty: 5,
                chest_tier: 5,
                ends_at: '2026-11-02T00:00:00+08:00',
                progress: { current: 420, target: 1000 },
              }),
            ],
          })
        }
        return response({ detail: 'not found' }, 404)
      }),
    )

    renderList()
    expect(await screen.findByText('周末 · 1000 XP')).toBeInTheDocument()
    expect(screen.getByTestId('task-progress')).toHaveTextContent(
      '420 / 1000 XP',
    )
    expect(screen.queryByRole('button', { name: /拍照完成/ })).not.toBeInTheDocument()
    expect(screen.queryByText('周六周日累计 1000 XP。')).not.toBeInTheDocument()
  })

  it('opens task settings from the section header', async () => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/v1/me/tasks')) {
          return response({ server_now: '2026-11-04T12:00:00+08:00', tasks: [] })
        }
        return response({ detail: 'not found' }, 404)
      }),
    )

    const onOpenSettings = vi.fn()
    renderList(onOpenSettings)
    await userEvent.click(screen.getByRole('button', { name: '任务设置' }))
    expect(onOpenSettings).toHaveBeenCalledTimes(1)
  })
})
