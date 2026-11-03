import { ApiError } from '../api/client'

export const RARITY_LABELS: Record<string, string> = {
  common: '微光',
  uncommon: '星辉',
  rare: '耀星',
  epic: '奇点',
  legendary: '神话',
}

const RARITY_COLORS: Record<string, string> = {
  common: '#b8c7cf',
  uncommon: '#58cc02',
  rare: '#4e9bff',
  epic: '#ce82ff',
  legendary: '#ffc800',
}

export function rarityLabel(rarity: string): string {
  return RARITY_LABELS[rarity] ?? '未知稀有度'
}

export function rarityColor(rarity: string): string {
  return RARITY_COLORS[rarity] ?? 'var(--muted)'
}

export function formatRate(value: number): string {
  if (!Number.isFinite(value)) return '—'
  const percent = Math.max(0, value) * 100
  if (percent >= 10) return `${Math.round(percent)}%`
  if (percent >= 1) return `${Number(percent.toFixed(1))}%`
  return `${Number(percent.toFixed(2))}%`
}

export function formatRemainingSeconds(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return ''
  const minutes = Math.ceil(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours < 24) return rest ? `${hours} 小时 ${rest} 分钟` : `${hours} 小时`
  const days = Math.floor(hours / 24)
  const dayHours = hours % 24
  return dayHours ? `${days} 天 ${dayHours} 小时` : `${days} 天`
}

export function formatRemaining(
  until: string | null,
  now: Date = new Date(),
): string {
  if (!until) return ''
  const target = new Date(until)
  if (Number.isNaN(target.getTime())) return ''
  return formatRemainingSeconds((target.getTime() - now.getTime()) / 1000)
}

export function formatSeasonKey(seasonKey: string | null | undefined): string {
  if (!seasonKey) return ''
  return /^\d{4}-\d{2}$/.test(seasonKey)
    ? `${seasonKey} 限定`
    : seasonKey
}

export function formatAcquiredAt(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Shanghai',
  }).format(date)
}

function errorDetail(error: ApiError): Record<string, unknown> | null {
  const payload = error.detail
  if (!payload || typeof payload !== 'object') return null
  const nested = (payload as { detail?: unknown }).detail
  if (nested && typeof nested === 'object') {
    return nested as Record<string, unknown>
  }
  return payload as Record<string, unknown>
}

function detailCode(error: ApiError): string | null {
  const code = errorDetail(error)?.code
  return typeof code === 'string' ? code : null
}

function detailCooldown(error: ApiError): string | null {
  const until = errorDetail(error)?.cooldown_until
  return typeof until === 'string' ? until : null
}

/**
 * Turn a shop failure into user-facing copy. The backend code is the stable
 * signal; its English detail is only shown when the code is unknown.
 */
export function describeShopError(error: unknown): string {
  if (!(error instanceof ApiError)) return '购买没有完成，请稍后重试。'
  if (error.status === 0) return error.message
  if (error.status === 401) return '登录已失效，请重新输入令牌。'
  const code = detailCode(error)
  if (code === 'insufficient_diamonds') return '钻石不足，先去完成本周目标吧。'
  if (code === 'cooldown') {
    const remaining = formatRemaining(detailCooldown(error))
    return remaining
      ? `这个补给还在冷却中，${remaining}后再来。`
      : '这个补给还在冷却中，请稍后再来。'
  }
  if (code === 'seasonal_star_owned') return '本月已经获得过季节星了，下个月再来。'
  if (code === 'cap_unavailable') return '仓库等级已经变化，刷新后再试。'
  if (code === 'boost_inactive') return '这个经验宝现在不能购买。'
  if (code === 'boost_config_invalid') return '这个经验宝现在不能购买。'
  if (code === 'unknown_item') return '商店里没有这个条目。'
  if (code === 'not_available') return '这个条目现在暂时不能购买。'
  if (code === 'not_allowed') return '当前账号不能购买这个条目。'
  if (error.status >= 500) return '服务暂时不可用，请稍后重试。'
  return error.message || '购买没有完成，请稍后重试。'
}
