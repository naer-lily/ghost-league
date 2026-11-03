import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import type {
  Collection,
  Loadout,
  ShopItem,
  StarPurchaseResult,
  Status,
} from '../api/types'
import { makeSnapshot, makeStar, makeStatus } from '../test/fixtures'
import { useUiStore } from '../store/useUiStore'
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
      id: 'diamond_boost_25',
      name: '经验宝 · 25 分钟',
      description: '',
      price_diamonds: 25,
      currency: 'diamonds',
      kind: 'boost',
      active: true,
      minutes: 25,
      multiplier: 2,
      owned_quantity: 0,
      cooldown_seconds: 0,
      cooldown_until: null,
      available: true,
    },
    {
      id: 'diamond_boost_60',
      name: '经验宝 · 60 分钟',
      description: '',
      price_diamonds: 60,
      currency: 'diamonds',
      kind: 'boost',
      active: true,
      minutes: 60,
      multiplier: 2,
      owned_quantity: 0,
      cooldown_seconds: 0,
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
    {
      id: 'repair_kit',
      name: '补签券',
      description: '补回漏掉的一天。',
      price_diamonds: 120,
      currency: 'diamonds',
      kind: 'inventory',
      owned_quantity: 0,
      cooldown_seconds: 0,
      cooldown_until: null,
      available: true,
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
      {
        id: 'title_ignition',
        name: '点火',
        description: '首次完成 100 XP 打卡。',
        awarded_at: '2026-10-30T09:00:00+08:00',
        season_id: null,
        equipped: false,
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
        id: 'frame_clown',
        name: '小丑帽',
        slot: 'frame',
        description: '断掉连胜后获得。',
        awarded_at: '2026-10-30T10:00:00+08:00',
        season_id: null,
        equipped: false,
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
      {
        id: 'badge_champion',
        name: '冠军环',
        slot: 'badge_accent',
        description: '冠军徽章底色。',
        awarded_at: '2026-10-28T09:00:00+08:00',
        season_id: null,
        equipped: false,
      },
      {
        id: 'sticker_mystery',
        name: '神秘贴纸',
        slot: 'sticker',
        description: '没有装备槽的收藏品。',
        awarded_at: '2026-10-27T09:00:00+08:00',
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
  loadout?: (body: Record<string, string | null>) => Response
}

const SLOT_BY_FIELD: Record<string, string> = {
  frame_id: 'frame',
  backdrop_id: 'backdrop',
  badge_accent_id: 'badge_accent',
}

function loadoutFor(collection: Collection): Loadout {
  const title = collection.titles.find((entry) => entry.equipped)
  const frame = collection.items.find(
    (entry) => entry.slot === 'frame' && entry.equipped,
  )
  const backdrop = collection.items.find(
    (entry) => entry.slot === 'backdrop' && entry.equipped,
  )
  const badge = collection.items.find(
    (entry) => entry.slot === 'badge_accent' && entry.equipped,
  )
  return {
    player_id: collection.player_id,
    title_id: title?.id ?? null,
    title: title?.name ?? null,
    frame_id: frame?.id ?? null,
    frame: frame?.name ?? null,
    backdrop_id: backdrop?.id ?? null,
    backdrop: backdrop?.name ?? null,
    badge_accent_id: badge?.id ?? null,
    badge_accent: badge?.name ?? null,
    updated_at: collection.equipped.updated_at,
  }
}

function applyLoadout(
  collection: Collection,
  body: Record<string, string | null>,
): void {
  for (const [field, value] of Object.entries(body)) {
    if (field === 'title_id') {
      collection.equipped.title_id = value
      for (const title of collection.titles) {
        title.equipped = title.id === value
      }
      continue
    }
    const slot = SLOT_BY_FIELD[field]
    if (!slot) continue
    collection.equipped[field as 'frame_id' | 'backdrop_id' | 'badge_accent_id'] =
      value
    for (const item of collection.items) {
      if (item.slot === slot) item.equipped = item.id === value
    }
  }
}

function mockApi(options: MockOptions = {}) {
  const snapshot = makeSnapshot()
  snapshot.status = makeStatus({
    ...snapshot.status,
    diamonds: 720,
    ...options.status,
  })
  const catalog = options.catalog ?? makeCatalog()
  const collection = JSON.parse(
    JSON.stringify(options.collection ?? makeCollection()),
  ) as Collection
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/v1/shop/purchase')) {
        return options.purchase ? options.purchase() : jsonResponse(purchaseResult())
      }
      if (url.includes('/v1/me/loadout')) {
        const body = JSON.parse(String(init?.body ?? '{}')) as Record<
          string,
          string | null
        >
        if (options.loadout) return options.loadout(body)
        applyLoadout(collection, body)
        return jsonResponse(loadoutFor(collection))
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

function loadoutBodies(fetchMock: ReturnType<typeof mockApi>) {
  return fetchMock.mock.calls
    .filter(([input]) => String(input).includes('/v1/me/loadout'))
    .map(
      ([, init]) =>
        JSON.parse(String(init?.body ?? '{}')) as Record<string, string | null>,
    )
}

describe('InventoryPage', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    useUiStore.setState({ toast: null })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('keeps stars as one inventory category and groups the shop into product categories', async () => {
    mockApi()
    renderInventory()

    expect(
      await screen.findByRole('heading', { name: '物品' }),
    ).toBeInTheDocument()
    expect(document.body.textContent ?? '').not.toMatch(
      /星库|星图|物品 \/ 商店|星星、边框、称号和其他物品都在这里|已拥有的星星都在这里|都是商店里的商品类别/,
    )
    expect(screen.getByTestId('inventory-tab-stars')).toHaveAttribute(
      'aria-selected',
      'true',
    )
    for (const id of ['stars', 'frames', 'titles', 'other']) {
      expect(screen.getByTestId(`inventory-tab-${id}`)).toBeInTheDocument()
    }

    const starLib = screen.getByTestId('star-library')
    expect(starLib).toHaveTextContent('霜蓝')
    expect(screen.queryByTestId('inventory-shop')).toBeInTheDocument()

    const shop = screen.getByTestId('inventory-shop')
    expect(within(shop).getByRole('heading', { name: '商店' })).toBeInTheDocument()
    const starsCategory = within(shop).getByTestId('shop-category-stars')
    expect(within(starsCategory).getByTestId('shop-item-star')).toBeInTheDocument()
    expect(
      within(starsCategory).getByTestId('shop-item-seasonal_star'),
    ).toBeInTheDocument()
    expect(
      within(within(shop).getByTestId('shop-category-embers')).getByTestId(
        'shop-item-ember',
      ),
    ).toBeInTheDocument()
    const boostsCategory = within(shop).getByTestId('shop-category-boosts')
    expect(within(boostsCategory).getByTestId('shop-item-diamond_boost_25'))
      .toBeInTheDocument()
    expect(within(boostsCategory).getByTestId('shop-item-diamond_boost_60'))
      .toBeInTheDocument()
    expect(within(boostsCategory).queryByTestId('diamond-boost-status'))
      .not.toBeInTheDocument()
    expect(
      within(within(shop).getByTestId('shop-category-cap')).getByTestId(
        'shop-item-diamond_cap_1',
      ),
    ).toBeInTheDocument()
    expect(
      within(within(shop).getByTestId('shop-category-other')).getByTestId(
        'shop-item-repair_kit',
      ),
    ).toBeInTheDocument()

    const starItem = screen.getByTestId('shop-item-star')
    expect(starItem).toHaveTextContent('抽取一颗')
    expect(starItem).toHaveTextContent('13 种星体')
    expect(starItem).not.toHaveTextContent('300 钻石抽一颗随机星。')
    expect(within(starItem).getAllByTestId('star-rate')).toHaveLength(5)

    const seasonalItem = screen.getByTestId('shop-item-seasonal_star')
    expect(seasonalItem).toHaveTextContent('2026-11 限定')
    expect(seasonalItem).toHaveTextContent('抽取季节星')
    expect(seasonalItem).not.toHaveTextContent('500 钻石抽一颗当季随机星。')

    const emberItem = within(shop).getByTestId('shop-item-ember')
    expect(emberItem).not.toHaveTextContent('立即获得 1 枚余烬。')
    expect(within(shop).queryByText('抽取随机星体，每次抽取的结果都在抽取后揭晓。'))
      .not.toBeInTheDocument()
    expect(within(shop).queryByText('补签等操作需要的消耗品。'))
      .not.toBeInTheDocument()

    expect(document.body.textContent ?? '').not.toMatch(
      /common|uncommon|legendary|gacha/,
    )
  })

  it('shows frames and titles from the real collection with equipped state', async () => {
    mockApi()
    renderInventory()
    await screen.findByRole('heading', { name: '物品' })

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

  it('shows other items and the real shop products under their categories', async () => {
    mockApi({ status: { inventory: { star: 1, seasonal_star: 0, ember: 2 } } })
    renderInventory()
    await screen.findByRole('heading', { name: '物品' })

    await userEvent.click(screen.getByTestId('inventory-tab-other'))
    const list = await screen.findByRole('list', { name: '其他物品列表' })
    expect(within(list).getByText('夜空')).toBeInTheDocument()
    expect(within(list).getByText('冠军环')).toBeInTheDocument()
    expect(within(list).getByText('余烬')).toBeInTheDocument()
    expect(screen.getByTestId('shop-item-ember')).toHaveTextContent(
      '当前余烬 2 / 3',
    )
    expect(screen.getByTestId('shop-item-diamond_cap_1')).toHaveTextContent(
      '当前仓库 0 级',
    )
  })

  it('shows empty states for every non-star category', async () => {
    mockApi({
      status: { stars: [], inventory: {} },
      collection: makeCollection({ titles: [], items: [] }),
    })
    renderInventory()
    await screen.findByRole('heading', { name: '物品' })

    expect(screen.getByText('还没有星星')).toBeInTheDocument()
    expect(
      screen.queryByText('去商店抽一颗，抽到的星会放进物品里。'),
    ).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('inventory-tab-frames'))
    expect(await screen.findByText('还没有边框')).toBeInTheDocument()
    expect(
      screen.queryByText('完成里程碑后，边框会出现在这里。'),
    ).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('inventory-tab-titles'))
    expect(await screen.findByText('还没有称号')).toBeInTheDocument()
    expect(
      screen.queryByText('参加联赛、保持连胜后，称号会自动解锁。'),
    ).not.toBeInTheDocument()
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
    expect(
      within(reveal).queryByText('这颗星已经放进物品栏，收下后可以随时查看。'),
    ).not.toBeInTheDocument()
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

  it('equips a frame and switches frames without sending other slots', async () => {
    const fetchMock = mockApi()
    renderInventory()
    await screen.findByRole('heading', { name: '物品' })

    await userEvent.click(screen.getByTestId('inventory-tab-frames'))
    const frames = await screen.findByRole('list', { name: '边框列表' })
    const callsTo = (suffix: string) =>
      fetchMock.mock.calls.filter(([input]) => String(input).includes(suffix))
        .length
    const statusCalls = callsTo('/v1/me/status')
    const collectionCalls = callsTo('/v1/me/collection')

    await userEvent.click(
      within(frames).getByTestId('collection-action-frame_clown'),
    )
    await waitFor(() =>
      expect(loadoutBodies(fetchMock)).toEqual([{ frame_id: 'frame_clown' }]),
    )
    await waitFor(() =>
      expect(useUiStore.getState().toast?.message).toBe('小丑帽已装备。'),
    )
    await waitFor(() =>
      expect(
        within(frames).getByTestId('collection-action-frame_clown'),
      ).toHaveTextContent('卸下'),
    )
    await waitFor(() => {
      expect(callsTo('/v1/me/status')).toBeGreaterThan(statusCalls)
      expect(callsTo('/v1/me/collection')).toBeGreaterThan(collectionCalls)
    })

    await userEvent.click(
      within(frames).getByTestId('collection-action-frame_ember'),
    )
    await waitFor(() =>
      expect(loadoutBodies(fetchMock)).toEqual([
        { frame_id: 'frame_clown' },
        { frame_id: 'frame_ember' },
      ]),
    )
  })

  it('equips a title through title_id', async () => {
    const fetchMock = mockApi()
    renderInventory()
    await screen.findByRole('heading', { name: '物品' })

    await userEvent.click(screen.getByTestId('inventory-tab-titles'))
    const titles = await screen.findByRole('list', { name: '称号列表' })
    await userEvent.click(
      within(titles).getByTestId('collection-action-title_ignition'),
    )

    await waitFor(() =>
      expect(loadoutBodies(fetchMock)).toEqual([{ title_id: 'title_ignition' }]),
    )
    await waitFor(() =>
      expect(useUiStore.getState().toast?.message).toBe('点火已装备。'),
    )
  })

  it('equips backdrop and badge accent items through their slots', async () => {
    const fetchMock = mockApi()
    renderInventory()
    await screen.findByRole('heading', { name: '物品' })

    await userEvent.click(screen.getByTestId('inventory-tab-other'))
    const list = await screen.findByRole('list', { name: '其他物品列表' })

    await userEvent.click(
      within(list).getByTestId('collection-action-backdrop_night'),
    )
    await waitFor(() =>
      expect(loadoutBodies(fetchMock)).toEqual([
        { backdrop_id: 'backdrop_night' },
      ]),
    )
    await waitFor(() =>
      expect(
        within(list).getByTestId('collection-action-backdrop_night'),
      ).toHaveTextContent('卸下'),
    )

    await userEvent.click(
      within(list).getByTestId('collection-action-badge_champion'),
    )
    await waitFor(() =>
      expect(loadoutBodies(fetchMock)).toEqual([
        { backdrop_id: 'backdrop_night' },
        { badge_accent_id: 'badge_champion' },
      ]),
    )
  })

  it('unequips an equipped item with null', async () => {
    const fetchMock = mockApi()
    renderInventory()
    await screen.findByRole('heading', { name: '物品' })

    await userEvent.click(screen.getByTestId('inventory-tab-frames'))
    const frames = await screen.findByRole('list', { name: '边框列表' })
    expect(
      within(frames).getByTestId('collection-action-frame_ember'),
    ).toHaveTextContent('卸下')

    await userEvent.click(
      within(frames).getByTestId('collection-action-frame_ember'),
    )

    await waitFor(() =>
      expect(loadoutBodies(fetchMock)).toEqual([{ frame_id: null }]),
    )
    await waitFor(() =>
      expect(useUiStore.getState().toast?.message).toBe('余烬已卸下。'),
    )
    await waitFor(() =>
      expect(
        within(frames).getByTestId('collection-action-frame_ember'),
      ).toHaveTextContent('装备'),
    )
  })

  it('does not render an equip button for an item without a loadout slot', async () => {
    mockApi()
    renderInventory()
    await screen.findByRole('heading', { name: '物品' })

    await userEvent.click(screen.getByTestId('inventory-tab-other'))
    const list = await screen.findByRole('list', { name: '其他物品列表' })
    const row = within(list).getByText('神秘贴纸').closest('li')
    expect(row).not.toBeNull()
    expect(within(row as HTMLElement).queryByRole('button')).toBeNull()
    expect(within(row as HTMLElement).getByText('没有装备槽的收藏品。'))
      .toBeInTheDocument()
  })

  it('shows the boost category and remaining time only while a boost is active', async () => {
    const fetchMock = mockApi({
      status: {
        diamond_boost: {
          expires_at: '2026-11-02T13:00:00+08:00',
          remaining_seconds: 900,
          multiplier: 2,
        },
      },
    })
    renderInventory()
    await screen.findByRole('heading', { name: '物品' })

    const category = await screen.findByTestId('shop-category-boosts')
    expect(within(category).getByTestId('shop-item-diamond_boost_25'))
      .toHaveTextContent('25 分钟')
    expect(within(category).getByText('剩余 15 分钟')).toBeInTheDocument()

    await userEvent.click(
      within(category).getByTestId('shop-item-diamond_boost_25')
        .querySelector('button') as HTMLButtonElement,
    )
    const purchaseCall = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith('/v1/shop/purchase'),
    )
    const body = JSON.parse(String(purchaseCall?.[1]?.body)) as {
      item_id: string
      quantity: number
      request_id: string
    }
    expect(body.item_id).toBe('diamond_boost_25')
    expect(body.quantity).toBe(1)
    expect(body.request_id.length).toBeGreaterThan(8)
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
