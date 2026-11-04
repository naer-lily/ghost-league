import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type { TaskItem } from '../api/types'
import { useUiStore } from '../store/useUiStore'
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
    missed_date: null,
    status: 'active',
    completed_at: null,
    chest_status: 'none',
    chest_amount: null,
    proof_url: null,
    progress: null,
    ...overrides,
  }
}

function renderList(embersBalance = 1, onOpenSettings = vi.fn()) {
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
        <TaskList
          embersBalance={embersBalance}
          onOpenSettings={onOpenSettings}
        />
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
        return response({ server_now: '2026-11-04T14:51:00+08:00', tasks: [task] })
      }
      return response({ detail: 'not found' }, 404)
    })
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal('fetch', fetchMock)

    const { container } = renderList()
    expect(await screen.findByText('速写一张')).toBeInTheDocument()
    expect(screen.getByText('还剩 9 小时 9 分')).toBeInTheDocument()
    expect(screen.queryByText(/截止/)).not.toBeInTheDocument()

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

  it('repairs a missed day from the task card and then shows completed', async () => {
    let task = makeTask({
      id: 'ti_repair',
      source: 'repair',
      title: '补断联 · 10/29',
      description: '当天只拿到 74 XP；用余烬补上。',
      difficulty: 1,
      chest_tier: 1,
      starts_at: '2026-11-04T00:00:00+08:00',
      ends_at: '2026-11-06T00:00:00+08:00',
      missed_date: '2026-10-29',
      progress: { current: 0, target: 1 },
    })
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.endsWith('/v1/me/repair')) {
          expect(init?.method).toBe('POST')
          task = makeTask({
            id: 'ti_repair',
            source: 'repair',
            title: '补断联 · 10/29',
            description: '当天只拿到 74 XP；用余烬补上。',
            difficulty: 1,
            chest_tier: 1,
            starts_at: '2026-11-04T00:00:00+08:00',
            ends_at: '2026-11-06T00:00:00+08:00',
            missed_date: '2026-10-29',
            status: 'completed',
            completed_at: '2026-11-04T12:30:00+08:00',
            chest_status: 'available',
            progress: { current: 1, target: 1 },
          })
          return response({ repaired: true })
        }
        if (url.endsWith('/v1/me/tasks')) {
          return response({
            server_now: '2026-11-04T12:00:00+08:00',
            tasks: [task],
          })
        }
        return response({ detail: 'not found' }, 404)
      },
    )
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal('fetch', fetchMock)

    renderList(1)
    const repair = await screen.findByRole('button', { name: '用余烬补' })
    await userEvent.click(repair)

    const repairCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/v1/me/repair'),
    )
    expect(repairCall).toBeTruthy()
    const body = JSON.parse(String(repairCall?.[1]?.body)) as {
      date: string
      idempotency_key: string
    }
    expect(body.date).toBe('2026-10-29')
    expect(typeof body.idempotency_key).toBe('string')
    expect(body.idempotency_key.length).toBeGreaterThan(0)

    expect(
      await screen.findByRole('button', { name: '领取补断联 · 10/29的宝箱' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '用余烬补' })).not.toBeInTheDocument()
    await waitFor(() =>
      expect(useUiStore.getState().toast?.message).toBe('补上了。'),
    )
  })

  it('disables repair at zero embers without sending a request', async () => {
    const repairTask = makeTask({
      id: 'ti_repair',
      source: 'repair',
      title: '补断联 · 10/29',
      description: '当天只拿到 74 XP；用余烬补上。',
      difficulty: 1,
      chest_tier: 1,
      starts_at: '2026-11-04T00:00:00+08:00',
      ends_at: '2026-11-06T00:00:00+08:00',
      missed_date: '2026-10-29',
      progress: { current: 0, target: 1 },
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/v1/me/tasks')) {
        return response({
          server_now: '2026-11-04T12:00:00+08:00',
          tasks: [repairTask],
        })
      }
      return response({ detail: 'not found' }, 404)
    })
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal('fetch', fetchMock)

    renderList(0)
    const repair = await screen.findByRole('button', { name: '还差一枚余烬' })
    expect(repair).toBeDisabled()
    await userEvent.click(repair)

    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).endsWith('/v1/me/repair'),
      ),
    ).toBe(false)
    expect(screen.queryByRole('button', { name: '用余烬补' })).not.toBeInTheDocument()
  })

  it('does not offer repair for completed or expired repair tasks', async () => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/v1/me/tasks')) {
          return response({
            server_now: '2026-11-04T12:00:00+08:00',
            tasks: [
              makeTask({
                id: 'ti_done',
                source: 'repair',
                title: '补断联 · 10/29',
                difficulty: 1,
                chest_tier: 1,
                missed_date: '2026-10-29',
                status: 'completed',
                completed_at: '2026-11-04T12:30:00+08:00',
                chest_status: 'available',
                progress: { current: 1, target: 1 },
              }),
              makeTask({
                id: 'ti_expired',
                source: 'repair',
                title: '补断联 · 10/30',
                difficulty: 1,
                chest_tier: 1,
                missed_date: '2026-10-30',
                status: 'expired',
                chest_status: 'forfeited',
                progress: { current: 0, target: 1 },
              }),
            ],
          })
        }
        return response({ detail: 'not found' }, 404)
      }),
    )

    renderList()
    expect(await screen.findByText('补断联 · 10/29')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '用余烬补' })).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: '领取补断联 · 10/29的宝箱' }),
    ).toBeInTheDocument()
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
    renderList(1, onOpenSettings)
    await userEvent.click(screen.getByRole('button', { name: '任务设置' }))
    expect(onOpenSettings).toHaveBeenCalledTimes(1)
  })
})
