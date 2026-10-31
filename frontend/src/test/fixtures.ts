import type {
  HomeSnapshot,
  Profile,
  StandingRow,
  Standings,
  Status,
} from '../api/types'

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
    today_seconds: 779,
    today_xp: 129,
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
): StandingRow {
  return {
    rank,
    user_id,
    display_name,
    avatar_url: null,
    is_me,
    xp,
    checkin,
    streak,
    title: rank === 1 ? '点火' : '三日不息',
    frame: '余烬',
    frame_id: 'frame_ember',
    backdrop: null,
  }
}

export function makeStandings(overrides: Partial<Standings> = {}): Standings {
  return {
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
      row(10, 'naer-lily', '那尔', 524, true),
      row(11, 'ch-shai', '筛滤淘', 453, false, 'verified', 2),
      row(12, 'ch-lan', '蓝啼儿', 237, false, null, 1),
      row(13, 'ch-jun', '@Junhao', 201, false, 'verified', 1),
      row(14, 'ch-qdmxy', 'qdmxy', 182, false, null, 1),
      row(15, 'ch-ao', '@aoaostar', 59, false, null, 0),
    ],
    ...overrides,
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
