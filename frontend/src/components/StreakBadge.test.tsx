import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StreakBadge } from './StreakBadge'

function badge() {
  return document.querySelector('[data-testid="streak-badge"]') as HTMLElement
}

function rgb(hex: string): [number, number, number] {
  return [
    Number.parseInt(hex.slice(1, 3), 16),
    Number.parseInt(hex.slice(3, 5), 16),
    Number.parseInt(hex.slice(5, 7), 16),
  ]
}

describe('StreakBadge', () => {
  it('shows only the flame and an integer, with a gray inactive state', () => {
    render(<StreakBadge value={7} checkedIn={false} />)

    const node = badge()
    expect(node.textContent).toBe('7')
    expect(node.textContent).not.toMatch(/天|连胜|连续|已打卡/)
    expect(node).toHaveAttribute('data-checked', 'false')
    expect(node.getAttribute('aria-label')).toBe(
      '连续 7 天，今天未打卡',
    )
    const flame = node.style.getPropertyValue('--streak-flame')
    const number = node.style.getPropertyValue('--streak-number')
    for (const color of [flame, number]) {
      const [r, g, b] = rgb(color)
      expect(r).toBe(g)
      expect(g).toBe(b)
    }
    expect(
      window.getComputedStyle(node.querySelector('svg')!).color,
    ).toBe('rgb(140, 140, 140)')
    expect(
      window.getComputedStyle(node.querySelector('[data-streak-value]')!).color,
    ).toBe('rgb(166, 166, 166)')
  })

  it('uses a colorful flame and warm number after check-in', () => {
    render(<StreakBadge value={2} checkedIn size="lg" />)

    const node = badge()
    expect(node.textContent).toBe('2')
    expect(node).toHaveAttribute('data-checked', 'true')
    expect(node.getAttribute('aria-label')).toBe(
      '连续 2 天，今天已打卡',
    )
    expect(node.style.getPropertyValue('--streak-flame')).toBe('#ff9d1f')
    expect(node.style.getPropertyValue('--streak-number')).toBe('#fff8ef')
    expect(
      window.getComputedStyle(node.querySelector('svg')!).color,
    ).toBe('rgb(255, 157, 31)')
  })

  it('accepts an explicit accessible label without adding visible text', () => {
    render(
      <StreakBadge
        value={12}
        checkedIn
        label="最长连续 12 天"
      />,
    )

    expect(badge().textContent).toBe('12')
    expect(badge().getAttribute('aria-label')).toBe('最长连续 12 天')
  })
})
