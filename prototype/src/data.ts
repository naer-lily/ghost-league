export type PageId = 'home' | 'league' | 'embers' | 'history' | 'me'

export type AvatarTone =
  | 'mint'
  | 'gold'
  | 'coral'
  | 'violet'
  | 'sky'
  | 'peach'
  | 'lime'
  | 'rose'

export interface Member {
  id: string
  name: string
  initial: string
  tone: AvatarTone
  xp: number
  streak: number
  title: string
  isMe?: boolean
}

export interface FeedItem {
  id: string
  memberId: string
  text: string
  time: string
  reactions: number
}

export interface EmberEntry {
  id: string
  title: string
  detail: string
  delta: number
  icon: 'flame' | 'calendar' | 'gift' | 'star'
}

export interface WeekRecord {
  id: string
  label: string
  range: string
  rank: number
  xp: number
  groupSize: number
  result: string
  resultTone: 'up' | 'stay'
  tier: string
  tierAsset: string
  top: { name: string; xp: number }[]
}

export type CollectionKind = 'frame' | 'badge' | 'background'

export interface CollectionItem {
  id: string
  kind: CollectionKind
  name: string
  owned: boolean
  unlock?: string
  icon?: 'flame' | 'sunrise' | 'trophy' | 'star' | 'calendar'
  gradient?: string
  frame?: 'ember' | 'bronze' | 'mint' | 'sun' | 'crown' | 'comet'
}

export interface NearbyPerson {
  id: string
  name: string
  initial: string
  tone: AvatarTone
  note: string
  xp: number
}

export interface RepairDay {
  id: string
  label: string
  meta: string
}

export type DayStatus = 'done' | 'today' | 'locked' | 'missed'

export interface PathDay {
  id: string
  weekday: string
  date: string
  xp: number
  status: DayStatus
  repaired?: boolean
}

export const GOAL_XP = 100
export const TODAY_XP = 110
export const WEEK_XP = 1320
export const STREAK = 3
export const EMBER_BALANCE = 1
export const PROMOTION_COUNT = 3
export const DEMOTION_COUNT = 3
export const GROUP_SIZE = 15

export const me: Member = {
  id: 'me',
  name: '你',
  initial: '你',
  tone: 'mint',
  xp: WEEK_XP,
  streak: STREAK,
  title: '本周第 4',
  isMe: true,
}

export const group = {
  name: 'G01',
  tier: '青铜',
  tierEn: 'Bronze',
  tierAsset: '/assets/tiers/bronze.png',
  size: GROUP_SIZE,
  promotion: PROMOTION_COUNT,
  demotion: DEMOTION_COUNT,
  settleLabel: '周日结算',
}

export const members: Member[] = [
  { id: 'u1', name: '星野', initial: '星', tone: 'violet', xp: 2450, streak: 6, title: '火力全开' },
  { id: 'u2', name: '小橙子', initial: '橙', tone: 'peach', xp: 1820, streak: 4, title: '稳步上分' },
  { id: 'u3', name: '阿团', initial: '团', tone: 'sky', xp: 1560, streak: 3, title: '不服就追' },
  me,
  { id: 'u4', name: '薄荷糖', initial: '薄', tone: 'mint', xp: 1180, streak: 3, title: '清凉选手' },
  { id: 'u5', name: '小满', initial: '满', tone: 'gold', xp: 1105, streak: 2, title: '刚好及格' },
  { id: 'u6', name: '纸飞机', initial: '纸', tone: 'coral', xp: 1040, streak: 2, title: '顺风飞行' },
  { id: 'u7', name: '橘子汽水', initial: '橘', tone: 'peach', xp: 980, streak: 1, title: '冒个泡' },
  { id: 'u8', name: '夜航', initial: '夜', tone: 'violet', xp: 915, streak: 2, title: '夜里最亮' },
  { id: 'u9', name: '麦芽', initial: '麦', tone: 'gold', xp: 860, streak: 1, title: '慢慢来' },
  { id: 'u10', name: '青柠', initial: '青', tone: 'lime', xp: 800, streak: 1, title: '酸一下' },
  { id: 'u11', name: '云朵', initial: '云', tone: 'sky', xp: 760, streak: 0, title: '飘着' },
  { id: 'u12', name: '小鹿', initial: '鹿', tone: 'rose', xp: 690, streak: 0, title: '刚上场' },
  { id: 'u13', name: '光年', initial: '光', tone: 'gold', xp: 620, streak: 0, title: '跑得远' },
  { id: 'u14', name: '团子', initial: '团', tone: 'peach', xp: 580, streak: 0, title: '软着陆' },
]

export const friends: Member[] = [
  members[0],
  { ...me, xp: 1320 },
  members[4],
  members[7],
  members[10],
  { id: 'f1', name: '小北', initial: '北', tone: 'sky', xp: 720, streak: 1, title: '老对手' },
  { id: 'f2', name: '可乐', initial: '可', tone: 'rose', xp: 660, streak: 0, title: '冒泡中' },
  { id: 'f3', name: '晴天', initial: '晴', tone: 'gold', xp: 610, streak: 1, title: '刚上线' },
]

export const pathDays: PathDay[] = [
  { id: 'mon', weekday: '周一', date: '10/26', xp: 0, status: 'missed' },
  { id: 'tue', weekday: '周二', date: '10/27', xp: 420, status: 'done' },
  { id: 'wed', weekday: '周三', date: '10/28', xp: 790, status: 'done' },
  { id: 'thu', weekday: '周四', date: '10/29', xp: TODAY_XP, status: 'today' },
  { id: 'fri', weekday: '周五', date: '10/30', xp: 0, status: 'locked' },
  { id: 'sat', weekday: '周六', date: '10/31', xp: 0, status: 'locked' },
  { id: 'sun', weekday: '周日', date: '11/01', xp: 0, status: 'locked' },
]

export const feed: FeedItem[] = [
  { id: 'ev1', memberId: 'u1', text: '点火 6 天', time: '2 小时前', reactions: 3 },
  { id: 'ev2', memberId: 'u4', text: '反超到第 5', time: '4 小时前', reactions: 5 },
  { id: 'ev3', memberId: 'u5', text: '解锁「早起鸟」', time: '昨天', reactions: 2 },
  { id: 'ev4', memberId: 'u3', text: '单日 480 XP', time: '昨天', reactions: 4 },
  { id: 'ev5', memberId: 'u7', text: '回来点火', time: '昨天', reactions: 1 },
  { id: 'ev6', memberId: 'u8', text: '本周首进前十', time: '2 天前', reactions: 6 },
]

export const repairDays: RepairDay[] = [
  { id: 'mon', label: '周一', meta: '10/26 · 1 枚' },
  { id: 'sun', label: '周日', meta: '10/25 · 1 枚' },
]

export const emberHistory: EmberEntry[] = [
  { id: 'e1', title: '累积 2,000 XP', detail: '昨天', delta: 1, icon: 'flame' },
  { id: 'e2', title: '补签周一', detail: '3 天前', delta: -1, icon: 'calendar' },
  { id: 'e3', title: '上周结算', detail: '6 天前', delta: 3, icon: 'gift' },
]

export const weeks: WeekRecord[] = [
  {
    id: 'w43',
    label: '第 43 周',
    range: '10/20 - 10/26',
    rank: 4,
    xp: 1240,
    groupSize: 15,
    result: '守住青铜',
    resultTone: 'stay',
    tier: '青铜',
    tierAsset: '/assets/tiers/bronze.png',
    top: [
      { name: '星野', xp: 2380 },
      { name: '小橙子', xp: 1900 },
      { name: '薄荷糖', xp: 1600 },
    ],
  },
  {
    id: 'w42',
    label: '第 42 周',
    range: '10/13 - 10/19',
    rank: 2,
    xp: 1860,
    groupSize: 15,
    result: '拿下第 2',
    resultTone: 'up',
    tier: '青铜',
    tierAsset: '/assets/tiers/bronze.png',
    top: [
      { name: '小橙子', xp: 2100 },
      { name: '你', xp: 1860 },
      { name: '星野', xp: 1750 },
    ],
  },
  {
    id: 'w41',
    label: '第 41 周',
    range: '10/06 - 10/12',
    rank: 9,
    xp: 640,
    groupSize: 15,
    result: '留在青铜',
    resultTone: 'stay',
    tier: '青铜',
    tierAsset: '/assets/tiers/bronze.png',
    top: [
      { name: '阿团', xp: 1680 },
      { name: '夜航', xp: 1540 },
      { name: '云朵', xp: 1420 },
    ],
  },
  {
    id: 'w40',
    label: '第 40 周',
    range: '09/29 - 10/05',
    rank: 12,
    xp: 410,
    groupSize: 15,
    result: '惊险留级',
    resultTone: 'stay',
    tier: '青铜',
    tierAsset: '/assets/tiers/bronze.png',
    top: [
      { name: '纸飞机', xp: 1490 },
      { name: '光年', xp: 1370 },
      { name: '橘子汽水', xp: 1250 },
    ],
  },
]

export const collectionItems: CollectionItem[] = [
  { id: 'frame-ember', kind: 'frame', name: '余烬框', owned: true, frame: 'ember' },
  { id: 'frame-bronze', kind: 'frame', name: '青铜框', owned: true, frame: 'bronze' },
  { id: 'frame-mint', kind: 'frame', name: '薄荷框', owned: true, frame: 'mint' },
  { id: 'frame-sun', kind: 'frame', name: '日轮框', owned: false, frame: 'sun', unlock: '连续 7 天' },
  { id: 'frame-crown', kind: 'frame', name: '王冠框', owned: false, frame: 'crown', unlock: '组内第 1' },
  { id: 'frame-comet', kind: 'frame', name: '彗星框', owned: false, frame: 'comet', unlock: '满 5 周' },
  { id: 'badge-spark', kind: 'badge', name: '点火者', owned: true, icon: 'flame' },
  { id: 'badge-early', kind: 'badge', name: '早起鸟', owned: true, icon: 'sunrise' },
  { id: 'badge-streak', kind: 'badge', name: '七日火', owned: false, icon: 'star', unlock: '连续 7 天' },
  { id: 'badge-top', kind: 'badge', name: '前三席', owned: false, icon: 'trophy', unlock: '组内第 1' },
  { id: 'badge-week', kind: 'badge', name: '满周', owned: false, icon: 'calendar', unlock: '满 7 天' },
  { id: 'bg-night', kind: 'background', name: '午夜蓝', owned: true, gradient: 'night' },
  { id: 'bg-mint', kind: 'background', name: '薄荷雾', owned: true, gradient: 'mint' },
  { id: 'bg-ember', kind: 'background', name: '余烬日落', owned: false, gradient: 'ember', unlock: '连续 7 天' },
  { id: 'bg-aurora', kind: 'background', name: '极光', owned: false, gradient: 'aurora', unlock: '组内第 1' },
]

export const nearbyPeople: NearbyPerson[] = [
  { id: 'n1', name: '小北', initial: '北', tone: 'sky', note: '同组 · 第 7', xp: 720 },
  { id: 'n2', name: '可乐', initial: '可', tone: 'rose', note: '同组 · 第 10', xp: 530 },
  { id: 'n3', name: '晴天', initial: '晴', tone: 'gold', note: '同组 · 第 11', xp: 480 },
]

export const tips = {
  streak: {
    label: '火焰与补签',
    title: '火焰怎么续？',
    body: '断签用 1 枚余烬补 1 天。只补签，不加 XP。',
  },
  league: {
    label: '晋级与降级',
    title: '晋级怎么算？',
    body: '15 人组。前 3 晋级，后 3 降级，周日 24:00 结算。',
  },
  embers: {
    label: '余烬用途',
    title: '余烬怎么用？',
    body: '1 XP = 6 秒。满 100 XP 点火。每 2,000 XP 得 1 枚。',
  },
  history: {
    label: '历史结算',
    title: '周怎么结算？',
    body: '周日 24:00 结算。名次和 XP 都按当周最终值。',
  },
  appearance: {
    label: '外观影响',
    title: '外观影响战绩？',
    body: '装饰品不影响 XP。',
  },
}

export const iconThemeOptions = [
  { id: 'rounded', label: '圆润' },
  { id: 'line', label: '线性' },
  { id: 'solid', label: '填色' },
] as const

export type IconTheme = (typeof iconThemeOptions)[number]['id']

export function findMember(id: string): Member | undefined {
  return [
    ...members,
    ...friends,
    ...nearbyPeople.map((p) => ({
      id: p.id,
      name: p.name,
      initial: p.initial,
      tone: p.tone,
      xp: p.xp,
      streak: 0,
      title: p.note,
    })),
  ].find((m) => m.id === id)
}
