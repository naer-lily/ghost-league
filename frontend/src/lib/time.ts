const GAME_TIME_ZONE = 'Asia/Shanghai'
const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

function parseDate(value: string): Date | null {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function gameDayNumber(value: Date): number {
  const formatted = new Intl.DateTimeFormat('en-CA', {
    timeZone: GAME_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(value)
  const [year, month, day] = formatted.split('-').map(Number)
  return Math.floor(Date.UTC(year ?? 1970, (month ?? 1) - 1, day ?? 1) / DAY)
}

function zonedParts(value: Date): Record<string, string> {
  const formatter = new Intl.DateTimeFormat('zh-CN', {
    timeZone: GAME_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  })
  return Object.fromEntries(
    formatter
      .formatToParts(value)
      .filter((part) => part.type !== 'literal')
      .map((part) => [part.type, part.value]),
  )
}

export function formatDateOnly(value: string): string {
  const parsed = parseDate(value)
  if (!parsed) return '时间未知'
  const parts = zonedParts(parsed)
  return `${parts.year}-${parts.month}-${parts.day}`
}

export function formatAbsoluteTime(value: string): string {
  const parsed = parseDate(value)
  if (!parsed) return '时间未知'
  const parts = zonedParts(parsed)
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`
}

/** Task deadlines are stored on the hour and shown as ``MM/DD HH:00``. */
export function formatTaskDeadline(value: string): string {
  const parsed = parseDate(value)
  if (!parsed) return '时间未知'
  const parts = zonedParts(parsed)
  return `${parts.month}/${parts.day} ${parts.hour}:00`
}

/**
 * Relative label for history and feed timestamps. Calendar-day differences are
 * evaluated in the game timezone so “昨天” matches the server's day, not the
 * browser's locale timezone.
 */
export function formatRelativeTime(
  value: string,
  now: Date = new Date(),
): string {
  const parsed = parseDate(value)
  if (!parsed) return '时间未知'
  const diff = now.getTime() - parsed.getTime()
  if (diff < MINUTE) return '刚刚'
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)} 分钟前`
  if (diff < DAY) return `${Math.floor(diff / HOUR)} 小时前`

  const dayDiff = gameDayNumber(now) - gameDayNumber(parsed)
  if (dayDiff <= 1) return '昨天'
  if (dayDiff < 7) return `${dayDiff} 天前`
  return formatDateOnly(value)
}
