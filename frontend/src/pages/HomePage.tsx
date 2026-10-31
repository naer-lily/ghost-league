import type { CSSProperties } from 'react'
import { useHomeSnapshot } from '../api/queries'
import { GoalRing } from '../components/GoalRing'
import { PageError, PageLoading } from '../components/PageState'
import { PlayerHeader } from '../components/PlayerHeader'
import { StandingsBoard } from '../components/StandingsBoard'
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
  const ringColor = view.checkedIn ? 'var(--green)' : view.tier.color

  return (
    <div className={styles.page}>
      <PlayerHeader view={view} />

      <section
        className={styles.today}
        style={style}
        aria-label="今日 XP"
        data-flat="true"
      >
        <GoalRing
          value={view.todayXp}
          goal={view.goalXp}
          color={ringColor}
          size={180}
          stroke={13}
        />
      </section>

      <StandingsBoard view={view} onRefresh={() => void home.refetch()} />
    </div>
  )
}
