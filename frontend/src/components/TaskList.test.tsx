import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import { tasksQueryKey } from '../api/queries'
import type { Bet, RivalPlayer, RivalState, TaskItem } from '../api/types'
import { makeBetOptions } from '../test/fixtures'
import { compressTaskProof } from '../lib/image'
import { useUiStore } from '../store/useUiStore'
import { TaskList } from './TaskList'

vi.mock('../lib/image', () => ({
  compressTaskProof: vi.fn((file: File) => Promise.resolve(file)),
}))

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
    chest_pool: 'daily_1',
    sort_order: 10,
    starts_at: '2026-11-04T00:00:00+08:00',
    ends_at: '2026-11-05T00:00:00+08:00',
    missed_date: null,
    status: 'active',
    completed_at: null,
    chest_status: 'none',
    chest_amount: null,
    chest_reward_type: 'diamonds',
    chest_boost_minutes: null,
    chest_star: null,
    proof_url: null,
    progress: null,
    ...overrides,
  }
}

interface RenderListOptions {
  rivalState?: RivalState | null
  onOpenBets?: (kind: 'daily' | 'weekly') => void
}

function renderList(
  embersBalance = 1,
  onOpenSettings = vi.fn(),
  options: RenderListOptions = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { gcTime: 0, retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
  return {
    onOpenSettings,
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <TaskList
          embersBalance={embersBalance}
          onOpenSettings={onOpenSettings}
          {...(options.rivalState !== undefined
            ? { rivalState: options.rivalState }
            : {})}
          {...(options.onOpenBets
            ? { onOpenBets: options.onOpenBets }
            : {})}
        />
      </QueryClientProvider>,
    ),
  }
}

function taskTitles(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('h3')).map(
    (heading) => heading.textContent ?? '',
  )
}

function player(overrides: Partial<RivalPlayer> = {}): RivalPlayer {
  return {
    user_id: 'naer-lily',
    display_name: '那尔',
    avatar_url: null,
    group_no: 1,
    tier: 'Bronze',
    power: 1000,
    week_xp: 900,
    today_xp: 20,
    ...overrides,
  }
}

function makeBet(overrides: Partial<Bet> = {}): Bet {
  return {
    id: 1,
    kind: 'daily',
    period_key: '2026-11-04',
    rival_id: 'ch-rival',
    stake: 120,
    free_stake: 20,
    paid_stake: 100,
    target_margin: 5,
    odds: 2,
    status: 'placed',
    placed_at: '2026-11-04T10:00:00+08:00',
    locked_at: null,
    settled_at: null,
    payout: 0,
    result_diff: null,
    ...overrides,
  }
}

function makeRivalState(overrides: Partial<RivalState> = {}): RivalState {
  return {
    server_now: '2026-11-04T12:00:00+08:00',
    week_start: '2026-11-02',
    selection: {
      open: true,
      locks_at: '2026-11-02T23:59:59+08:00',
      auto_select_at: '2026-11-03T09:00:00+08:00',
      mode: 'manual',
    },
    me: player({ week_xp: 1000, today_xp: 10 }),
    rival: player({
      user_id: 'ch-rival',
      display_name: '林间',
      group_no: 7,
      power: 980,
      week_xp: 900,
      today_xp: 20,
    }),
    result: null,
    bets: { weekly: null, daily: null, group: null },
    bet_options: makeBetOptions(),
    projection: null,
    bet_windows: {
      weekly_locks_at: '2026-11-02T23:59:59+08:00',
      daily_locks_at: '2026-11-04T21:00:00+08:00',
      daily_settles_at: '2026-11-04T22:30:00+08:00',
    },
    ...overrides,
  }
}

function entryKeys(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('[data-entry-kind]')).map(
    (entry) => entry.getAttribute('data-entry-kind') ?? '',
  )
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
        task = {
          ...task,
          chest_status: 'claimed',
          chest_amount: 7,
          chest_reward_type: 'diamonds',
        }
        return response({
          amount: 7,
          balance: 1007,
          duplicate: false,
          reward_type: 'diamonds',
          boost_minutes: null,
          star: null,
          diamond_boost: {
            expires_at: null,
            remaining_seconds: 0,
            multiplier: 1,
          },
        })
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

    const chest = await screen.findByRole('button', { name: '开宝箱' })
    await userEvent.click(chest)

    const dialog = await screen.findByTestId('chest-open-dialog')
    expect(dialog).toHaveTextContent('速写一张')
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes('/chest'),
      ),
    ).toBe(false)

    await userEvent.click(within(dialog).getByRole('button', { name: '开启' }))
    expect(await within(dialog).findByTestId('chest-reward')).toHaveTextContent(
      '7 钻',
    )
    expect(within(dialog).queryByTestId('chest-glow')).not.toBeInTheDocument()
    expect(await screen.findByTestId('task-claimed')).toHaveTextContent('7 钻')
    expect(screen.queryByText(/概率|机制|DSL/)).not.toBeInTheDocument()

    await userEvent.click(within(dialog).getByRole('button', { name: '收下' }))
    await waitFor(() =>
      expect(screen.queryByTestId('chest-open-dialog')).not.toBeInTheDocument(),
    )
  })

  it('claims a boost chest and shows the boost duration without a photo action', async () => {
    let task = makeTask({
      id: 'ti_checkin',
      source: 'checkin',
      title: '每日打卡',
      description: '画满 10 分钟，开个小宝箱。',
      difficulty: 1,
      chest_tier: 1,
      chest_pool: 'daily_1',
      sort_order: 0,
      status: 'completed',
      completed_at: '2026-11-04T12:10:00+08:00',
      chest_status: 'available',
      progress: { current: 1, target: 1 },
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/chest')) {
        task = {
          ...task,
          chest_status: 'claimed',
          chest_amount: null,
          chest_reward_type: 'boost',
          chest_boost_minutes: 25,
        }
        return response({
          amount: 0,
          balance: 1000,
          duplicate: false,
          reward_type: 'boost',
          boost_minutes: 25,
          star: null,
          diamond_boost: {
            expires_at: '2026-11-04T12:35:00+08:00',
            remaining_seconds: 1500,
            multiplier: 2,
          },
        })
      }
      if (url.endsWith('/v1/me/tasks')) {
        return response({
          server_now: '2026-11-04T12:10:00+08:00',
          tasks: [task],
        })
      }
      return response({ detail: 'not found' }, 404)
    })
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal('fetch', fetchMock)

    const { container } = renderList()
    expect(await screen.findByText('每日打卡')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /拍照完成/ }),
    ).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '开宝箱' }))
    const dialog = await screen.findByTestId('chest-open-dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: '开启' }))
    expect(await within(dialog).findByTestId('chest-reward')).toHaveTextContent(
      '经验宝 25 分钟',
    )
    await waitFor(() =>
      expect(screen.getByTestId('task-claimed')).toHaveTextContent(
        '经验宝 25 分钟',
      ),
    )
    expect(screen.queryByText('0 钻')).not.toBeInTheDocument()
    expect(container.querySelector('input[type="file"]')).toBeNull()
  })

  it('claims a star chest and shows the star name in both places', async () => {
    const star = {
      id: 'star_1',
      name: '北辰',
      kind: 'normal' as const,
      season_key: null,
      star_type: 'red_dwarf',
      type_label: '红矮星',
      rarity: 'common',
      rarity_label: '普通',
      palette: ['#111111', '#222222', '#333333'],
      visual_seed: 1,
      companion_count: 0,
      catalog_code: 'GL-2026-ABCD',
      acquired_at: '2026-11-04T12:00:00+08:00',
      svg_url: '/v1/me/stars/star_1/svg',
    }
    let task = makeTask({
      status: 'completed',
      completed_at: '2026-11-04T12:00:00+08:00',
      chest_status: 'available',
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/chest')) {
        task = {
          ...task,
          chest_status: 'claimed',
          chest_amount: 0,
          chest_reward_type: 'star',
          chest_star: star,
        }
        return response({
          amount: 0,
          balance: 1000,
          duplicate: false,
          reward_type: 'star',
          boost_minutes: null,
          star,
          diamond_boost: {
            expires_at: null,
            remaining_seconds: 0,
            multiplier: 1,
          },
        })
      }
      if (url.endsWith('/v1/me/tasks')) {
        return response({
          server_now: '2026-11-04T12:00:00+08:00',
          tasks: [task],
        })
      }
      return response({ detail: 'not found' }, 404)
    })
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal('fetch', fetchMock)

    renderList()
    await userEvent.click(
      await screen.findByRole('button', { name: '开宝箱' }),
    )
    const dialog = await screen.findByTestId('chest-open-dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: '开启' }))
    expect(await within(dialog).findByTestId('chest-reward')).toHaveTextContent(
      '星星：北辰',
    )
    await waitFor(() =>
      expect(screen.getByTestId('task-claimed')).toHaveTextContent(
        '星星：北辰',
      ),
    )
    expect(screen.queryByText(/概率|池子|档位/)).not.toBeInTheDocument()
  })

  it('keeps the dialog open with the API error and does not show a reward', async () => {
    let task = makeTask({
      status: 'completed',
      completed_at: '2026-11-04T12:00:00+08:00',
      chest_status: 'available',
    })
    let failClaim = true
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/chest')) {
        if (failClaim) return response({ detail: 'boom' }, 500)
        task = {
          ...task,
          chest_status: 'claimed',
          chest_amount: 7,
          chest_reward_type: 'diamonds',
        }
        return response({
          amount: 7,
          balance: 1007,
          duplicate: false,
          reward_type: 'diamonds',
          boost_minutes: null,
          star: null,
          diamond_boost: {
            expires_at: null,
            remaining_seconds: 0,
            multiplier: 1,
          },
        })
      }
      if (url.endsWith('/v1/me/tasks')) {
        return response({
          server_now: '2026-11-04T12:00:00+08:00',
          tasks: [task],
        })
      }
      return response({ detail: 'not found' }, 404)
    })
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal('fetch', fetchMock)

    renderList()
    await userEvent.click(
      await screen.findByRole('button', { name: '开宝箱' }),
    )
    const dialog = await screen.findByTestId('chest-open-dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: '开启' }))

    expect(
      await within(dialog).findByTestId('chest-open-error'),
    ).toHaveTextContent('服务暂时不可用，请稍后重试。')
    expect(within(dialog).queryByTestId('chest-reward')).not.toBeInTheDocument()
    expect(screen.queryByTestId('task-claimed')).not.toBeInTheDocument()
    expect(dialog).toBeInTheDocument()

    failClaim = false
    await userEvent.click(within(dialog).getByRole('button', { name: '开启' }))
    expect(await within(dialog).findByTestId('chest-reward')).toHaveTextContent(
      '7 钻',
    )
    expect(within(dialog).queryByTestId('chest-open-error')).not.toBeInTheDocument()
  })

  it('disables 开启 while claiming and ignores repeated clicks', async () => {
    let task = makeTask({
      status: 'completed',
      completed_at: '2026-11-04T12:00:00+08:00',
      chest_status: 'available',
    })
    let chestCalls = 0
    let resolveClaim: (() => void) | null = null
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/chest')) {
        chestCalls += 1
        return new Promise<Response>((resolve) => {
          resolveClaim = () => {
            task = {
              ...task,
              chest_status: 'claimed',
              chest_amount: 9,
              chest_reward_type: 'diamonds',
            }
            resolve(
              response({
                amount: 9,
                balance: 1009,
                duplicate: false,
                reward_type: 'diamonds',
                boost_minutes: null,
                star: null,
                diamond_boost: {
                  expires_at: null,
                  remaining_seconds: 0,
                  multiplier: 1,
                },
              }),
            )
          }
        })
      }
      if (url.endsWith('/v1/me/tasks')) {
        return response({
          server_now: '2026-11-04T12:00:00+08:00',
          tasks: [task],
        })
      }
      return response({ detail: 'not found' }, 404)
    })
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal('fetch', fetchMock)

    renderList()
    await userEvent.click(
      await screen.findByRole('button', { name: '开宝箱' }),
    )
    const dialog = await screen.findByTestId('chest-open-dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: '开启' }))

    const pending = await within(dialog).findByRole('button', {
      name: '开启中…',
    })
    expect(pending).toBeDisabled()
    expect(chestCalls).toBe(1)
    await userEvent.click(pending)
    expect(chestCalls).toBe(1)

    await act(async () => resolveClaim?.())
    expect(await within(dialog).findByTestId('chest-reward')).toHaveTextContent(
      '9 钻',
    )
    expect(chestCalls).toBe(1)
  })

  it('shows 处理中… while compressing and uploads the compressed file', async () => {
    const deferred: { resolve: (file: File) => void } = {
      resolve: () => {},
    }
    const compressed = new File(['jpeg-bytes'], 'big.jpg', {
      type: 'image/jpeg',
    })
    vi.mocked(compressTaskProof).mockImplementationOnce(
      () =>
        new Promise<File>((resolve) => {
          deferred.resolve = resolve
        }),
    )
    let uploaded: File | null = null
    let task = makeTask()
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.includes('/complete')) {
          uploaded = (init?.body as FormData).get('file') as File
          task = makeTask({
            status: 'completed',
            completed_at: '2026-11-04T12:30:00+08:00',
            chest_status: 'available',
            proof_url: '/v1/me/tasks/ti_1/proof',
          })
          return response({ task })
        }
        if (url.endsWith('/v1/me/tasks')) {
          return response({
            server_now: '2026-11-04T14:51:00+08:00',
            tasks: [task],
          })
        }
        return response({ detail: 'not found' }, 404)
      },
    )
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal('fetch', fetchMock)

    const { container } = renderList()
    expect(await screen.findByText('速写一张')).toBeInTheDocument()

    const input = container.querySelector('input[type="file"]')
    const original = new File(['large-bytes'], 'large.jpg', {
      type: 'image/jpeg',
    })
    fireEvent.change(input as HTMLInputElement, {
      target: { files: [original] },
    })

    const processing = await screen.findByRole('button', { name: '处理中…' })
    expect(processing).toBeDisabled()
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes('/complete'),
      ),
    ).toBe(false)

    await act(async () => deferred.resolve(compressed))

    await waitFor(() => expect(uploaded).toBe(compressed))
    expect(
      await screen.findByRole('button', { name: '开宝箱' }),
    ).toBeInTheDocument()
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
                chest_pool: 'daily_1',
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

  it('shows weekly chain progress in XP without extra copy', async () => {
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
                id: 'ti_chain_2',
                source: 'weekly_chain',
                title: '本周 2000 XP',
                chest_pool: 'weekly_chain_2',
                sort_order: 20,
                starts_at: '2026-11-02T00:00:00+08:00',
                ends_at: '2026-11-09T00:00:00+08:00',
                progress: { current: 1200, target: 2000 },
              }),
            ],
          })
        }
        return response({ detail: 'not found' }, 404)
      }),
    )

    renderList()
    expect(await screen.findByText('本周 2000 XP')).toBeInTheDocument()
    expect(screen.getByTestId('task-progress')).toHaveTextContent(
      '1200 / 2000 XP',
    )
    expect(screen.queryByText(/连续任务/)).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /拍照完成/ }),
    ).not.toBeInTheDocument()
  })

  it('sinks claimed weekly stages and keeps unclaimed stages in place', async () => {
    const tasks = [
      makeTask({
        id: 'ti_chain_3',
        source: 'weekly_chain',
        title: '本周 3000 XP',
        chest_pool: 'weekly_chain_3',
        sort_order: 30,
        starts_at: '2026-11-02T00:00:00+08:00',
        ends_at: '2026-11-09T00:00:00+08:00',
        progress: { current: 2400, target: 3000 },
      }),
      makeTask({
        id: 'ti_chain_1',
        source: 'weekly_chain',
        title: '本周 1000 XP',
        chest_pool: 'weekly_chain_1',
        sort_order: 10,
        starts_at: '2026-11-02T00:00:00+08:00',
        ends_at: '2026-11-09T00:00:00+08:00',
        status: 'completed',
        completed_at: '2026-11-04T10:00:00+08:00',
        chest_status: 'claimed',
        chest_amount: 7,
        progress: { current: 1000, target: 1000 },
      }),
      makeTask({
        id: 'ti_chain_2',
        source: 'weekly_chain',
        title: '本周 2000 XP',
        chest_pool: 'weekly_chain_2',
        sort_order: 20,
        starts_at: '2026-11-02T00:00:00+08:00',
        ends_at: '2026-11-09T00:00:00+08:00',
        status: 'completed',
        completed_at: '2026-11-04T11:00:00+08:00',
        chest_status: 'available',
        progress: { current: 1000, target: 2000 },
      }),
    ]
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith('/v1/me/tasks')) {
          return response({
            server_now: '2026-11-04T12:00:00+08:00',
            tasks,
          })
        }
        return response({ detail: 'not found' }, 404)
      }),
    )

    const { container } = renderList()
    await screen.findByText('本周 2000 XP')
    expect(taskTitles(container)).toEqual([
      '本周 2000 XP',
      '本周 3000 XP',
      '本周 1000 XP',
    ])
    expect(screen.getByRole('button', { name: '开宝箱' })).toBeInTheDocument()
    expect(screen.getByTestId('task-claimed')).toHaveTextContent('7 钻')
  })

  it('reveals the next weekly stage after claiming its chest', async () => {
    const first = makeTask({
      id: 'ti_chain_1',
      source: 'weekly_chain',
      title: '本周 1000 XP',
      chest_pool: 'weekly_chain_1',
      sort_order: 10,
      starts_at: '2026-11-02T00:00:00+08:00',
      ends_at: '2026-11-09T00:00:00+08:00',
      status: 'completed',
      completed_at: '2026-11-04T10:00:00+08:00',
      chest_status: 'available',
      progress: { current: 1200, target: 1000 },
    })
    const next = makeTask({
      id: 'ti_chain_2',
      source: 'weekly_chain',
      title: '本周 2000 XP',
      chest_pool: 'weekly_chain_2',
      sort_order: 20,
      starts_at: '2026-11-02T00:00:00+08:00',
      ends_at: '2026-11-09T00:00:00+08:00',
      progress: { current: 1200, target: 2000 },
    })
    let tasks = [first]
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/chest')) {
        tasks = [
          {
            ...first,
            chest_status: 'claimed',
            chest_amount: 7,
          },
          next,
        ]
        return response({
          amount: 7,
          balance: 1007,
          duplicate: false,
          reward_type: 'diamonds',
          boost_minutes: null,
          star: null,
          diamond_boost: {
            expires_at: null,
            remaining_seconds: 0,
            multiplier: 1,
          },
        })
      }
      if (url.endsWith('/v1/me/tasks')) {
        return response({
          server_now: '2026-11-04T12:00:00+08:00',
          tasks,
        })
      }
      return response({ detail: 'not found' }, 404)
    })
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal('fetch', fetchMock)

    const { container } = renderList()
    await userEvent.click(
      await screen.findByRole('button', { name: '开宝箱' }),
    )
    const dialog = await screen.findByTestId('chest-open-dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: '开启' }))
    expect(await within(dialog).findByTestId('chest-reward')).toHaveTextContent(
      '7 钻',
    )
    await userEvent.click(within(dialog).getByRole('button', { name: '收下' }))

    await waitFor(() =>
      expect(taskTitles(container)).toEqual([
        '本周 2000 XP',
        '本周 1000 XP',
      ]),
    )
    expect(screen.getByTestId('task-progress')).toHaveTextContent(
      '1200 / 2000 XP',
    )
    expect(screen.getByTestId('task-claimed')).toHaveTextContent('7 钻')
  })

  it('repairs a missed day from the task card and then shows completed', async () => {
    let task = makeTask({
      id: 'ti_repair',
      source: 'repair',
      title: '补断联 · 10/29',
      description: '当天只拿到 74 XP；用余烬补上。',
      difficulty: 1,
      chest_tier: 1,
      chest_pool: 'daily_1',
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
            chest_pool: 'daily_1',
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
      await screen.findByRole('button', { name: '开宝箱' }),
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
      chest_pool: 'daily_1',
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
                chest_pool: 'daily_1',
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
                chest_pool: 'daily_1',
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
      screen.getByRole('button', { name: '开宝箱' }),
    ).toBeInTheDocument()
  })

  it('sorts active and unclaimed-chest tasks ahead of claimed completions', async () => {
    const tasks = [
      makeTask({
        id: 'ti_b',
        title: 'B',
        status: 'completed',
        chest_status: 'claimed',
        sort_order: 20,
      }),
      makeTask({
        id: 'ti_d',
        title: 'D',
        status: 'completed',
        chest_status: 'available',
        sort_order: 40,
      }),
      makeTask({ id: 'ti_a', title: 'A', sort_order: 10 }),
      makeTask({ id: 'ti_c', title: 'C', sort_order: 30 }),
    ]
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith('/v1/me/tasks')) {
          return response({
            server_now: '2026-11-04T12:00:00+08:00',
            tasks,
          })
        }
        return response({ detail: 'not found' }, 404)
      }),
    )

    const { container } = renderList()
    await screen.findByText('A')

    expect(taskTitles(container)).toEqual(['A', 'C', 'D', 'B'])
  })

  it("puts an active repair task after today's tasks by its 11/06 deadline", async () => {
    const tasks = [
      makeTask({
        id: 'ti_repair',
        source: 'repair',
        title: '补断联 · 10/29',
        ends_at: '2026-11-06T00:00:00+08:00',
        missed_date: '2026-10-29',
        sort_order: 0,
        progress: { current: 0, target: 1 },
      }),
      makeTask({ id: 'ti_b', title: 'B', sort_order: 20 }),
      makeTask({ id: 'ti_a', title: 'A', sort_order: 10 }),
    ]
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith('/v1/me/tasks')) {
          return response({
            server_now: '2026-11-04T12:00:00+08:00',
            tasks,
          })
        }
        return response({ detail: 'not found' }, 404)
      }),
    )

    const { container } = renderList()
    await screen.findByText('A')

    expect(taskTitles(container)).toEqual(['A', 'B', '补断联 · 10/29'])
  })

  it('follows the new sort_order after a settings reorder refetch', async () => {
    let tasks = [
      makeTask({ id: 'ti_a', title: 'A', sort_order: 10 }),
      makeTask({ id: 'ti_b', title: 'B', sort_order: 20 }),
    ]
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith('/v1/me/tasks')) {
          return response({
            server_now: '2026-11-04T12:00:00+08:00',
            tasks,
          })
        }
        return response({ detail: 'not found' }, 404)
      }),
    )

    const { container, queryClient } = renderList()
    await screen.findByText('A')
    expect(taskTitles(container)).toEqual(['A', 'B'])

    tasks = [
      makeTask({ id: 'ti_a', title: 'A', sort_order: 20 }),
      makeTask({ id: 'ti_b', title: 'B', sort_order: 10 }),
    ]
    await act(async () => {
      await queryClient.refetchQueries({ queryKey: tasksQueryKey })
    })

    await waitFor(() => expect(taskTitles(container)).toEqual(['B', 'A']))
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

  it('renders daily/weekly bet rows from today/week data and keeps completed tasks last', async () => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    const tasks = [
      makeTask({
        id: 'ti_daily',
        title: '每日速写',
        ends_at: '2026-11-05T00:00:00+08:00',
        sort_order: 10,
      }),
      makeTask({
        id: 'ti_weekly',
        source: 'weekly_chain',
        title: '本周 1000 XP',
        ends_at: '2026-11-09T00:00:00+08:00',
        sort_order: 20,
      }),
      makeTask({
        id: 'ti_done',
        title: '已领任务',
        status: 'completed',
        chest_status: 'claimed',
        sort_order: 1,
      }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith('/v1/me/tasks')) {
          return response({
            server_now: '2026-11-04T12:00:00+08:00',
            tasks,
          })
        }
        return response({ detail: 'not found' }, 404)
      }),
    )
    const onOpenBets = vi.fn()
    const rivalState = makeRivalState({
      bets: {
        weekly: makeBet({
          id: 2,
          kind: 'weekly',
          period_key: '2026-11-02',
          target_margin: 100,
        }),
        daily: makeBet({ id: 1, kind: 'daily', target_margin: 5 }),
        group: null,
      },
    })

    const { container } = renderList(1, vi.fn(), { rivalState, onOpenBets })
    await screen.findByText('每日速写')

    const daily = screen.getByTestId('bet-task-daily')
    expect(within(daily).getByTestId('bet-task-me-daily')).toHaveTextContent(
      '10',
    )
    expect(
      within(daily).getByTestId('bet-task-rival-daily'),
    ).toHaveTextContent('25')
    expect(
      within(daily).getByTestId('bet-task-diff-daily'),
    ).toHaveTextContent('-15')
    const weekly = screen.getByTestId('bet-task-weekly')
    expect(within(weekly).getByTestId('bet-task-me-weekly')).toHaveTextContent(
      '1,000',
    )
    expect(
      within(weekly).getByTestId('bet-task-rival-weekly'),
    ).toHaveTextContent('1,000')
    expect(
      within(weekly).getByTestId('bet-task-diff-weekly'),
    ).toHaveTextContent('0')

    expect(entryKeys(container)).toEqual([
      'bet',
      'task',
      'bet',
      'task',
      'task',
    ])
    expect(taskTitles(container)).toEqual([
      '每日速写',
      '本周 1000 XP',
      '已领任务',
    ])
    const weeklyEntries = container.querySelectorAll('[data-entry-kind]')
    expect(weeklyEntries[2]).toHaveAttribute('data-list-gap', 'true')

    await userEvent.click(
      within(daily).getByTestId('bet-task-toggle-daily'),
    )
    expect(screen.getByTestId('bet-task-details-daily')).toBeVisible()
    expect(
      screen.queryByTestId('bet-task-details-weekly'),
    ).not.toBeInTheDocument()

    await userEvent.click(
      within(weekly).getByTestId('bet-task-toggle-weekly'),
    )
    expect(screen.getByTestId('bet-task-details-weekly')).toBeVisible()
    expect(
      screen.queryByTestId('bet-task-details-daily'),
    ).not.toBeInTheDocument()
    expect(onOpenBets).not.toHaveBeenCalled()
  })

  it('opens the matching bet dialog from the unbet rows', async () => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith('/v1/me/tasks')) {
          return response({
            server_now: '2026-11-02T12:00:00+08:00',
            tasks: [],
          })
        }
        return response({ detail: 'not found' }, 404)
      }),
    )
    const onOpenBets = vi.fn()
    renderList(1, vi.fn(), { rivalState: makeRivalState(), onOpenBets })

    await userEvent.click(await screen.findByTestId('bet-task-open-daily'))
    expect(onOpenBets).toHaveBeenLastCalledWith('daily')
    await userEvent.click(screen.getByTestId('bet-task-open-weekly'))
    expect(onOpenBets).toHaveBeenLastCalledWith('weekly')
  })

  it('shows locked bet rows without clickable buttons after the windows close', async () => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith('/v1/me/tasks')) {
          return response({
            server_now: '2026-11-04T22:00:00+08:00',
            tasks: [],
          })
        }
        return response({ detail: 'not found' }, 404)
      }),
    )
    const rivalState = makeRivalState({
      bet_windows: {
        weekly_locks_at: '2026-11-02T23:59:59+08:00',
        daily_locks_at: '2026-11-04T21:00:00+08:00',
        daily_settles_at: '2026-11-04T22:30:00+08:00',
      },
    })
    renderList(1, vi.fn(), { rivalState, onOpenBets: vi.fn() })

    expect(await screen.findByTestId('bet-task-locked-daily')).toHaveTextContent(
      '今天的注已截止',
    )
    expect(screen.getByTestId('bet-task-locked-weekly')).toHaveTextContent(
      '本周的注已截止',
    )
    expect(
      screen.queryByTestId('bet-task-open-daily'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('bet-task-open-weekly'),
    ).not.toBeInTheDocument()
  })

  it('does not render bet rows without a rival', async () => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).endsWith('/v1/me/tasks')) {
          return response({
            server_now: '2026-11-04T12:00:00+08:00',
            tasks: [makeTask({ id: 'ti_a', title: 'A' })],
          })
        }
        return response({ detail: 'not found' }, 404)
      }),
    )
    renderList(1, vi.fn(), {
      rivalState: makeRivalState({ rival: null, bets: { weekly: null, daily: null, group: null } }),
      onOpenBets: vi.fn(),
    })

    expect(await screen.findByText('A')).toBeInTheDocument()
    expect(screen.queryByTestId('bet-task-daily')).not.toBeInTheDocument()
    expect(screen.queryByTestId('bet-task-weekly')).not.toBeInTheDocument()
  })
})
