import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type { TaskDefinition } from '../api/types'
import { useUiStore } from '../store/useUiStore'
import { TaskSettingsDialog } from './TaskSettingsDialog'

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

function makeDefinition(
  id: string,
  title: string,
  sortOrder: number,
): TaskDefinition {
  return {
    id,
    user_id: 'owner',
    title,
    description: '',
    difficulty: 1,
    active: true,
    sort_order: sortOrder,
    created_at: '2026-11-04T10:00:00+08:00',
    updated_at: '2026-11-04T10:00:00+08:00',
  }
}

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { gcTime: 0, retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <TaskSettingsDialog open onOpenChange={() => undefined} />
    </QueryClientProvider>,
  )
}

function dragFirstBelowSecond(title: string) {
  const handle = screen.getByRole('button', { name: `拖动排序 ${title}` })
  fireEvent.pointerDown(handle, {
    pointerId: 1,
    pointerType: 'touch',
    isPrimary: true,
    button: 0,
    clientY: 20,
  })
  fireEvent.pointerMove(handle, {
    pointerId: 1,
    pointerType: 'touch',
    isPrimary: true,
    button: 0,
    clientY: 100,
  })
  fireEvent.pointerUp(handle, {
    pointerId: 1,
    pointerType: 'touch',
    isPrimary: true,
    button: 0,
    clientY: 100,
  })
}

async function expectTitles(expected: string[]) {
  await waitFor(() => {
    const list = screen.getByRole('list')
    const titles = within(list)
      .getAllByRole('listitem')
      .map((row) => row.querySelector('strong')?.textContent ?? '')
    expect(titles).toEqual(expected)
  })
}

describe('TaskSettingsDialog ordering', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    useUiStore.getState().dismissToast()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    useUiStore.getState().dismissToast()
  })

  it('drags by the handle, calls the batch order endpoint and shows the new order', async () => {
    let current = [
      makeDefinition('td_a', 'A', 10),
      makeDefinition('td_b', 'B', 20),
    ]
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.includes('/order') && init?.method === 'PUT') {
          const ids = JSON.parse(String(init.body)).ids as string[]
          const byId = new Map(current.map((row) => [row.id, row]))
          current = ids.map((id, index) => ({
            ...byId.get(id)!,
            sort_order: (index + 1) * 10,
          }))
          return response(current)
        }
        return response(current)
      },
    )
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
      function (this: HTMLElement) {
        const index = this.dataset.taskId === 'td_b' ? 1 : 0
        const top = index * 58
        return {
          top,
          bottom: top + 50,
          height: 50,
          left: 0,
          right: 300,
          width: 300,
          x: 0,
          y: top,
          toJSON: () => undefined,
        } as DOMRect
      },
    )

    const { container } = renderDialog()
    await expectTitles(['A', 'B'])
    expect(container).toBeInTheDocument()

    dragFirstBelowSecond('A')

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/v1/me/task-definitions/order',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ ids: ['td_b', 'td_a'] }),
        }),
      ),
    )
    await expectTitles(['B', 'A'])
    expect(current.map((row) => row.sort_order)).toEqual([10, 20])
  })

  it('rolls the order back and notifies when the reorder request fails', async () => {
    const current = [
      makeDefinition('td_a', 'A', 10),
      makeDefinition('td_b', 'B', 20),
    ]
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).includes('/order') && init?.method === 'PUT') {
          return response({ detail: '保存失败' }, 500)
        }
        return response(current)
      },
    )
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
      function (this: HTMLElement) {
        const index = this.dataset.taskId === 'td_b' ? 1 : 0
        const top = index * 58
        return {
          top,
          bottom: top + 50,
          height: 50,
          left: 0,
          right: 300,
          width: 300,
          x: 0,
          y: top,
          toJSON: () => undefined,
        } as DOMRect
      },
    )

    const { container } = renderDialog()
    await expectTitles(['A', 'B'])
    expect(container).toBeInTheDocument()

    dragFirstBelowSecond('A')

    await waitFor(() =>
      expect(useUiStore.getState().toast).toMatchObject({
        tone: 'error',
      }),
    )
    await expectTitles(['A', 'B'])
  })
})
