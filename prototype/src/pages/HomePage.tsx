import { Trophy } from 'lucide-react'
import { group, tips } from '../data'
import { useApp } from '../store'
import { WeekPath } from '../components/WeekPath'
import { EmberSprite } from '../components/EmberSprite'
import { InfoTip } from '../components/InfoTip'

export function HomePage() {
  const { navigate } = useApp()

  return (
    <div className="home-page" data-testid="home-page">
      <div className="unit-banner">
        <button
          type="button"
          className="unit-banner__main"
          aria-label={`${group.tier}联赛，第 1 周，查看小组榜`}
          onClick={() => navigate('league')}
        >
          <span className="unit-banner__trophy" aria-hidden="true">
            <Trophy className="icon-28" />
          </span>
          <span className="unit-banner__text">
            {group.tier}联赛 · 第 1 周
          </span>
        </button>
        <span className="unit-banner__tip">
          <InfoTip {...tips.league} side="bottom" />
        </span>
      </div>

      <div className="path-buddy" aria-hidden="false">
        <span className="path-buddy__bubble">今天也来点火！</span>
        <EmberSprite size={108} label="余烬精灵" aura />
      </div>

      <WeekPath />
    </div>
  )
}
