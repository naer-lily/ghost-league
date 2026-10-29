import type { ReactNode } from 'react'
import { ArrowUpRight, type LucideIcon } from 'lucide-react'

interface StatTileProps {
  icon: LucideIcon
  label: string
  value: string
  onClick?: () => void
  ariaLabel?: string
  tip?: ReactNode
  accent?: 'mint' | 'gold' | 'default'
}

export function StatTile({ icon: Icon, label, value, onClick, ariaLabel, tip, accent = 'default' }: StatTileProps) {
  const content = (
    <>
      <span className="stat-tile__top">
        <span className={`stat-tile__icon stat-tile__icon--${accent}`} aria-hidden="true">
          <Icon className="icon-28" />
        </span>
        {onClick ? <ArrowUpRight className="stat-tile__chevron icon-16" aria-hidden="true" /> : null}
      </span>
      <span className="stat-tile__label">{label}</span>
      <span className="stat-tile__value">{value}</span>
      {tip ? <span className="stat-tile__tip">{tip}</span> : null}
    </>
  )

  if (onClick) {
    return (
      <button type="button" className="stat-tile stat-tile--action" onClick={onClick} aria-label={ariaLabel}>
        {content}
      </button>
    )
  }

  return <div className="stat-tile">{content}</div>
}
