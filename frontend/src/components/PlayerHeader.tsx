import { Diamond } from 'lucide-react'
import type { CSSProperties } from 'react'
import type { HomeView } from '../lib/home'
import { formatNumber, tierStyleVars } from '../lib/home'
import { Avatar } from './Avatar'
import { StreakBadge } from './StreakBadge'
import { TierIcon } from './TierIcon'
import styles from './PlayerHeader.module.css'

interface PlayerHeaderProps {
  view: HomeView
  className?: string
  /** Optional wallet chip; the Me page uses it so diamonds stay at the top. */
  diamonds?: number | undefined
}

/**
 * One horizontal identity row: avatar, name, tier and streak. It deliberately
 * has no surface, border or radius of its own so it can sit on the page.
 */
export function PlayerHeader({
  view,
  className,
  diamonds,
}: PlayerHeaderProps) {
  const style = tierStyleVars(view.tier) as CSSProperties

  return (
    <header
      className={[styles.header, className].filter(Boolean).join(' ')}
      style={style}
      data-testid="player-header"
      data-flat="true"
    >
      <span className={styles.avatar} data-testid="player-avatar">
        <Avatar
          src={view.avatarUrl}
          name={view.displayName}
          size={64}
          loading="eager"
        />
      </span>

      <h1 className={styles.name} data-testid="player-name">
        {view.displayName}
      </h1>

      <span className={styles.tier} data-testid="player-tier">
        <TierIcon
          tier={view.tier.key}
          theme={view.iconTheme}
          size={20}
          decorative
        />
        <span className={styles.tierName}>{view.tier.label}</span>
      </span>

      {diamonds === undefined ? null : (
        <span
          className={styles.diamonds}
          data-testid="player-diamonds"
          aria-label={`钻石 ${diamonds}`}
        >
          <Diamond size={15} aria-hidden="true" />
          <span>{formatNumber(diamonds)}</span>
        </span>
      )}

      <StreakBadge
        className={styles.streak}
        value={view.streak}
        checkedIn={view.checkedIn}
        size="lg"
      />
    </header>
  )
}
