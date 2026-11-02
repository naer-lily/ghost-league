import {
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react'
import styles from './PullToRefresh.module.css'

const THRESHOLD = 64
const MAX_PULL = 96

interface PullToRefreshProps {
  onRefresh: () => Promise<unknown> | unknown
  children: ReactNode
  label?: string
}

function isAtTop(): boolean {
  return window.scrollY <= 0
}

/**
 * Touch pull-to-refresh for the two main pages. It only engages when the page
 * is already scrolled to the top, shows an honest progress label, and calls the
 * caller's real refetch. Desktop simply renders its children unchanged.
 */
export function PullToRefresh({
  onRefresh,
  children,
  label = '下拉刷新',
}: PullToRefreshProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const startY = useRef<number | null>(null)
  const pulling = useRef(false)
  const refreshRef = useRef(onRefresh)
  const [pull, setPull] = useState(0)
  const pullRef = useRef(0)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  refreshRef.current = onRefresh

  function updatePull(value: number) {
    pullRef.current = value
    setPull(value)
  }

  const runRefresh = useCallback(async () => {
    if (refreshing) return
    setRefreshing(true)
    setError(null)
    try {
      await refreshRef.current()
    } catch {
      setError('刷新没有完成，请重试。')
    } finally {
      setRefreshing(false)
      updatePull(0)
    }
  }, [refreshing])

  useEffect(() => {
    const node = containerRef.current
    if (!node) return

    function onTouchStart(event: TouchEvent) {
      if (refreshing || !isAtTop() || event.touches.length !== 1) {
        startY.current = null
        pulling.current = false
        return
      }
      startY.current = event.touches[0]!.clientY
      pulling.current = true
    }

    function onTouchMove(event: TouchEvent) {
      if (!pulling.current || startY.current === null) return
      if (!isAtTop()) {
        pulling.current = false
        startY.current = null
        updatePull(0)
        return
      }
      const delta = event.touches[0]!.clientY - startY.current
      if (delta <= 0) {
        updatePull(0)
        return
      }
      if (event.cancelable) event.preventDefault()
      updatePull(Math.min(MAX_PULL, delta * 0.55))
    }

    function onTouchEnd() {
      if (!pulling.current) return
      pulling.current = false
      startY.current = null
      if (pullRef.current >= THRESHOLD) {
        void runRefresh()
      } else {
        updatePull(0)
      }
    }

    node.addEventListener('touchstart', onTouchStart, { passive: true })
    node.addEventListener('touchmove', onTouchMove, { passive: false })
    node.addEventListener('touchend', onTouchEnd)
    node.addEventListener('touchcancel', onTouchEnd)
    return () => {
      node.removeEventListener('touchstart', onTouchStart)
      node.removeEventListener('touchmove', onTouchMove)
      node.removeEventListener('touchend', onTouchEnd)
      node.removeEventListener('touchcancel', onTouchEnd)
    }
  }, [refreshing, runRefresh])

  const ready = pull >= THRESHOLD
  const stateLabel = refreshing
    ? '正在刷新…'
    : ready
      ? '松开刷新'
      : label

  return (
    <div
      ref={containerRef}
      className={styles.wrap}
      data-testid="pull-to-refresh"
      data-refreshing={refreshing ? 'true' : undefined}
    >
      <div
        className={styles.indicator}
        data-ready={ready ? 'true' : undefined}
        data-refreshing={refreshing ? 'true' : undefined}
        style={{
          height: refreshing ? 44 : pull,
          opacity: refreshing || pull > 0 ? 1 : 0,
        }}
        role="status"
        aria-live="polite"
      >
        <span
          className={styles.spinner}
          data-spinning={refreshing ? 'true' : undefined}
          aria-hidden="true"
        />
        <span>{stateLabel}</span>
      </div>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      <div
        className={styles.content}
        style={{
          transform: pull > 0 ? `translateY(${Math.round(pull / 2)}px)` : undefined,
        }}
      >
        {children}
      </div>
    </div>
  )
}
