import { useEffect, useMemo, useState } from 'react'

/** Map the browser clock onto the API's `server_now` and tick once a second. */
export function useServerNow(serverNow: string | undefined, active: boolean): Date {
  const [tick, setTick] = useState(() => Date.now())

  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setTick(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])

  return useMemo(() => {
    if (!serverNow) return new Date(tick)
    const server = new Date(serverNow).getTime()
    if (Number.isNaN(server)) return new Date(tick)
    return new Date(tick + (server - Date.now()))
  }, [tick, serverNow])
}
