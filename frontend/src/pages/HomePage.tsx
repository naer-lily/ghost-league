import { ChevronRight, Swords } from 'lucide-react'
import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { useHomeSnapshot } from '../api/queries'
import { PageError, PageLoading } from '../components/PageState'
import { PlayerHeader } from '../components/PlayerHeader'
import { StandingsBoard } from '../components/StandingsBoard'
import { TodayProgress } from '../components/TodayProgress'
import {
  buildHomeView,
  describeApiError,
  tierStyleVars,
} from '../lib/home'
import styles from './HomePage.module.css'

export function HomePage() {
  const home = useHomeSnapshot()

  if (home.isPending) return <PageLoading />

  if (home.isError) {
    return (
      <PageError
        message={describeApiError(home.error)}
        retrying={home.isFetching}
        onRetry={() => void home.refetch()}
      />
    )
  }

  if (!home.data) return <PageLoading />

  const view = buildHomeView(home.data)
  const style = tierStyleVars(view.tier) as CSSProperties

  return (
    <div className={styles.page}>
      <PlayerHeader view={view} />

      <div className={styles.today} style={style} data-flat="true">
        <TodayProgress
          todayXp={view.todayXp}
          todaySeconds={view.todaySeconds}
          updatedAt={view.todayUpdatedAt}
          tier={view.tier}
        />
      </div>

      <Link className={styles.rivalEntry} to="/rival" data-testid="rival-entry">
        <span className={styles.rivalIcon} aria-hidden="true">
          <Swords size={20} />
        </span>
        <span className={styles.rivalCopy}>
          <strong>宿敌</strong>
          <small>本周追一个对手，实时对撞。</small>
        </span>
        <ChevronRight size={18} aria-hidden="true" />
      </Link>

      <StandingsBoard view={view} onRefresh={() => void home.refetch()} />
    </div>
  )
}
