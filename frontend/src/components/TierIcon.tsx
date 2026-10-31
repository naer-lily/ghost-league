import { useEffect, useState, type CSSProperties } from 'react'
import { tierMeta } from '../lib/home'
import {
  alternateTheme,
  iconTheme,
  tierIconSrc,
  tierKey,
  type IconTheme,
} from '../lib/tiers'
import styles from './TierIcon.module.css'

export interface TierIconProps {
  tier: string | null | undefined
  theme: string | null | undefined
  size?: number
  className?: string | undefined
  /** Decorative icons inside labelled headings should not add alt text. */
  decorative?: boolean
}

export function TierIcon({
  tier,
  theme,
  size = 56,
  className,
  decorative = false,
}: TierIconProps) {
  const key = tierKey(tier)
  const primary = iconTheme(theme)
  const [activeTheme, setActiveTheme] = useState<IconTheme>(primary)
  const [failedTheme, setFailedTheme] = useState<IconTheme | null>(null)
  const [exhausted, setExhausted] = useState(false)

  useEffect(() => {
    setActiveTheme(primary)
    setFailedTheme(null)
    setExhausted(false)
  }, [primary, key])

  const label = `${tierMeta(key).label}段位`

  function handleError() {
    if (activeTheme === primary) {
      const fallback = alternateTheme(primary)
      setFailedTheme(primary)
      setActiveTheme(fallback)
      return
    }
    setExhausted(true)
  }

  const style = {
    '--tier-icon-size': `${size}px`,
  } as CSSProperties

  return (
    <span
      className={[styles.tile, className].filter(Boolean).join(' ')}
      style={style}
      data-testid="tier-icon"
      data-tier={key}
      data-theme={activeTheme}
      data-fallback={failedTheme ? 'true' : 'false'}
      data-failed={exhausted ? 'true' : 'false'}
    >
      <img
        className={styles.image}
        src={tierIconSrc(key, activeTheme)}
        alt={decorative ? '' : label}
        width={size}
        height={size}
        loading="eager"
        decoding="async"
        draggable={false}
        onError={handleError}
      />
    </span>
  )
}
