export interface LeagueGroup {
  id: number
  no: number
  tier: string
  week_start: string
  size: number
}

export interface Profile {
  user_id: string
  display_name: string
  avatar_url: string | null
  activity_label: string
  icon_theme: string
  tier: string
  group_id: number | null
  group_no: number | null
  joined_week: string
  week_start: string
  equipped_title: string | null
  frame: string | null
  backdrop: string | null
  badge_accent: string | null
  updated_at: string
}

export interface Streak {
  current: number
  longest: number
  clean_current: number
  last_checked_date: string | null
}

export interface EmberSummary {
  balance: number
  cap: number
  earned_this_week: number
}

export interface Star {
  id: string
  name: string
  kind: 'normal' | 'seasonal'
  season_key: string | null
  star_type: string
  type_label: string
  rarity: string
  rarity_label: string
  palette: string[]
  visual_seed: number
  companion_count: number
  catalog_code: string
  acquired_at: string
  svg_url: string
}

export interface ShopItem {
  id: string
  name: string
  description: string
  price_diamonds: number
  currency: 'diamonds'
  kind: 'star' | 'seasonal_star' | 'ember' | 'cap' | 'inventory'
  owned_quantity: number
  cooldown_seconds: number
  cooldown_until: string | null
  available: boolean
  gacha?: boolean
  rates?: Record<string, number>
  types?: string[]
  season_key?: string
  required_cap_level?: number
}

export interface StarPurchaseResult {
  ok: boolean
  item_id: string
  quantity: number
  diamonds: number
  diamond_cap: number
  diamond_cap_level: number
  diamond_excess: number
  inventory: Record<string, number>
  cooldown_until: string | null
  replayed: boolean
  star?: Star
  season_key?: string
}

export interface Status {
  user_id: string
  display_name: string
  avatar_url: string | null
  activity_label: string
  icon_theme: string
  tier: string
  group: LeagueGroup | null
  group_id: number | null
  group_size: number
  week_start: string
  seconds: number
  xp: number
  rank: number | null
  power: number | null
  power_percentile: number | null
  power_updated_at: string | null
  power_provisional: boolean
  today_seconds: number
  today_xp: number
  required_xp: number
  checkin: string | null
  streak: Streak
  embers: EmberSummary
  gems: number
  diamonds: number
  diamond_cap: number
  diamond_cap_level: number
  diamond_excess: number
  inventory: Record<string, number>
  stars: Star[]
  equipped_title: string | null
  equipped_title_id: string | null
  frame: string | null
  frame_id: string | null
  backdrop: string | null
  badge_accent: string | null
  next_settlement_at: string
  updated_at: string
}

export interface StandingRow {
  rank: number
  user_id: string
  display_name: string
  avatar_url: string | null
  is_me: boolean
  xp: number
  power: number | null
  checkin: string | null
  streak: number
  title: string | null
  frame: string | null
  frame_id: string | null
  backdrop: string | null
}

export interface Standings {
  week_start: string
  group: LeagueGroup | null
  group_id: number | null
  group_size: number
  me: { rank: number; xp: number } | null
  standings: StandingRow[]
}

export interface HomeSnapshot {
  profile: Profile
  status: Status
  standings: Standings
}

export interface TokenRotateResponse {
  user_id: string
  token: string
}
