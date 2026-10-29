import { useEffect, useState } from 'react'
import { CalendarDays, ChevronRight, History, Star, Trophy } from 'lucide-react'
import { group, weeks } from '../data'
import { useApp } from '../store'
import { EmptyState } from '../components/EmptyState'

function HistorySkeleton() {
  return (
    <div className="history-skeleton" aria-busy="true" aria-label="历史加载中">
      {[0, 1, 2].map((row) => (
        <div key={row} className="skeleton-row">
          <span className="skeleton skeleton--avatar" />
          <span className="skeleton-row__text">
            <span className="skeleton skeleton--line-lg" />
            <span className="skeleton skeleton--line-sm" />
          </span>
          <span className="skeleton skeleton--value" />
        </div>
      ))}
    </div>
  )
}

export function HistoryPage() {
  const { openSheet } = useApp()
  const params = new URLSearchParams(window.location.search)
  const previewEmpty = params.get('history') === 'empty'
  const holdLoading = params.get('history') === 'loading'
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (holdLoading) return
    const id = window.setTimeout(() => setLoading(false), 650)
    return () => window.clearTimeout(id)
  }, [holdLoading])

  const shownWeeks = previewEmpty ? [] : weeks
  const totalXp = shownWeeks.reduce((sum, week) => sum + week.xp, 0)
  const best = shownWeeks.length ? Math.min(...shownWeeks.map((week) => week.rank)) : null

  return (
    <div className="history-page" data-testid="history-page">
      <div className="history-layout">
        <aside className="history-aside">
          <section className="card history-summary" aria-labelledby="history-summary-title">
            <p className="eyebrow">赛季档案</p>
            <h2 className="card-title" id="history-summary-title">
              走过 {shownWeeks.length} 周
            </h2>
            {loading ? (
              <div className="history-summary__skeleton" aria-hidden="true">
                <span className="skeleton skeleton--score" />
                <span className="skeleton skeleton--line-lg" />
              </div>
            ) : (
              <>
                <div className="history-summary__score">
                  <span>{totalXp.toLocaleString('en-US')}</span>
                  <span className="history-summary__unit">XP</span>
                </div>
                <dl className="history-summary__stats">
                  <div>
                    <dt>最佳名次</dt>
                    <dd>{best === null ? '还没上场' : `#${best}`}</dd>
                  </div>
                  <div>
                    <dt>当前段位</dt>
                    <dd>{group.tier}</dd>
                  </div>
                </dl>
              </>
            )}
            <p className="history-summary__note">
              <CalendarDays className="icon-16" aria-hidden="true" />
              第 44 周正在进行，周日结算。
            </p>
          </section>
        </aside>

        <div className="history-main">
          {loading ? (
            <section className="card history-board" aria-label="已结束的周">
              <div className="card-head">
                <div>
                  <p className="eyebrow">已结束的周</p>
                  <h2 className="card-title">翻旧账</h2>
                </div>
              </div>
              <HistorySkeleton />
            </section>
          ) : previewEmpty ? (
            <section className="card history-board">
              <EmptyState
                icon={History}
                title="还没有结束的周"
                body="第一周还在跑。等周日结算，再来翻旧账。"
              />
            </section>
          ) : (
            <section className="card history-board" aria-labelledby="history-list-title">
              <div className="card-head">
                <div>
                  <p className="eyebrow">已结束的周</p>
                  <h2 className="card-title" id="history-list-title">
                    翻旧账
                  </h2>
                </div>
                <span className="caption">点一周看详情</span>
              </div>
              <ul className="week-list">
                {weeks.map((week) => (
                  <li key={week.id}>
                    <button
                      type="button"
                      className="week-row"
                      onClick={() => openSheet({ kind: 'week', weekId: week.id })}
                      aria-label={`${week.label}，第 ${week.rank} 名，${week.xp} XP，查看详情`}
                    >
                      <span className="week-row__badge" aria-hidden="true">
                        {week.label.replace('第 ', 'W').replace(' 周', '')}
                      </span>
                      <span className="week-row__body">
                        <span className="week-row__title">{week.label}</span>
                        <span className="week-row__meta">
                          {week.range} · {group.tier} {group.name}
                        </span>
                      </span>
                      <span className="week-row__result">
                        <span className={`chip ${week.resultTone === 'up' ? 'chip--mint' : 'chip--quiet'}`}>
                          {week.resultTone === 'up' ? (
                            <Trophy className="icon-16" aria-hidden="true" />
                          ) : (
                            <Star className="icon-16" aria-hidden="true" />
                          )}
                          {week.result}
                        </span>
                      </span>
                      <span className="week-row__score">
                        <span className="week-row__rank">#{week.rank}</span>
                        <span className="week-row__xp">{week.xp.toLocaleString('en-US')} XP</span>
                      </span>
                      <ChevronRight className="icon-20 week-row__chevron" aria-hidden="true" />
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
