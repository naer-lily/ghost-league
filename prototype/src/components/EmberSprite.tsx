interface EmberSpriteProps {
  size?: number
  className?: string
  label?: string
}

/** A small original ember spirit: rounded body, two eyes, one flame. */
export function EmberSprite({ size = 72, className = '', label }: EmberSpriteProps) {
  return (
    <span
      className={`ember-sprite ${className}`.trim()}
      style={{ width: size, height: size }}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <svg viewBox="0 0 120 120" width={size} height={size} aria-hidden="true">
        <defs>
          <radialGradient id="ember-body" cx="42%" cy="34%" r="72%">
            <stop offset="0%" stopColor="#ffd86f" />
            <stop offset="45%" stopColor="#ff9600" />
            <stop offset="100%" stopColor="#ff4b4b" />
          </radialGradient>
          <linearGradient id="ember-flame" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ffc800" />
            <stop offset="100%" stopColor="#ff9600" />
          </linearGradient>
        </defs>
        <path
          className="ember-sprite__flame"
          d="M62 7c3 11-7 13-4 24 5-2 7-6 7-11 9 7 14 17 14 28 0 13-10 22-23 22S33 61 33 48c0-14 12-23 22-36 1-2 4-4 7-5Z"
          fill="url(#ember-flame)"
        />
        <path
          className="ember-sprite__inner-flame"
          d="M60 33c1 7-6 9-4 16 4-1 5-4 5-8 5 5 8 10 8 16 0 8-6 13-14 13s-14-5-14-13c0-8 8-15 14-22 1-1 3-1 5-2Z"
          fill="#ff4b4b"
          opacity="0.75"
        />
        <path
          d="M16 80c0-14 12-24 27-24h30c15 0 27 10 27 24 0 13-11 23-26 23H42c-15 0-26-10-26-23Z"
          fill="url(#ember-body)"
        />
        <ellipse cx="44" cy="73" rx="9" ry="11" fill="#fff" />
        <ellipse cx="72" cy="73" rx="9" ry="11" fill="#fff" />
        <ellipse className="ember-sprite__pupil" cx="45" cy="75" rx="4.2" ry="5.2" fill="#3b2016" />
        <ellipse className="ember-sprite__pupil" cx="73" cy="75" rx="4.2" ry="5.2" fill="#3b2016" />
        <circle cx="46" cy="73" r="1.4" fill="#fff" />
        <circle cx="74" cy="73" r="1.4" fill="#fff" />
        <path
          d="M52 90c3 4 12 4 15 0"
          fill="none"
          stroke="#3b2016"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <ellipse cx="29" cy="88" rx="6" ry="4" fill="#ff4b4b" opacity="0.45" />
        <ellipse cx="87" cy="88" rx="6" ry="4" fill="#ff4b4b" opacity="0.45" />
      </svg>
    </span>
  )
}

/** Flat ember glyph for stats and log rows. */
export function EmberGlyph({ className = '', size = 24 }: { className?: string; size?: number }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M12.7 2.4c.4 3.3-2.5 4.2-1.9 6.9 1.1-.4 1.6-1.5 1.6-2.8 2 1.5 3.3 3.8 3.3 6.4A5.8 5.8 0 0 1 12 18.8a5.8 5.8 0 0 1-4-5.7c0-3.2 2.4-5 4.7-10.7Z"
        fill="currentColor"
      />
      <path
        d="M11.9 11.1c.2 1.8-1.5 2.4-1.1 4 1.2-.5 1.9-1.5 2.2-2.6 1 1 1.5 2.1 1.5 3.2a2.8 2.8 0 0 1-5.6 0c0-1.6 1.5-2.7 2.8-4.6Z"
        fill="#fff"
        opacity="0.55"
      />
    </svg>
  )
}
