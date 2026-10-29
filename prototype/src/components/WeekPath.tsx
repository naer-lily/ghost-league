import { CalendarPlus, Check, Flame, Lock } from 'lucide-react'
import type { PathDay } from '../data'
import { useApp } from '../store'
import { EmberSprite } from './EmberSprite'

function statusLabel(day: PathDay): string {
  if (day.status === 'today') return `今天，${day.weekday} ${day.date}，${day.xp} XP，已点火`
  if (day.status === 'done') {
    return day.repaired
      ? `${day.weekday} ${day.date}，已补签`
      : `${day.weekday} ${day.date}，已点火，${day.xp} XP`
  }
  if (day.status === 'missed') return `${day.weekday} ${day.date}，断签，可补签`
  return `${day.weekday} ${day.date}，未解锁`
}

export function WeekPath() {
  const { days, openSheet, todayXp } = useAppDays()

  return (
    <section className="week-path" aria-label="本周路径" data-testid="week-path">
      <div className="path-buddy" aria-hidden="false">
        <EmberSprite size={58} label="余烬精灵" />
        <span className="path-buddy__bubble">火还亮着。</span>
      </div>

      <span className="path-spine" aria-hidden="true" />

      <ol className="path-list">
        {days.map((day, index) => {
          const side = index % 2 === 0 ? 'left' : 'right'
          return (
            <li key={day.id} className={`path-row path-row--${side}`}>
              <span className="path-row__stem" aria-hidden="true" />
              <button
                type="button"
                className={`day-node day-node--${day.status}`}
                data-testid={day.status === 'today' ? 'day-node-today' : `day-node-${day.status}`}
                data-day-id={day.id}
                aria-label={statusLabel(day)}
                onClick={() => openSheet({ kind: 'day', dayId: day.id })}
              >
                {day.status === 'today' ? (
                  <>
                    <Flame className="day-node__icon" aria-hidden="true" />
                    <span className="day-node__xp" data-testid="today-xp">
                      {todayXp}
                    </span>
                    <span className="day-node__unit">XP</span>
                  </>
                ) : day.status === 'done' ? (
                  day.repaired ? (
                    <Flame className="day-node__icon" aria-hidden="true" />
                  ) : (
                    <Check className="day-node__icon" aria-hidden="true" />
                  )
                ) : day.status === 'missed' ? (
                  <CalendarPlus className="day-node__icon" aria-hidden="true" />
                ) : (
                  <Lock className="day-node__icon" aria-hidden="true" />
                )}
              </button>
              <span className="path-row__meta" aria-hidden="true">
                <span className="path-row__weekday">{day.weekday}</span>
              </span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

function useAppDays() {
  const { days, openSheet } = useApp()
  const today = days.find((day) => day.status === 'today')
  return {
    days,
    openSheet,
    todayXp: today?.xp ?? 0,
  }
}
