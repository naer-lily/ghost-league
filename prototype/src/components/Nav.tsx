import { Flame, History, House, Trophy, UserRound, type LucideIcon } from 'lucide-react'
import type { PageId } from '../data'
import { useApp } from '../store'

interface NavItem {
  id: PageId
  label: string
  icon: LucideIcon
}

const items: NavItem[] = [
  { id: 'home', label: '首页', icon: House },
  { id: 'league', label: '小组榜', icon: Trophy },
  { id: 'embers', label: '余烬', icon: Flame },
  { id: 'history', label: '历史', icon: History },
  { id: 'me', label: '我的', icon: UserRound },
]

export function NavRail() {
  const { page, navigate } = useApp()
  return (
    <nav className="nav-rail" aria-label="主导航">
      <span className="nav-rail__mark" aria-hidden="true">
        <Flame className="icon-28" />
      </span>
      <div className="nav-rail__items">
        {items.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            className="nav-rail__item"
            aria-current={page === id ? 'page' : undefined}
            onClick={() => navigate(id)}
          >
            <Icon className="icon-24" aria-hidden="true" />
            <span className="nav-rail__label">{label}</span>
            <span className="nav-rail__underline" aria-hidden="true" />
          </button>
        ))}
      </div>
    </nav>
  )
}

export function BottomNav() {
  const { page, navigate } = useApp()
  return (
    <nav className="bottom-nav" aria-label="主导航">
      <div className="bottom-nav__items">
        {items.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            className="bottom-nav__item"
            aria-current={page === id ? 'page' : undefined}
            onClick={() => navigate(id)}
          >
            <Icon className="icon-24" aria-hidden="true" />
            <span className="bottom-nav__label">{label}</span>
            <span className="bottom-nav__underline" aria-hidden="true" />
          </button>
        ))}
      </div>
    </nav>
  )
}
