import {
  Flame,
  Gem,
  History,
  House,
  RefreshCw,
  Trophy,
  UserRound,
  Volume2,
  VolumeX,
  type LucideIcon,
} from 'lucide-react'
import { members, type PageId } from '../data'
import { useApp } from '../store'

const pageMeta: Record<Exclude<PageId, 'home'>, { title: string; icon: LucideIcon }> = {
  league: { title: '小组榜', icon: Trophy },
  embers: { title: '余烬', icon: Flame },
  history: { title: '历史', icon: History },
  me: { title: '我的', icon: UserRound },
}

export function TopBar() {
  const {
    page,
    navigate,
    embers,
    streak,
    refresh,
    refreshing,
    sound,
    toggleSound,
    openSheet,
  } = useApp()
  const rank = members.findIndex((member) => member.isMe) + 1
  const meta = page === 'home' ? { title: '首页', icon: House } : pageMeta[page]
  const PageIcon = meta.icon

  return (
    <header className="topbar" role="banner">
      {page === 'home' ? (
        <div className="status-strip" aria-label="我的状态">
          <button
            type="button"
            className="status-pill status-pill--streak"
            aria-label={`连续 ${streak} 天`}
            data-testid="status-streak"
            onClick={() => openSheet({ kind: 'repair' })}
          >
            <Flame className="status-pill__icon" aria-hidden="true" />
            <span className="status-pill__value">{streak}</span>
          </button>
          <button
            type="button"
            className="status-pill status-pill--embers"
            aria-label={`余烬 ${embers}`}
            data-testid="status-embers"
            onClick={() => navigate('embers')}
          >
            <Gem className="status-pill__icon" aria-hidden="true" />
            <span className="status-pill__value">{embers}</span>
          </button>
          <button
            type="button"
            className="status-pill status-pill--rank"
            aria-label={`组内第 ${rank}，查看小组榜`}
            data-testid="status-rank"
            onClick={() => navigate('league')}
          >
            <Trophy className="status-pill__icon" aria-hidden="true" />
            <span className="status-pill__value">#{rank}</span>
          </button>
        </div>
      ) : (
        <div className="page-heading">
          <span className="page-heading__mark" aria-hidden="true">
            <PageIcon className="icon-24" />
          </span>
          <h1 className="page-heading__title" data-testid="page-title">
            {meta.title}
          </h1>
        </div>
      )}

      <div className="topbar__tools">
        <button
          type="button"
          className="icon-button"
          aria-label="刷新"
          onClick={refresh}
          disabled={refreshing}
          data-testid="refresh-button"
        >
          <RefreshCw className={`icon-22 ${refreshing ? 'is-spinning' : ''}`} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label={sound ? '关闭声音' : '开启声音'}
          aria-pressed={sound}
          onClick={toggleSound}
          data-testid="sound-button"
        >
          {sound ? (
            <Volume2 className="icon-22" aria-hidden="true" />
          ) : (
            <VolumeX className="icon-22" aria-hidden="true" />
          )}
        </button>
      </div>
    </header>
  )
}
