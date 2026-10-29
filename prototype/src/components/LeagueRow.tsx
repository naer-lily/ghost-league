import { ArrowDown } from 'lucide-react'
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
  const label = `第 ${rank} 名，${isMe ? '你' : member.name}，${member.xp.toLocaleString('en-US')} XP`

  const inner = (
    <>
      <span className="league-row__rank" aria-hidden="true">
        {rank}
      </span>
      <Avatar initial={member.initial} tone={member.tone} size={compact ? 'sm' : 'md'} frame={frame} />
      <span className="league-row__name">{isMe ? '你' : member.name}</span>
      <span className="league-row__xp">
        {demotion ? <ArrowDown className="league-row__arrow" aria-hidden="true" /> : null}
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
    <button
      type="button"
      className={className}
      onClick={onClick}
      aria-label={label}
      data-testid="league-row"
      data-me={isMe ? 'true' : undefined}
    >
      {inner}
    </button>
  )
}
