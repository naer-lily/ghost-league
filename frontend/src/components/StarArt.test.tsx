import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TOKEN_KEY } from '../api/client'
import { makeStar } from '../test/fixtures'
import { StarArt } from './StarArt'

function svgResponse(): Response {
  return {
    ok: true,
    status: 200,
    json: async () => ({}),
    blob: async () =>
      new Blob(['<svg xmlns="http://www.w3.org/2000/svg"></svg>'], {
        type: 'image/svg+xml',
      }),
  } as Response
}

describe('StarArt', () => {
  beforeEach(() => {
    window.localStorage.setItem(TOKEN_KEY, 'test-token')
    vi.mocked(URL.createObjectURL).mockReturnValue('blob:star-art')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('fetches the private SVG with Bearer auth and renders a blob image', async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) => svgResponse(),
    )
    vi.stubGlobal('fetch', fetchMock)
    const star = makeStar()

    const { container, unmount } = render(<StarArt star={star} />)

    expect(screen.getByTestId('star-art')).toHaveAttribute(
      'data-state',
      'loading',
    )

    const image = await waitFor(() => {
      const node = container.querySelector('img')
      expect(node).not.toBeNull()
      return node as HTMLImageElement
    })
    expect(image).toHaveAttribute('src', 'blob:star-art')
    expect(screen.getByTestId('star-art')).toHaveAttribute('data-state', 'ready')

    const [input, init] = fetchMock.mock.calls[0]!
    expect(String(input)).toBe(star.svg_url)
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      'Bearer test-token',
    )
    expect(init?.cache).toBe('no-store')

    unmount()
    await waitFor(() =>
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:star-art'),
    )
  })

  it('shows a neutral failure state instead of an invented star', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 404,
        json: async () => ({ detail: 'star not found' }),
      })),
    )

    render(<StarArt star={makeStar()} />)

    await waitFor(() =>
      expect(screen.getByTestId('star-art')).toHaveAttribute(
        'data-state',
        'failed',
      ),
    )
    expect(screen.queryByRole('img', { hidden: true })).not.toBeInTheDocument()
    expect(screen.getByText('星星图像加载失败')).toBeInTheDocument()
  })
})
