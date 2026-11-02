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

export type RivalOutcome = 'win' | 'loss' | 'draw'

export type BetKind = 'weekly' | 'daily' | 'group'

export type BetStatus = 'placed' | 'won' | 'lost' | 'void'

export interface RivalPlayer {
  user_id: string
  display_name: string
  avatar_url: string | null
  group_no: number | null
  tier: string
  power: number
  week_xp: number
  today_xp: number
}

export interface RivalSelection {
  open: boolean
  locks_at: string
  auto_select_at: string
  mode: 'manual' | 'auto' | null
}

export interface RivalResult {
  week_start: string
  rival_id: string
  my_xp: number
  rival_xp: number
  outcome: RivalOutcome
  reward_diamonds: number
  settled_at: string
}

export interface Bet {
  id: number
  kind: BetKind
  period_key: string
  rival_id: string | null
  stake: number
  free_stake: number
  paid_stake: number
  target_margin: number
  odds: number
  status: BetStatus
  placed_at: string
  locked_at: string | null
  settled_at: string | null
  payout: number
  result_diff: number | null
  group_id?: number
  group_rank?: number | null
}

export interface RivalBets {
  weekly: Bet | null
  daily: Bet | null
  group: Bet | null
}

export interface BetWindows {
  weekly_locks_at: string
  daily_locks_at: string
  daily_settles_at: string
}

export interface RivalProjection {
  rival_week_estimate: number
  week_line: number
  rival_today_estimate: number
  daily_lines: Record<string, number>
}

export interface RivalState {
  server_now: string
  week_start: string
  selection: RivalSelection
  me: RivalPlayer
  rival: RivalPlayer | null
  result: RivalResult | null
  bets: RivalBets
  projection: RivalProjection | null
  bet_windows: BetWindows
}

export interface RivalCandidateList {
  server_now: string
  week_start: string
  selection_open: boolean
  candidates: RivalPlayer[]
}

export interface BetsState {
  server_now: string
  week_start: string
  day: string
  weekly: Bet | null
  daily: Bet | null
  group: Bet | null
  bets: RivalBets
  bet_windows: BetWindows
}

export interface PlaceBetResult {
  bet: Bet
  state: RivalState
}
