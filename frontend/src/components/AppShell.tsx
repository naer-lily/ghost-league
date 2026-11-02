import * as Tooltip from '@radix-ui/react-tooltip'
import type { UseQueryResult } from '@tanstack/react-query'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import {
  Diamond,
  Flame,
  History,
  Home,
  Package,
  Trophy,
  User,
} from 'lucide-react'
import type { CSSProperties } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useHomeSnapshot } from '../api/queries'
import type { HomeSnapshot } from '../api/types'
import { buildHomeView, formatNumber } from '../lib/home'
import { playClick } from '../lib/sound'
import { useUnauthorizedSignOut } from '../store/useSession'
import { useUiStore } from '../store/useUiStore'
import { Avatar } from './Avatar'
import { SettingsDialog } from './SettingsDialog'
import { Toast } from './Toast'
import styles from './AppShell.module.css'

const NAV_ITEMS = [
  {
    to: '/',
    label: '首页',
    icon: Home,
    end: true,
    color: '#58cc02',
    soft: 'rgba(88, 204, 2, 0.16)',
  },
  {
    to: '/league',
    label: '小组',
    icon: Trophy,
    end: false,
    color: '#ffc800',
    soft: 'rgba(255, 200, 0, 0.16)',
  },
  {
    to: '/inventory',
    label: '物品栏',
    icon: Package,
    end: false,
    color: '#ce82ff',
    soft: 'rgba(206, 130, 255, 0.16)',
  },
  {
    to: '/history',
    label: '历史',
    icon: History,
    end: false,
    color: '#1cb0f6',
    soft: 'rgba(28, 176, 246, 0.16)',
  },
  {
    to: '/me',
    label: '我的',
    icon: User,
    end: false,
    color: '#ce82ff',
    soft: 'rgba(206, 130, 255, 0.16)',
  },
] as const

type NavItemConfig = (typeof NAV_ITEMS)[number]

function TopBar({ home }: { home: UseQueryResult<HomeSnapshot, Error> }) {
  const view = home.data ? buildHomeView(home.data) : null
  const diamonds = view?.diamonds ?? 0

  return (
    <header className={styles.topbar}>
      <div className={styles.topbarInner}>
        <Link className={styles.brand} to="/" aria-label="炉火联赛首页">
          <span className={styles.brandMark} aria-hidden="true">
            <Flame size={22} />
          </span>
        </Link>

        <div className={styles.topActions}>
          <Link
            className={styles.diamondBalance}
            to="/inventory"
            data-testid="diamond-balance"
            aria-label={`钻石 ${diamonds}`}
          >
            <Diamond size={18} aria-hidden="true" />
            <span className={styles.diamondValue}>
              {formatNumber(diamonds)}
            </span>
          </Link>
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

function NavItem({
  item,
  variant,
}: {
  item: NavItemConfig
  variant: 'rail' | 'bottom'
}) {
  const soundEnabled = useUiStore((state) => state.soundEnabled)
  const location = useLocation()
  const Icon = item.icon
  const isActive = item.end
    ? location.pathname === item.to
    : location.pathname === item.to ||
      location.pathname.startsWith(`${item.to}/`)
  const style = {
    '--nav-color': item.color,
    '--nav-soft': item.soft,
  } as CSSProperties

  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <NavLink
          to={item.to}
          end={item.end}
          aria-label={item.label}
          style={style}
          onClick={() => playClick(soundEnabled, 640)}
          className={[
            variant === 'rail' ? styles.railItem : styles.bottomItem,
            isActive
              ? variant === 'rail'
                ? styles.railActive
                : styles.bottomActive
              : '',
          ]
            .filter(Boolean)
            .join(' ')}
        >
          <span
            className={
              variant === 'rail' ? styles.railIconBlock : styles.bottomIconBlock
            }
            aria-hidden="true"
          >
            <Icon size={variant === 'rail' ? 25 : 24} />
          </span>
        </NavLink>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          className={styles.tooltip}
          side={variant === 'rail' ? 'right' : 'top'}
          sideOffset={8}
        >
          {item.label}
          <Tooltip.Arrow className={styles.tooltipArrow} />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  )
}

function NavRail() {
  return (
    <nav className={styles.rail} aria-label="主导航">
      <Link className={styles.railBrand} to="/" aria-label="炉火联赛首页">
        <Flame size={24} aria-hidden="true" />
      </Link>
      <div className={styles.railItems}>
        {NAV_ITEMS.map((item) => (
          <NavItem key={item.to} item={item} variant="rail" />
        ))}
      </div>
    </nav>
  )
}

function BottomNav() {
  return (
    <nav className={styles.bottomNav} aria-label="主导航">
      {NAV_ITEMS.map((item) => (
        <NavItem key={item.to} item={item} variant="bottom" />
      ))}
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
