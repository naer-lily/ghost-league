// Task proof photos are uploaded from phones.  Keep the browser-side result
// under the same 1MB ceiling the API enforces, but never block the upload:
// if the browser cannot decode the file (typically HEIC in Chrome), return the
// original file and let the server convert it.

export const MAX_TASK_PROOF_BYTES = 1_000_000

const JPEG_QUALITIES = [0.9, 0.75, 0.6, 0.45] as const
const MAX_LONG_EDGES = [2400, 1600, 1200, 800] as const
const DECODE_TIMEOUT_MS = 15_000

interface DecodedProof {
  source: CanvasImageSource
  width: number
  height: number
  release: () => void
}

function supportsCanvasEncoding(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return typeof canvas.toBlob === 'function' && Boolean(canvas.getContext('2d'))
  } catch {
    return false
  }
}

async function decodeWithImageBitmap(file: File): Promise<DecodedProof | null> {
  if (typeof createImageBitmap !== 'function') return null
  try {
    const bitmap = await createImageBitmap(file, {
      imageOrientation: 'from-image',
    })
    return {
      source: bitmap,
      width: bitmap.width,
      height: bitmap.height,
      release: () => bitmap.close(),
    }
  } catch {
    return null
  }
}

function decodeWithImageElement(file: File): Promise<DecodedProof | null> {
  if (
    typeof Image === 'undefined' ||
    typeof URL.createObjectURL !== 'function'
  ) {
    return Promise.resolve(null)
  }
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const image = new Image()
    let settled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    function finish(value: DecodedProof | null) {
      if (settled) return
      settled = true
      if (timer !== undefined) clearTimeout(timer)
      image.onload = null
      image.onerror = null
      URL.revokeObjectURL(url)
      resolve(value)
    }

    image.onload = () => {
      const width = image.naturalWidth || image.width
      const height = image.naturalHeight || image.height
      if (!width || !height) {
        finish(null)
        return
      }
      finish({ source: image, width, height, release: () => {} })
    }
    image.onerror = () => finish(null)
    image.src = url
    timer = setTimeout(() => finish(null), DECODE_TIMEOUT_MS)
  })
}

async function decodeProof(file: File): Promise<DecodedProof | null> {
  const bitmap = await decodeWithImageBitmap(file)
  if (bitmap) return bitmap
  return decodeWithImageElement(file)
}

function renderJpeg(
  image: DecodedProof,
  longEdge: number,
  quality: number,
): Promise<Blob | null> {
  const scale = Math.min(1, longEdge / Math.max(image.width, image.height))
  const width = Math.max(1, Math.round(image.width * scale))
  const height = Math.max(1, Math.round(image.height * scale))
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  let context: CanvasRenderingContext2D | null = null
  try {
    context = canvas.getContext('2d')
  } catch {
    return Promise.resolve(null)
  }
  if (!context) return Promise.resolve(null)
  // Proof photos are photos, not transparent art: flatten onto white.
  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, width, height)
  context.drawImage(image.source, 0, 0, width, height)
  if (typeof canvas.toBlob !== 'function') return Promise.resolve(null)
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), 'image/jpeg', quality)
  })
}

function jpegFileName(name: string): string {
  const dot = name.lastIndexOf('.')
  const base = dot > 0 ? name.slice(0, dot) : name
  return `${base || 'proof'}.jpg`
}

function asJpegFile(file: File, blob: Blob): File {
  return new File([blob], jpegFileName(file.name), {
    type: 'image/jpeg',
    lastModified: file.lastModified,
  })
}

/**
 * Compress a task proof to JPEG under 1,000,000 bytes when the browser can
 * decode it.  Files that are already small or cannot be decoded are returned
 * unchanged; HEIC/HEIF therefore falls through to the server converter.
 */
export async function compressTaskProof(file: File): Promise<File> {
  if (file.size <= MAX_TASK_PROOF_BYTES) return file
  if (!supportsCanvasEncoding()) return file

  const decoded = await decodeProof(file)
  if (!decoded) return file

  try {
    let smallest: Blob | null = null
    for (const longEdge of MAX_LONG_EDGES) {
      for (const quality of JPEG_QUALITIES) {
        const blob = await renderJpeg(decoded, longEdge, quality)
        if (!blob) continue
        if (!smallest || blob.size < smallest.size) smallest = blob
        if (blob.size <= MAX_TASK_PROOF_BYTES) {
          return asJpegFile(file, blob)
        }
      }
    }
    return smallest ? asJpegFile(file, smallest) : file
  } catch {
    return file
  } finally {
    decoded.release()
  }
}
