import {
  Award,
  Diamond,
  Flame,
  Frame,
  Package,
  RotateCcw,
  Star,
  Timer,
} from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'
import { useState } from 'react'
import {
  createRequestId,
  useCollection,
  useHomeSnapshot,
  usePurchaseShopItem,
  useShopCatalog,
  useUpdateLoadout,
} from '../api/queries'
import type {
  CollectionItem,
  CollectionTitle,
  LoadoutField,
  ShopItem,
  Star as StarModel,
} from '../api/types'
import { PageError, PageLoading } from '../components/PageState'
import { PlayerHeader } from '../components/PlayerHeader'
import { StarArt } from '../components/StarArt'
import { StarDialog } from '../components/StarDialog'
import {
  buildHomeView,
  describeApiError,
  formatNumber,
  formatPower,
  tierStyleVars,
} from '../lib/home'
import {
  describeShopError,
  formatAcquiredAt,
  formatRate,
  formatRemaining,
  formatSeasonKey,
  rarityColor,
  rarityLabel,
} from '../lib/shop'
import { useUiStore } from '../store/useUiStore'
import styles from './InventoryPage.module.css'

type InventoryTab = 'stars' | 'frames' | 'titles' | 'other'

const TABS: ReadonlyArray<{
  id: InventoryTab
  label: string
  icon: typeof Star
}> = [
  { id: 'stars', label: '星星', icon: Star },
  { id: 'frames', label: '边框', icon: Frame },
  { id: 'titles', label: '称号', icon: Award },
  { id: 'other', label: '其他', icon: Package },
]

const SLOT_FIELDS: Record<string, LoadoutField> = {
  frame: 'frame_id',
  backdrop: 'backdrop_id',
  badge_accent: 'badge_accent_id',
}

type ShopCategoryId = 'stars' | 'embers' | 'cap' | 'other'

interface ShopCategory {
  id: ShopCategoryId
  label: string
  icon: typeof Star
  items: ShopItem[]
}

function groupShopItems(items: ShopItem[]): ShopCategory[] {
  const categories: ShopCategory[] = [
    {
      id: 'stars',
      label: '星星',
      icon: Star,
      items: items.filter(
        (item) => item.kind === 'star' || item.kind === 'seasonal_star',
      ),
    },
    {
      id: 'embers',
      label: '余烬',
      icon: Flame,
      items: items.filter((item) => item.kind === 'ember'),
    },
    {
      id: 'cap',
      label: '仓库上限',
      icon: Package,
      items: items.filter((item) => item.kind === 'cap'),
    },
    {
      id: 'other',
      label: '其他商品',
      icon: Package,
      items: items.filter(
        (item) =>
          item.kind !== 'star' &&
          item.kind !== 'seasonal_star' &&
          item.kind !== 'ember' &&
          item.kind !== 'cap',
      ),
    },
  ]
  return categories.filter((category) => category.items.length > 0)
}

interface DrawEntryProps {
  item: ShopItem
  diamonds: number
  seasonalOwned: boolean
  pending: boolean
  pendingItemId: string | undefined
  onDraw: (item: ShopItem) => void
}

function DrawEntry({
  item,
  diamonds,
  seasonalOwned,
  pending,
  pendingItemId,
  onDraw,
}: DrawEntryProps) {
  const shortfall = Math.max(0, item.price_diamonds - diamonds)
  const unavailable = !item.available
  const isPending = pending && pendingItemId === item.id
  const isSeasonal = item.kind === 'seasonal_star'
  const types = item.types ?? []
  const rates = Object.entries(item.rates ?? {})
  const cooldown = formatRemaining(item.cooldown_until)

  let label = isSeasonal ? '抽取季节星' : '抽取一颗'
  if (isPending) label = '抽取中…'
  else if (unavailable) {
    label = isSeasonal && seasonalOwned ? '本月已获得' : '暂不可用'
  }

  return (
    <article
      className={styles.drawCard}
      data-testid={`shop-item-${item.id}`}
      data-available={item.available ? 'true' : 'false'}
    >
      <div className={styles.drawHead}>
        <span className={styles.drawIcon} aria-hidden="true">
          <Star size={20} />
        </span>
        <div className={styles.drawTitle}>
          <h3>{item.name}</h3>
          {isSeasonal && item.season_key ? (
            <span className={styles.seasonBadge}>
              {formatSeasonKey(item.season_key)}
            </span>
          ) : null}
        </div>
        <span className={styles.price}>
          <Diamond size={15} aria-hidden="true" />
          {formatNumber(item.price_diamonds)}
        </span>
      </div>

      <div className={styles.chips}>
        <span>{types.length} 种星体</span>
        <span>已拥有 {formatNumber(item.owned_quantity)} 颗</span>
        {cooldown ? (
          <span className={styles.cooldownChip}>
            <Timer size={13} aria-hidden="true" />
            {cooldown}
          </span>
        ) : null}
      </div>

      {rates.length > 0 ? (
        <div className={styles.rates} aria-label={`${item.name}概率`}>
          {rates.map(([key, value]) => (
            <div className={styles.rateRow} key={key} data-testid="star-rate">
              <span
                className={styles.rateLabel}
                style={{ color: rarityColor(key) }}
              >
                {rarityLabel(key)}
              </span>
              <span className={styles.rateBar} aria-hidden="true">
                <span
                  className={styles.rateFill}
                  style={{
                    width: `${Math.max(0, Math.min(100, value * 100))}%`,
                    background: rarityColor(key),
                  }}
                />
              </span>
              <span className={styles.rateValue}>{formatRate(value)}</span>
            </div>
          ))}
        </div>
      ) : null}

      <button
        type="button"
        className="button button--primary button--full"
        disabled={pending || unavailable || shortfall > 0}
        onClick={() => onDraw(item)}
      >
        {label}
      </button>
      {shortfall > 0 && !unavailable ? (
        <p className={styles.shortfall}>还差 {formatNumber(shortfall)} 钻石</p>
      ) : null}
    </article>
  )
}

interface ProductCardProps {
  item: ShopItem
  diamonds: number
  emberBalance: number
  emberCap: number
  diamondCap: number
  diamondCapLevel: number
  pending: boolean
  pendingItemId: string | undefined
  onBuy: (item: ShopItem) => void
}

function ProductCard({
  item,
  diamonds,
  emberBalance,
  emberCap,
  diamondCap,
  diamondCapLevel,
  pending,
  pendingItemId,
  onBuy,
}: ProductCardProps) {
  const shortfall = Math.max(0, item.price_diamonds - diamonds)
  const unavailable = !item.available
  const isPending = pending && pendingItemId === item.id
  const cooldown = formatRemaining(item.cooldown_until)
  const capReady =
    item.kind !== 'cap' ||
    (item.required_cap_level ?? diamondCapLevel) === diamondCapLevel
  const Icon = item.kind === 'ember' ? Flame : Package
  const iconClass =
    item.kind === 'ember'
      ? styles.emberIcon
      : item.kind === 'cap'
        ? styles.capIcon
        : styles.otherIcon

  let label = '购买'
  if (item.kind === 'ember') label = '兑换余烬'
  else if (item.kind === 'cap') label = '升级仓库'
  if (isPending) label = '购买中…'
  else if (!capReady) label = '等级不匹配'
  else if (unavailable) label = '暂不可用'
  else if (cooldown) label = '冷却中'

  const stats =
    item.kind === 'ember'
      ? `当前余烬 ${formatNumber(emberBalance)} / ${formatNumber(emberCap)}`
      : item.kind === 'cap'
        ? `当前仓库 ${diamondCapLevel} 级 · 上限 ${formatNumber(diamondCap)}`
        : `已拥有 ${formatNumber(item.owned_quantity)}`

  return (
    <article
      className={styles.drawCard}
      data-testid={`shop-item-${item.id}`}
      data-available={item.available ? 'true' : 'false'}
    >
      <div className={styles.drawHead}>
        <span
          className={`${styles.drawIcon} ${iconClass}`}
          aria-hidden="true"
        >
          <Icon size={20} />
        </span>
        <div className={styles.drawTitle}>
          <h3>{item.name}</h3>
        </div>
        <span className={styles.price}>
          <Diamond size={15} aria-hidden="true" />
          {formatNumber(item.price_diamonds)}
        </span>
      </div>

      <div className={styles.chips}>
        <span>{stats}</span>
        {cooldown ? (
          <span className={styles.cooldownChip}>
            <Timer size={13} aria-hidden="true" />
            {cooldown}
          </span>
        ) : null}
      </div>

      <button
        type="button"
        className="button button--primary button--full"
        disabled={pending || unavailable || !capReady || shortfall > 0}
        onClick={() => onBuy(item)}
      >
        {label}
      </button>
      {shortfall > 0 && !unavailable ? (
        <p className={styles.shortfall}>还差 {formatNumber(shortfall)} 钻石</p>
      ) : null}
    </article>
  )
}

function EmptyState({
  icon: Icon,
  title,
}: {
  icon: typeof Star
  title: string
}) {
  return (
    <div className={styles.empty} data-testid="inventory-empty">
      <span className={styles.emptyIcon} aria-hidden="true">
        <Icon size={28} />
      </span>
      <p className={styles.emptyTitle}>{title}</p>
    </div>
  )
}

function CollectionState({
  pending,
  error,
  retrying,
  onRetry,
  children,
}: {
  pending: boolean
  error: Error | null
  retrying: boolean
  onRetry: () => void
  children: ReactNode
}) {
  if (pending) {
    return (
      <div className={styles.collectionSkeleton} aria-busy="true">
        <span className="visually-hidden">正在读取物品…</span>
        {[0, 1, 2].map((row) => (
          <span className={styles.skeletonRow} key={row} />
        ))}
      </div>
    )
  }
  if (error) {
    return (
      <div className={styles.empty}>
        <span className={styles.emptyIcon} aria-hidden="true">
          <Package size={28} />
        </span>
        <p className={styles.emptyTitle}>{describeApiError(error)}</p>
        <button
          type="button"
          className="button button--secondary"
          onClick={onRetry}
          disabled={retrying}
        >
          <RotateCcw size={16} aria-hidden="true" />
          {retrying ? '正在重试…' : '重试'}
        </button>
      </div>
    )
  }
  return <>{children}</>
}

function CollectionRow({
  id,
  name,
  description,
  meta,
  equipped,
  pending,
  onToggle,
}: {
  id: string
  name: string
  description: string
  meta: string
  equipped: boolean
  pending: boolean
  onToggle?: (() => void) | undefined
}) {
  return (
    <li className={styles.collectionRow} data-equipped={equipped ? 'true' : undefined}>
      <div className={styles.collectionText}>
        <strong>{name}</strong>
        <p>{description || '暂无描述'}</p>
        <small>{meta}</small>
      </div>
      <div className={styles.collectionActions}>
        {equipped ? <span className={styles.equippedTag}>已装备</span> : null}
        {onToggle ? (
          <button
            type="button"
            className="button button--secondary"
            data-testid={`collection-action-${id}`}
            disabled={pending}
            onClick={onToggle}
          >
            {equipped ? '卸下' : '装备'}
          </button>
        ) : null}
      </div>
    </li>
  )
}

export function InventoryPage() {
  const home = useHomeSnapshot()
  const shop = useShopCatalog()
  const purchase = usePurchaseShopItem()
  const updateLoadout = useUpdateLoadout()
  const notify = useUiStore((state) => state.notify)
  const [tab, setTab] = useState<InventoryTab>('stars')
  const collection = useCollection(tab !== 'stars')
  const [revealStar, setRevealStar] = useState<StarModel | null>(null)
  const [detailStar, setDetailStar] = useState<StarModel | null>(null)
  const [drawError, setDrawError] = useState<string | null>(null)
  const [supplyError, setSupplyError] = useState<string | null>(null)

  if (home.isPending) return <PageLoading />

  if (home.isError) {
    return (
      <PageError
        message={describeApiError(home.error)}
        retrying={home.isFetching}
        onRetry={() => void home.refetch()}
      />
    )
  }

  if (!home.data) return <PageLoading />

  const view = buildHomeView(home.data)
  const style = tierStyleVars(view.tier) as CSSProperties

  if (shop.isPending) {
    return (
      <div className={styles.page}>
        <PlayerHeader view={view} />
        <PageLoading />
      </div>
    )
  }

  if (shop.isError) {
    return (
      <div className={styles.page}>
        <PlayerHeader view={view} />
        <PageError
          message={describeApiError(shop.error)}
          retrying={shop.isFetching}
          onRetry={() => void shop.refetch()}
        />
      </div>
    )
  }

  const items = shop.data ?? []
  const shopCategories = groupShopItems(items)
  const pendingItemId = purchase.isPending
    ? purchase.variables?.itemId
    : undefined
  const stars = view.stars
  const emberBalance =
    view.inventory.ember ??
    items.find((item) => item.kind === 'ember')?.owned_quantity ??
    view.embersBalance
  const emberCap = home.data.status.embers.cap
  const collectionItems = collection.data?.items ?? []
  const frames = collectionItems.filter((item) => item.slot === 'frame')
  const otherItems = collectionItems.filter((item) => item.slot !== 'frame')
  const consumables = Object.entries(view.inventory).filter(
    ([key, quantity]) => key !== 'star' && key !== 'seasonal_star' && quantity > 0,
  )

  function seasonalOwned(item: ShopItem): boolean {
    return stars.some(
      (star) =>
        star.kind === 'seasonal' &&
        Boolean(item.season_key) &&
        star.season_key === item.season_key,
    )
  }

  function handleDraw(item: ShopItem) {
    if (purchase.isPending) return
    setDrawError(null)
    setSupplyError(null)
    purchase.mutate(
      { itemId: item.id, requestId: createRequestId() },
      {
        onSuccess: (result) => {
          if (result.star) {
            setDetailStar(null)
            setRevealStar(result.star)
            notify('物品里多了一颗星。')
          } else {
            setDrawError('这次没有拿到星星，请稍后再试。')
          }
        },
        onError: (error) => setDrawError(describeShopError(error)),
      },
    )
  }

  function handlePurchase(item: ShopItem) {
    if (purchase.isPending) return
    setSupplyError(null)
    setDrawError(null)
    purchase.mutate(
      { itemId: item.id, requestId: createRequestId() },
      {
        onSuccess: () => {
          notify(
            item.kind === 'cap'
              ? '仓库已升级。'
              : item.kind === 'ember'
                ? '补给已兑换。'
                : '已购买。',
          )
        },
        onError: (error) => setSupplyError(describeShopError(error)),
      },
    )
  }

  function handleToggle(
    field: LoadoutField,
    id: string,
    name: string,
    equipped: boolean,
  ) {
    if (updateLoadout.isPending) return
    updateLoadout.mutate(
      { field, value: equipped ? null : id, name },
      {
        onError: (error) => notify(describeApiError(error), 'error'),
      },
    )
  }

  return (
    <div className={styles.page} style={style}>
      <PlayerHeader view={view} />

      <section className={styles.hero} aria-labelledby="inventory-title">
        <div className={styles.heroText}>
          <h1 id="inventory-title">物品</h1>
        </div>
        <div className={styles.wallet} data-testid="inventory-wallet">
          <span className={styles.balance} aria-label={`钻石 ${view.diamonds}`}>
            <Diamond size={18} aria-hidden="true" />
            <strong>{formatNumber(view.diamonds)}</strong>
            <small>钻石</small>
          </span>
          <span className={styles.cap}>
            仓库 {formatNumber(view.diamonds)} / {formatNumber(view.diamondCap)}
          </span>
          {view.diamondExcess > 0 ? (
            <span className={styles.excess}>
              超出 {formatNumber(view.diamondExcess)}，超出部分会随时间损耗
            </span>
          ) : null}
          <span className={styles.powerLine}>战力 {formatPower(view.power)}</span>
        </div>
      </section>

      <div className={styles.tabs} role="tablist" aria-label="物品分类">
        {TABS.map((entry) => {
          const Icon = entry.icon
          return (
            <button
              key={entry.id}
              type="button"
              role="tab"
              aria-selected={tab === entry.id}
              className={[
                styles.tab,
                tab === entry.id ? styles.tabActive : '',
              ]
                .filter(Boolean)
                .join(' ')}
              data-testid={`inventory-tab-${entry.id}`}
              onClick={() => setTab(entry.id)}
            >
              <Icon size={15} aria-hidden="true" />
              {entry.label}
            </button>
          )
        })}
      </div>

      {tab === 'stars' ? (
        <div className={styles.tabPanel} role="tabpanel" aria-label="星星">
          <section className={styles.section} aria-labelledby="inventory-stars-title">
            <div className={styles.sectionHead}>
              <div>
                <h2 id="inventory-stars-title">我的星星</h2>
              </div>
              {stars.length > 0 ? (
                <span className={styles.count}>{stars.length} 颗</span>
              ) : null}
            </div>
            {stars.length === 0 ? (
              <EmptyState
                icon={Star}
                title="还没有星星"
              />
            ) : (
              <div className={styles.starGrid} data-testid="star-library">
                {stars.map((star) => (
                  <button
                    key={star.id}
                    type="button"
                    className={styles.starCard}
                    data-testid="star-card"
                    data-rarity={star.rarity}
                    aria-label={`查看 ${star.name}，${star.type_label}，${star.rarity_label}`}
                    style={
                      {
                        '--rarity-color': rarityColor(star.rarity),
                      } as CSSProperties
                    }
                    onClick={() => setDetailStar(star)}
                  >
                    <StarArt star={star} className={styles.cardArt} />
                    <span className={styles.starName}>{star.name}</span>
                    <span className={styles.starMeta}>
                      <span>{star.type_label}</span>
                      <span
                        className={styles.starRarity}
                        style={{ color: rarityColor(star.rarity) }}
                      >
                        {star.rarity_label}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>
      ) : null}

      {tab === 'frames' ? (
        <div className={styles.tabPanel} role="tabpanel" aria-label="边框">
          <section className={styles.section} aria-labelledby="inventory-frames-title">
            <div className={styles.sectionHead}>
              <div>
                <h2 id="inventory-frames-title">边框</h2>
              </div>
              {frames.length > 0 ? (
                <span className={styles.count}>{frames.length} 个</span>
              ) : null}
            </div>
            <CollectionState
              pending={collection.isPending}
              error={collection.error}
              retrying={collection.isFetching}
              onRetry={() => void collection.refetch()}
            >
              {frames.length === 0 ? (
                <EmptyState
                  icon={Frame}
                  title="还没有边框"
                />
              ) : (
                <ul className={styles.collectionList} aria-label="边框列表">
                  {frames.map((item) => {
                    const field = SLOT_FIELDS[item.slot]
                    return (
                      <CollectionRow
                        key={item.id}
                        id={item.id}
                        name={item.name}
                        description={item.description}
                        meta={`获得于 ${formatAcquiredAt(item.awarded_at)}`}
                        equipped={item.equipped}
                        pending={updateLoadout.isPending}
                        onToggle={
                          field
                            ? () =>
                                handleToggle(
                                  field,
                                  item.id,
                                  item.name,
                                  item.equipped,
                                )
                            : undefined
                        }
                      />
                    )
                  })}
                </ul>
              )}
            </CollectionState>
          </section>
        </div>
      ) : null}

      {tab === 'titles' ? (
        <div className={styles.tabPanel} role="tabpanel" aria-label="称号">
          <section className={styles.section} aria-labelledby="inventory-titles-title">
            <div className={styles.sectionHead}>
              <div>
                <h2 id="inventory-titles-title">称号</h2>
              </div>
              {collection.data && collection.data.titles.length > 0 ? (
                <span className={styles.count}>
                  {collection.data.titles.length} 个
                </span>
              ) : null}
            </div>
            <CollectionState
              pending={collection.isPending}
              error={collection.error}
              retrying={collection.isFetching}
              onRetry={() => void collection.refetch()}
            >
              {(collection.data?.titles ?? []).length === 0 ? (
                <EmptyState
                  icon={Award}
                  title="还没有称号"
                />
              ) : (
                <ul className={styles.collectionList} aria-label="称号列表">
                  {(collection.data?.titles ?? []).map((title: CollectionTitle) => (
                    <CollectionRow
                      key={title.id}
                      id={title.id}
                      name={title.name}
                      description={title.description}
                      meta={`获得于 ${formatAcquiredAt(title.awarded_at)}`}
                      equipped={title.equipped}
                      pending={updateLoadout.isPending}
                      onToggle={() =>
                        handleToggle(
                          'title_id',
                          title.id,
                          title.name,
                          title.equipped,
                        )
                      }
                    />
                  ))}
                </ul>
              )}
            </CollectionState>
          </section>
        </div>
      ) : null}

      {tab === 'other' ? (
        <div className={styles.tabPanel} role="tabpanel" aria-label="其他">
          <section className={styles.section} aria-labelledby="inventory-other-title">
            <div className={styles.sectionHead}>
              <div>
                <h2 id="inventory-other-title">其他物品</h2>
              </div>
            </div>
            <CollectionState
              pending={collection.isPending}
              error={collection.error}
              retrying={collection.isFetching}
              onRetry={() => void collection.refetch()}
            >
              {otherItems.length === 0 && consumables.length === 0 ? (
                <EmptyState
                  icon={Package}
                  title="还没有其他物品"
                />
              ) : (
                <ul className={styles.collectionList} aria-label="其他物品列表">
                  {otherItems.map((item: CollectionItem) => {
                    const field = SLOT_FIELDS[item.slot]
                    return (
                      <CollectionRow
                        key={item.id}
                        id={item.id}
                        name={item.name}
                        description={item.description}
                        meta={`获得于 ${formatAcquiredAt(item.awarded_at)}`}
                        equipped={item.equipped}
                        pending={updateLoadout.isPending}
                        onToggle={
                          field
                            ? () =>
                                handleToggle(
                                  field,
                                  item.id,
                                  item.name,
                                  item.equipped,
                                )
                            : undefined
                        }
                      />
                    )
                  })}
                  {consumables.map(([key, quantity]) => (
                    <CollectionRow
                      key={key}
                      id={key}
                      name={
                        key === 'ember'
                          ? '余烬'
                          : (items.find((item) => item.id === key)?.name ?? key)
                      }
                      description={
                        key === 'ember'
                          ? '用于补签等操作的消耗品。'
                          : '消耗品'
                      }
                      meta={`持有 ${formatNumber(quantity)}`}
                      equipped={false}
                      pending={false}
                    />
                  ))}
                </ul>
              )}
            </CollectionState>
          </section>
        </div>
      ) : null}

      <section
        className={styles.shopSection}
        aria-labelledby="inventory-shop-title"
        data-testid="inventory-shop"
      >
        <div className={styles.sectionHead}>
          <div>
            <h2 id="inventory-shop-title">商店</h2>
          </div>
          {shopCategories.length > 0 ? (
            <span className={styles.count}>{items.length} 件商品</span>
          ) : null}
        </div>

        {drawError ? (
          <p role="alert" className={styles.error} data-testid="shop-draw-error">
            {drawError}
          </p>
        ) : null}
        {supplyError ? (
          <p role="alert" className={styles.error} data-testid="shop-purchase-error">
            {supplyError}
          </p>
        ) : null}

        {shopCategories.length === 0 ? (
          <EmptyState
            icon={Package}
            title="商店暂时没有商品"
          />
        ) : (
          <div className={styles.shopCategories}>
            {shopCategories.map((category) => {
              const Icon = category.icon
              return (
                <section
                  key={category.id}
                  className={styles.shopCategory}
                  aria-labelledby={`shop-category-${category.id}-title`}
                  data-testid={`shop-category-${category.id}`}
                >
                  <div className={styles.categoryHead}>
                    <span
                      className={[
                        styles.categoryIcon,
                        category.id === 'embers' ? styles.emberIcon : '',
                        category.id === 'cap' ? styles.capIcon : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      aria-hidden="true"
                    >
                      <Icon size={18} />
                    </span>
                    <div className={styles.categoryText}>
                      <h3 id={`shop-category-${category.id}-title`}>
                        {category.label}
                      </h3>
                    </div>
                    <span className={styles.count}>
                      {category.items.length} 件
                    </span>
                  </div>
                  <div className={styles.drawGrid}>
                    {category.id === 'stars'
                      ? category.items.map((item) => (
                          <DrawEntry
                            key={item.id}
                            item={item}
                            diamonds={view.diamonds}
                            seasonalOwned={seasonalOwned(item)}
                            pending={purchase.isPending}
                            pendingItemId={pendingItemId}
                            onDraw={handleDraw}
                          />
                        ))
                      : category.items.map((item) => (
                          <ProductCard
                            key={item.id}
                            item={item}
                            diamonds={view.diamonds}
                            emberBalance={emberBalance}
                            emberCap={emberCap}
                            diamondCap={view.diamondCap}
                            diamondCapLevel={view.diamondCapLevel}
                            pending={purchase.isPending}
                            pendingItemId={pendingItemId}
                            onBuy={handlePurchase}
                          />
                        ))}
                  </div>
                </section>
              )
            })}
          </div>
        )}
      </section>

      <StarDialog
        reveal={revealStar}
        detail={detailStar}
        onClose={() => {
          setRevealStar(null)
          setDetailStar(null)
        }}
      />
    </div>
  )
}
