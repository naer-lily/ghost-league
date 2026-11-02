import { useEffect, useState } from 'react'
import { apiFetchBlob } from '../api/client'
import type { Star } from '../api/types'
import styles from './StarArt.module.css'

interface StarSvgEntry {
  refs: number
  objectUrl: string | null
  settled: boolean
  promise: Promise<string>
}

const cache = new Map<string, StarSvgEntry>()

function acquire(path: string): StarSvgEntry {
  let entry = cache.get(path)
  if (!entry) {
    const created: StarSvgEntry = {
      refs: 0,
      objectUrl: null,
      settled: false,
      promise: Promise.resolve(''),
    }
    created.promise = apiFetchBlob(path).then(
      (blob) => {
        created.settled = true
        created.objectUrl = URL.createObjectURL(blob)
        if (created.refs === 0) {
          URL.revokeObjectURL(created.objectUrl)
          created.objectUrl = null
          cache.delete(path)
        }
        return created.objectUrl ?? ''
      },
      (error: unknown) => {
        created.settled = true
        if (created.refs === 0) cache.delete(path)
        throw error
      },
    )
    cache.set(path, created)
    entry = created
  }
  entry.refs += 1
  return entry
}

function release(path: string): void {
  const entry = cache.get(path)
  if (!entry) return
  entry.refs = Math.max(0, entry.refs - 1)
  if (entry.refs > 0) return
  if (entry.objectUrl) {
    URL.revokeObjectURL(entry.objectUrl)
    entry.objectUrl = null
    cache.delete(path)
  } else if (entry.settled) {
    cache.delete(path)
  }
}

/** Load a private star SVG with the same Bearer token as the API calls. */
export function useStarSvg(path: string) {
  const [src, setSrc] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    setSrc(null)
    setFailed(false)
    const entry = acquire(path)
    entry.promise.then(
      (objectUrl) => {
        if (active && objectUrl) setSrc(objectUrl)
      },
      () => {
        if (active) setFailed(true)
      },
    )
    return () => {
      active = false
      release(path)
    }
  }, [path])

  return { src, failed }
}

interface StarArtProps {
  star: Star
  className?: string | undefined
}

export function StarArt({ star, className }: StarArtProps) {
  const { src, failed } = useStarSvg(star.svg_url)

  return (
    <span
      className={[styles.frame, className].filter(Boolean).join(' ')}
      data-testid="star-art"
      data-state={failed ? 'failed' : src ? 'ready' : 'loading'}
    >
      {src ? (
        <img
          className={styles.image}
          src={src}
          alt=""
          aria-hidden="true"
          draggable={false}
        />
      ) : failed ? (
        <span className={styles.failed} aria-hidden="true" />
      ) : (
        <span className={styles.placeholder} aria-hidden="true" />
      )}
      {failed ? (
        <span className="visually-hidden">星星图像加载失败</span>
      ) : null}
    </span>
  )
}
