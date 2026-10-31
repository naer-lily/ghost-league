export const TIER_KEYS = [
  'Bronze',
  'Silver',
  'Gold',
  'Sapphire',
  'Ruby',
  'Emerald',
  'Amethyst',
  'Pearl',
  'Obsidian',
  'Diamond',
] as const

export type TierKey = (typeof TIER_KEYS)[number]
export type IconTheme = 'classic' | 'material'

export const TIER_SLUGS: Record<TierKey, string> = {
  Bronze: 'bronze',
  Silver: 'silver',
  Gold: 'gold',
  Sapphire: 'sapphire',
  Ruby: 'ruby',
  Emerald: 'emerald',
  Amethyst: 'amethyst',
  Pearl: 'pearl',
  Obsidian: 'obsidian',
  Diamond: 'diamond',
}

const TIER_BY_LOWER = new Map<string, TierKey>(
  TIER_KEYS.map((tier) => [tier.toLowerCase(), tier]),
)

export function tierKey(tier: string | null | undefined): TierKey {
  if (!tier) return 'Bronze'
  return TIER_BY_LOWER.get(tier.trim().toLowerCase()) ?? 'Bronze'
}

export function iconTheme(theme: string | null | undefined): IconTheme {
  return theme === 'material' ? 'material' : 'classic'
}

export function alternateTheme(theme: IconTheme): IconTheme {
  return theme === 'classic' ? 'material' : 'classic'
}

function baseUrl(): string {
  const base = import.meta.env.BASE_URL || '/'
  return base.endsWith('/') ? base : `${base}/`
}

export function tierIconSrc(
  tier: string | null | undefined,
  theme: string | null | undefined,
): string {
  const key = tierKey(tier)
  const variant = iconTheme(theme)
  return `${baseUrl()}assets/tiers/${variant}/${TIER_SLUGS[key]}.png`
}
