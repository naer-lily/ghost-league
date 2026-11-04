import { describe, expect, it } from 'vitest'
import {
  formatAbsoluteTime,
  formatDateOnly,
  formatRelativeTime,
  formatTaskDeadline,
} from './time'

const NOW = new Date('2026-11-02T22:30:00+08:00')

describe('time formatting', () => {
  it('formats recent timestamps relative to the game timezone', () => {
    expect(formatRelativeTime('2026-11-02T22:29:30+08:00', NOW)).toBe('刚刚')
    expect(formatRelativeTime('2026-11-02T22:10:00+08:00', NOW)).toBe(
      '20 分钟前',
    )
    expect(formatRelativeTime('2026-11-02T18:30:00+08:00', NOW)).toBe(
      '4 小时前',
    )
    expect(formatRelativeTime('2026-11-01T20:00:00+08:00', NOW)).toBe('昨天')
    expect(formatRelativeTime('2026-10-30T20:00:00+08:00', NOW)).toBe('3 天前')
  })

  it('falls back to the absolute game date for older records', () => {
    expect(formatRelativeTime('2026-10-20T20:00:00+08:00', NOW)).toBe(
      '2026-10-20',
    )
    expect(formatDateOnly('2026-10-20T23:59:00+08:00')).toBe('2026-10-20')
    expect(formatAbsoluteTime('2026-11-02T22:31:00+08:00')).toBe(
      '2026-11-02 22:31',
    )
    expect(formatTaskDeadline('2026-11-05T00:00:00+08:00')).toBe('11/05 00:00')
  })

  it('does not crash on malformed input', () => {
    expect(formatRelativeTime('not-a-date', NOW)).toBe('时间未知')
    expect(formatAbsoluteTime('')).toBe('时间未知')
  })
})
