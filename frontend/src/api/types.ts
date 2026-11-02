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
  last_activity_at: string | null
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
  promoted?: boolean
  demoted?: boolean
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
  promotion_quota?: number
  demotion_quota?: number
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

export type GroupMarket = 'top3' | 'promote' | 'no_demote'

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
  market?: GroupMarket
  market_label?: string
  target_rank?: number | null
  group_id?: number
  group_size?: number | null
  promotion_quota?: number | null
  demotion_quota?: number | null
  group_rank?: number | null
}

export interface GroupMarketOption {
  market: GroupMarket
  label: string
  available: boolean
  can_place: boolean
  reason: string | null
  target_rank: number | null
  promotion_quota: number
  demotion_quota: number
  odds: number | null
  status: string
  bet: Bet | null
}

export interface RivalBets {
  weekly: Bet | null
  daily: Bet | null
  group: Bet | null
  groups?: GroupMarketOption[]
}

export interface BetWindows {
  weekly_locks_at: string
  daily_locks_at: string
  daily_settles_at: string
}

export interface TargetOption {
  margin: number
  odds: number
}

export interface RivalBetOption {
  target_options: TargetOption[]
  min_target_margin: number
  max_target_margin: number
  min_paid_stake: number
  max_paid_stake: number
  free_stake: number
  reference: number
}

export interface GroupBetOption {
  target_rank: number
  target_margin: 0
  min_paid_stake: number
  max_paid_stake: number
  free_stake: number
  odds: number | null
  markets?: GroupMarketOption[]
}

export interface BetOptions {
  weekly: RivalBetOption | null
  daily: RivalBetOption | null
  group: GroupBetOption | null
}

export interface RivalProjection {
  rival_week_estimate: number
  rival_today_estimate: number
  weekly_target_max: number
  daily_target_max: number
}

export interface RivalState {
  server_now: string
  week_start: string
  selection: RivalSelection
  me: RivalPlayer
  rival: RivalPlayer | null
  result: RivalResult | null
  bets: RivalBets
  bet_options: BetOptions
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
  groups?: GroupMarketOption[]
  bets: RivalBets
  bet_options: BetOptions
  bet_windows: BetWindows
}

export interface PlaceBetResult {
  bet: Bet
  state: RivalState
}


export interface CollectionTitle {
  id: string
  name: string
  description: string
  awarded_at: string
  season_id: number | null
  equipped: boolean
}

export interface CollectionItem {
  id: string
  name: string
  slot: 'frame' | 'backdrop' | 'badge_accent' | string
  description: string
  awarded_at: string
  season_id: number | null
  equipped: boolean
}

export interface CollectionEquipped {
  title_id: string | null
  frame_id: string | null
  backdrop_id: string | null
  badge_accent_id: string | null
  updated_at: string | null
}

export interface Collection {
  player_id: string
  titles: CollectionTitle[]
  items: CollectionItem[]
  equipped: CollectionEquipped
}

export interface FriendSummary {
  user_id: string
  display_name: string
  avatar_url: string | null
  activity_label: string | null
  tier: string | null
  group_id: number | null
  week_start: string
  xp: number
  rank: number | null
  group_size: number
  checkin: string | null
  streak: number
  equipped_title: string | null
  frame: string | null
  backdrop: string | null
  badge_accent: string | null
  is_following: boolean
  following_count: number
  followers_count: number
}

export interface FriendsStandings {
  week_start: string
  members: FriendSummary[]
}

export interface UserComparison {
  viewer_id: string
  target_id: string
  viewer_xp: number
  target_xp: number
  viewer_rank: number | null
  target_rank: number | null
  viewer_group_size: number
  target_group_size: number
  xp_diff: number
  leader: 'me' | 'them' | 'tie'
}

export interface UserSummary extends FriendSummary {
  comparison?: UserComparison | null
}

export type HistoryType =
  | 'checkin'
  | 'bet'
  | 'group_bet'
  | 'rival'
  | 'star'
  | 'week'

export interface HistoryItem {
  id: string
  type: HistoryType
  at: string
  title: string
  body: string
  data: Record<string, unknown>
}

export interface HistoryFeed {
  user_id: string
  generated_at: string
  limit: number
  items: HistoryItem[]
}

export interface FeedAuthor {
  id: string
  name: string
  title: string | null
  frame: string | null
  avatar_url: string | null
}

export interface FeedReaction {
  emoji: string
  count: number
  mine: boolean
}

export interface FeedTag {
  tag: string
  count: number
}

export interface FeedItem {
  id: number
  kind: string
  day: string
  body: string
  author: FeedAuthor
  reactions: FeedReaction[]
  tags: FeedTag[]
  created_at: string
}

export interface LeagueFeed {
  week_start: string
  generated_at: string
  items: FeedItem[]
}
