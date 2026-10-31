import { describe, expect, it } from 'vitest'
import {
  alternateTheme,
  iconTheme,
  TIER_KEYS,
  TIER_SLUGS,
  tierIconSrc,
  tierKey,
} from './tiers'

describe('tier resources', () => {
  it('maps all ten tier keys to lowercase asset slugs', () => {
    expect(TIER_KEYS).toHaveLength(10)
    for (const tier of TIER_KEYS) {
      expect(TIER_SLUGS[tier]).toBe(tier.toLowerCase())
    }
  })

  it('builds classic and material paths from BASE_URL', () => {
    expect(tierIconSrc('Bronze', 'classic')).toBe(
      '/assets/tiers/classic/bronze.png',
    )
    expect(tierIconSrc('Diamond', 'material')).toBe(
      '/assets/tiers/material/diamond.png',
    )
  })

  it('falls back to classic for unknown themes and bronze for unknown tiers', () => {
    expect(iconTheme('neon')).toBe('classic')
    expect(iconTheme(undefined)).toBe('classic')
    expect(iconTheme('material')).toBe('material')
    expect(alternateTheme('material')).toBe('classic')
    expect(tierKey('unknown')).toBe('Bronze')
    expect(tierIconSrc('unknown', 'nope')).toBe(
      '/assets/tiers/classic/bronze.png',
    )
  })
})
