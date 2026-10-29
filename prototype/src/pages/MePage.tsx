import { useState } from 'react'
import {
  Award,
  Check,
  Flame,
  Gem,
  Lock,
  Pencil,
  Settings,
  Sparkles,
  Trophy,
  UserRound,
  Zap,
} from 'lucide-react'
import {
  collectionItems,
  group,
  members,
  tips,
  WEEK_XP,
  type CollectionKind,
} from '../data'
import { useApp } from '../store'
import { Avatar, type FrameKind } from '../components/Avatar'
import { InfoTip } from '../components/InfoTip'
import { Segmented } from '../components/Segmented'

type Filter = 'all' | CollectionKind

const filters: { id: Filter; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'frame', label: '边框' },
  { id: 'badge', label: '勋章' },
  { id: 'background', label: '背景' },
]

const groupMeta: { kind: CollectionKind; label: string; icon: typeof UserRound }[] = [
  { kind: 'frame', label: '边框', icon: UserRound },
  { kind: 'badge', label: '勋章', icon: Award },
  { kind: 'background', label: '背景', icon: Sparkles },
]

const badgeIcons = {
  flame: Flame,
  sunrise: Sparkles,
  trophy: Trophy,
  star: Award,
  calendar: Sparkles,
}

export function MePage() {
  const {
    profileName,
    avatarSrc,
    embers,
    streak,
    equipped,
    equip,
    openSheet,
    navigate,
  } = useApp()
  const [filter, setFilter] = useState<Filter>('all')
  const rank = members.findIndex((member) => member.isMe) + 1
  const visibleGroups = groupMeta.filter((entry) => filter === 'all' || filter === entry.kind)

  return (
    <div className="me-page" data-testid="me-page">
      <section className="profile-hero" aria-labelledby="profile-name">
        <div className="profile-hero__avatar">
          <Avatar
            initial="你"
            tone="mint"
            size="xl"
            frame="ember"
            image={avatarSrc}
            name={profileName}
          />
        </div>
        <div className="profile-hero__id">
          <h2 className="profile-hero__name" id="profile-name">
            {profileName}
          </h2>
          <span className="tier-chip">
            <img src={group.tierAsset} alt="" width={22} height={22} />
            {group.tier}
          </span>
        </div>
        <div className="profile-hero__actions">
          <button
            type="button"
            className="icon-button"
            aria-label="编辑资料"
            data-testid="edit-profile"
            onClick={() => openSheet({ kind: 'edit' })}
          >
            <Pencil className="icon-20" aria-hidden="true" />
          </button>
          <button
            type="button"
            className="icon-button"
            aria-label="更多设置"
            data-testid="settings-button"
            onClick={() => openSheet({ kind: 'settings' })}
          >
            <Settings className="icon-20" aria-hidden="true" />
          </button>
        </div>
      </section>

      <div className="stat-quad" aria-label="我的统计">
        <button type="button" className="stat-cell" onClick={() => openSheet({ kind: 'repair' })} aria-label={`连续 ${streak} 天`}>
          <Flame className="stat-cell__icon stat-cell__icon--orange" aria-hidden="true" />
          <span className="stat-cell__value">{streak}</span>
          <span className="stat-cell__label">连续</span>
        </button>
        <button type="button" className="stat-cell" onClick={() => navigate('history')} aria-label={`本周 ${WEEK_XP} XP`}>
          <Zap className="stat-cell__icon stat-cell__icon--green" aria-hidden="true" />
          <span className="stat-cell__value">{WEEK_XP.toLocaleString('en-US')}</span>
          <span className="stat-cell__label">本周 XP</span>
        </button>
        <button type="button" className="stat-cell" onClick={() => navigate('league')} aria-label={`组内第 ${rank}`}>
          <Trophy className="stat-cell__icon stat-cell__icon--blue" aria-hidden="true" />
          <span className="stat-cell__value">#{rank}</span>
          <span className="stat-cell__label">组内排名</span>
        </button>
        <button type="button" className="stat-cell" onClick={() => navigate('embers')} aria-label={`余烬 ${embers}`}>
          <Gem className="stat-cell__icon stat-cell__icon--yellow" aria-hidden="true" />
          <span className="stat-cell__value">{embers}</span>
          <span className="stat-cell__label">余烬</span>
        </button>
      </div>

      <section className="collection" aria-labelledby="collection-title">
        <div className="section-head">
          <h2 className="section-head__title" id="collection-title">
            收藏
          </h2>
          <InfoTip {...tips.appearance} />
        </div>

        <Segmented value={filter} label="收藏筛选" options={filters} onChange={setFilter} />

        <div className="collection__groups">
          {visibleGroups.map(({ kind, label, icon: GroupIcon }) => {
            const items = collectionItems.filter((item) => item.kind === kind)
            const owned = items.filter((item) => item.owned).length
            return (
              <section key={kind} className="collection-group" aria-labelledby={`group-${kind}`}>
                <div className="collection-group__head">
                  <h3 className="collection-group__title" id={`group-${kind}`}>
                    <GroupIcon className="icon-18" aria-hidden="true" />
                    {label}
                  </h3>
                  <span className="collection-group__count">
                    {owned}/{items.length}
                  </span>
                </div>
                <ul className="collection-strip">
                  {items.map((item) => {
                    const isEquipped = equipped[kind] === item.id
                    const status = !item.owned ? 'locked' : isEquipped ? 'equipped' : 'available'
                    const BadgeIcon = item.icon ? badgeIcons[item.icon] : Sparkles
                    return (
                      <li key={item.id} className="collection-item">
                        <button
                          type="button"
                          className={`collection-tile is-${status}`}
                          aria-pressed={isEquipped}
                          disabled={!item.owned}
                          aria-label={`${item.name}，${
                            !item.owned ? `未解锁，${item.unlock}` : isEquipped ? '已装备' : '可装备'
                          }`}
                          data-testid="collection-tile"
                          onClick={() => equip(item.id)}
                        >
                          <span className="collection-tile__preview" aria-hidden="true">
                            {item.kind === 'frame' ? (
                              <Avatar
                                initial="你"
                                tone="mint"
                                size="sm"
                                frame={(item.frame ?? 'ember') as FrameKind}
                              />
                            ) : item.kind === 'badge' ? (
                              <span className={`badge-preview badge-preview--${item.icon ?? 'star'}`}>
                                <BadgeIcon className="icon-26" />
                              </span>
                            ) : (
                              <span className={`bg-preview bg-preview--${item.gradient ?? 'night'}`} />
                            )}
                          </span>
                          <span className="collection-tile__name">{item.name}</span>
                          {status === 'equipped' ? (
                            <span className="collection-tile__state" aria-hidden="true">
                              <Check className="icon-14" />
                            </span>
                          ) : status === 'locked' ? (
                            <span className="collection-tile__state" aria-hidden="true">
                              <Lock className="icon-14" />
                            </span>
                          ) : null}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </section>
            )
          })}
        </div>
      </section>
    </div>
  )
}
