import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, Timer } from 'lucide-react'
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
  return days > 0 ? `${days}天 ${clock}` : clock
}

function ZoneBar({ tone }: { tone: 'promotion' | 'demotion' }) {
  const isUp = tone === 'promotion'
  return (
    <div
      className={`zone-bar zone-bar--${tone}`}
      role="separator"
      aria-label={isUp ? '前 3 名晋级区' : '后 3 名降级区'}
    >
      <span className="zone-bar__line" aria-hidden="true" />
      <span className="zone-bar__badge" aria-hidden="true">
        {isUp ? <ArrowUp className="icon-16" /> : <ArrowDown className="icon-16" />}
        <span>3</span>
      </span>
      <span className="zone-bar__line" aria-hidden="true" />
    </div>
  )
}

function Podium() {
  const { openSheet } = useApp()
  const top = members.slice(0, 3)
  const order = [top[1], top[0], top[2]]
  const rankOf = (id: string) => members.findIndex((member) => member.id === id) + 1

  return (
    <div className="podium" aria-label="前三名" data-testid="podium">
      {order.map((member) => {
        const rank = rankOf(member.id)
        return (
          <button
            key={member.id}
            type="button"
            className={`podium-card podium-card--rank-${rank}`}
            aria-label={`第 ${rank} 名，${member.name}，${member.xp.toLocaleString('en-US')} XP`}
            data-testid="podium-card"
            onClick={() => openSheet({ kind: 'user', memberId: member.id, rank })}
          >
            <span className="podium-card__medal" aria-hidden="true">
              {rank}
            </span>
            <Avatar
              initial={member.initial}
              tone={member.tone}
              size={rank === 1 ? 'xl' : 'lg'}
              frame={rank === 1 ? 'crown' : rank === 2 ? 'bronze' : 'mint'}
            />
            <span className="podium-card__name">{member.name}</span>
            <span className="podium-card__xp">{member.xp.toLocaleString('en-US')}</span>
          </button>
        )
      })}
    </div>
  )
}

export function LeaguePage() {
  const { openSheet } = useApp()
  const [tab, setTab] = useState<LeagueTab>('group')
  const [deadline] = useState(() => Date.now() + (2 * 86400 + 14 * 3600 + 32 * 60 + 17) * 1000)
  const [remaining, setRemaining] = useState(() => deadline - Date.now())

  useEffect(() => {
    const id = window.setInterval(() => setRemaining(deadline - Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [deadline])

  const countdown = formatCountdown(remaining)
  const promotionRows = members.slice(3, 12)
  const demotionRows = members.slice(12)

  return (
    <div className="league-page" data-testid="league-page">
      <section className="league-hero" aria-labelledby="league-hero-title">
        <div className="league-hero__identity">
          <img className="league-hero__tier" src={group.tierAsset} alt="" width={56} height={56} />
          <div className="league-hero__text">
            <h2 className="league-hero__title" id="league-hero-title">
              {group.tier}联赛
            </h2>
            <span className="league-hero__group">{group.name}</span>
          </div>
        </div>
        <div className="league-hero__right">
          <span className="countdown-pill" data-testid="countdown">
            <Timer className="icon-16" aria-hidden="true" />
            {countdown}
          </span>
          <InfoTip {...tips.league} side="bottom" />
        </div>
      </section>

      <div className="league-tabs">
        <Segmented
          value={tab}
          label="榜单范围"
          options={[
            { id: 'group', label: '小组' },
            { id: 'friends', label: '好友' },
          ]}
          onChange={setTab}
        />
      </div>

      {tab === 'group' ? (
        <section className="card league-board" aria-label="我的小组榜单" data-testid="group-board">
          <div className="league-board__head">
            <span className="league-board__title">{group.name}</span>
            <span className="league-board__count">{group.size} 人</span>
          </div>

          <Podium />
          <ZoneBar tone="promotion" />

          <ol className="league-list">
            {promotionRows.map((member, index) => {
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

          <ZoneBar tone="demotion" />

          <ol className="league-list league-list--demotion" aria-label="降级区">
            {demotionRows.map((member, index) => {
              const rank = index + 13
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
            <span className="league-board__title">好友</span>
            <span className="league-board__count">{friends.length}</span>
          </div>
          <ol className="league-list">
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
  )
}
