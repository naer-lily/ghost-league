import { CalendarPlus, Flame, Gift, Minus, Plus, Sparkles, Zap } from 'lucide-react'
import { tips } from '../data'
import { useApp } from '../store'
import { InfoTip } from '../components/InfoTip'

export function EmbersPage() {
  const { embers, emberLog, repairDays, openSheet } = useApp()

  return (
    <div className="embers-page" data-testid="embers-page">
      <div className="embers-grid">
        <div className="embers-col">
          <section className="card embers-hero" aria-labelledby="embers-balance-title">
            <div className="embers-hero__top">
              <div>
                <p className="eyebrow">余烬余额</p>
                <h2 className="embers-hero__title" id="embers-balance-title">
                  <Flame className="icon-32" aria-hidden="true" />
                  <span data-testid="embers-balance">{embers}</span>
                  <span className="embers-hero__unit">枚</span>
                </h2>
              </div>
              <InfoTip {...tips.embers} />
            </div>
            <p className="embers-hero__rule">只补签。不加 XP，不改名次。</p>
            <div className="embers-hero__actions">
              <button
                type="button"
                className="button button--primary"
                onClick={() => openSheet({ kind: 'repair' })}
                disabled={embers < 1 || repairDays.length === 0}
                data-testid="embers-repair-button"
              >
                <CalendarPlus className="icon-20" aria-hidden="true" />
                去补签
              </button>
              <span className="caption">
                {embers < 1 ? '余烬不够。再攒 2,000 XP。' : `${repairDays.length} 个日子可补`}
              </span>
            </div>
          </section>

          <section className="card earn-card" aria-labelledby="earn-title">
            <div className="card-head">
              <div>
                <p className="eyebrow">获取规则</p>
                <h2 className="card-title" id="earn-title">
                  火里怎么长出余烬
                </h2>
              </div>
              <Sparkles className="icon-24 icon--gold" aria-hidden="true" />
            </div>
            <ul className="rule-list">
              <li>
                <span className="rule-list__icon" aria-hidden="true">
                  <Zap className="icon-20" />
                </span>
                <span>
                  <strong>每满 2,000 XP</strong>
                  <span>本周有效 XP 每满 2,000，得 1 枚。</span>
                </span>
                <span className="rule-list__gain">+1</span>
              </li>
              <li>
                <span className="rule-list__icon" aria-hidden="true">
                  <Gift className="icon-20" />
                </span>
                <span>
                  <strong>周日结算</strong>
                  <span>留在小组里，就有一份结算奖励。</span>
                </span>
                <span className="rule-list__gain">+N</span>
              </li>
            </ul>
          </section>

          <section className="card repair-entry" aria-labelledby="repair-entry-title">
            <div className="card-head">
              <div>
                <p className="eyebrow">补签入口</p>
                <h2 className="card-title" id="repair-entry-title">
                  断了一天？
                </h2>
              </div>
              <span className="chip chip--mint">1 天 = 1 枚</span>
            </div>
            <p className="card-copy">选一天，用 1 枚余烬把火焰续上。和首页是同一个入口。</p>
            <button
              type="button"
              className="button button--secondary"
              onClick={() => openSheet({ kind: 'repair' })}
              disabled={embers < 1 || repairDays.length === 0}
            >
              <CalendarPlus className="icon-20" aria-hidden="true" />
              选择日期
            </button>
          </section>
        </div>

        <div className="embers-col">
          <section className="card ember-log" aria-labelledby="ember-log-title">
            <div className="card-head">
              <div>
                <p className="eyebrow">历史消耗</p>
                <h2 className="card-title" id="ember-log-title">
                  余烬流水
                </h2>
              </div>
              <span className="caption">近 7 天</span>
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
                  <span className="log-row__text">
                    <span className="log-row__title">{entry.title}</span>
                    <span className="log-row__detail">{entry.detail}</span>
                  </span>
                  <span
                    className={`log-row__delta ${entry.delta > 0 ? 'log-row__delta--plus' : 'log-row__delta--minus'}`}
                  >
                    {entry.delta > 0 ? (
                      <Plus className="icon-16" aria-hidden="true" />
                    ) : (
                      <Minus className="icon-16" aria-hidden="true" />
                    )}
                    {Math.abs(entry.delta)}
                  </span>
                </li>
              ))}
            </ul>
            <p className="card-foot__hint">补签是唯一的消耗。没有商店，也不卖余烬。</p>
          </section>
        </div>
      </div>
    </div>
  )
}
