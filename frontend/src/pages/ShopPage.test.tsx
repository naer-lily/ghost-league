import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type { ShopItem, StarPurchaseResult, Status } from '../api/types'
import { makeSnapshot, makeStar, makeStatus } from '../test/fixtures'
import { ShopPage } from './ShopPage'

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
  purchase?: () => Response
}

function mockApi(options: MockOptions = {}) {
  const snapshot = makeSnapshot({
    status: makeStatus({ diamonds: 720, ...options.status }),
  })
  snapshot.status = makeStatus({ ...snapshot.status, ...options.status })
  const catalog = options.catalog ?? makeCatalog()
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/v1/shop/purchase')) {
        return options.purchase ? options.purchase() : jsonResponse(purchaseResult())
      }
      if (url.includes('/v1/shop')) return jsonResponse(catalog)
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

function renderShop() {
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
        initialEntries={['/shop']}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <ShopPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ShopPage', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders both draw entries with rates and type counts from the API', async () => {
    mockApi()
    renderShop()

    expect(
      await screen.findByRole('heading', { name: '星图' }),
    ).toBeInTheDocument()
    const starItem = screen.getByTestId('shop-item-star')
    expect(starItem).toHaveTextContent('星星')
    expect(starItem).toHaveTextContent('抽取一颗')
    expect(starItem).toHaveTextContent('13 种星体')
    expect(within(starItem).getAllByTestId('star-rate')).toHaveLength(5)
    expect(within(starItem).getByText('微光')).toBeInTheDocument()
    expect(within(starItem).getByText('50%')).toBeInTheDocument()
    expect(within(starItem).getByText('0.5%')).toBeInTheDocument()

    const seasonalItem = screen.getByTestId('shop-item-seasonal_star')
    expect(seasonalItem).toHaveTextContent('季节星')
    expect(seasonalItem).toHaveTextContent('2026-11 限定')
    expect(seasonalItem).toHaveTextContent('抽取季节星')
    expect(within(seasonalItem).getAllByTestId('star-rate')).toHaveLength(5)
    expect(document.body.textContent ?? '').not.toMatch(
      /common|uncommon|legendary|gacha/,
    )
  })

  it('disables a draw when diamonds are short and shows the exact gap', async () => {
    mockApi({ status: { diamonds: 200 } })
    renderShop()

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
    const star = makeStar({
      name: '霜蓝',
      type_label: '蓝白星',
      rarity: 'rare',
      rarity_label: '耀星',
      catalog_code: 'GL-2026-0A1B2C3D',
    })
    const fetchMock = mockApi({
      purchase: () => jsonResponse(purchaseResult({ star })),
    })
    renderShop()

    const button = await screen.findByRole('button', { name: '抽取一颗' })
    await userEvent.click(button)

    const reveal = await screen.findByTestId('star-reveal')
    expect(within(reveal).getByText('霜蓝')).toBeInTheDocument()
    expect(within(reveal).getByText('蓝白星')).toBeInTheDocument()
    expect(within(reveal).getByText('耀星')).toBeInTheDocument()
    expect(within(reveal).getByText(/GL-2026-0A1B2C3D/)).toBeInTheDocument()
    expect(within(reveal).getByRole('button', { name: '收下' })).toBeVisible()

    const purchaseCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/v1/shop/purchase'),
    )
    expect(purchaseCall).toBeDefined()
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
    renderShop()

    await userEvent.click(
      await screen.findByRole('button', { name: '抽取一颗' }),
    )

    expect(await screen.findByTestId('shop-draw-error')).toHaveTextContent(
      '钻石不足',
    )
    expect(screen.queryByTestId('star-reveal')).not.toBeInTheDocument()
  })

  it('shows an honest empty library with no placeholder cards', async () => {
    mockApi({ status: { stars: [] } })
    renderShop()

    const empty = await screen.findByTestId('star-library-empty')
    expect(empty).toHaveTextContent('还没有星，去抽一颗')
    expect(screen.queryByTestId('star-card')).not.toBeInTheDocument()
    expect(screen.queryByText('0 颗')).not.toBeInTheDocument()
  })

  it('marks an owned seasonal star as unavailable', async () => {
    const seasonal = makeStar({
      id: 'star-seasonal',
      name: '望舒',
      kind: 'seasonal',
      season_key: '2026-11',
    })
    const catalog = makeCatalog().map((item) =>
      item.kind === 'seasonal_star'
        ? { ...item, available: false, owned_quantity: 1 }
        : item,
    )
    mockApi({
      status: { stars: [seasonal] },
      catalog,
    })
    renderShop()

    const seasonalItem = await screen.findByTestId('shop-item-seasonal_star')
    expect(
      within(seasonalItem).getByRole('button', { name: '本月已获得' }),
    ).toBeDisabled()
  })

  it('opens star details and closes them with Escape', async () => {
    mockApi()
    renderShop()

    const card = await screen.findByRole('button', { name: /查看 霜蓝/ })
    await userEvent.click(card)

    const detail = await screen.findByTestId('star-detail')
    expect(
      within(detail).getByRole('heading', { name: '霜蓝', level: 2 }),
    ).toBeInTheDocument()
    expect(within(detail).getByText('GL-2026-0A1B2C3D')).toBeInTheDocument()
    expect(within(detail).getByText('目录编号')).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    await waitFor(() =>
      expect(screen.queryByTestId('star-detail')).not.toBeInTheDocument(),
    )
  })

  it('renders supply items with real balances and disables short upgrades', async () => {
    mockApi()
    renderShop()

    const ember = await screen.findByTestId('shop-item-ember')
    expect(ember).toHaveTextContent('当前余烬 0 / 3')
    expect(ember).toHaveTextContent('还差 80 钻石')
    expect(within(ember).getByRole('button', { name: '兑换余烬' })).toBeDisabled()

    const cap = screen.getByTestId('shop-item-cap')
    expect(cap).toHaveTextContent('当前仓库 0 级')
    expect(cap).toHaveTextContent('1,000')
    expect(within(cap).getByRole('button', { name: '升级仓库' })).toBeEnabled()
  })
})
