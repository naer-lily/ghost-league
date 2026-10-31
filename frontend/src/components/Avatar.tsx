import { useEffect, useState, type CSSProperties } from 'react'
import { resolveApiUrl } from '../api/client'
import styles from './Avatar.module.css'

interface AvatarProps {
  src: string | null
  name: string
  size?: number
  className?: string
  loading?: 'eager' | 'lazy'
}

function initialOf(name: string): string {
  const trimmed = name.trim()
  if (!trimmed) return '?'
  return Array.from(trimmed)[0] ?? '?'
}

export function Avatar({
  src,
  name,
  size = 44,
  className,
  loading = 'lazy',
}: AvatarProps) {
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setFailed(false)
  }, [src])

  const style = {
    '--avatar-size': `${size}px`,
    '--avatar-font-size': `${Math.max(12, Math.round(size * 0.38))}px`,
  } as CSSProperties

  return (
    <span
      className={[styles.avatar, className].filter(Boolean).join(' ')}
      style={style}
    >
      <span className={styles.fallback} aria-hidden="true">
        {initialOf(name)}
      </span>
      {src && !failed ? (
        <img
          src={resolveApiUrl(src)}
          alt=""
          loading={loading}
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : null}
    </span>
  )
}
