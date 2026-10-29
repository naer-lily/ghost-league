import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, CalendarClock, Star, Timer } from 'lucide-react'
import { friends, group, members, tips } from '../data'
import { useApp } from '../store'
import { Avatar } from '../components/Avatar'
import { InfoTip } from '../components/InfoTip'
import { LeagueRow } from '../components/LeagueRow'
import { Segmented } from '../components/Segmented'

type LeagueTab = 'group' | 'friends'

function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const clock = [hours, minutes, seconds].map((value) => String(value).padStart(2, '0')).join(':')
  return days > 0 ? `${days} 天 ${clock}` : clock
}

function ZoneDivider({ tone, label }: { tone: 'promotion' | 'demotion'; label: string }) {
  return (
    <div className={`zone-divider zone-divider--${tone}`} role="separator" aria-label={label}>
      <span className="zone-divider__line" aria-hidden="true" />
      <span className="zone-divider__pill">
        {tone === 'promotion' ? (
          <ArrowUp className="icon-16" aria-hidden="true" />
        ) : (
          <ArrowDown className="icon-16" aria-hidden="true" />
        )}
        {label}
      </span>
      <span className="zone-divider__line" aria-hidden="true" />
    </div>
  )
}

function Podium() {
  const { openSheet } = useApp()
  const top = members.slice(0, 3)
  const order = [top[1], top[0], top[2]]
  const rankOf = (id: string) => members.findIndex((member) => member.id === id) + 1
  const stars = [2, 3, 1]

  return (
    <div className="podium" aria-label="前三名">
      {order.map((member, index) => {
        const rank = rankOf(member.id)
        return (
          <button
            key={member.id}
            type="button"
            className={`podium__card podium__card--rank-${rank}`}
            aria-label={`第 ${rank} 名，${member.name}，${member.xp.toLocaleString('en-US')} XP`}
            onClick={() => openSheet({ kind: 'user', memberId: member.id, rank })}
          >
            <span className="podium__rank" aria-hidden="true">
              {rank}
            </span>
            <Avatar
              initial={member.initial}
              tone={member.tone}
              size={rank === 1 ? 'lg' : 'md'}
              frame={rank === 1 ? 'crown' : rank === 2 ? 'bronze' : 'mint'}
            />
            <span className="podium__name">{member.name}</span>
            <span className="podium__xp">
              <Star className="icon-16" aria-hidden="true" />
              {member.xp.toLocaleString('en-US')}
            </span>
            <span className="podium__stars" aria-hidden="true">
              {Array.from({ length: stars[index] }).map((_, starIndex) => (
                <Star key={starIndex} className="icon-12" />
              ))}
            </span>
          </button>
        )
      })}
    </div>
  )
}

export function LeaguePage() {
  const { openSheet, follows } = useApp()
  const [tab, setTab] = useState<LeagueTab>('group')
  const [deadline] = useState(() => Date.now() + (2 * 86400 + 14 * 3600 + 32 * 60 + 17) * 1000)
  const [remaining, setRemaining] = useState(() => deadline - Date.now())

  useEffect(() => {
    const id = window.setInterval(() => setRemaining(deadline - Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [deadline])

  const groupRows = members.slice(3, 11)
  const demotionRows = members.slice(11)
  const countdown = formatCountdown(remaining)

  return (
    <div className="league-page" data-testid="league-page">
      <div className="league-controls">
        <Segmented
          value={tab}
          label="榜单范围"
          options={[
            { id: 'group', label: '我的小组' },
            { id: 'friends', label: '好友榜' },
          ]}
          onChange={setTab}
        />
        <span className="chip chip--gold">
          <CalendarClock className="icon-16" aria-hidden="true" />
          {group.settleLabel}
        </span>
      </div>

      <div className="league-layout">
        <aside className="league-aside">
          <section className="card league-hero" aria-labelledby="league-hero-title">
            <div className="league-hero__tier">
              <img src={group.tierAsset} alt="" width={64} height={64} />
              <div>
                <p className="eyebrow">本周段位</p>
                <h2 className="league-hero__name" id="league-hero-title">
                  {group.tier}
                </h2>
                <p className="league-hero__meta">
                  {group.tierEn} · {group.name} · {group.size} 人
                </p>
              </div>
            </div>

            <div className="countdown">
              <span className="countdown__label">
                <Timer className="icon-16" aria-hidden="true" />
                距结算
              </span>
              <span className="countdown__value" data-testid="countdown">
                {countdown}
              </span>
              <InfoTip {...tips.league} />
            </div>

            <ul className="zone-legend" aria-label="区段说明">
              <li>
                <span className="zone-legend__dot zone-legend__dot--up" aria-hidden="true" />
                前 {group.promotion} 名晋级
              </li>
              <li>
                <span className="zone-legend__dot zone-legend__dot--down" aria-hidden="true" />
                后 {group.demotion} 名可能降级
              </li>
            </ul>
          </section>
        </aside>

        <div className="league-main">
          {tab === 'group' ? (
            <section className="card league-board" aria-label="我的小组榜单" data-testid="group-board">
              <div className="league-board__head">
                <div>
                  <p className="eyebrow">我的小组</p>
                  <h2 className="card-title">{group.tier} · {group.name}</h2>
                </div>
                <span className="caption">第 4 名是你 · 共 {group.size} 人</span>
              </div>

              <Podium />
              <ZoneDivider tone="promotion" label={`前 ${group.promotion} 晋级`} />

              <ol className="league-list">
                {groupRows.map((member, index) => {
                  const rank = index + 4
                  return (
                    <li key={member.id}>
                      <LeagueRow
                        member={member}
                        rank={rank}
                        frame={member.isMe ? 'ember' : undefined}
                        onClick={() => openSheet({ kind: 'user', memberId: member.id, rank })}
                      />
                    </li>
                  )
                })}
              </ol>

              <ZoneDivider tone="demotion" label={`后 ${group.demotion} 可能降级`} />

              <ol className="league-list" aria-label="降级区">
                {demotionRows.map((member, index) => {
                  const rank = index + group.size - group.demotion + 1
                  return (
                    <li key={member.id}>
                      <LeagueRow
                        member={member}
                        rank={rank}
                        demotion
                        onClick={() => openSheet({ kind: 'user', memberId: member.id, rank })}
                      />
                    </li>
                  )
                })}
              </ol>
            </section>
          ) : (
            <section className="card league-board" aria-label="好友榜" data-testid="friends-board">
              <div className="league-board__head">
                <div>
                  <p className="eyebrow">好友榜</p>
                  <h2 className="card-title">你关注的人</h2>
                </div>
                <span className="caption">{friends.length} 位 · 本周</span>
              </div>
              <p className="league-board__note">
                已关注 {follows.length} 位。好友的成绩不影响小组升降。
              </p>
              <ol className="league-list league-list--friends">
                {friends.map((member, index) => {
                  const rank = index + 1
                  return (
                    <li key={member.id}>
                      <LeagueRow
                        member={member}
                        rank={rank}
                        frame={member.isMe ? 'ember' : undefined}
                        onClick={() => openSheet({ kind: 'user', memberId: member.id, rank })}
                      />
                    </li>
                  )
                })}
              </ol>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
