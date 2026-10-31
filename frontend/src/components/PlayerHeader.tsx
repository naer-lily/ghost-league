import type { CSSProperties } from 'react'
import type { HomeView } from '../lib/home'
import { tierStyleVars } from '../lib/home'
import { Avatar } from './Avatar'
import { StreakBadge } from './StreakBadge'
import { TierIcon } from './TierIcon'
import styles from './PlayerHeader.module.css'

interface PlayerHeaderProps {
  view: HomeView
  className?: string
}

/**
 * One horizontal identity row: avatar, name, tier and streak. It deliberately
 * has no surface, border or radius of its own so it can sit on the page.
 */
export function PlayerHeader({ view, className }: PlayerHeaderProps) {
  const style = tierStyleVars(view.tier) as CSSProperties
  const groupNo = view.group ? `G${String(view.group.no).padStart(2, '0')}` : null

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
        <span className={styles.group}>{groupNo ?? '待分入'}</span>
      </span>

      <StreakBadge
        className={styles.streak}
        value={view.streak}
        checkedIn={view.checkedIn}
        size="lg"
      />
    </header>
  )
}
