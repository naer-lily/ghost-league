import {
  CalendarCheck2,
  History,
  RotateCcw,
  Swords,
  Star,
  Ticket,
  Trophy,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import { useHistory } from '../api/queries'
import type { HistoryItem, HistoryType } from '../api/types'
import { PullToRefresh } from '../components/PullToRefresh'
import { describeApiError } from '../lib/home'
import {
  filterHistory,
  HISTORY_FILTERS,
  HISTORY_TYPE_LABELS,
  type HistoryFilter,
} from '../lib/history'
import { formatAbsoluteTime, formatRelativeTime } from '../lib/time'
import { useUiStore } from '../store/useUiStore'
import styles from './HistoryPage.module.css'

const TYPE_ICONS: Record<HistoryType, LucideIcon> = {
  checkin: CalendarCheck2,
  bet: Ticket,
  group_bet: Ticket,
  rival: Swords,
  star: Star,
  week: Trophy,
}

function HistoryCard({ item }: { item: HistoryItem }) {
  const Icon = TYPE_ICONS[item.type]
  return (
    <li
      className={styles.item}
      data-type={item.type}
      data-testid="history-item"
    >
      <span className={styles.icon} aria-hidden="true">
        <Icon size={19} />
      </span>
      <article className={styles.card}>
        <div className={styles.cardHead}>
          <h2>{item.title}</h2>
          <span className={styles.typeTag}>{HISTORY_TYPE_LABELS[item.type]}</span>
        </div>
        <p className={styles.body}>{item.body}</p>
        <div className={styles.timeRow}>
          <time dateTime={item.at}>{formatRelativeTime(item.at)}</time>
          <span aria-hidden="true">·</span>
          <time dateTime={item.at}>{formatAbsoluteTime(item.at)}</time>
        </div>
      </article>
    </li>
  )
}

function HistoryLoading() {
  return (
    <div className={styles.state} aria-busy="true">
      <span className={styles.stateIcon} aria-hidden="true">
        <History size={26} />
      </span>
      <p className={styles.stateTitle}>正在读取历史记录</p>
      <p className={styles.stateCopy}>打卡、下注、星星和周结算会按时间汇总。</p>
    </div>
  )
}

export function HistoryPage() {
  const history = useHistory()
  const notify = useUiStore((state) => state.notify)
  const [filter, setFilter] = useState<HistoryFilter>('all')

  async function refresh() {
    const result = await history.refetch()
    if (result.error) {
      notify(describeApiError(result.error), 'error')
    } else {
      notify('历史记录已刷新。')
    }
  }

  if (history.isPending) {
    return (
      <div className={styles.page}>
        <HistoryHead onRefresh={() => void history.refetch()} refreshing />
        <HistoryLoading />
      </div>
    )
  }

  if (history.isError) {
    return (
      <div className={styles.page}>
        <HistoryHead onRefresh={() => void history.refetch()} refreshing />
        <section className={styles.state} role="alert">
          <span className={styles.stateIcon} aria-hidden="true">
            <History size={26} />
          </span>
          <p className={styles.stateTitle}>历史没有加载出来</p>
          <p className={styles.stateCopy}>{describeApiError(history.error)}</p>
          <button
            type="button"
            className="button button--primary"
            onClick={() => void history.refetch()}
            disabled={history.isFetching}
          >
            <RotateCcw size={17} aria-hidden="true" />
            {history.isFetching ? '正在重试…' : '重试'}
          </button>
        </section>
      </div>
    )
  }

  const items = history.data?.items ?? []
  const visible = filterHistory(items, filter)
  const filterLabel =
    HISTORY_FILTERS.find((item) => item.id === filter)?.label ?? '全部'

  return (
    <PullToRefresh onRefresh={refresh}>
      <div className={styles.page}>
        <HistoryHead onRefresh={() => void refresh()} refreshing={false} />

        <div
          className={styles.filters}
          role="group"
          aria-label="历史筛选"
        >
          {HISTORY_FILTERS.map((option) => (
            <button
              key={option.id}
              type="button"
              className={[
                styles.filter,
                filter === option.id ? styles.filterActive : '',
              ]
                .filter(Boolean)
                .join(' ')}
              aria-pressed={filter === option.id}
              data-testid={`history-filter-${option.id}`}
              onClick={() => setFilter(option.id)}
            >
              {option.label}
            </button>
          ))}
        </div>

        <p className={styles.count} data-testid="history-count" aria-live="polite">
          {filter === 'all' ? '全部' : filterLabel} {visible.length} 条
          {filter === 'all' ? null : ` / 全部 ${items.length} 条`}
        </p>

        {visible.length === 0 ? (
          <section className={styles.state} data-testid="history-empty">
            <span className={styles.stateIcon} aria-hidden="true">
              <History size={26} />
            </span>
            <p className={styles.stateTitle}>
              {items.length === 0
                ? '还没有历史记录'
                : `还没有${filterLabel}记录`}
            </p>
            <p className={styles.stateCopy}>
              {items.length === 0
                ? '完成打卡、下注或周结算后，真实记录会出现在这里。'
                : '换一个筛选，或下拉刷新后再看。'}
            </p>
            {items.length === 0 ? null : (
              <button
                type="button"
                className="button button--secondary"
                onClick={() => setFilter('all')}
              >
                查看全部
              </button>
            )}
          </section>
        ) : (
          <ol className={styles.timeline} aria-label="历史时间线">
            {visible.map((item) => (
              <HistoryCard key={item.id} item={item} />
            ))}
          </ol>
        )}
      </div>
    </PullToRefresh>
  )
}

function HistoryHead({
  onRefresh,
  refreshing,
}: {
  onRefresh: () => void
  refreshing: boolean
}) {
  return (
    <header className={styles.head}>
      <div className={styles.headText}>
        <p className="eyebrow">历史</p>
        <h1>我的历史</h1>
        <p className={styles.copy}>
          打卡、下注、宿敌、星星和周结算，按时间倒序排列。
        </p>
      </div>
      <button
        type="button"
        className={styles.refresh}
        onClick={onRefresh}
        disabled={refreshing}
        aria-label="刷新历史记录"
      >
        <RotateCcw size={18} aria-hidden="true" />
      </button>
    </header>
  )
}
