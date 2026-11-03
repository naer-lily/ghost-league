import type {
  BetOptions,
  GroupMarketOption,
  HomeSnapshot,
  Profile,
  StandingRow,
  Standings,
  Star,
  Status,
} from '../api/types'

export function makeGroupMarkets(
  overrides: Partial<Record<GroupMarketOption['market'], Partial<GroupMarketOption>>> = {},
): GroupMarketOption[] {
  const base: GroupMarketOption[] = [
    {
      market: 'top3',
      label: '押前三',
      available: true,
      can_place: true,
      reason: null,
      target_rank: 3,
      promotion_quota: 4,
      demotion_quota: 4,
      odds: 5.13,
      status: 'open',
      bet: null,
    },
    {
      market: 'promote',
      label: '押升段',
      available: true,
      can_place: true,
      reason: null,
      target_rank: 4,
      promotion_quota: 4,
      demotion_quota: 4,
      odds: 4.19,
      status: 'open',
      bet: null,
    },
    {
      market: 'no_demote',
      label: '押不降段',
      available: true,
      can_place: true,
      reason: null,
      target_rank: 12,
      promotion_quota: 4,
      demotion_quota: 4,
      odds: 1.62,
      status: 'open',
      bet: null,
    },
  ]
  return base
    .filter((entry) => overrides[entry.market] !== null)
    .map((entry) => ({ ...entry, ...(overrides[entry.market] ?? {}) }))
}

export function makeBetOptions(
  overrides: Partial<BetOptions> = {},
): BetOptions {
  return {
    weekly: {
      target_options: [
        { margin: 0, odds: 1.2, expected_xp: 500 },
        { margin: 150, odds: 1.5, expected_xp: 650 },
        { margin: 300, odds: 2, expected_xp: 800 },
        { margin: 600, odds: 3.2, expected_xp: 1100 },
      ],
      min_target_margin: 0,
      max_target_margin: 600,
      min_paid_stake: 0,
      max_paid_stake: 500,
      free_stake: 20,
      reference: 340,
    },
    daily: {
      target_options: [
        { margin: 1, odds: 1.2, expected_xp: 510 },
        { margin: 150, odds: 2, expected_xp: 660 },
        { margin: 300, odds: 3.1, expected_xp: 810 },
        { margin: 600, odds: 5, expected_xp: 1110 },
      ],
      min_target_margin: 1,
      max_target_margin: 600,
      min_paid_stake: 0,
      max_paid_stake: 500,
      free_stake: 20,
      reference: 100,
    },
    group: {
      target_rank: 3,
      target_margin: 0,
      min_paid_stake: 0,
      max_paid_stake: 500,
      free_stake: 20,
      odds: 5.13,
      markets: makeGroupMarkets(),
    },
    ...overrides,
  }
}

export function makeStar(overrides: Partial<Star> = {}): Star {
  return {
    id: 'star-1',
    name: '霜蓝',
    kind: 'normal',
    season_key: null,
    star_type: 'blue_white_star',
    type_label: '蓝白星',
    rarity: 'rare',
    rarity_label: '耀星',
    palette: ['#bfe4ff', '#ffffff', '#2b5b8a'],
    visual_seed: 4242,
    companion_count: 0,
    catalog_code: 'GL-2026-0A1B2C3D',
    acquired_at: '2026-10-31T10:00:00+08:00',
    svg_url: '/v1/me/stars/star-1/svg',
    ...overrides,
  }
}

export function makeProfile(overrides: Partial<Profile> = {}): Profile {
  return {
    user_id: 'naer-lily',
    display_name: '那尔',
    avatar_url: '/avatars/naer-lily',
    activity_label: '绘画',
    icon_theme: 'material',
    tier: 'Bronze',
    group_id: 1,
    group_no: 1,
    joined_week: '2026-10-26',
    week_start: '2026-10-26',
    equipped_title: '小丑',
    frame: '余烬',
    backdrop: null,
    badge_accent: null,
    updated_at: '2026-10-31T09:06:34+08:00',
    ...overrides,
  }
}

export function makeStatus(overrides: Partial<Status> = {}): Status {
  return {
    user_id: 'naer-lily',
    display_name: '那尔',
    avatar_url: '/avatars/naer-lily',
    activity_label: '绘画',
    icon_theme: 'material',
    tier: 'Bronze',
    group: {
      id: 1,
      no: 1,
      tier: 'Bronze',
      week_start: '2026-10-26',
      size: 15,
    },
    group_id: 1,
    group_size: 15,
    week_start: '2026-10-26',
    seconds: 3149,
    xp: 524,
    rank: 10,
    power: 1667,
    power_percentile: 0.625,
    power_updated_at: '2026-11-02T12:00:00+08:00',
    power_provisional: false,
    today_seconds: 779,
    today_xp: 129,
    last_activity_at: '2026-10-31T09:06:34+08:00',
    required_xp: 100,
    checkin: 'verified',
    streak: {
      current: 2,
      longest: 2,
      clean_current: 2,
      last_checked_date: '2026-10-31',
    },
    embers: { balance: 0, cap: 3, earned_this_week: 0 },
    gems: 128,
    diamonds: 720,
    diamond_cap: 1000,
    diamond_cap_level: 0,
    diamond_excess: 0,
    diamond_boost: {
      expires_at: null,
      remaining_seconds: 0,
      multiplier: 1,
    },
    inventory: { star: 1, seasonal_star: 0, ember: 0 },
    stars: [makeStar()],
    equipped_title: '小丑',
    equipped_title_id: 'title_clown',
    frame: '余烬',
    frame_id: 'frame_ember',
    backdrop: null,
    badge_accent: null,
    next_settlement_at: '2026-11-02T00:00:00+08:00',
    updated_at: '2026-10-31T09:06:34+08:00',
    ...overrides,
  }
}

function row(
  rank: number,
  user_id: string,
  display_name: string,
  xp: number,
  is_me = false,
  checkin: string | null = rank === 1 ? null : 'verified',
  streak = 2,
  power: number | null = 1200,
): StandingRow {
  return {
    rank,
    user_id,
    display_name,
    avatar_url: null,
    is_me,
    xp,
    power,
    checkin,
    streak,
    title: rank === 1 ? '点火' : '三日不息',
    frame: '余烬',
    frame_id: 'frame_ember',
    backdrop: null,
  }
}

export function makeStandings(overrides: Partial<Standings> = {}): Standings {
  const base: Standings = {
    week_start: '2026-10-26',
    group: {
      id: 1,
      no: 1,
      tier: 'Bronze',
      week_start: '2026-10-26',
      size: 15,
    },
    group_id: 1,
    group_size: 15,
    promotion_quota: 4,
    demotion_quota: 4,
    me: { rank: 10, xp: 524 },
    standings: [
      row(1, 'ch-xkein', '@Xkein', 8019),
      row(2, 'ch-roger', 'RogerRordo', 4975),
      row(3, 'ch-red', 'RedMcro', 4244),
      row(4, 'ch-kookouse', '@kookouse', 4071, false, 'verified', 2),
      row(5, 'ch-jipai', 'JiPai', 2342, false, null, 3),
      row(6, 'ch-night', '夜航', 1552, false, 'verified', 2),
      row(7, 'ch-hana', 'HanaTaka2137', 1057, false, null, 2),
      row(8, 'ch-gao', 'Gaopeiwen', 873, false, null, 1),
      row(9, 'ch-nine', '第九名', 748, false, null, 2),
      row(10, 'naer-lily', '那尔', 524, true, 'verified', 2, 1667),
      row(11, 'ch-shai', '筛滤淘', 453, false, 'verified', 2),
      row(12, 'ch-lan', '蓝啼儿', 237, false, null, 1),
      row(13, 'ch-jun', '@Junhao', 201, false, 'verified', 1),
      row(14, 'ch-qdmxy', 'qdmxy', 182, false, null, 1),
      row(15, 'ch-ao', '@aoaostar', 59, false, null, 0, null),
    ],
  }
  const group = 'group' in overrides ? overrides.group : base.group
  const groupSize =
    overrides.group_size ?? group?.size ?? base.group_size
  const tier = group?.tier ?? 'Bronze'
  const quota = Math.max(1, Math.floor((groupSize * 3) / 10))
  const rows = (overrides.standings ?? base.standings).map((entry) => ({
    ...entry,
    promoted: tier !== 'Diamond' && entry.rank <= quota,
    demoted: tier !== 'Bronze' && entry.rank > groupSize - quota,
  }))
  return {
    ...base,
    ...overrides,
    group,
    group_size: groupSize,
    promotion_quota: quota,
    demotion_quota: quota,
    standings: rows,
  }
}

export function makeSnapshot(
  overrides: Partial<{
    profile: Partial<Profile>
    status: Partial<Status>
    standings: Partial<Standings>
  }> = {},
): HomeSnapshot {
  return {
    profile: makeProfile(overrides.profile ?? {}),
    status: makeStatus(overrides.status ?? {}),
    standings: makeStandings(overrides.standings ?? {}),
  }
}
