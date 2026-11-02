import { describe, expect, it } from 'vitest'
import { filterHistory, historyMatchesFilter } from './history'
import type { HistoryItem } from '../api/types'

function item(id: string, type: HistoryItem['type']): HistoryItem {
  return { id, type, at: '2026-11-02T10:00:00+08:00', title: '', body: '', data: {} }
}

describe('history filters', () => {
  it('treats regular and group bets as the 下注 filter', () => {
    expect(historyMatchesFilter(item('bet:1', 'bet'), 'bet')).toBe(true)
    expect(historyMatchesFilter(item('group_bet:1', 'group_bet'), 'bet')).toBe(
      true,
    )
    expect(historyMatchesFilter(item('checkin:2026-11-02', 'checkin'), 'bet')).toBe(
      false,
    )
    expect(historyMatchesFilter(item('star:1', 'star'), 'all')).toBe(true)
  })

  it('keeps source order after filtering', () => {
    const items = [
      item('checkin:2026-11-02', 'checkin'),
      item('bet:2', 'bet'),
      item('group_bet:1', 'group_bet'),
      item('week:2026-10-26', 'week'),
    ]
    expect(filterHistory(items, 'bet').map((entry) => entry.id)).toEqual([
      'bet:2',
      'group_bet:1',
    ])
    expect(filterHistory(items, 'week')).toHaveLength(1)
  })
})
