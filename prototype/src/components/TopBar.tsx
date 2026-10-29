import { RefreshCw, Volume2, VolumeX, Flame } from 'lucide-react'
import { group, me, type PageId } from '../data'
import { useApp } from '../store'
import { Avatar } from './Avatar'

const pageMeta: Record<Exclude<PageId, 'home'>, { title: string; sub: string }> = {
  league: { title: '小组榜', sub: `${group.tierEn} · ${group.name}` },
  embers: { title: '余烬', sub: '只补签 · 不加 XP' },
  history: { title: '历史', sub: '已结束的周' },
  me: { title: '我的', sub: '资料 · 收藏 · 设置' },
}

export function TopBar() {
  const {
    page,
    navigate,
    embers,
    refresh,
    refreshing,
    sound,
    toggleSound,
    profileName,
    avatarSrc,
  } = useApp()
  const meta = page === 'home' ? null : pageMeta[page]

  return (
    <header className="topbar" role="banner">
      <div className="topbar__inner">
        {page === 'home' ? (
          <>
            <button
              type="button"
              className="topbar__identity"
              aria-label="进入我的"
              onClick={() => navigate('me')}
            >
              <Avatar initial="你" tone="mint" size="sm" frame="ember" image={avatarSrc} />
              <span className="topbar__greeting">
                <span className="topbar__greeting-main">早早早，今天也来点火！</span>
                <span className="topbar__greeting-sub">
                  {profileName} · 连续 {me.streak} 天
                </span>
              </span>
            </button>
          </>
        ) : (
          <div className="topbar__title-block">
            <span className="topbar__mark" aria-hidden="true">
              <Flame className="icon-20" />
            </span>
            <h1 className="topbar__title">{meta?.title}</h1>
            <span className="topbar__sub">{meta?.sub}</span>
          </div>
        )}

        <div className="topbar__actions">
          {page === 'embers' ? <span className="topbar__count">{embers} 枚</span> : null}
          <button
            type="button"
            className="icon-button"
            aria-label="刷新"
            onClick={refresh}
            disabled={refreshing}
            data-testid="refresh-button"
          >
            <RefreshCw className={`icon-24 ${refreshing ? 'is-spinning' : ''}`} aria-hidden="true" />
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
              <Volume2 className="icon-24" aria-hidden="true" />
            ) : (
              <VolumeX className="icon-24" aria-hidden="true" />
            )}
          </button>
          <button
            type="button"
            className="icon-button topbar__avatar-action"
            aria-label="进入我的"
            onClick={() => navigate('me')}
          >
            <Avatar initial="你" tone="mint" size="sm" frame="ember" image={avatarSrc} />
          </button>
        </div>
      </div>
    </header>
  )
}
