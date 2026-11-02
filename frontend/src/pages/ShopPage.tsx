import type { CSSProperties } from 'react'
import { useState } from 'react'
import {
  Diamond,
  Flame,
  Package,
  Sparkles,
  Star,
  Timer,
} from 'lucide-react'
import {
  createRequestId,
  useHomeSnapshot,
  usePurchaseShopItem,
  useShopCatalog,
} from '../api/queries'
import type { ShopItem, Star as StarModel } from '../api/types'
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
  formatRate,
  formatRemaining,
  formatSeasonKey,
  rarityColor,
  rarityLabel,
} from '../lib/shop'
import { useUiStore } from '../store/useUiStore'
import styles from './ShopPage.module.css'

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
      data-testid={`shop-item-${item.kind}`}
      data-available={item.available ? 'true' : 'false'}
    >
      <div className={styles.drawHead}>
        <span className={styles.drawIcon} aria-hidden="true">
          {isSeasonal ? <Sparkles size={20} /> : <Star size={20} />}
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

      <p className={styles.description}>{item.description}</p>

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
        <p className={styles.shortfall}>
          还差 {formatNumber(shortfall)} 钻石
        </p>
      ) : null}
    </article>
  )
}

export function ShopPage() {
  const home = useHomeSnapshot()
  const shop = useShopCatalog()
  const purchase = usePurchaseShopItem()
  const notify = useUiStore((state) => state.notify)
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
  const drawItems = items.filter(
    (item) => item.kind === 'star' || item.kind === 'seasonal_star',
  )
  const emberItem = items.find((item) => item.kind === 'ember')
  const capItem = items.find((item) => item.kind === 'cap')
  const pendingItemId = purchase.isPending
    ? purchase.variables?.itemId
    : undefined
  const stars = view.stars
  const emberBalance =
    view.inventory.ember ?? emberItem?.owned_quantity ?? view.embersBalance
  const emberCap = home.data.status.embers.cap
  const emberCooldown = formatRemaining(emberItem?.cooldown_until ?? null)
  const capReady =
    capItem !== undefined &&
    (capItem.required_cap_level ?? view.diamondCapLevel) ===
      view.diamondCapLevel
  const emberShortfall = emberItem
    ? Math.max(0, emberItem.price_diamonds - view.diamonds)
    : 0
  const capShortfall = capItem
    ? Math.max(0, capItem.price_diamonds - view.diamonds)
    : 0

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
            notify('星图里多了一颗星。')
          } else {
            setDrawError('这次没有拿到星星，请稍后再试。')
          }
        },
        onError: (error) => setDrawError(describeShopError(error)),
      },
    )
  }

  function handleSupply(item: ShopItem) {
    if (purchase.isPending) return
    setSupplyError(null)
    setDrawError(null)
    purchase.mutate(
      { itemId: item.id, requestId: createRequestId() },
      {
        onSuccess: () => {
          notify(item.kind === 'cap' ? '仓库已升级。' : '补给已兑换。')
        },
        onError: (error) => setSupplyError(describeShopError(error)),
      },
    )
  }

  return (
    <div className={styles.page} style={style}>
      <PlayerHeader view={view} />

      <section className={styles.hero} aria-labelledby="shop-title">
        <div className={styles.heroText}>
          <p className="eyebrow">星图</p>
          <h1 id="shop-title">星图</h1>
          <p className={styles.heroCopy}>
            用钻石抽取星星，收集属于你的星库；也可以在这里补给余烬、升级仓库上限。
          </p>
        </div>
        <div className={styles.wallet} data-testid="shop-wallet">
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

      <section className={styles.section} aria-labelledby="shop-draw-title">
        <div className={styles.sectionHead}>
          <div>
            <h2 id="shop-draw-title">抽取</h2>
            <p>每次抽取随机得到一颗星，结果在抽取后揭晓。</p>
          </div>
        </div>
        {drawError ? (
          <p className={styles.error} role="alert" data-testid="shop-draw-error">
            {drawError}
          </p>
        ) : null}
        {drawItems.length === 0 ? (
          <p className={styles.emptyCopy}>商店暂时没有可抽取的星。</p>
        ) : (
          <div className={styles.drawGrid}>
            {drawItems.map((item) => (
              <DrawEntry
                key={item.id}
                item={item}
                diamonds={view.diamonds}
                seasonalOwned={seasonalOwned(item)}
                pending={purchase.isPending}
                pendingItemId={pendingItemId}
                onDraw={handleDraw}
              />
            ))}
          </div>
        )}
      </section>

      <section className={styles.section} aria-labelledby="shop-library-title">
        <div className={styles.sectionHead}>
          <div>
            <h2 id="shop-library-title">星库</h2>
            <p>已拥有的星星都在这里。</p>
          </div>
          {stars.length > 0 ? (
            <span className={styles.count}>{stars.length} 颗</span>
          ) : null}
        </div>
        {stars.length === 0 ? (
          <div className={styles.libraryEmpty} data-testid="star-library-empty">
            <span className={styles.emptyStar} aria-hidden="true">
              <Star size={30} />
            </span>
            <p>还没有星，去抽一颗</p>
          </div>
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

      <section className={styles.section} aria-labelledby="shop-supply-title">
        <div className={styles.sectionHead}>
          <div>
            <h2 id="shop-supply-title">补给</h2>
            <p>余烬和仓库上限，用钻石兑换。</p>
          </div>
        </div>
        {supplyError ? (
          <p
            className={styles.error}
            role="alert"
            data-testid="shop-supply-error"
          >
            {supplyError}
          </p>
        ) : null}
        <div className={styles.supplyGrid}>
          {emberItem ? (
            <article className={styles.supplyCard} data-testid="shop-item-ember">
              <div className={styles.supplyHead}>
                <span
                  className={`${styles.supplyIcon} ${styles.emberIcon}`}
                  aria-hidden="true"
                >
                  <Flame size={19} />
                </span>
                <div>
                  <h3>{emberItem.name}</h3>
                  <p>{emberItem.description}</p>
                </div>
              </div>
              <div className={styles.supplyStats}>
                <span>
                  当前余烬 {formatNumber(emberBalance)} / {formatNumber(emberCap)}
                </span>
                <span>
                  <Diamond size={14} aria-hidden="true" />
                  {formatNumber(emberItem.price_diamonds)}
                </span>
                {emberCooldown ? (
                  <span className={styles.cooldownChip}>
                    <Timer size={13} aria-hidden="true" />
                    剩余 {emberCooldown}
                  </span>
                ) : null}
              </div>
              <button
                type="button"
                className="button button--secondary button--full"
                disabled={
                  purchase.isPending ||
                  !emberItem.available ||
                  emberShortfall > 0
                }
                onClick={() => handleSupply(emberItem)}
              >
                {purchase.isPending && pendingItemId === emberItem.id
                  ? '兑换中…'
                  : emberCooldown
                    ? '冷却中'
                    : '兑换余烬'}
              </button>
              {emberShortfall > 0 ? (
                <p className={styles.shortfall}>
                  还差 {formatNumber(emberShortfall)} 钻石
                </p>
              ) : null}
            </article>
          ) : null}

          {capItem ? (
            <article
              className={styles.supplyCard}
              data-testid="shop-item-cap"
            >
              <div className={styles.supplyHead}>
                <span
                  className={`${styles.supplyIcon} ${styles.capIcon}`}
                  aria-hidden="true"
                >
                  <Package size={19} />
                </span>
                <div>
                  <h3>{capItem.name}</h3>
                  <p>{capItem.description}</p>
                </div>
              </div>
              <div className={styles.supplyStats}>
                <span>
                  当前仓库 {view.diamondCapLevel} 级 · 上限{' '}
                  {formatNumber(view.diamondCap)}
                </span>
                <span>
                  <Diamond size={14} aria-hidden="true" />
                  {formatNumber(capItem.price_diamonds)}
                </span>
                {!capReady ? (
                  <span className={styles.cooldownChip}>等级不匹配</span>
                ) : null}
              </div>
              <button
                type="button"
                className="button button--secondary button--full"
                disabled={
                  purchase.isPending ||
                  !capItem.available ||
                  !capReady ||
                  capShortfall > 0
                }
                onClick={() => handleSupply(capItem)}
              >
                {purchase.isPending && pendingItemId === capItem.id
                  ? '升级中…'
                  : '升级仓库'}
              </button>
              {capShortfall > 0 ? (
                <p className={styles.shortfall}>
                  还差 {formatNumber(capShortfall)} 钻石
                </p>
              ) : null}
            </article>
          ) : null}
        </div>
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
