import { useEffect, useRef, useState } from 'react'
import {
  ArrowRight,
  CalendarPlus,
  Cable,
  Check,
  CheckCheck,
  Flame,
  KeyRound,
  Loader2,
  Lock,
  LogOut,
  RefreshCw,
  Share2,
  Sparkles,
  Star,
  Trophy,
  UserCheck,
  UserPlus,
  X,
} from 'lucide-react'
import {
  feed,
  friends,
  group,
  iconThemeOptions,
  members,
  nearbyPeople,
  weeks,
  type IconTheme,
  type Member,
  type PathDay,
} from '../data'
import { useApp } from '../store'
import { Avatar } from './Avatar'
import { EmberSprite } from './EmberSprite'
import { Sheet } from './Sheet'
import { Switch } from './Switch'

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="mini-stat">
      <span className="mini-stat__value">{value}</span>
      <span className="mini-stat__label">{label}</span>
    </div>
  )
}

function UserDetail({ member, rank }: { member: Member; rank: number }) {
  const { follows, toggleFollow, closeSheet } = useApp()
  const following = follows.includes(member.id)
  const isMe = Boolean(member.isMe)

  return (
    <Sheet
      open
      onClose={closeSheet}
      title={isMe ? '你' : member.name}
      variant="right"
      testId="user-detail-sheet"
    >
      <div className="user-detail">
        <div className="user-detail__hero">
          <Avatar
            initial={member.initial}
            tone={member.tone}
            size="xl"
            frame={isMe ? 'ember' : undefined}
            name={isMe ? '你' : member.name}
          />
          <div className="user-detail__id">
            <p className="user-detail__name">{isMe ? '你' : member.name}</p>
            <span className="tier-chip">
              <img src={group.tierAsset} alt="" width={20} height={20} />
              {group.tier}
            </span>
          </div>
        </div>

        <div className="detail-stats">
          <MiniStat label="名次" value={`#${rank}`} />
          <MiniStat label="XP" value={member.xp.toLocaleString('en-US')} />
          <MiniStat label="连续" value={`${member.streak}`} />
        </div>

        {isMe ? (
          <p className="sheet-note">这是你。</p>
        ) : (
          <button
            type="button"
            className={`button ${following ? 'button--secondary' : 'button--primary'} button--full`}
            onClick={() => toggleFollow(member.id)}
          >
            {following ? (
              <UserCheck className="icon-20" aria-hidden="true" />
            ) : (
              <UserPlus className="icon-20" aria-hidden="true" />
            )}
            {following ? '已关注' : '关注'}
          </button>
        )}
      </div>
    </Sheet>
  )
}

function DayIcon({ day }: { day: PathDay }) {
  if (day.status === 'today') return <Flame className="day-detail__icon" aria-hidden="true" />
  if (day.status === 'done') {
    return day.repaired ? (
      <Flame className="day-detail__icon" aria-hidden="true" />
    ) : (
      <CheckCheck className="day-detail__icon" aria-hidden="true" />
    )
  }
  if (day.status === 'missed') return <CalendarPlus className="day-detail__icon" aria-hidden="true" />
  return <Lock className="day-detail__icon" aria-hidden="true" />
}

function statusWord(day: PathDay): string {
  if (day.status === 'today') return '已点火'
  if (day.status === 'done') return day.repaired ? '已补签' : '已点火'
  if (day.status === 'missed') return '断签'
  return '未解锁'
}

function DaySheet({ dayId }: { dayId: string }) {
  const { days, repair, repairDays, closeSheet, share, navigate, openSheet } = useApp()
  const day = days.find((item) => item.id === dayId)
  if (!day) return null
  const canRepair = day.status === 'missed' && repairDays.some((item) => item.id === day.id)
  const isOpen = day.status === 'today' || day.status === 'done'

  return (
    <Sheet
      open
      onClose={closeSheet}
      title={`${day.weekday} ${day.date}`}
      variant="bottom"
      testId="day-sheet"
    >
      <div className={`day-detail day-detail--${day.status}`}>
        <span className={`day-detail__orb day-detail__orb--${day.status}`} aria-hidden="true">
          <DayIcon day={day} />
        </span>
        <div className="day-detail__score">
          <span className="day-detail__xp">{day.xp}</span>
          <span className="day-detail__unit">XP</span>
        </div>
        <span className={`day-detail__status day-detail__status--${day.status}`}>{statusWord(day)}</span>
      </div>

      <div className="sheet-actions">
        {canRepair ? (
          <button
            type="button"
            className="button button--primary button--full"
            onClick={() => repair(day.id)}
            data-testid="day-repair-button"
          >
            <CalendarPlus className="icon-20" aria-hidden="true" />
            补签 · 1
          </button>
        ) : null}
        {isOpen ? (
          <button
            type="button"
            className="button button--secondary button--full"
            onClick={share}
            data-testid="day-share-button"
          >
            <Share2 className="icon-20" aria-hidden="true" />
            分享
          </button>
        ) : null}
        <div className="button-row">
          <button
            type="button"
            className="button button--secondary"
            onClick={() => navigate('league')}
            data-testid="day-league-button"
          >
            <Trophy className="icon-20" aria-hidden="true" />
            小组榜
          </button>
          {day.status === 'today' ? (
            <button
              type="button"
              className="button button--secondary"
              onClick={() => openSheet({ kind: 'feed' })}
              data-testid="day-feed-button"
            >
              <Sparkles className="icon-20" aria-hidden="true" />
              动态
            </button>
          ) : null}
        </div>
      </div>
    </Sheet>
  )
}

function RepairSheet() {
  const { embers, repairDays, repair, closeSheet } = useApp()
  const [selected, setSelected] = useState(repairDays[0]?.id ?? '')

  useEffect(() => {
    if (!repairDays.some((day) => day.id === selected)) {
      setSelected(repairDays[0]?.id ?? '')
    }
  }, [repairDays, selected])

  const disabled = embers < 1 || repairDays.length === 0 || !selected

  return (
    <Sheet
      open
      onClose={closeSheet}
      title="补签"
      subtitle="1 枚 = 1 天"
      variant="center"
      testId="repair-sheet"
      footer={
        <button
          type="button"
          className="button button--primary button--full"
          disabled={disabled}
          onClick={() => repair(selected)}
          data-testid="repair-confirm"
        >
          <CalendarPlus className="icon-20" aria-hidden="true" />
          补签 · 1
        </button>
      }
    >
      <div className="repair">
        <div className="repair__balance">
          <EmberSprite size={34} />
          <strong>{embers}</strong>
          <span className="repair__balance-label">余烬</span>
        </div>

        {repairDays.length > 0 ? (
          <div className="repair__options" role="radiogroup" aria-label="选择补签日期">
            {repairDays.map((day) => (
              <button
                key={day.id}
                type="button"
                role="radio"
                aria-checked={selected === day.id}
                className={`repair__option ${selected === day.id ? 'is-selected' : ''}`}
                onClick={() => setSelected(day.id)}
              >
                <span className="repair__option-radio" aria-hidden="true">
                  {selected === day.id ? <Check className="icon-16" /> : null}
                </span>
                <span className="repair__option-label">{day.label}</span>
                <span className="repair__option-meta">{day.meta}</span>
              </button>
            ))}
          </div>
        ) : (
          <p className="sheet-note">没有可补的日子。</p>
        )}

        <p className={`repair__hint ${embers < 1 ? 'repair__hint--warn' : ''}`}>
          {embers < 1 ? '余烬不够。' : '只续火，不加 XP。'}
        </p>
      </div>
    </Sheet>
  )
}

function FeedSheet() {
  const { closeSheet, memberById } = useApp()
  return (
    <Sheet
      open
      onClose={closeSheet}
      title="动态"
      variant="right"
      testId="feed-sheet"
    >
      <ul className="feed-sheet-list">
        {feed.map((item) => {
          const actor = memberById(item.memberId)
          if (!actor) return null
          return (
            <li key={item.id} className="feed-row">
              <Avatar initial={actor.initial} tone={actor.tone} size="sm" />
              <span className="feed-row__body">
                <span className="feed-row__text">
                  <strong>{actor.name}</strong> {item.text}
                </span>
                <span className="feed-row__time">{item.time}</span>
              </span>
            </li>
          )
        })}
      </ul>
    </Sheet>
  )
}

function SettingsSheet() {
  const {
    closeSheet,
    openSheet,
    iconTheme,
    setIconTheme,
    sound,
    toggleSound,
    haptics,
    toggleHaptics,
  } = useApp()

  return (
    <Sheet open onClose={closeSheet} title="更多" variant="right" testId="settings-sheet">
      <section className="settings-block" aria-labelledby="theme-title">
        <h3 className="settings-block__title" id="theme-title">
          图标
        </h3>
        <div className="theme-options" role="group" aria-label="图标主题">
          {iconThemeOptions.map((option) => (
            <button
              key={option.id}
              type="button"
              className="theme-option"
              aria-pressed={iconTheme === option.id}
              onClick={() => setIconTheme(option.id as IconTheme)}
            >
              <Flame className="icon-22" aria-hidden="true" />
              <span>{option.label}</span>
            </button>
          ))}
        </div>
      </section>

      <div className="settings-list">
        <div className="setting-row">
          <span className="setting-row__icon" aria-hidden="true">
            <Sparkles className="icon-20" />
          </span>
          <span className="setting-row__title">声音</span>
          <Switch checked={sound} onChange={toggleSound} label="声音" />
        </div>
        <div className="setting-row">
          <span className="setting-row__icon" aria-hidden="true">
            <Flame className="icon-20" />
          </span>
          <span className="setting-row__title">轻触反馈</span>
          <Switch checked={haptics} onChange={toggleHaptics} label="轻触反馈" />
        </div>
        <button
          type="button"
          className="setting-row"
          onClick={() => openSheet({ kind: 'integration' })}
        >
          <span className="setting-row__icon" aria-hidden="true">
            <Cable className="icon-20" />
          </span>
          <span className="setting-row__title">集成说明</span>
          <ArrowRight className="icon-20" aria-hidden="true" />
        </button>
        <button
          type="button"
          className="setting-row"
          onClick={() => openSheet({ kind: 'nearby' })}
        >
          <span className="setting-row__icon" aria-hidden="true">
            <Star className="icon-20" />
          </span>
          <span className="setting-row__title">附近的人</span>
          <ArrowRight className="icon-20" aria-hidden="true" />
        </button>
        <button
          type="button"
          className="setting-row setting-row--danger"
          onClick={() => openSheet({ kind: 'logout' })}
          data-testid="logout-button"
        >
          <span className="setting-row__icon" aria-hidden="true">
            <LogOut className="icon-20" />
          </span>
          <span className="setting-row__title">退出</span>
          <ArrowRight className="icon-20" aria-hidden="true" />
        </button>
      </div>
    </Sheet>
  )
}

function EditSheet() {
  const { profileName, avatarSrc, saveProfile, closeSheet } = useApp()
  const [draftName, setDraftName] = useState(profileName)
  const [draftAvatar, setDraftAvatar] = useState<string | null>(avatarSrc)
  const [saving, setSaving] = useState(false)
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

  return (
    <Sheet
      open
      onClose={closeSheet}
      title="编辑资料"
      variant="center"
      testId="edit-sheet"
      footer={
        <button
          type="button"
          className="button button--primary button--full"
          onClick={handleSave}
          disabled={saving}
          data-testid="save-profile"
        >
          {saving ? (
            <Loader2 className="icon-20 is-spinning" aria-hidden="true" />
          ) : (
            <Check className="icon-20" aria-hidden="true" />
          )}
          {saving ? '保存中' : '保存'}
        </button>
      }
    >
      <div className="edit-profile">
        <div className="edit-profile__avatar">
          <Avatar initial="你" tone="mint" size="xl" frame="ember" image={draftAvatar} name={draftName} />
          {previewChanged ? <span className="edit-profile__preview">预览</span> : null}
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="visually-hidden"
          onChange={(event) => handleFile(event.target.files?.[0])}
          data-testid="avatar-input"
        />
        <button
          type="button"
          className="button button--secondary button--full"
          onClick={() => fileRef.current?.click()}
          data-testid="choose-avatar"
        >
          选择图片
        </button>
        <label className="field">
          <span className="field__label">名字</span>
          <input
            className="field__input"
            value={draftName}
            maxLength={12}
            onChange={(event) => setDraftName(event.target.value)}
            placeholder="选手"
            autoComplete="off"
          />
        </label>
      </div>
    </Sheet>
  )
}

function IntegrationSheet() {
  const { closeSheet } = useApp()
  return (
    <Sheet
      open
      onClose={closeSheet}
      title="集成"
      variant="center"
      testId="integration-sheet"
      footer={
        <button type="button" className="button button--secondary button--full" onClick={closeSheet}>
          知道了
        </button>
      }
    >
      <ol className="step-list">
        <li>
          <span className="step-list__icon" aria-hidden="true">
            <KeyRound className="icon-20" />
          </span>
          <span className="step-list__text">拿令牌</span>
        </li>
        <li>
          <span className="step-list__icon" aria-hidden="true">
            <Cable className="icon-20" />
          </span>
          <span className="step-list__text">填进工具</span>
        </li>
        <li>
          <span className="step-list__icon" aria-hidden="true">
            <RefreshCw className="icon-20" />
          </span>
          <span className="step-list__text">等刷新</span>
        </li>
      </ol>
      <p className="sheet-note">只读活动时间。</p>
    </Sheet>
  )
}

function NearbySheet() {
  const { follows, toggleFollow, closeSheet } = useApp()
  return (
    <Sheet
      open
      onClose={closeSheet}
      title="附近的人"
      variant="right"
      testId="nearby-sheet"
    >
      <ul className="people-list">
        {nearbyPeople.map((person) => {
          const following = follows.includes(person.id)
          return (
            <li key={person.id} className="people-row">
              <Avatar initial={person.initial} tone={person.tone} size="md" />
              <span className="people-row__id">
                <span className="people-row__name">{person.name}</span>
                <span className="people-row__meta">
                  {person.note} · {person.xp.toLocaleString('en-US')} XP
                </span>
              </span>
              <button
                type="button"
                className="chip-button"
                aria-pressed={following}
                onClick={() => toggleFollow(person.id)}
              >
                {following ? '已关注' : '关注'}
              </button>
            </li>
          )
        })}
      </ul>
    </Sheet>
  )
}

function WeekSheet({ weekId }: { weekId: string }) {
  const { closeSheet } = useApp()
  const week = weeks.find((item) => item.id === weekId)
  if (!week) return null

  return (
    <Sheet
      open
      onClose={closeSheet}
      title={week.label}
      subtitle={week.range}
      variant="right"
      testId="week-sheet"
    >
      <div className="week-detail">
        <div className="week-detail__hero">
          <img className="week-detail__tier" src={week.tierAsset} alt="" width={48} height={48} />
          <span className="week-detail__rank">
            <span>#</span>
            {week.rank}
          </span>
          <span className="week-detail__xp">
            {week.xp.toLocaleString('en-US')}
            <span>XP</span>
          </span>
        </div>
        <div className="top-list">
          {week.top.map((row, index) => (
            <div key={`${row.name}-${index}`} className="top-list__row">
              <span className="top-list__rank">{index + 1}</span>
              <span className="top-list__name">{row.name}</span>
              <span className="top-list__xp">{row.xp.toLocaleString('en-US')}</span>
            </div>
          ))}
        </div>
        <button type="button" className="chip-button" onClick={closeSheet}>
          关闭
        </button>
      </div>
    </Sheet>
  )
}

function LogoutSheet() {
  const { closeSheet, logout } = useApp()
  return (
    <Sheet
      open
      onClose={closeSheet}
      title="退出"
      variant="center"
      testId="logout-sheet"
      footer={
        <div className="button-row">
          <button type="button" className="button button--secondary" onClick={closeSheet}>
            <X className="icon-20" aria-hidden="true" />
            取消
          </button>
          <button type="button" className="button button--danger" onClick={logout} data-testid="logout-confirm">
            退出
            <ArrowRight className="icon-20" aria-hidden="true" />
          </button>
        </div>
      }
    >
      <p className="sheet-copy">下次要重新进入。</p>
    </Sheet>
  )
}

export function SheetHost() {
  const { sheet, memberById } = useApp()
  if (!sheet) return null

  if (sheet.kind === 'day') return <DaySheet dayId={sheet.dayId} />
  if (sheet.kind === 'repair') return <RepairSheet />
  if (sheet.kind === 'feed') return <FeedSheet />
  if (sheet.kind === 'settings') return <SettingsSheet />
  if (sheet.kind === 'edit') return <EditSheet />
  if (sheet.kind === 'integration') return <IntegrationSheet />
  if (sheet.kind === 'nearby') return <NearbySheet />
  if (sheet.kind === 'week') return <WeekSheet weekId={sheet.weekId} />
  if (sheet.kind === 'logout') return <LogoutSheet />

  if (sheet.kind === 'user') {
    const member = memberById(sheet.memberId)
    if (!member) return null
    const groupIndex = members.findIndex((item) => item.id === member.id)
    const friendIndex = friends.findIndex((item) => item.id === member.id)
    const rank = sheet.rank ?? (groupIndex >= 0 ? groupIndex + 1 : Math.max(1, friendIndex + 1))
    return <UserDetail member={member} rank={rank} />
  }

  return null
}
