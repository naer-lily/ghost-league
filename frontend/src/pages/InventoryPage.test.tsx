import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type {
  Collection,
  ShopItem,
  StarPurchaseResult,
  Status,
} from '../api/types'
import { makeSnapshot, makeStar, makeStatus } from '../test/fixtures'
import { InventoryPage } from './InventoryPage'

const RATES = {
  common: 0.5,
  uncommon: 0.3,
  rare: 0.15,
  epic: 0.045,
  legendary: 0.005,
}

const TYPES = [
  'red_dwarf',
  'orange_dwarf',
  'yellow_dwarf',
  'white_dwarf',
  'blue_white_star',
  'variable_star',
  'red_giant',
  'blue_giant',
  'binary_star',
  'triple_star',
  'neutron_star',
  'pulsar',
  'black_hole_relic',
]

function makeCatalog(): ShopItem[] {
  return [
    {
      id: 'star',
      name: '星星',
      description: '300 钻石抽一颗随机星。',
      price_diamonds: 300,
      currency: 'diamonds',
      kind: 'star',
      owned_quantity: 1,
      cooldown_seconds: 0,
      cooldown_until: null,
      available: true,
      gacha: true,
      rates: RATES,
      types: TYPES,
    },
    {
      id: 'seasonal_star',
      name: '季节星',
      description: '500 钻石抽一颗当季随机星。',
      price_diamonds: 500,
      currency: 'diamonds',
      kind: 'seasonal_star',
      owned_quantity: 0,
      cooldown_seconds: 0,
      cooldown_until: null,
      available: true,
      gacha: true,
      rates: RATES,
      types: TYPES,
      season_key: '2026-11',
    },
    {
      id: 'ember',
      name: '余烬',
      description: '立即获得 1 枚余烬。',
      price_diamonds: 800,
      currency: 'diamonds',
      kind: 'ember',
      owned_quantity: 0,
      cooldown_seconds: 259_200,
      cooldown_until: null,
      available: true,
    },
    {
      id: 'diamond_cap_1',
      name: '仓库上限 1 级',
      description: '仓库上限 +500。',
      price_diamonds: 500,
      currency: 'diamonds',
      kind: 'cap',
      owned_quantity: 0,
      cooldown_seconds: 0,
      cooldown_until: null,
      available: true,
      required_cap_level: 0,
    },
  ]
}

function makeCollection(overrides: Partial<Collection> = {}): Collection {
  return {
    player_id: 'naer-lily',
    titles: [
      {
        id: 'title_clown',
        name: '小丑',
        description: '坚持到最后的奖励。',
        awarded_at: '2026-10-31T09:00:00+08:00',
        season_id: null,
        equipped: true,
      },
    ],
    items: [
      {
        id: 'frame_ember',
        name: '余烬',
        slot: 'frame',
        description: '燃烧的边框。',
        awarded_at: '2026-10-30T09:00:00+08:00',
        season_id: null,
        equipped: true,
      },
      {
        id: 'backdrop_night',
        name: '夜空',
        slot: 'backdrop',
        description: '深色背景。',
        awarded_at: '2026-10-29T09:00:00+08:00',
        season_id: null,
        equipped: false,
      },
    ],
    equipped: {
      title_id: 'title_clown',
      frame_id: 'frame_ember',
      backdrop_id: null,
      badge_accent_id: null,
      updated_at: '2026-10-31T09:00:00+08:00',
    },
    ...overrides,
  }
}

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
    blob: async () => new Blob(['']),
  } as Response
}

function svgResponse(): Response {
  return {
    ok: true,
    status: 200,
    json: async () => ({}),
    blob: async () =>
      new Blob(['<svg xmlns="http://www.w3.org/2000/svg"></svg>'], {
        type: 'image/svg+xml',
      }),
  } as Response
}

function purchaseResult(overrides: Partial<StarPurchaseResult> = {}): StarPurchaseResult {
  return {
    ok: true,
    item_id: 'star',
    quantity: 1,
    diamonds: 420,
    diamond_cap: 1000,
    diamond_cap_level: 0,
    diamond_excess: 0,
    inventory: { star: 2, seasonal_star: 0, ember: 0 },
    cooldown_until: null,
    replayed: false,
    star: makeStar(),
    ...overrides,
  }
}

interface MockOptions {
  status?: Partial<Status>
  catalog?: ShopItem[]
  collection?: Collection
  purchase?: () => Response
}

function mockApi(options: MockOptions = {}) {
  const snapshot = makeSnapshot()
  snapshot.status = makeStatus({
    ...snapshot.status,
    diamonds: 720,
    ...options.status,
  })
  const catalog = options.catalog ?? makeCatalog()
  const collection = options.collection ?? makeCollection()
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/v1/shop/purchase')) {
        return options.purchase ? options.purchase() : jsonResponse(purchaseResult())
      }
      if (url.includes('/v1/shop')) return jsonResponse(catalog)
      if (url.includes('/v1/me/collection')) return jsonResponse(collection)
      if (url.includes('/v1/me/profile')) return jsonResponse(snapshot.profile)
      if (url.includes('/v1/me/status')) return jsonResponse(snapshot.status)
      if (url.includes('/v1/league/standings'))
        return jsonResponse(snapshot.standings)
      if (url.includes('/svg')) return svgResponse()
      return jsonResponse({ detail: 'not found' }, 404)
    },
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderInventory() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        gcTime: 0,
        retry: false,
        refetchOnWindowFocus: false,
      },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={['/inventory']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <InventoryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('InventoryPage', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the inventory title, four categories and stars under the stars tab', async () => {
    mockApi()
    renderInventory()

    expect(
      await screen.findByRole('heading', { name: '物品栏' }),
    ).toBeInTheDocument()
    expect(document.body.textContent ?? '').not.toMatch(/星库|星图/)
    expect(screen.getByTestId('inventory-tab-stars')).toHaveAttribute(
      'aria-selected',
      'true',
    )
    for (const id of ['stars', 'frames', 'titles', 'other']) {
      expect(screen.getByTestId(`inventory-tab-${id}`)).toBeInTheDocument()
    }

    const starItem = screen.getByTestId('shop-item-star')
    expect(starItem).toHaveTextContent('星星')
    expect(starItem).toHaveTextContent('抽取一颗')
    expect(starItem).toHaveTextContent('13 种星体')
    expect(within(starItem).getAllByTestId('star-rate')).toHaveLength(5)

    const seasonalItem = screen.getByTestId('shop-item-seasonal_star')
    expect(seasonalItem).toHaveTextContent('2026-11 限定')
    expect(seasonalItem).toHaveTextContent('抽取季节星')

    expect(screen.getByTestId('star-library')).toHaveTextContent('霜蓝')
    expect(document.body.textContent ?? '').not.toMatch(
      /common|uncommon|legendary|gacha/,
    )
  })

  it('shows frames and titles from the real collection with equipped state', async () => {
    mockApi()
    renderInventory()
    await screen.findByRole('heading', { name: '物品栏' })

    await userEvent.click(screen.getByTestId('inventory-tab-frames'))
    const frames = await screen.findByRole('list', { name: '边框列表' })
    expect(within(frames).getByText('余烬')).toBeInTheDocument()
    expect(within(frames).getByText('已装备')).toBeInTheDocument()
    expect(within(frames).queryByText('夜空')).not.toBeInTheDocument()

    await userEvent.click(screen.getByTestId('inventory-tab-titles'))
    const titles = await screen.findByRole('list', { name: '称号列表' })
    expect(within(titles).getByText('小丑')).toBeInTheDocument()
    expect(within(titles).getByText('已装备')).toBeInTheDocument()
  })

  it('shows other items and the real supply section under other', async () => {
    mockApi({ status: { inventory: { star: 1, seasonal_star: 0, ember: 2 } } })
    renderInventory()
    await screen.findByRole('heading', { name: '物品栏' })

    await userEvent.click(screen.getByTestId('inventory-tab-other'))
    const list = await screen.findByRole('list', { name: '其他物品列表' })
    expect(within(list).getByText('夜空')).toBeInTheDocument()
    expect(within(list).getByText('余烬')).toBeInTheDocument()
    expect(screen.getByTestId('shop-item-ember')).toHaveTextContent(
      '当前余烬 2 / 3',
    )
    expect(screen.getByTestId('shop-item-cap')).toHaveTextContent(
      '当前仓库 0 级',
    )
  })

  it('shows empty states for every non-star category', async () => {
    mockApi({
      status: { stars: [], inventory: {} },
      collection: makeCollection({ titles: [], items: [] }),
    })
    renderInventory()
    await screen.findByRole('heading', { name: '物品栏' })

    expect(screen.getByText('还没有星星')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('inventory-tab-frames'))
    expect(await screen.findByText('还没有边框')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('inventory-tab-titles'))
    expect(await screen.findByText('还没有称号')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('inventory-tab-other'))
    expect(await screen.findByText('还没有其他物品')).toBeInTheDocument()
  })

  it('disables a draw when diamonds are short and shows the exact gap', async () => {
    mockApi({ status: { diamonds: 200 } })
    renderInventory()

    const starItem = await screen.findByTestId('shop-item-star')
    expect(within(starItem).getByRole('button', { name: '抽取一颗' })).toBeDisabled()
    expect(starItem).toHaveTextContent('还差 100 钻石')

    const seasonalItem = screen.getByTestId('shop-item-seasonal_star')
    expect(
      within(seasonalItem).getByRole('button', { name: '抽取季节星' }),
    ).toBeDisabled()
    expect(seasonalItem).toHaveTextContent('还差 300 钻石')
  })

  it('posts one purchase with a request id and reveals the real star', async () => {
    const star = makeStar({ name: '霜蓝' })
    const fetchMock = mockApi({
      purchase: () => jsonResponse(purchaseResult({ star })),
    })
    renderInventory()

    await userEvent.click(
      await screen.findByRole('button', { name: '抽取一颗' }),
    )

    const reveal = await screen.findByTestId('star-reveal')
    expect(within(reveal).getByText('霜蓝')).toBeInTheDocument()
    const purchaseCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/v1/shop/purchase'),
    )
    const body = JSON.parse(String(purchaseCall?.[1]?.body)) as {
      item_id: string
      quantity: number
      request_id: string
    }
    expect(body.item_id).toBe('star')
    expect(body.quantity).toBe(1)
    expect(body.request_id.length).toBeGreaterThan(8)

    await userEvent.click(within(reveal).getByRole('button', { name: '收下' }))
    await waitFor(() =>
      expect(screen.queryByTestId('star-reveal')).not.toBeInTheDocument(),
    )
  })

  it('shows the backend error and no fake result when a purchase fails', async () => {
    mockApi({
      status: { diamonds: 900 },
      purchase: () =>
        jsonResponse(
          {
            detail: {
              code: 'insufficient_diamonds',
              message: 'not enough diamonds',
              balance: 0,
            },
          },
          409,
        ),
    })
    renderInventory()

    await userEvent.click(
      await screen.findByRole('button', { name: '抽取一颗' }),
    )

    expect(await screen.findByTestId('shop-draw-error')).toHaveTextContent(
      '钻石不足',
    )
    expect(screen.queryByTestId('star-reveal')).not.toBeInTheDocument()
  })

  it('opens star details and closes them with Escape', async () => {
    mockApi()
    renderInventory()

    const card = await screen.findByRole('button', { name: /查看 霜蓝/ })
    await userEvent.click(card)

    const detail = await screen.findByTestId('star-detail')
    expect(
      within(detail).getByRole('heading', { name: '霜蓝', level: 2 }),
    ).toBeInTheDocument()
    await userEvent.keyboard('{Escape}')
    await waitFor(() =>
      expect(screen.queryByTestId('star-detail')).not.toBeInTheDocument(),
    )
  })
})
