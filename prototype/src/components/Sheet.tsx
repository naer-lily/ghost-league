import { useEffect, useId, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'

interface SheetProps {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: string
  variant?: 'bottom' | 'right' | 'center'
  children: ReactNode
  footer?: ReactNode
  testId?: string
}

export function Sheet({
  open,
  onClose,
  title,
  subtitle,
  variant = 'bottom',
  children,
  footer,
  testId,
}: SheetProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      dialog.showModal()
      document.documentElement.classList.add('has-modal')
    } else if (!open && dialog.open) {
      dialog.close()
      document.documentElement.classList.remove('has-modal')
    }
    return () => {
      if (dialog.open) dialog.close()
      document.documentElement.classList.remove('has-modal')
    }
  }, [open])

  return (
    <dialog
      ref={ref}
      className={`sheet sheet--${variant}`}
      aria-labelledby={titleId}
      data-testid={testId}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose()
      }}
    >
      <div className="sheet__inner">
        <header className="sheet__header">
          <div className="sheet__heading">
            <h2 className="sheet__title" id={titleId}>
              {title}
            </h2>
            {subtitle ? <p className="sheet__subtitle">{subtitle}</p> : null}
          </div>
          <button type="button" className="icon-button" aria-label="关闭" onClick={onClose}>
            <X className="icon-24" aria-hidden="true" />
          </button>
        </header>
        <div className="sheet__body">{children}</div>
        {footer ? <footer className="sheet__footer">{footer}</footer> : null}
      </div>
    </dialog>
  )
}
