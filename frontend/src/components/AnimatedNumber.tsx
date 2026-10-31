import { animate, useReducedMotion } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'
import { formatNumber } from '../lib/home'

interface AnimatedNumberProps {
  value: number
  className?: string | undefined
  format?: ((value: number) => string) | undefined
  duration?: number | undefined
}

/**
 * Counts to the latest server value with a spring-ish ease. Reduced-motion
 * users get the final value immediately.
 */
export function AnimatedNumber({
  value,
  className,
  format = formatNumber,
  duration = 0.55,
}: AnimatedNumberProps) {
  const reducedMotion = useReducedMotion()
  const [display, setDisplay] = useState(value)
  const previous = useRef(value)

  useEffect(() => {
    if (reducedMotion || previous.current === value) {
      previous.current = value
      setDisplay(value)
      return
    }
    const controls = animate(previous.current, value, {
      duration,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (latest) => setDisplay(Math.round(latest)),
    })
    previous.current = value
    return () => controls.stop()
  }, [duration, reducedMotion, value])

  return <span className={className}>{format(display)}</span>
}
