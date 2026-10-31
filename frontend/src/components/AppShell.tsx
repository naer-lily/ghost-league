import * as Tooltip from '@radix-ui/react-tooltip'
import type { UseQueryResult } from '@tanstack/react-query'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import {
  Flame,
  History,
  Home,
  RefreshCw,
  Settings,
  Trophy,
  User,
  Volume2,
  VolumeX,
} from 'lucide-react'
import {
  type ReactNode,
  useState,
} from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useHomeSnapshot } from '../api/queries'
import type { HomeSnapshot } from '../api/types'
import {
  buildHomeView,
  describeApiError,
} from '../lib/home'
import { playClick } from '../lib/sound'
import { useUnauthorizedSignOut } from '../store/useSession'
import { useUiStore } from '../store/useUiStore'
import { Avatar } from './Avatar'
import { SettingsDialog } from './SettingsDialog'
import { Toast } from './Toast'
import styles from './AppShell.module.css'

const NAV_ITEMS = [
  { to: '/', label: '首页', icon: Home, end: true },
  { to: '/league', label: '小组', icon: Trophy, end: false },
  { to: '/embers', label: '余烬', icon: Flame, end: false },
  { to: '/history', label: '历史', icon: History, end: false },
  { to: '/me', label: '我的', icon: User, end: false },
] as const

interface IconActionProps {
  label: string
  tooltip: string
  onClick: () => void
  children: ReactNode
  pressed?: boolean
  disabled?: boolean
}

function IconAction({
  label,
  tooltip,
  onClick,
  children,
  pressed,
  disabled,
}: IconActionProps) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <button
          type="button"
          className={styles.iconAction}
          aria-label={label}
          aria-pressed={pressed}
          onClick={onClick}
          disabled={disabled}
        >
          {children}
        </button>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          className={styles.tooltip}
          side="bottom"
          sideOffset={7}
        >
          {tooltip}
          <Tooltip.Arrow className={styles.tooltipArrow} />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}

function TopBar({
  home,
}: {
  home: UseQueryResult<HomeSnapshot, Error>
}) {
  const soundEnabled = useUiStore((state) => state.soundEnabled)
  const toggleSound = useUiStore((state) => state.toggleSound)
  const notify = useUiStore((state) => state.notify)
  const setSettingsOpen = useUiStore((state) => state.setSettingsOpen)
  const [refreshing, setRefreshing] = useState(false)

  const view = home.data ? buildHomeView(home.data) : null
  const groupText = view
    ? view.groupLabel
    : home.isLoading
      ? '正在读取本周数据…'
      : '本周数据未连接'

  async function handleRefresh() {
    if (refreshing) return
    playClick(soundEnabled, 720)
    setRefreshing(true)
    const result = await home.refetch()
    setRefreshing(false)
    if (result.error) {
      notify(describeApiError(result.error), 'error')
    } else {
      notify('联赛数据已刷新。')
    }
  }

  function handleSound() {
    const next = toggleSound()
    playClick(next, 820)
    notify(next ? '声音已开启。' : '声音已关闭。')
  }

  return (
    <header className={styles.topbar}>
      <div className={styles.topbarInner}>
        <Link className={styles.brand} to="/" aria-label="炉火联赛首页">
          <span className={styles.brandMark} aria-hidden="true">
            <Flame size={22} />
          </span>
          <span className={styles.brandCopy}>
            <strong>炉火联赛</strong>
            <small>{groupText}</small>
          </span>
        </Link>

        <div className={styles.topActions}>
          <IconAction
            label="刷新联赛数据"
            tooltip="刷新"
            onClick={() => void handleRefresh()}
            disabled={refreshing}
          >
            <RefreshCw
              size={19}
              className={refreshing ? styles.spinning : undefined}
              aria-hidden="true"
            />
          </IconAction>
          <IconAction
            label={soundEnabled ? '关闭声音' : '开启声音'}
            tooltip={soundEnabled ? '关闭声音' : '开启声音'}
            onClick={handleSound}
            pressed={soundEnabled}
          >
            {soundEnabled ? (
              <Volume2 size={19} aria-hidden="true" />
            ) : (
              <VolumeX size={19} aria-hidden="true" />
            )}
          </IconAction>
          <IconAction
            label="打开设置"
            tooltip="设置"
            onClick={() => {
              playClick(soundEnabled, 760)
              setSettingsOpen(true)
            }}
          >
            <Settings size={19} aria-hidden="true" />
          </IconAction>
          <Link className={styles.avatarButton} to="/me" aria-label="个人页">
            <Avatar
              src={view?.avatarUrl ?? null}
              name={view?.displayName ?? '?'}
              size={34}
              loading="eager"
            />
          </Link>
        </div>
      </div>
    </header>
  )
}

function NavRail() {
  const soundEnabled = useUiStore((state) => state.soundEnabled)
  return (
    <nav className={styles.rail} aria-label="主导航">
      <Link className={styles.railBrand} to="/" aria-label="炉火联赛首页">
        <Flame size={24} aria-hidden="true" />
      </Link>
      <div className={styles.railItems}>
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={() => playClick(soundEnabled, 640)}
              className={({ isActive }) =>
                [styles.railItem, isActive ? styles.railActive : '']
                  .filter(Boolean)
                  .join(' ')
              }
            >
              <Icon size={24} aria-hidden="true" />
              <span>{item.label}</span>
            </NavLink>
          )
        })}
      </div>
    </nav>
  )
}

function BottomNav() {
  const soundEnabled = useUiStore((state) => state.soundEnabled)
  return (
    <nav className={styles.bottomNav} aria-label="主导航">
      {NAV_ITEMS.map((item) => {
        const Icon = item.icon
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={() => playClick(soundEnabled, 640)}
            className={({ isActive }) =>
              [styles.bottomItem, isActive ? styles.bottomActive : '']
                .filter(Boolean)
                .join(' ')
            }
          >
            <Icon size={22} aria-hidden="true" />
            <span>{item.label}</span>
          </NavLink>
        )
      })}
    </nav>
  )
}

export function AppShell() {
  const home = useHomeSnapshot()
  useUnauthorizedSignOut(home.error)
  const location = useLocation()
  const reducedMotion = useReducedMotion()
  const iconTheme = home.data?.profile.icon_theme ?? 'classic'

  return (
    <Tooltip.Provider delayDuration={180} skipDelayDuration={0}>
      <div className={styles.app} data-icon-theme={iconTheme}>
        <a className="skip-link" href="#main">
          跳到主内容
        </a>
        <TopBar home={home} />
        <NavRail />
        <div className={styles.contentWrap}>
          <main id="main" className={styles.main} tabIndex={-1}>
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={location.pathname}
                className={styles.pageMotion}
                initial={reducedMotion ? false : { opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reducedMotion ? { opacity: 1 } : { opacity: 0, y: -6 }}
                transition={
                  reducedMotion
                    ? { duration: 0 }
                    : { duration: 0.22, ease: [0.22, 1, 0.36, 1] }
                }
              >
                <Outlet />
              </motion.div>
            </AnimatePresence>
          </main>
        </div>
        <BottomNav />
        <SettingsDialog home={home} />
        <Toast />
      </div>
    </Tooltip.Provider>
  )
}
