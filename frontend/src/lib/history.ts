import type { HistoryItem, HistoryType } from '../api/types'

export type HistoryFilter =
  | 'all'
  | 'checkin'
  | 'bet'
  | 'rival'
  | 'star'
  | 'week'

export const HISTORY_FILTERS: ReadonlyArray<{
  id: HistoryFilter
  label: string
}> = [
  { id: 'all', label: '全部' },
  { id: 'checkin', label: '打卡' },
  { id: 'bet', label: '下注' },
  { id: 'rival', label: '宿敌' },
  { id: 'star', label: '星星' },
  { id: 'week', label: '周结算' },
]

export const HISTORY_TYPE_LABELS: Record<HistoryType, string> = {
  checkin: '打卡',
  bet: '下注',
  group_bet: '组内下注',
  rival: '宿敌',
  star: '星星',
  week: '周结算',
}

export function historyMatchesFilter(
  item: HistoryItem,
  filter: HistoryFilter,
): boolean {
  if (filter === 'all') return true
  if (filter === 'bet') return item.type === 'bet' || item.type === 'group_bet'
  return item.type === filter
}

export function filterHistory(
  items: HistoryItem[],
  filter: HistoryFilter,
): HistoryItem[] {
  return items.filter((item) => historyMatchesFilter(item, filter))
}
