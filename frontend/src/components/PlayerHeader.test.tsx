import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { buildHomeView } from '../lib/home'
import { makeSnapshot } from '../test/fixtures'
import { PlayerHeader } from './PlayerHeader'

function renderHeader() {
  const view = buildHomeView(makeSnapshot())
  return render(<PlayerHeader view={view} />)
}

describe('PlayerHeader', () => {
  it('keeps avatar, name, tier and streak in one non-wrapping flex row', () => {
    renderHeader()

    const header = screen.getByTestId('player-header')
    const style = window.getComputedStyle(header)
    expect(style.display).toBe('flex')
    expect(style.flexWrap).toBe('nowrap')
    expect(style.alignItems).toBe('center')

    expect(header.children).toHaveLength(4)
    expect(header.children[0]).toBe(screen.getByTestId('player-avatar'))
    expect(header.children[1]).toBe(screen.getByTestId('player-name'))
    expect(header.children[2]).toBe(screen.getByTestId('player-tier'))
    expect(header.children[3]).toBe(screen.getByTestId('streak-badge'))

    const avatar = screen
      .getByTestId('player-avatar')
      .querySelector<HTMLElement>('span[class*="avatar"]')
    expect(avatar?.style.getPropertyValue('--avatar-size')).toBe('64px')
    const tierIcon = screen.getByTestId('tier-icon')
    expect(tierIcon.style.getPropertyValue('--tier-icon-size')).toBe('20px')

    expect(screen.getByTestId('player-name')).toHaveTextContent('那尔')
    expect(screen.getByTestId('player-tier')).toHaveTextContent('青铜G01')
    expect(screen.getByTestId('streak-badge')).toHaveTextContent('2')
    expect(screen.getByTestId('streak-badge')).toHaveAttribute(
      'aria-label',
      '连续 2 天，今天已打卡',
    )
  })

  it('uses no card wrapper around the identity row', () => {
    renderHeader()

    expect(document.querySelectorAll('[class*="card"]')).toHaveLength(0)
    expect(screen.getByTestId('player-header')).toHaveAttribute(
      'data-flat',
      'true',
    )
  })
})
