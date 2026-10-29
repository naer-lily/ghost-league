import { useEffect, useState } from 'react'
import {
  ArrowRight,
  CalendarPlus,
  Cable,
  Check,
  Flame,
  KeyRound,
  RefreshCw,
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
  members,
  nearbyPeople,
  weeks,
  type Member,
} from '../data'
import { useApp } from '../store'
import { Avatar } from './Avatar'
import { Sheet } from './Sheet'

function DetailStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-stat">
      <span className="detail-stat__value">{value}</span>
      <span className="detail-stat__label">{label}</span>
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
      title={isMe ? '你的资料' : member.name}
      subtitle={`${group.tier} · ${group.name} · 本周`}
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
            <p className="user-detail__title">{member.title}</p>
            <span className="chip chip--gold">
              <Star className="icon-16" aria-hidden="true" />
              本周 {member.xp.toLocaleString('en-US')} XP
            </span>
          </div>
        </div>

        <div className="detail-stats">
          <DetailStat label="本周 XP" value={member.xp.toLocaleString('en-US')} />
          <DetailStat label="连续点火" value={`${member.streak} 天`} />
          <DetailStat label="榜上名次" value={`#${rank}`} />
        </div>

        <section className="sheet-section" aria-label="本周高光">
          <h3 className="sheet-section__title">本周高光</h3>
          <ul className="highlight-list">
            <li>
              <Flame className="icon-20" aria-hidden="true" />
              点火 {Math.max(1, member.streak)} 天，火还亮着
            </li>
            <li>
              <Sparkles className="icon-20" aria-hidden="true" />
              最高单日 {Math.round(member.xp / 4).toLocaleString('en-US')} XP
            </li>
            <li>
              <Trophy className="icon-20" aria-hidden="true" />
              距离上一名还差 {Math.max(0, 80 - (rank % 3) * 20)} XP
            </li>
          </ul>
        </section>

        {isMe ? (
          <p className="sheet-note">这是你。自己的行永远在榜上。</p>
        ) : (
          <button type="button" className="button button--secondary button--full" onClick={() => toggleFollow(member.id)}>
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
      subtitle="用 1 枚余烬补 1 天。"
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
          消耗 1 枚余烬补签
        </button>
      }
    >
      <div className="repair">
        <div className="repair__balance">
          <span className="repair__balance-icon" aria-hidden="true">
            <Flame className="icon-24" />
          </span>
          <span>
            现有 <strong>{embers}</strong> 枚余烬
          </span>
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
          <p className="sheet-note">这周没有可补的日子。</p>
        )}

        <p className={`repair__hint ${embers < 1 ? 'repair__hint--warn' : ''}`}>
          {embers < 1 ? '余烬不够。再攒 2,000 XP。' : '补签不加 XP，只把火焰续上。'}
        </p>
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
      title="集成说明"
      subtitle="把活动时间接进来，XP 自动折算。"
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
          <span>
            <strong>拿一枚个人令牌</strong>
            <span>只属于你的接入凭证。</span>
          </span>
        </li>
        <li>
          <span className="step-list__icon" aria-hidden="true">
            <Cable className="icon-20" />
          </span>
          <span>
            <strong>填进活动工具</strong>
            <span>选了哪些天，就同步哪些天。</span>
          </span>
        </li>
        <li>
          <span className="step-list__icon" aria-hidden="true">
            <RefreshCw className="icon-20" />
          </span>
          <span>
            <strong>等榜刷新</strong>
            <span>时间自动折成 XP，不用手填。</span>
          </span>
        </li>
      </ol>
      <p className="sheet-note">只读取活动时间，不改你的原始记录。</p>
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
      subtitle="同一个小组，离你不远。"
      variant="right"
      testId="nearby-sheet"
      footer={
        <button type="button" className="button button--secondary button--full" onClick={closeSheet}>
          关闭
        </button>
      }
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
      <p className="sheet-note">只显示同组的人，不显示精确位置。</p>
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
      footer={
        <button type="button" className="button button--secondary button--full" onClick={closeSheet}>
          关闭
        </button>
      }
    >
      <div className="week-detail">
        <div className={`result-banner result-banner--${week.resultTone}`}>
          <Trophy className="icon-24" aria-hidden="true" />
          <span>{week.result}</span>
        </div>
        <div className="detail-stats">
          <DetailStat label="最终名次" value={`#${week.rank}`} />
          <DetailStat label="周 XP" value={week.xp.toLocaleString('en-US')} />
          <DetailStat label="小组人数" value={`${week.groupSize}`} />
        </div>
        <section className="sheet-section" aria-label="前三名">
          <h3 className="sheet-section__title">前三名</h3>
          <ol className="week-top">
            {week.top.map((row, index) => (
              <li key={`${row.name}-${index}`} className="week-top__row">
                <span className="week-top__rank" aria-hidden="true">
                  {index + 1}
                </span>
                <span className="week-top__name">{row.name}</span>
                <span className="week-top__xp">
                  <Star className="icon-16" aria-hidden="true" />
                  {row.xp.toLocaleString('en-US')}
                </span>
              </li>
            ))}
          </ol>
        </section>
        <p className="sheet-note">那一周的你：第 {week.rank} 名，{week.xp.toLocaleString('en-US')} XP。</p>
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
      title="全部动态"
      subtitle="小组里的新动静。"
      variant="right"
      testId="feed-sheet"
      footer={
        <button type="button" className="button button--secondary button--full" onClick={closeSheet}>
          关闭
        </button>
      }
    >
      <ul className="feed-sheet-list">
        {feed.map((item) => {
          const actor = memberById(item.memberId)
          if (!actor) return null
          return (
            <li key={item.id} className="feed-item feed-item--wide">
              <Avatar initial={actor.initial} tone={actor.tone} size="sm" />
              <div className="feed-item__body">
                <p className="feed-item__text">
                  <strong>{actor.name}</strong> {item.text}
                </p>
                <span className="feed-item__time">
                  {item.time} · {item.reactions} 个回应
                </span>
              </div>
            </li>
          )
        })}
      </ul>
    </Sheet>
  )
}

function LogoutSheet() {
  const { closeSheet, logout } = useApp()
  return (
    <Sheet
      open
      onClose={closeSheet}
      title="退出登录"
      subtitle="本机登录会清除。"
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
      <p className="sheet-copy">下次要重新进入。你的战绩还在，火焰不会灭。</p>
    </Sheet>
  )
}

export function SheetHost() {
  const { sheet, memberById } = useApp()
  if (!sheet) return null

  if (sheet.kind === 'repair') return <RepairSheet />
  if (sheet.kind === 'feed') return <FeedSheet />
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
