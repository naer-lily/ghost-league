import type { AvatarTone } from '../data'

export type AvatarSize = 'sm' | 'md' | 'lg' | 'xl'
export type FrameKind = 'ember' | 'bronze' | 'mint' | 'sun' | 'crown' | 'comet'

interface AvatarProps {
  initial: string
  tone: AvatarTone
  size?: AvatarSize
  frame?: FrameKind
  image?: string | null
  name?: string
  className?: string
}

export function Avatar({
  initial,
  tone,
  size = 'sm',
  frame,
  image,
  name,
  className = '',
}: AvatarProps) {
  return (
    <span
      className={`avatar avatar--${size} avatar--${tone} ${className}`.trim()}
      data-frame={frame && frame !== 'ember' ? frame : undefined}
      role={name ? 'img' : undefined}
      aria-label={name}
      aria-hidden={name ? undefined : true}
    >
      <span className="avatar__disc">
        {image ? (
          <img className="avatar__image" src={image} alt="" />
        ) : (
          <span className="avatar__initial">{initial}</span>
        )}
      </span>
      {frame === 'ember' ? (
        <img className="avatar__frame-img" src="/assets/frames/frame_ember.png" alt="" aria-hidden="true" />
      ) : null}
    </span>
  )
}
