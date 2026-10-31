import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  apiFetch,
  ApiError,
  clearStoredToken,
  readStoredToken,
  storeToken,
  TOKEN_KEY,
} from './client'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('apiFetch', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'stored-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('injects the existing bearer token and parses JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    const payload = await apiFetch<{ ok: boolean }>('/v1/me/status')

    expect(payload).toEqual({ ok: true })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/v1/me/status')
    expect((init.headers as Headers).get('Authorization')).toBe(
      'Bearer stored-token',
    )
    expect(init.cache).toBe('no-store')
  })

  it('lets an explicit token win during login validation', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await apiFetch('/v1/me/profile', { token: 'pasted-token' })

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Headers).get('Authorization')).toBe(
      'Bearer pasted-token',
    )
  })

  it('sends JSON bodies for real profile writes', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await apiFetch('/v1/me/profile', {
      method: 'PATCH',
      body: { icon_theme: 'material' },
    })

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('PATCH')
    expect(init.body).toBe(JSON.stringify({ icon_theme: 'material' }))
    expect((init.headers as Headers).get('Content-Type')).toBe(
      'application/json',
    )
  })

  it('turns FastAPI errors into ApiError with status and detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ detail: 'Invalid or missing bearer token' }, 401),
      ),
    )

    await expect(apiFetch('/v1/me/status')).rejects.toMatchObject({
      name: 'ApiError',
      status: 401,
      message: 'Invalid or missing bearer token',
    })
  })

  it('reports a network failure without leaking internals', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('network down')),
    )

    await expect(apiFetch('/v1/me/status')).rejects.toMatchObject({
      name: 'ApiError',
      status: 0,
      message: '网络连接失败，请检查网络后重试。',
    })
    await expect(apiFetch('/v1/me/status')).rejects.toBeInstanceOf(ApiError)
  })
})

describe('token storage', () => {
  it('reads, stores and clears the legacy gl.token.v1 key', () => {
    expect(readStoredToken()).toBeNull()
    storeToken('  abc  ')
    expect(window.localStorage.getItem(TOKEN_KEY)).toBe('abc')
    expect(readStoredToken()).toBe('abc')
    clearStoredToken()
    expect(readStoredToken()).toBeNull()
  })
})
