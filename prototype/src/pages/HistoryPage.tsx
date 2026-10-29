import { useEffect, useState } from 'react'
import { ChevronRight, History } from 'lucide-react'
import { tips, weeks } from '../data'
import { useApp } from '../store'
import { EmptyState } from '../components/EmptyState'
import { InfoTip } from '../components/InfoTip'

function HistorySkeleton() {
  return (
    <div className="history-skeleton" aria-busy="true" aria-label="历史加载中">
      {[0, 1, 2].map((row) => (
        <div key={row} className="skeleton-row">
          <span className="skeleton skeleton--rank" />
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

  return (
    <div className="history-page" data-testid="history-page">
      <div className="section-head">
        <h2 className="section-head__title">往期</h2>
        <InfoTip {...tips.history} side="bottom" />
      </div>

      {loading ? (
        <section className="card history-board" aria-label="已结束的周">
          <HistorySkeleton />
        </section>
      ) : previewEmpty ? (
        <section className="card history-board">
          <EmptyState
            icon={History}
            title="还没有结束的周"
            body="等周日结算。"
          />
        </section>
      ) : (
        <section className="card history-board" aria-labelledby="history-list-title">
          <h2 className="visually-hidden" id="history-list-title">
            已结束的周
          </h2>
          <ul className="week-list">
            {weeks.map((week) => (
              <li key={week.id}>
                <button
                  type="button"
                  className="week-row"
                  onClick={() => openSheet({ kind: 'week', weekId: week.id })}
                  aria-label={`${week.label}，第 ${week.rank} 名，${week.xp} XP，查看详情`}
                >
                  <span className="week-row__rank" aria-hidden="true">
                    <span className="week-row__hash">#</span>
                    {week.rank}
                  </span>
                  <span className="week-row__body">
                    <span className="week-row__title">
                      <img src={week.tierAsset} alt="" width={22} height={22} />
                      {week.label}
                    </span>
                    <span className="week-row__meta">{week.range}</span>
                  </span>
                  <span className="week-row__xp">
                    {week.xp.toLocaleString('en-US')}
                    <span className="week-row__unit">XP</span>
                  </span>
                  <ChevronRight className="week-row__chevron" aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

    </div>
  )
}
