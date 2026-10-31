import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { useEffect } from 'react'
import { useUiStore } from '../store/useUiStore'
import styles from './Toast.module.css'

export function Toast() {
  const toast = useUiStore((state) => state.toast)
  const dismiss = useUiStore((state) => state.dismissToast)
  const reducedMotion = useReducedMotion()

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => dismiss(), 2600)
    return () => window.clearTimeout(timer)
  }, [dismiss, toast])

  return (
    <div className={styles.region} aria-live="polite" aria-atomic="true">
      <AnimatePresence initial={false}>
        {toast ? (
          <motion.p
            key={toast.id}
            className={[styles.toast, toast.tone === 'error' ? styles.error : '']
              .filter(Boolean)
              .join(' ')}
            role={toast.tone === 'error' ? 'alert' : 'status'}
            initial={reducedMotion ? false : { opacity: 0, y: 12, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reducedMotion ? { opacity: 0 } : { opacity: 0, y: 8 }}
            transition={{ duration: reducedMotion ? 0 : 0.2 }}
          >
            {toast.message}
          </motion.p>
        ) : null}
      </AnimatePresence>
    </div>
  )
}
