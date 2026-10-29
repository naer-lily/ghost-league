import { ArrowDown, Star } from 'lucide-react'
import type { Member } from '../data'
import { Avatar, type FrameKind } from './Avatar'

interface LeagueRowProps {
  member: Member
  rank: number
  demotion?: boolean
  onClick?: () => void
  compact?: boolean
  frame?: FrameKind
}

export function LeagueRow({ member, rank, demotion = false, onClick, compact = false, frame }: LeagueRowProps) {
  const isMe = Boolean(member.isMe)
  const label = `第 ${rank} 名，${isMe ? '你' : member.name}，${member.xp.toLocaleString('en-US')} XP${
    isMe ? '，我的行' : ''
  }`

  const inner = (
    <>
      <span className={`league-row__rank ${isMe ? 'league-row__rank--me' : ''}`} aria-hidden="true">
        {rank}
      </span>
      <Avatar
        initial={member.initial}
        tone={member.tone}
        size="sm"
        frame={frame}
      />
      <span className="league-row__identity">
        <span className="league-row__name">
          <span className="league-row__name-text">{isMe ? '你' : member.name}</span>
          {isMe ? <span className="league-row__me-tag">我</span> : null}
        </span>
        <span className="league-row__meta">
          {isMe ? `连续 ${member.streak} 天` : member.title}
        </span>
      </span>
      <span className="league-row__xp">
        {demotion ? (
          <ArrowDown className="league-row__xp-icon league-row__xp-icon--down icon-16" aria-hidden="true" />
        ) : (
          <Star className="league-row__xp-icon icon-16" aria-hidden="true" />
        )}
        {member.xp.toLocaleString('en-US')}
      </span>
    </>
  )

  const className = [
    'league-row',
    isMe ? 'league-row--me' : '',
    demotion ? 'league-row--demotion' : '',
    compact ? 'league-row--compact' : '',
  ]
    .filter(Boolean)
    .join(' ')

  if (!onClick) {
    return (
      <div className={className} aria-label={label}>
        {inner}
      </div>
    )
  }

  return (
    <button type="button" className={className} onClick={onClick} aria-label={label}>
      {inner}
    </button>
  )
}
