import { useState } from 'react'
import {
  ArrowRight,
  CalendarPlus,
  Flame,
  Share2,
  Sparkles,
  Star,
  Users,
  Zap,
} from 'lucide-react'
import { feed, GOAL_XP, group, members, me, tips, TODAY_XP, WEEK_XP } from '../data'
import { useApp } from '../store'
import { Avatar } from '../components/Avatar'
import { InfoTip } from '../components/InfoTip'
import { LeagueRow } from '../components/LeagueRow'
import { ProgressRing } from '../components/ProgressRing'
import { StatTile } from '../components/StatTile'

export function HomePage() {
  const {
    embers,
    navigate,
    openSheet,
    share,
    notify,
    profileName,
    avatarSrc,
    memberById,
  } = useApp()
  const [reactions, setReactions] = useState<Record<string, number>>({})
  const [reacted, setReacted] = useState<string[]>([])
  const rank = members.findIndex((member) => member.isMe) + 1
  const remaining = Math.max(0, GOAL_XP - TODAY_XP)

  const react = (eventId: string, actor: string) => {
    if (reacted.includes(eventId)) return
    setReacted((list) => [...list, eventId])
    setReactions((map) => ({ ...map, [eventId]: (map[eventId] ?? 0) + 1 }))
    notify(`回应已送出 · ${actor}`)
  }

  const renderStats = (className: string) => (
    <div className={`stat-grid ${className}`}>
      <StatTile
        icon={Users}
        label="小组"
        value={`${rank}/${group.size}`}
        ariaLabel="查看小组榜"
        onClick={() => navigate('league')}
      />
      <StatTile
        icon={Flame}
        label="余烬"
        value={`${embers}`}
        accent="gold"
        ariaLabel="查看余烬"
        onClick={() => navigate('embers')}
      />
      <StatTile
        icon={Zap}
        label="本周 XP"
        value={String(WEEK_XP)}
        accent="mint"
        tip={<InfoTip {...tips.weekCalc} />}
      />
    </div>
  )

  return (
    <div className="home-grid" data-testid="home-page">
      <div className="home-col home-col--left">
        <section className="card identity-card" aria-label="你的身份">
          <Avatar initial="你" tone="mint" size="xl" frame="ember" image={avatarSrc} name={profileName} />
          <div className="identity-card__text">
            <h2 className="identity-card__name">{profileName}</h2>
            <p className="identity-card__meta">本周第 {rank} · 连续 {me.streak} 天</p>
          </div>
          <div className="identity-card__tier">
            <img src={group.tierAsset} alt="" width={48} height={48} />
            <span>
              <strong>{group.tier}</strong>
              <span>{group.name}</span>
            </span>
          </div>
        </section>

        {renderStats('stat-grid--desktop')}

        <section className="card recap-card" aria-label="本周回顾">
          <h2 className="card-title">本周回顾</h2>
          <dl className="recap-list">
            <div>
              <dt>已获</dt>
              <dd>{WEEK_XP} XP</dd>
            </div>
            <div>
              <dt>今日目标</dt>
              <dd>{GOAL_XP} XP</dd>
            </div>
            <div>
              <dt>还差</dt>
              <dd className="recap-list__warn">{remaining > 0 ? `${remaining} XP` : '已点火'}</dd>
            </div>
          </dl>
          <p className="recap-card__note">{remaining > 0 ? `再 ${remaining} XP，火焰亮到今天。` : '今天已经点火，火焰亮着。'}</p>
        </section>
      </div>

      <div className="home-col home-col--center">
        <section className="card home-hero" aria-labelledby="home-progress-heading">
          <div className="home-hero__head">
            <div>
              <p className="eyebrow">今日进度</p>
              <h2 className="card-title" id="home-progress-heading">
                {remaining > 0 ? '再点一把火' : '火已经亮了'}
              </h2>
            </div>
            <span className="streak-wrap">
              <span className="streak-chip" aria-label={`连续 ${me.streak} 天`}>
                <Flame className="icon-20" aria-hidden="true" />
                <span className="streak-chip__value">{me.streak}</span>
                <span className="streak-chip__unit">天</span>
              </span>
              <InfoTip {...tips.streak} />
            </span>
          </div>

          <ProgressRing xp={TODAY_XP} goal={GOAL_XP} lit={TODAY_XP >= GOAL_XP} />

          <div className="checkin-state" data-testid="checkin-state">
            <span className="checkin-state__icon" aria-hidden="true">
              <Flame className="icon-20" />
            </span>
            <span className="checkin-state__text">
              <span className="checkin-state__label">今日打卡</span>
              <strong className="checkin-state__value">{TODAY_XP >= GOAL_XP ? '已点火' : '还没点火'}</strong>
            </span>
            <span className="checkin-state__auto">满 {GOAL_XP} XP 自动点火</span>
          </div>

          <div className="home-actions">
            <button
              type="button"
              className="button button--primary home-actions__share"
              onClick={share}
              data-testid="share-button"
            >
              <Share2 className="icon-20" aria-hidden="true" />
              分享战绩
            </button>
            <button
              type="button"
              className="button button--secondary"
              onClick={() => openSheet({ kind: 'repair' })}
              data-testid="repair-button"
            >
              <CalendarPlus className="icon-20" aria-hidden="true" />
              补签
            </button>
          </div>

          <div className="home-links">
            <button type="button" className="text-link" onClick={() => navigate('league')}>
              查看完整榜
              <ArrowRight className="icon-16" aria-hidden="true" />
            </button>
            <button type="button" className="text-link" onClick={() => openSheet({ kind: 'feed' })}>
              查看全部动态
              <ArrowRight className="icon-16" aria-hidden="true" />
            </button>
            <button type="button" className="text-link" onClick={() => navigate('embers')}>
              查看余烬
              <ArrowRight className="icon-16" aria-hidden="true" />
            </button>
          </div>
        </section>
        {renderStats('stat-grid--mobile')}
      </div>

      <div className="home-col home-col--right">
        <section className="card group-card" aria-labelledby="group-position-heading">
          <div className="card-head">
            <div>
              <p className="eyebrow">组内位置</p>
              <h2 className="card-title" id="group-position-heading">
                第 {rank} 名
              </h2>
            </div>
            <span className="chip chip--mint">
              <Star className="icon-16" aria-hidden="true" />
              前 {group.promotion} 晋级
            </span>
          </div>
          <ol className="mini-standings">
            {members.slice(0, 5).map((member, index) => (
              <li key={member.id}>
                <LeagueRow
                  member={member}
                  rank={index + 1}
                  compact
                  frame={member.isMe ? 'ember' : undefined}
                  onClick={() => openSheet({ kind: 'user', memberId: member.id })}
                />
              </li>
            ))}
          </ol>
          <div className="card-foot">
            <span className="card-foot__hint">后 {group.demotion} 名可能降级</span>
            <button type="button" className="text-link" onClick={() => navigate('league')}>
              查看完整榜
              <ArrowRight className="icon-16" aria-hidden="true" />
            </button>
          </div>
        </section>

        <section className="card feed-card" aria-labelledby="feed-heading">
          <div className="card-head">
            <div>
              <p className="eyebrow">最近动态</p>
              <h2 className="card-title" id="feed-heading">
                组里很热闹
              </h2>
            </div>
            <button type="button" className="text-link" onClick={() => openSheet({ kind: 'feed' })}>
              查看全部
              <ArrowRight className="icon-16" aria-hidden="true" />
            </button>
          </div>
          <ul className="feed-list">
            {feed.slice(0, 3).map((item) => {
              const actor = memberById(item.memberId)
              if (!actor) return null
              const count = item.reactions + (reactions[item.id] ?? 0)
              const pressed = reacted.includes(item.id)
              return (
                <li key={item.id} className="feed-item">
                  <Avatar initial={actor.initial} tone={actor.tone} size="sm" />
                  <div className="feed-item__body">
                    <p className="feed-item__text">
                      <strong>{actor.name}</strong> {item.text}
                    </p>
                    <span className="feed-item__time">{item.time}</span>
                  </div>
                  <button
                    type="button"
                    className={`reaction-button ${pressed ? 'is-pressed' : ''}`}
                    aria-label={`回应 ${actor.name} 的动态`}
                    aria-pressed={pressed}
                    onClick={() => react(item.id, actor.name)}
                  >
                    <Sparkles className="icon-16" aria-hidden="true" />
                    <span>{count}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </section>
      </div>
    </div>
  )
}
