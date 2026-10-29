interface SegmentOption<T extends string> {
  id: T
  label: string
  count?: number
}

interface SegmentedProps<T extends string> {
  value: T
  options: SegmentOption<T>[]
  onChange: (value: T) => void
  label: string
}

export function Segmented<T extends string>({ value, options, onChange, label }: SegmentedProps<T>) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          className="segmented__item"
          aria-pressed={value === option.id}
          onClick={() => onChange(option.id)}
        >
          <span>{option.label}</span>
          {typeof option.count === 'number' ? (
            <span className="segmented__count">{option.count}</span>
          ) : null}
        </button>
      ))}
    </div>
  )
}
