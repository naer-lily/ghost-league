import type { CSSProperties } from 'react'
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

      <StandingsBoard view={view} onRefresh={() => void home.refetch()} />
    </div>
  )
}
