type AudioContextConstructor = typeof AudioContext

let context: AudioContext | null = null

function audioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null
  const Constructor =
    window.AudioContext ??
    (window as Window & { webkitAudioContext?: AudioContextConstructor })
      .webkitAudioContext
  if (!Constructor) return null
  if (!context) {
    try {
      context = new Constructor()
    } catch {
      return null
    }
  }
  return context
}

/** A short, real UI click. Never throws when audio is unavailable. */
export function playClick(enabled: boolean, pitch = 660): void {
  if (!enabled) return
  const ctx = audioContext()
  if (!ctx) return
  try {
    if (ctx.state === 'suspended') void ctx.resume()
    const oscillator = ctx.createOscillator()
    const gain = ctx.createGain()
    oscillator.type = 'sine'
    oscillator.frequency.setValueAtTime(pitch, ctx.currentTime)
    oscillator.frequency.exponentialRampToValueAtTime(
      pitch * 1.32,
      ctx.currentTime + 0.055,
    )
    gain.gain.setValueAtTime(0.0001, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.045, ctx.currentTime + 0.008)
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.09)
    oscillator.connect(gain)
    gain.connect(ctx.destination)
    oscillator.start()
    oscillator.stop(ctx.currentTime + 0.1)
  } catch {
    // Audio is a progressive enhancement only.
  }
}
