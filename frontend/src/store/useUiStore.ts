import { create } from 'zustand'
import { clearStoredToken, readStoredToken, storeToken } from '../api/client'

const SOUND_KEY = 'gl.sound.v1'

function readSoundPreference(): boolean {
  try {
    return window.localStorage.getItem(SOUND_KEY) !== '0'
  } catch {
    return true
  }
}

function writeSoundPreference(enabled: boolean): void {
  try {
    window.localStorage.setItem(SOUND_KEY, enabled ? '1' : '0')
  } catch {
    // Ignore storage failures.
  }
}

export type ToastTone = 'default' | 'error'

export interface ToastMessage {
  id: number
  message: string
  tone: ToastTone
}

interface UiState {
  token: string | null
  soundEnabled: boolean
  settingsOpen: boolean
  toast: ToastMessage | null
  signIn: (token: string) => void
  signOut: () => void
  toggleSound: () => boolean
  setSettingsOpen: (open: boolean) => void
  notify: (message: string, tone?: ToastTone) => void
  dismissToast: () => void
}

export const useUiStore = create<UiState>((set, get) => ({
  token: readStoredToken(),
  soundEnabled: readSoundPreference(),
  settingsOpen: false,
  toast: null,
  signIn: (token) => {
    const value = token.trim()
    if (!value) return
    storeToken(value)
    set({ token: value })
  },
  signOut: () => {
    clearStoredToken()
    set({ token: null, settingsOpen: false, toast: null })
  },
  toggleSound: () => {
    const next = !get().soundEnabled
    writeSoundPreference(next)
    set({ soundEnabled: next })
    return next
  },
  setSettingsOpen: (open) => set({ settingsOpen: open }),
  notify: (message, tone = 'default') =>
    set({ toast: { id: Date.now(), message, tone } }),
  dismissToast: () => set({ toast: null }),
}))
