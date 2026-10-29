import { useRef, useState } from 'react'
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import { CircleHelp } from 'lucide-react'

interface InfoTipProps {
  label: string
  title: string
  body: string
  side?: 'top' | 'bottom' | 'left' | 'right'
}

export function InfoTip({ label, title, body, side = 'top' }: InfoTipProps) {
  const [open, setOpen] = useState(false)
  const openRef = useRef(false)
  const touchNextRef = useRef<boolean | null>(null)

  const handleOpenChange = (next: boolean) => {
    openRef.current = next
    setOpen(next)
  }

  return (
    <TooltipPrimitive.Root open={open} onOpenChange={handleOpenChange}>
      <TooltipPrimitive.Trigger asChild>
        <button
          type="button"
          className="info-tip__trigger"
          aria-label={label}
          onPointerDown={(event) => {
            if (event.pointerType !== 'mouse') {
              touchNextRef.current = !openRef.current
            }
          }}
          onClick={(event) => {
            let next = touchNextRef.current
            if (next !== null) {
              touchNextRef.current = null
            } else if (event.detail === 0) {
              next = !openRef.current
            } else {
              return
            }
            // Radix closes the tooltip on click; re-apply the intended toggle
            // after the composed handlers have finished.
            window.setTimeout(() => handleOpenChange(next), 0)
          }}
        >
          <CircleHelp className="icon-20" aria-hidden="true" />
        </button>
      </TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          className="info-tip__bubble"
          side={side}
          sideOffset={8}
          collisionPadding={16}
          avoidCollisions
          onPointerDownOutside={() => setOpen(false)}
        >
          <span className="info-tip__title">{title}</span>
          <span className="info-tip__body">{body}</span>
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  )
}
