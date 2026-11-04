export const TOKEN_KEY = 'gl.token.v1'

const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '')

export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(message: string, status: number, detail: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export function readStoredToken(): string | null {
  try {
    const value = window.localStorage.getItem(TOKEN_KEY)
    return value && value.trim() ? value.trim() : null
  } catch {
    return null
  }
}

export function storeToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token.trim())
  } catch {
    // Private browsing may deny storage; the in-memory session still works.
  }
}

export function clearStoredToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY)
  } catch {
    // Ignore storage failures.
  }
}

export function resolveApiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}

function detailMessage(payload: unknown): string | null {
  if (typeof payload === 'string') return payload
  if (!payload || typeof payload !== 'object') return null
  const detail = (payload as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    const nested = detail as { message?: unknown; msg?: unknown }
    if (typeof nested.message === 'string') return nested.message
    if (typeof nested.msg === 'string') return nested.msg
  }
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: unknown } | undefined
    if (first && typeof first.msg === 'string') return first.msg
  }
  return null
}

export interface ApiFetchOptions {
  token?: string
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
  headers?: HeadersInit
}

export interface ApiBlobOptions {
  token?: string
  signal?: AbortSignal
  headers?: HeadersInit
}

function authorizedHeaders(headers: HeadersInit | undefined, accept: string): Headers {
  const result = new Headers(headers)
  result.set('Accept', accept)
  const token = readStoredToken()
  if (token) result.set('Authorization', `Bearer ${token}`)
  return result
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }
  const message =
    detailMessage(payload) ?? `请求没有成功（HTTP ${response.status}）`
  return new ApiError(message, response.status, payload)
}

async function request(
  path: string,
  options: ApiFetchOptions,
  accept: string,
): Promise<Response> {
  const headers = authorizedHeaders(options.headers, accept)
  if (options.token) headers.set('Authorization', `Bearer ${options.token}`)

  let body: BodyInit | null = null
  if (options.body instanceof FormData) {
    body = options.body
  } else if (options.body !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(options.body)
  }

  let response: Response
  try {
    response = await fetch(resolveApiUrl(path), {
      method: options.method ?? 'GET',
      headers,
      body,
      cache: 'no-store',
      ...(options.signal ? { signal: options.signal } : {}),
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError('网络连接失败，请检查网络后重试。', 0, error)
  }

  if (!response.ok) throw await errorFromResponse(response)
  return response
}

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const response = await request(path, options, 'application/json')
  if (response.status === 204) return undefined as T
  try {
    return (await response.json()) as T
  } catch {
    throw new ApiError('服务返回了无法读取的数据。', response.status, null)
  }
}

/**
 * Fetch a private binary resource with the same Bearer token as ``apiFetch``.
 * ``<img src>`` cannot attach an Authorization header, so callers turn the
 * resulting blob into an object URL and revoke it when done.
 */
export async function apiFetchBlob(
  path: string,
  options: ApiBlobOptions = {},
): Promise<Blob> {
  const requestOptions: ApiFetchOptions = {}
  if (options.token) requestOptions.token = options.token
  if (options.signal) requestOptions.signal = options.signal
  if (options.headers) requestOptions.headers = options.headers
  const response = await request(
    path,
    requestOptions,
    'image/svg+xml,image/*;q=0.8',
  )
  try {
    return await response.blob()
  } catch {
    throw new ApiError('图片没有读取成功。', response.status, null)
  }
}
