import { Trophy } from 'lucide-react'
import { group } from '../data'
import { useApp } from '../store'
import { WeekPath } from '../components/WeekPath'

export function HomePage() {
  const { navigate } = useApp()

  return (
    <div className="home-page" data-testid="home-page">
      <button
        type="button"
        className="unit-banner"
        aria-label={`${group.tier}联赛，第 1 周，查看小组榜`}
        onClick={() => navigate('league')}
      >
        <span className="unit-banner__text">青铜联赛 · 第 1 周</span>
        <span className="unit-banner__trophy" aria-hidden="true">
          <Trophy className="icon-22" />
        </span>
      </button>

      <WeekPath />
    </div>
  )
}
