import {
  ArrowRight,
  Award,
  Flame,
  Gem,
  Palette,
  Sparkles,
  Star,
  Trophy,
  UserRound,
  Zap,
} from 'lucide-react'
import {
  collectionItems,
  feed,
  group,
  members,
  tips,
  WEEK_XP,
  weeks,
} from '../data'
import { useApp } from '../store'
import { Avatar } from './Avatar'
import { InfoTip } from './InfoTip'

function AsideHead({
  icon: Icon,
  title,
  onOpen,
  label,
  tip,
}: {
  icon: typeof Trophy
  title: string
  onOpen?: () => void
  label?: string
  tip?: { label: string; title: string; body: string }
}) {
  return (
    <div className="aside-head">
      <span className="aside-head__icon" aria-hidden="true">
        <Icon className="icon-18" />
      </span>
      <h2 className="aside-head__title">{title}</h2>
      {tip ? <InfoTip {...tip} /> : null}
      {onOpen ? (
        <button type="button" className="aside-head__link" aria-label={label ?? title} onClick={onOpen}>
          <ArrowRight className="icon-18" aria-hidden="true" />
        </button>
      ) : null}
    </div>
  )
}

function HomeAside() {
  const { navigate, openSheet } = useApp()
  const rank = members.findIndex((member) => member.isMe) + 1
  return (
    <>
      <section className="aside-card" aria-label="小组">
        <AsideHead icon={Trophy} title="小组" onOpen={() => navigate('league')} label="查看小组榜" />
        <ul className="aside-rows">
          {members.slice(0, 3).map((member, index) => (
            <li key={member.id} className="aside-row">
              <span className="aside-row__rank">{index + 1}</span>
              <Avatar initial={member.initial} tone={member.tone} size="sm" />
              <span className="aside-row__name">{member.name}</span>
              <span className="aside-row__xp">{member.xp.toLocaleString('en-US')}</span>
            </li>
          ))}
        </ul>
        <div className="aside-me">
          <span className="aside-me__rank">#{rank}</span>
          <span className="aside-me__name">你</span>
          <span className="aside-me__xp">{WEEK_XP.toLocaleString('en-US')}</span>
        </div>
      </section>

      <section className="aside-card" aria-label="动态">
        <AsideHead icon={Sparkles} title="动态" onOpen={() => openSheet({ kind: 'feed' })} label="查看全部动态" />
        <ul className="aside-feed">
          {feed.slice(0, 2).map((item) => {
            const actor = members.find((member) => member.id === item.memberId)
            if (!actor) return null
            return (
              <li key={item.id} className="aside-feed__row">
                <Avatar initial={actor.initial} tone={actor.tone} size="sm" />
                <span className="aside-feed__text">
                  <strong>{actor.name}</strong> {item.text}
                </span>
              </li>
            )
          })}
        </ul>
      </section>
    </>
  )
}

function LeagueAside() {
  const rank = members.findIndex((member) => member.isMe) + 1
  const above = members[group.promotion - 1]
  const gap = Math.max(0, above.xp - WEEK_XP + 1)
  return (
    <>
      <section className="aside-card aside-card--you" aria-label="你的位置">
        <AsideHead icon={UserRound} title="你" />
        <span className="aside-rank">#{rank}</span>
        <span className="aside-xp">{WEEK_XP.toLocaleString('en-US')} XP</span>
        <div className="aside-gap">
          <Flame className="icon-16" aria-hidden="true" />
          <span>{gap.toLocaleString('en-US')}</span>
        </div>
      </section>
      <section className="aside-card" aria-label="段位">
        <AsideHead icon={Trophy} title={group.tier} />
        <div className="aside-tier">
          <img src={group.tierAsset} alt="" width={44} height={44} />
          <span className="aside-tier__group">{group.name}</span>
          <span className="aside-tier__size">{group.size}</span>
        </div>
      </section>
    </>
  )
}

function EmbersAside() {
  const pct = Math.min(100, Math.round((WEEK_XP % 2000) / 20))
  return (
    <section className="aside-card" aria-label="下一枚余烬">
      <AsideHead icon={Gem} title="下一枚" tip={tips.embers} />
      <div className="aside-progress-row">
        <span>{WEEK_XP.toLocaleString('en-US')}</span>
        <span className="aside-progress-row__muted">2,000</span>
      </div>
      <div className="meter" aria-hidden="true">
        <span className="meter__fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="aside-foot-icon" aria-hidden="true">
        <Zap className="icon-16" />
        <span>{Math.max(0, 2000 - (WEEK_XP % 2000)).toLocaleString('en-US')}</span>
      </div>
    </section>
  )
}

function HistoryAside() {
  const best = Math.min(...weeks.map((week) => week.rank))
  const total = weeks.reduce((sum, week) => sum + week.xp, 0)
  return (
    <section className="aside-card" aria-label="历史概览">
      <AsideHead icon={Award} title="最佳" />
      <div className="aside-stats">
        <div>
          <span className="aside-stat__value">#{best}</span>
          <span className="aside-stat__label">名次</span>
        </div>
        <div>
          <span className="aside-stat__value">{total.toLocaleString('en-US')}</span>
          <span className="aside-stat__label">XP</span>
        </div>
      </div>
    </section>
  )
}

function MeAside() {
  const counts = {
    frame: collectionItems.filter((item) => item.kind === 'frame' && item.owned).length,
    badge: collectionItems.filter((item) => item.kind === 'badge' && item.owned).length,
    background: collectionItems.filter((item) => item.kind === 'background' && item.owned).length,
  }
  return (
    <section className="aside-card" aria-label="收藏概览">
      <AsideHead icon={Star} title="收藏" />
      <div className="aside-collection">
        <span>
          <UserRound className="icon-18" aria-hidden="true" />
          {counts.frame}
        </span>
        <span>
          <Award className="icon-18" aria-hidden="true" />
          {counts.badge}
        </span>
        <span>
          <Palette className="icon-18" aria-hidden="true" />
          {counts.background}
        </span>
      </div>
    </section>
  )
}

export function PageAside() {
  const { page } = useApp()
  return (
    <aside className="page-aside" aria-label="侧栏">
      {page === 'home' ? <HomeAside /> : null}
      {page === 'league' ? <LeagueAside /> : null}
      {page === 'embers' ? <EmbersAside /> : null}
      {page === 'history' ? <HistoryAside /> : null}
      {page === 'me' ? <MeAside /> : null}
    </aside>
  )
}
