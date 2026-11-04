import { afterEach, describe, expect, it, vi } from 'vitest'
import { MAX_TASK_PROOF_BYTES, compressTaskProof } from './image'

function largeFile(name = 'photo.heic', type = 'image/heic'): File {
  return new File([new Uint8Array(MAX_TASK_PROOF_BYTES + 1)], name, { type })
}

function mockBitmap(width = 3000, height = 2000) {
  const close = vi.fn()
  vi.stubGlobal(
    'createImageBitmap',
    vi.fn(async () => ({ width, height, close }) as unknown as ImageBitmap),
  )
  return close
}

function mockCanvasContext() {
  const context = {
    fillStyle: '',
    fillRect: vi.fn(),
    drawImage: vi.fn(),
  }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    context as unknown as CanvasRenderingContext2D,
  )
  return context
}

function mockToBlob(
  sizeFor: (canvas: HTMLCanvasElement, quality: number | undefined) => number,
) {
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(
    function (this: HTMLCanvasElement, callback, _type, quality) {
      callback(
        new Blob([new Uint8Array(sizeFor(this, quality))], {
          type: 'image/jpeg',
        }),
      )
    },
  )
}

describe('compressTaskProof', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('leaves a file that is already under 1MB untouched', async () => {
    const decode = vi.fn()
    vi.stubGlobal('createImageBitmap', decode)
    const file = new File(['small'], 'small.jpg', { type: 'image/jpeg' })

    await expect(compressTaskProof(file)).resolves.toBe(file)
    expect(decode).not.toHaveBeenCalled()
  })

  it('reduces JPEG quality until the result fits and returns a .jpg File', async () => {
    const close = mockBitmap()
    const context = mockCanvasContext()
    mockToBlob((_canvas, quality) => (quality === 0.9 ? 2_000_000 : 900_000))
    const file = largeFile('photo.heic', 'image/heic')

    const result = await compressTaskProof(file)

    expect(result).not.toBe(file)
    expect(result.name).toBe('photo.jpg')
    expect(result.type).toBe('image/jpeg')
    expect(result.size).toBeLessThanOrEqual(MAX_TASK_PROOF_BYTES)
    expect(close).toHaveBeenCalledTimes(1)
    expect(context.fillStyle).toBe('#ffffff')
    expect(context.fillRect).toHaveBeenCalled()
    expect(context.drawImage).toHaveBeenCalled()
  })

  it('shrinks the long edge when every quality at the current size is too big', async () => {
    mockBitmap()
    mockCanvasContext()
    const widths: number[] = []
    mockToBlob((canvas) => {
      widths.push(canvas.width)
      return canvas.width > 1600 ? 1_500_000 : 700_000
    })

    const result = await compressTaskProof(largeFile('photo.jpg', 'image/jpeg'))

    expect(widths).toEqual([2400, 2400, 2400, 2400, 1600])
    expect(result.size).toBe(700_000)
  })

  it('returns the original file when the browser cannot decode it', async () => {
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn(async () => {
        throw new Error('unsupported')
      }),
    )
    class FailingImage {
      onload: (() => void) | null = null
      onerror: (() => void) | null = null
      naturalWidth = 0
      naturalHeight = 0
      width = 0
      height = 0
      set src(_value: string) {
        queueMicrotask(() => this.onerror?.())
      }
    }
    vi.stubGlobal('Image', FailingImage)
    mockCanvasContext()
    const file = largeFile('proof.heic', 'image/heic')

    await expect(compressTaskProof(file)).resolves.toBe(file)
  })

  it('falls back to the original file when JPEG encoding fails', async () => {
    mockBitmap()
    mockCanvasContext()
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(
      (callback) => callback(null),
    )
    const file = largeFile('photo.png', 'image/png')

    await expect(compressTaskProof(file)).resolves.toBe(file)
  })
})
