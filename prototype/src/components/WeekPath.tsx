import { Check, Flame } from 'lucide-react'
import type { PathDay } from '../data'
import { useApp } from '../store'

function statusLabel(day: PathDay): string {
  if (day.status === 'today') return `今天，${day.weekday} ${day.date}，${day.xp} XP，已点火`
  if (day.status === 'done') {
    return day.repaired
      ? `${day.weekday} ${day.date}，已补签`
      : `${day.weekday} ${day.date}，已点火，${day.xp} XP`
  }
  if (day.status === 'missed') return `${day.weekday} ${day.date}，断签，可补签`
  return `${day.weekday} ${day.date}，未开始`
}

export function WeekPath() {
  const { days, openSheet, todayXp } = useAppDays()

  return (
    <section className="week-path" aria-label="本周路径" data-testid="week-path">
      <div className="path-track">
        <span className="path-spine" aria-hidden="true" />

        <ol className="path-list">
          {days.map((day, index) => {
            const side = index % 2 === 0 ? 'left' : 'right'
            return (
              <li key={day.id} className={`path-row path-row--${side}`}>
                <span className="path-row__stem" aria-hidden="true" />
                <span className="path-row__meta" aria-hidden="true">
                  <span className="path-row__weekday">{day.weekday}</span>
                  <span className="path-row__date">{day.date}</span>
                </span>
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
                      <span className="day-node__flag day-node__flag--today" aria-hidden="true">
                        今天
                      </span>
                      <Flame className="day-node__icon day-node__icon--today" aria-hidden="true" />
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
                    <>
                      <span className="day-node__flag day-node__flag--repair" aria-hidden="true">
                        补
                      </span>
                      <Flame className="day-node__icon" aria-hidden="true" />
                    </>
                  ) : (
                    <span className="day-node__dot" aria-hidden="true" />
                  )}
                </button>
              </li>
            )
          })}
        </ol>
      </div>
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
