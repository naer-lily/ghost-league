import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TIER_KEYS, TIER_SLUGS } from '../lib/tiers'
import { TierIcon } from './TierIcon'

function image(): HTMLImageElement {
  return screen.getByTestId('tier-icon').querySelector('img') as HTMLImageElement
}

describe('TierIcon', () => {
  it('loads the classic and material image for every tier', () => {
    for (const tier of TIER_KEYS) {
      const slug = TIER_SLUGS[tier]

      const classic = render(<TierIcon tier={tier} theme="classic" />)
      expect(image().getAttribute('src')).toBe(
        `/assets/tiers/classic/${slug}.png`,
      )
      expect(screen.getByTestId('tier-icon')).toHaveAttribute(
        'data-tier',
        tier,
      )
      classic.unmount()

      const material = render(<TierIcon tier={tier} theme="material" />)
      expect(image().getAttribute('src')).toBe(
        `/assets/tiers/material/${slug}.png`,
      )
      expect(screen.getByTestId('tier-icon')).toHaveAttribute(
        'data-theme',
        'material',
      )
      material.unmount()
    }
  })

  it('falls back to classic and bronze for unknown values', () => {
    render(<TierIcon tier="Neon" theme="neon" />)

    expect(screen.getByTestId('tier-icon')).toHaveAttribute(
      'data-tier',
      'Bronze',
    )
    expect(screen.getByTestId('tier-icon')).toHaveAttribute(
      'data-theme',
      'classic',
    )
    expect(image().getAttribute('src')).toBe('/assets/tiers/classic/bronze.png')
  })

  it('retries the other theme and then stops with no text fallback', () => {
    render(<TierIcon tier="Diamond" theme="material" />)

    fireEvent.error(image())
    expect(image().getAttribute('src')).toBe(
      '/assets/tiers/classic/diamond.png',
    )
    expect(screen.getByTestId('tier-icon')).toHaveAttribute(
      'data-fallback',
      'true',
    )

    fireEvent.error(image())
    expect(screen.getByTestId('tier-icon')).toHaveAttribute(
      'data-failed',
      'true',
    )
    expect(screen.getByTestId('tier-icon').textContent).toBe('')
  })
})
