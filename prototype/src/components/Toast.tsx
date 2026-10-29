import { AlertCircle, CheckCircle2 } from 'lucide-react'
import type { ToastState } from '../store'

export function Toast({ toast }: { toast: ToastState | null }) {
  if (!toast) return null
  const isError = toast.tone === 'error'
  return (
    <div
      key={toast.id}
      className={`toast ${isError ? 'toast--error' : ''}`}
      role={isError ? 'alert' : 'status'}
      aria-live={isError ? 'assertive' : 'polite'}
    >
      {isError ? (
        <AlertCircle className="icon-20" aria-hidden="true" />
      ) : (
        <CheckCircle2 className="icon-20" aria-hidden="true" />
      )}
      <span>{toast.message}</span>
    </div>
  )
}
