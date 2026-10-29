import { useRef, useState } from 'react'
import {
  Award,
  BookOpen,
  Camera,
  Check,
  ChevronRight,
  Compass,
  Flame,
  Image as ImageIcon,
  Loader2,
  Lock,
  LogOut,
  Palette,
  Plus,
  Sparkles,
  Trophy,
  UserRound,
  Volume2,
  Zap,
} from 'lucide-react'
import {
  collectionItems,
  group,
  iconThemeOptions,
  me,
  tips,
  WEEK_XP,
  type CollectionKind,
  type IconTheme,
} from '../data'
import { useApp } from '../store'
import { Avatar, type FrameKind } from '../components/Avatar'
import { InfoTip } from '../components/InfoTip'
import { Segmented } from '../components/Segmented'
import { Switch } from '../components/Switch'

type Filter = 'all' | CollectionKind

const filters: { id: Filter; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'frame', label: '头像框' },
  { id: 'badge', label: '勋章' },
  { id: 'background', label: '背景' },
]

const groupMeta: { kind: CollectionKind; label: string; icon: typeof UserRound }[] = [
  { kind: 'frame', label: '头像框', icon: UserRound },
  { kind: 'badge', label: '勋章', icon: Award },
  { kind: 'background', label: '背景', icon: Palette },
]

const badgeIcons = {
  flame: Flame,
  sunrise: Sparkles,
  trophy: Trophy,
  star: Award,
  calendar: BookOpen,
}

export function MePage() {
  const {
    profileName,
    avatarSrc,
    saveProfile,
    iconTheme,
    setIconTheme,
    sound,
    toggleSound,
    haptics,
    toggleHaptics,
    equipped,
    equip,
    openSheet,
  } = useApp()
  const [draftName, setDraftName] = useState(profileName)
  const [draftAvatar, setDraftAvatar] = useState<string | null>(avatarSrc)
  const [saving, setSaving] = useState(false)
  const [filter, setFilter] = useState<Filter>('all')
  const fileRef = useRef<HTMLInputElement>(null)
  const previewChanged = draftAvatar !== avatarSrc

  const handleFile = (file: File | undefined) => {
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => setDraftAvatar(typeof reader.result === 'string' ? reader.result : null)
    reader.readAsDataURL(file)
  }

  const handleSave = () => {
    if (saving) return
    setSaving(true)
    window.setTimeout(() => {
      saveProfile(draftName, draftAvatar)
      setSaving(false)
    }, 420)
  }

  const visibleGroups = groupMeta.filter((entry) => filter === 'all' || filter === entry.kind)

  return (
    <div className="me-page" data-testid="me-page">
      <div className="me-layout">
        <div className="me-col me-col--identity">
          <section className="card profile-card" aria-labelledby="profile-title">
            <div className="profile-card__avatar">
              <Avatar
                initial="你"
                tone="mint"
                size="xl"
                frame="ember"
                image={draftAvatar}
                name={draftName}
              />
              {previewChanged ? <span className="chip chip--gold profile-card__preview">预览 · 未保存</span> : null}
            </div>

            <div className="profile-card__id">
              <p className="eyebrow">我的资料</p>
              <h2 className="profile-card__name" id="profile-title">
                {draftName || '选手'}
              </h2>
              <p className="profile-card__meta">
                {group.tier} · {group.name} · 本周第 4
              </p>
            </div>

            <div className="field">
              <label className="field__label" htmlFor="display-name">
                显示名
              </label>
              <input
                id="display-name"
                className="field__input"
                value={draftName}
                maxLength={12}
                onChange={(event) => setDraftName(event.target.value)}
                placeholder="选手"
                autoComplete="off"
              />
              <span className="field__hint">最多 12 个字</span>
            </div>

            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="visually-hidden"
              onChange={(event) => handleFile(event.target.files?.[0])}
              data-testid="avatar-input"
            />

            <div className="profile-card__actions">
              <button
                type="button"
                className="button button--secondary"
                onClick={() => fileRef.current?.click()}
                data-testid="choose-avatar"
              >
                <Camera className="icon-20" aria-hidden="true" />
                选择图片
              </button>
              <button
                type="button"
                className="button button--primary"
                onClick={handleSave}
                disabled={saving}
                data-testid="save-profile"
              >
                {saving ? (
                  <Loader2 className="icon-20 is-spinning" aria-hidden="true" />
                ) : (
                  <Check className="icon-20" aria-hidden="true" />
                )}
                {saving ? '保存中' : '保存资料'}
              </button>
            </div>
          </section>

          <div className="profile-stats" aria-label="我的统计">
            <div className="profile-stat">
              <Flame className="icon-20" aria-hidden="true" />
              <span className="profile-stat__value">{me.streak} 天</span>
              <span className="profile-stat__label">连续点火</span>
            </div>
            <div className="profile-stat">
              <Zap className="icon-20" aria-hidden="true" />
              <span className="profile-stat__value">{WEEK_XP}</span>
              <span className="profile-stat__label">本周 XP</span>
            </div>
            <div className="profile-stat">
              <Trophy className="icon-20" aria-hidden="true" />
              <span className="profile-stat__value">#4</span>
              <span className="profile-stat__label">组内名次</span>
            </div>
          </div>

          <section className="card theme-card" aria-labelledby="theme-title">
            <div className="card-head">
              <div>
                <p className="eyebrow">图标主题</p>
                <h2 className="card-title" id="theme-title">
                  换个手势
                </h2>
              </div>
              <Palette className="icon-24 icon--mint" aria-hidden="true" />
            </div>
            <div className="theme-options" role="group" aria-label="图标主题">
              {iconThemeOptions.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  className="theme-option"
                  aria-pressed={iconTheme === option.id}
                  onClick={() => setIconTheme(option.id as IconTheme)}
                >
                  <Flame className="icon-24" aria-hidden="true" />
                  <span>{option.label}</span>
                </button>
              ))}
            </div>
            <p className="card-foot__hint">只改图标粗细，不改战绩。</p>
          </section>
        </div>

        <div className="me-col me-col--collection">
          <section className="collection" aria-labelledby="collection-title">
            <div className="collection__head">
              <div>
                <p className="eyebrow">收藏</p>
                <h2 className="card-title" id="collection-title">
                  你的样子
                </h2>
              </div>
              <span className="collection__meta">
                <span className="caption">外观不加 XP</span>
                <InfoTip {...tips.appearance} />
              </span>
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
                        <GroupIcon className="icon-20" aria-hidden="true" />
                        {label}
                      </h3>
                      <span className="collection-group__count">
                        {owned}/{items.length}
                      </span>
                    </div>
                    <ul className="collection-grid">
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
                                    <BadgeIcon className="icon-24" />
                                  </span>
                                ) : (
                                  <span className={`bg-preview bg-preview--${item.gradient ?? 'night'}`} />
                                )}
                              </span>
                              <span className={`collection-tile__status collection-tile__status--${status}`}>
                                {status === 'equipped' ? (
                                  <>
                                    <Check className="icon-12" aria-hidden="true" />
                                    已装备
                                  </>
                                ) : status === 'available' ? (
                                  <>
                                    <Plus className="icon-12" aria-hidden="true" />
                                    可装备
                                  </>
                                ) : (
                                  <>
                                    <Lock className="icon-12" aria-hidden="true" />
                                    未解锁
                                  </>
                                )}
                              </span>
                            </button>
                            <span className="collection-item__name">{item.name}</span>
                            {!item.owned ? (
                              <span className="collection-item__unlock">{item.unlock}</span>
                            ) : null}
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

        <div className="me-col me-col--settings">
          <section className="card settings-card" aria-labelledby="settings-title">
            <div className="card-head">
              <div>
                <p className="eyebrow">设置</p>
                <h2 className="card-title" id="settings-title">
                  顺手调一下
                </h2>
              </div>
              <Sparkles className="icon-24 icon--mint" aria-hidden="true" />
            </div>

            <button
              type="button"
              className="setting-row"
              onClick={() => openSheet({ kind: 'integration' })}
            >
              <span className="setting-row__icon" aria-hidden="true">
                <BookOpen className="icon-20" />
              </span>
              <span className="setting-row__text">
                <span className="setting-row__title">集成说明</span>
                <span className="setting-row__sub">把活动时间接进来</span>
              </span>
              <ChevronRight className="icon-20" aria-hidden="true" />
            </button>

            <button
              type="button"
              className="setting-row"
              onClick={() => openSheet({ kind: 'nearby' })}
            >
              <span className="setting-row__icon" aria-hidden="true">
                <Compass className="icon-20" />
              </span>
              <span className="setting-row__text">
                <span className="setting-row__title">附近的人</span>
                <span className="setting-row__sub">看看同组还有谁</span>
              </span>
              <ChevronRight className="icon-20" aria-hidden="true" />
            </button>

            <div className="setting-row">
              <span className="setting-row__icon" aria-hidden="true">
                <Volume2 className="icon-20" />
              </span>
              <span className="setting-row__text">
                <span className="setting-row__title">声音</span>
                <span className="setting-row__sub">点亮时来一点动静</span>
              </span>
              <Switch checked={sound} onChange={toggleSound} label="声音" />
            </div>

            <div className="setting-row">
              <span className="setting-row__icon" aria-hidden="true">
                <Flame className="icon-20" />
              </span>
              <span className="setting-row__text">
                <span className="setting-row__title">轻触反馈</span>
                <span className="setting-row__sub">按下时轻轻一震</span>
              </span>
              <Switch checked={haptics} onChange={toggleHaptics} label="轻触反馈" />
            </div>
          </section>

          <section className="card account-card" aria-labelledby="account-title">
            <div className="card-head">
              <div>
                <p className="eyebrow">账号</p>
                <h2 className="card-title" id="account-title">
                  本机登录
                </h2>
              </div>
            </div>
            <p className="card-copy">退出会清除本机登录，战绩不受影响。</p>
            <button
              type="button"
              className="button button--danger button--full"
              onClick={() => openSheet({ kind: 'logout' })}
              data-testid="logout-button"
            >
              <LogOut className="icon-20" aria-hidden="true" />
              退出登录
            </button>
          </section>

          <p className="me-footnote">
            <ImageIcon className="icon-16" aria-hidden="true" />
            头像只在这台设备预览。
          </p>
        </div>
      </div>
    </div>
  )
}
