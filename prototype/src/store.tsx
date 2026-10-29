import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  collectionItems as seedCollection,
  EMBER_BALANCE,
  emberHistory as seedEmberHistory,
  findMember,
  me,
  pathDays as seedPathDays,
  repairDays as seedRepairDays,
  STREAK,
  type CollectionKind,
  type EmberEntry,
  type IconTheme,
  type Member,
  type PageId,
  type PathDay,
  type RepairDay,
} from './data'

export type SheetState =
  | { kind: 'repair' }
  | { kind: 'day'; dayId: string }
  | { kind: 'user'; memberId: string; rank?: number }
  | { kind: 'feed' }
  | { kind: 'settings' }
  | { kind: 'edit' }
  | { kind: 'integration' }
  | { kind: 'nearby' }
  | { kind: 'week'; weekId: string }
  | { kind: 'logout' }
  | null

export interface ToastState {
  id: number
  message: string
  tone: 'success' | 'error'
}

interface AppContextValue {
  page: PageId
  navigate: (page: PageId) => void
  sound: boolean
  toggleSound: () => void
  haptics: boolean
  toggleHaptics: () => void
  iconTheme: IconTheme
  setIconTheme: (theme: IconTheme) => void
  profileName: string
  avatarSrc: string | null
  saveProfile: (name: string, avatar: string | null) => void
  embers: number
  streak: number
  days: PathDay[]
  repairDays: RepairDay[]
  emberLog: EmberEntry[]
  repair: (dayId: string) => void
  refreshing: boolean
  refresh: () => void
  share: () => void
  toast: ToastState | null
  notify: (message: string, tone?: 'success' | 'error') => void
  sheet: SheetState
  openSheet: (sheet: SheetState) => void
  closeSheet: () => void
  equipped: Record<CollectionKind, string>
  equip: (itemId: string) => void
  follows: string[]
  toggleFollow: (memberId: string) => void
  memberById: (id: string) => Member | undefined
  loggedOut: boolean
  logout: () => void
  login: () => void
}

const AppContext = createContext<AppContextValue | null>(null)

function read(key: string, fallback: string): string {
  try {
    return window.localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

function write(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    /* storage can be unavailable; the prototype keeps working in memory */
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<PageId>('home')
  const [sheet, setSheet] = useState<SheetState>(null)
  const [sound, setSound] = useState(() => read('gl.sound', 'true') === 'true')
  const [haptics, setHaptics] = useState(() => read('gl.haptics', 'true') === 'true')
  const [iconTheme, setIconThemeState] = useState<IconTheme>(
    () => (read('gl.iconTheme', 'rounded') as IconTheme) || 'rounded',
  )
  const [profileName, setProfileName] = useState(() => read('gl.profileName', '选手'))
  const [avatarSrc, setAvatarSrc] = useState<string | null>(null)
  const [embers, setEmbers] = useState(EMBER_BALANCE)
  const [streak, setStreak] = useState(STREAK)
  const [repairedDays, setRepairedDays] = useState<string[]>([])
  const [repairDays, setRepairDays] = useState<RepairDay[]>(() => [...seedRepairDays])
  const [emberLog, setEmberLog] = useState<EmberEntry[]>(() => [...seedEmberHistory])
  const [refreshing, setRefreshing] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [equipped, setEquipped] = useState<Record<CollectionKind, string>>({
    frame: 'frame-ember',
    badge: 'badge-spark',
    background: 'bg-night',
  })
  const [follows, setFollows] = useState<string[]>(['u2'])
  const [loggedOut, setLoggedOut] = useState(false)
  const toastSeq = useRef(0)
  const toastTimer = useRef<number | null>(null)

  const notify = useCallback((message: string, tone: 'success' | 'error' = 'success') => {
    toastSeq.current += 1
    setToast({ id: toastSeq.current, message, tone })
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), 2800)
  }, [])

  useEffect(() => {
    return () => {
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current)
    }
  }, [])

  useEffect(() => {
    write('gl.sound', String(sound))
  }, [sound])

  useEffect(() => {
    write('gl.haptics', String(haptics))
  }, [haptics])

  useEffect(() => {
    write('gl.iconTheme', iconTheme)
  }, [iconTheme])

  const navigate = useCallback((next: PageId) => {
    setPage(next)
    setSheet(null)
    window.scrollTo({ top: 0, behavior: 'auto' })
  }, [])

  const openSheet = useCallback((next: SheetState) => setSheet(next), [])
  const closeSheet = useCallback(() => setSheet(null), [])

  const buzz = useCallback(
    (ms = 12) => {
      if (!haptics) return
      try {
        navigator.vibrate?.(ms)
      } catch {
        /* devices without vibration simply skip it */
      }
    },
    [haptics],
  )

  const toggleSound = useCallback(() => {
    const next = !sound
    setSound(next)
    notify(next ? '声音已开' : '声音已关')
  }, [notify, sound])

  const toggleHaptics = useCallback(() => {
    const next = !haptics
    setHaptics(next)
    if (next) {
      try {
        navigator.vibrate?.(12)
      } catch {
        /* ignore unsupported devices */
      }
    }
    notify(next ? '轻触反馈已开' : '轻触反馈已关')
  }, [haptics, notify])

  const setIconTheme = useCallback((next: IconTheme) => {
    setIconThemeState(next)
  }, [])

  const saveProfile = useCallback(
    (name: string, avatar: string | null) => {
      const trimmed = name.trim() || '选手'
      setProfileName(trimmed)
      setAvatarSrc(avatar)
      write('gl.profileName', trimmed)
      setSheet(null)
      notify('已保存')
    },
    [notify],
  )

  const refresh = useCallback(() => {
    if (refreshing) return
    buzz()
    setRefreshing(true)
    window.setTimeout(() => {
      setRefreshing(false)
      notify('已更新')
    }, 600)
  }, [buzz, notify, refreshing])

  const share = useCallback(() => {
    buzz()
    notify('战绩卡已生成')
  }, [buzz, notify])

  const repair = useCallback(
    (dayId: string) => {
      const day = repairDays.find((item) => item.id === dayId)
      if (!day) return
      if (embers < 1) {
        notify('余烬不够。', 'error')
        return
      }
      setEmbers((value) => value - 1)
      setRepairDays((days) => days.filter((item) => item.id !== dayId))
      setRepairedDays((days) => (days.includes(dayId) ? days : [...days, dayId]))
      setStreak((value) => value + 1)
      setEmberLog((log) => [
        {
          id: `repair-${dayId}-${Date.now()}`,
          title: `补签${day.label}`,
          detail: '刚刚',
          delta: -1,
          icon: 'calendar',
        },
        ...log,
      ])
      setSheet(null)
      buzz(20)
      notify('火焰续上了。')
    },
    [buzz, embers, notify, repairDays],
  )

  const equip = useCallback(
    (itemId: string) => {
      const item = seedCollection.find((entry) => entry.id === itemId)
      if (!item || !item.owned) return
      if (equipped[item.kind] === item.id) return
      setEquipped((current) => ({ ...current, [item.kind]: item.id }))
      buzz()
      notify(`已装备 · ${item.name}`)
    },
    [buzz, equipped, notify],
  )

  const toggleFollow = useCallback(
    (memberId: string) => {
      const isFollowing = follows.includes(memberId)
      setFollows((current) =>
        isFollowing ? current.filter((id) => id !== memberId) : [...current, memberId],
      )
      buzz()
      notify(isFollowing ? '已取消关注' : '已关注')
    },
    [buzz, follows, notify],
  )

  const memberById = useCallback((id: string) => {
    if (id === 'me') return me
    return findMember(id)
  }, [])

  const logout = useCallback(() => {
    setSheet(null)
    setLoggedOut(true)
  }, [])

  const login = useCallback(() => {
    setLoggedOut(false)
    navigate('home')
    notify('欢迎回来')
  }, [navigate, notify])

  const days = useMemo<PathDay[]>(
    () =>
      seedPathDays.map((day) => {
        if (repairedDays.includes(day.id)) {
          return { ...day, status: 'done', xp: 0, repaired: true }
        }
        return day
      }),
    [repairedDays],
  )

  const value = useMemo<AppContextValue>(
    () => ({
      page,
      navigate,
      sound,
      toggleSound,
      haptics,
      toggleHaptics,
      iconTheme,
      setIconTheme,
      profileName,
      avatarSrc,
      saveProfile,
      embers,
      streak,
      days,
      repairDays,
      emberLog,
      repair,
      refreshing,
      refresh,
      share,
      toast,
      notify,
      sheet,
      openSheet,
      closeSheet,
      equipped,
      equip,
      follows,
      toggleFollow,
      memberById,
      loggedOut,
      logout,
      login,
    }),
    [
      page,
      navigate,
      sound,
      toggleSound,
      haptics,
      toggleHaptics,
      iconTheme,
      setIconTheme,
      profileName,
      avatarSrc,
      saveProfile,
      embers,
      streak,
      days,
      repairDays,
      emberLog,
      repair,
      refreshing,
      refresh,
      share,
      toast,
      notify,
      sheet,
      openSheet,
      closeSheet,
      equipped,
      equip,
      follows,
      toggleFollow,
      memberById,
      loggedOut,
      logout,
      login,
    ],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp(): AppContextValue {
  const value = useContext(AppContext)
  if (!value) throw new Error('useApp must be used inside AppProvider')
  return value
}
