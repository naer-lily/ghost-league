import { RotateCcw, Timer, Trophy, UserPlus, Users } from 'lucide-react'
import { useState } from 'react'
import { useFriendsStandings, useHomeSnapshot } from '../api/queries'
import type { FriendSummary, StandingRow } from '../api/types'
import { PageError, PageLoading } from '../components/PageState'
import { PlayerHeader } from '../components/PlayerHeader'
import { StandingList } from '../components/StandingList'
import {
  buildHomeView,
  describeApiError,
  formatSettlementShort,
} from '../lib/home'
import styles from './LeaguePage.module.css'

type BoardTab = 'group' | 'friends'

const TABS: ReadonlyArray<{ id: BoardTab; label: string }> = [
  { id: 'group', label: '小组' },
  { id: 'friends', label: '好友' },
]

function friendRows(members: FriendSummary[], myId: string): StandingRow[] {
  return members
    .filter((member) => member.user_id !== myId)
    .sort((left, right) => {
      if (right.xp !== left.xp) return right.xp - left.xp
      return left.user_id.localeCompare(right.user_id)
    })
    .map((member, index) => ({
      rank: index + 1,
      user_id: member.user_id,
      display_name: member.display_name,
      avatar_url: member.avatar_url,
      is_me: false,
      xp: member.xp,
      power: null,
      checkin: member.checkin,
      streak: member.streak,
      title: member.equipped_title,
      frame: member.frame,
      frame_id: null,
      backdrop: member.backdrop,
    }))
}

export function LeaguePage() {
  const home = useHomeSnapshot()
  const [tab, setTab] = useState<BoardTab>('group')
  const friends = useFriendsStandings(tab === 'friends')

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
  const rows = home.data.standings.standings
  const myId = home.data.profile.user_id
  const followed = friends.data ? friendRows(friends.data.members, myId) : []
  const isFriends = tab === 'friends'

  return (
    <div className={styles.page}>
      <PlayerHeader view={view} />

      <div className={styles.groupBar} data-flat="true">
        <span
          className={styles.settle}
          aria-label={`结算倒计时：${view.settlementLabel}`}
        >
          <Timer size={15} aria-hidden="true" />
          {formatSettlementShort(home.data.status.next_settlement_at)}
        </span>
      </div>

      <div
        className={styles.tabs}
        role="tablist"
        aria-label="榜单类型"
      >
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={[
              styles.tab,
              tab === item.id ? styles.tabActive : '',
            ]
              .filter(Boolean)
              .join(' ')}
            data-testid={`board-tab-${item.id}`}
            onClick={() => setTab(item.id)}
          >
            {item.id === 'group' ? (
              <Trophy size={15} aria-hidden="true" />
            ) : (
              <Users size={15} aria-hidden="true" />
            )}
            {item.label}
          </button>
        ))}
      </div>

      <section
        className={styles.board}
        aria-labelledby="league-board"
        data-flat="true"
      >
        <div className={styles.boardHead}>
          <div className={styles.boardTitle}>
            <span className={styles.boardIcon} aria-hidden="true">
              {isFriends ? <Users size={18} /> : <Trophy size={18} />}
            </span>
            <h2 id="league-board">{isFriends ? '好友榜' : '小组榜'}</h2>
          </div>
        </div>

        {isFriends ? (
          friends.isPending ? (
            <div className={styles.empty} aria-busy="true">
              <span className="visually-hidden">正在读取好友榜…</span>
              <span className={styles.emptyIcon} aria-hidden="true">
                <Users size={28} />
              </span>
              <p className={styles.emptyTitle}>正在读取好友榜</p>
            </div>
          ) : friends.isError ? (
            <div className={styles.empty}>
              <span className={styles.emptyIcon} aria-hidden="true">
                <Users size={28} />
              </span>
              <p className={styles.emptyTitle}>
                {describeApiError(friends.error)}
              </p>
              <button
                type="button"
                className="button button--secondary"
                onClick={() => void friends.refetch()}
                disabled={friends.isFetching}
              >
                <RotateCcw size={16} aria-hidden="true" />
                {friends.isFetching ? '正在重试…' : '重试'}
              </button>
            </div>
          ) : followed.length === 0 ? (
            <div className={styles.empty} data-testid="friends-empty">
              <span className={styles.emptyIcon} aria-hidden="true">
                <UserPlus size={28} />
              </span>
              <p className={styles.emptyTitle}>还没有关注的好友</p>
              <p className={styles.emptyCopy}>
                关注其他选手后，他们才会出现在好友榜；这里不会用假数据填充。
              </p>
            </div>
          ) : (
            <StandingList rows={followed} label="好友榜" showPower={false} />
          )
        ) : rows.length === 0 ? (
          <div className={styles.empty}>
            <span className={styles.emptyIcon} aria-hidden="true">
              <Users size={28} />
            </span>
            <p className={styles.emptyTitle}>
              {view.hasGroup ? '小组榜还没有成绩' : '本周还没有小组'}
            </p>
            <button
              type="button"
              className="button button--secondary"
              onClick={() => void home.refetch()}
            >
              刷新
            </button>
          </div>
        ) : (
          <StandingList rows={rows} label="完整小组榜" />
        )}
      </section>
    </div>
  )
}
