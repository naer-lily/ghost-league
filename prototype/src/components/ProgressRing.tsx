import { useEffect, useState } from 'react'
import { Flame } from 'lucide-react'
import { useCountUp } from '../hooks/useCountUp'

interface ProgressRingProps {
  xp: number
  goal: number
  lit: boolean
  loading?: boolean
}

const RADIUS = 100
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

export function ProgressRing({ xp, goal, lit, loading = false }: ProgressRingProps) {
  const pct = Math.min(1, Math.max(0, xp / goal))
  const display = useCountUp(xp)
  const [shown, setShown] = useState(false)

  useEffect(() => {
    const frame = requestAnimationFrame(() => setShown(true))
    return () => cancelAnimationFrame(frame)
  }, [])

  const status = lit ? '已点火。' : `再 ${goal - xp} XP，点火。`

  return (
    <div
      className={`xp-ring ${lit ? 'xp-ring--lit' : ''} ${loading ? 'is-loading' : ''}`.trim()}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={goal}
      aria-valuenow={Math.min(xp, goal)}
      aria-valuetext={`今日 ${xp} XP，目标 ${goal} XP`}
      aria-busy={loading || undefined}
    >
      <svg className="xp-ring__svg" viewBox="0 0 240 240" aria-hidden="true">
        <circle className="xp-ring__track" cx="120" cy="120" r={RADIUS} />
        <circle
          className="xp-ring__progress"
          cx="120"
          cy="120"
          r={RADIUS}
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={CIRCUMFERENCE * (1 - (shown ? pct : 0))}
        />
      </svg>
      <div className="xp-ring__center">
        <Flame className="xp-ring__flame" aria-hidden="true" />
        <span className="xp-ring__score">
          {loading ? '—' : display}
          <span className="xp-ring__unit">XP</span>
        </span>
        <span className="xp-ring__status" data-testid="ring-status">
          {loading ? '读取中…' : status}
        </span>
      </div>
    </div>
  )
}
