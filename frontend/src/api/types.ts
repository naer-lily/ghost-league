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
  today_seconds: number
  today_xp: number
  required_xp: number
  checkin: string | null
  streak: Streak
  embers: EmberSummary
  gems: number
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
