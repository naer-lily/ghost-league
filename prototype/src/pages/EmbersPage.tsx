import { CalendarPlus, Flame, Gift, Minus, Plus } from 'lucide-react'
import { tips } from '../data'
import { useApp } from '../store'
import { EmberSprite } from '../components/EmberSprite'
import { InfoTip } from '../components/InfoTip'

export function EmbersPage() {
  const { embers, emberLog, repairDays, openSheet } = useApp()

  return (
    <div className="embers-page" data-testid="embers-page">
      <section className="embers-hero card" aria-labelledby="embers-balance-title">
        <div className="embers-hero__art" aria-hidden="true">
          <EmberSprite size={118} />
        </div>
        <div className="embers-hero__body">
          <div className="embers-hero__head">
            <h2 className="embers-hero__label" id="embers-balance-title">
              余烬
            </h2>
            <InfoTip {...tips.embers} side="bottom" />
          </div>
          <p className="embers-hero__balance">
            <span data-testid="embers-balance">{embers}</span>
          </p>
          <button
            type="button"
            className="button button--primary"
            onClick={() => openSheet({ kind: 'repair' })}
            disabled={embers < 1 || repairDays.length === 0}
            data-testid="embers-repair-button"
          >
            <CalendarPlus className="icon-20" aria-hidden="true" />
            补签
          </button>
        </div>
      </section>

      <section className="card ember-log" aria-labelledby="ember-log-title">
        <div className="section-head">
          <h2 className="section-head__title" id="ember-log-title">
            流水
          </h2>
          <span className="section-head__count">{emberLog.length}</span>
        </div>
        <ul className="log-list">
          {emberLog.map((entry) => (
            <li key={entry.id} className="log-row">
              <span className={`log-row__icon log-row__icon--${entry.icon}`} aria-hidden="true">
                {entry.icon === 'calendar' ? (
                  <CalendarPlus className="icon-20" />
                ) : entry.icon === 'gift' ? (
                  <Gift className="icon-20" />
                ) : (
                  <Flame className="icon-20" />
                )}
              </span>
              <span className="log-row__title">{entry.title}</span>
              <span className="log-row__detail">{entry.detail}</span>
              <span
                className={`log-row__delta ${entry.delta > 0 ? 'log-row__delta--plus' : 'log-row__delta--minus'}`}
              >
                {entry.delta > 0 ? (
                  <Plus className="icon-14" aria-hidden="true" />
                ) : (
                  <Minus className="icon-14" aria-hidden="true" />
                )}
                {Math.abs(entry.delta)}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
