import * as Dialog from '@radix-ui/react-dialog'
import {
  Check,
  RotateCcw,
  UserCheck,
  UserPlus,
  Users,
  X,
} from 'lucide-react'
import { useSetFollow, useUserProfile } from '../api/queries'
import { Avatar } from './Avatar'
import { TierIcon } from './TierIcon'
import { describeApiError, formatNumber, tierMeta } from '../lib/home'
import { useUiStore } from '../store/useUiStore'
import styles from './UserProfileSheet.module.css'

interface UserProfileSheetProps {
  userId: string | null
  onOpenChange: (open: boolean) => void
}

function rankLabel(rank: number | null, groupSize: number): string {
  if (rank === null) return '—'
  return groupSize > 0 ? `第 ${rank} / ${groupSize} 名` : `第 ${rank} 名`
}

function comparisonLeader(
  leader: 'me' | 'them' | 'tie',
  diff: number,
  name: string,
): string {
  if (leader === 'tie') return '双方持平'
  return leader === 'me'
    ? `我领先 ${formatNumber(Math.abs(diff))} XP`
    : `${name}领先 ${formatNumber(Math.abs(diff))} XP`
}

export function UserProfileSheet({ userId, onOpenChange }: UserProfileSheetProps) {
  const open = Boolean(userId)
  const profile = useUserProfile(userId)
  const follow = useSetFollow()
  const notify = useUiStore((state) => state.notify)
  const data = profile.data

  function handleOpenChange(next: boolean) {
    if (!next) follow.reset()
    onOpenChange(next)
  }

  function toggleFollow() {
    if (!data || follow.isPending) return
    const nextFollow = !data.is_following
    follow.mutate(
      { userId: data.user_id, follow: nextFollow },
      {
        onSuccess: () => {
          notify(nextFollow ? '已关注。' : '已取消关注。')
        },
        onError: (error) => {
          notify(describeApiError(error), 'error')
        },
      },
    )
  }

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={styles.content}
          data-testid="user-profile-sheet"
        >
          <div className={styles.grabber} aria-hidden="true" />

          <div className={styles.head}>
            <span className={styles.headIcon} aria-hidden="true">
              <Users size={18} />
            </span>
            <div className={styles.headText}>
              <p className="eyebrow">选手资料</p>
              <Dialog.Title className={styles.title}>
                {data?.display_name ?? '正在读取资料'}
              </Dialog.Title>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className={styles.close}
                aria-label="关闭选手资料"
              >
                <X size={20} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </div>

          <Dialog.Description className={styles.description}>
            {data?.handle ? `@${data.handle}` : null}
          </Dialog.Description>

          {profile.isPending ? (
            <div className={styles.state} aria-busy="true">
              <span className={styles.stateIcon} aria-hidden="true">
                <Users size={24} />
              </span>
              <p className={styles.stateTitle}>正在读取资料</p>
            </div>
          ) : profile.isError ? (
            <div className={styles.state} role="alert">
              <span className={styles.stateIcon} aria-hidden="true">
                <Users size={24} />
              </span>
              <p className={styles.stateTitle}>资料没有加载出来</p>
              <p className={styles.stateCopy}>{describeApiError(profile.error)}</p>
              <button
                type="button"
                className="button button--secondary"
                onClick={() => void profile.refetch()}
                disabled={profile.isFetching}
              >
                <RotateCcw size={16} aria-hidden="true" />
                {profile.isFetching ? '正在重试…' : '重试'}
              </button>
            </div>
          ) : data ? (
            <>
              <div className={styles.identity}>
                <Avatar
                  src={data.avatar_url}
                  name={data.display_name}
                  size={68}
                  loading="eager"
                />
                <div className={styles.identityText}>
                  <p className={styles.name}>{data.display_name}</p>
                  <span className={styles.tier}>
                    <TierIcon
                      tier={data.tier}
                      theme="classic"
                      size={18}
                      decorative
                    />
                    {tierMeta(data.tier).label}
                  </span>
                </div>
              </div>

              <dl className={styles.stats}>
                <div>
                  <dt>本周 XP</dt>
                  <dd data-testid="profile-xp">{formatNumber(data.xp)}</dd>
                </div>
                <div>
                  <dt>组内排名</dt>
                  <dd data-testid="profile-rank">
                    {rankLabel(data.rank, data.group_size)}
                  </dd>
                </div>
                <div>
                  <dt>连胜</dt>
                  <dd data-testid="profile-streak">{data.streak}</dd>
                </div>
                <div>
                  <dt>关注</dt>
                  <dd data-testid="profile-following">
                    {formatNumber(data.following_count)}
                  </dd>
                </div>
                <div>
                  <dt>粉丝</dt>
                  <dd data-testid="profile-followers">
                    {formatNumber(data.followers_count)}
                  </dd>
                </div>
              </dl>

              {data.comparison ? (
                <section
                  className={styles.comparison}
                  aria-labelledby="profile-comparison-title"
                  data-testid="profile-comparison"
                >
                  <div className={styles.comparisonHead}>
                    <h3
                      id="profile-comparison-title"
                      className={styles.comparisonTitle}
                    >
                      我和他的本周对比
                    </h3>
                    <span
                      className={styles.comparisonLeader}
                      data-testid="profile-comparison-leader"
                    >
                      {comparisonLeader(
                        data.comparison.leader,
                        data.comparison.xp_diff,
                        data.display_name,
                      )}
                    </span>
                  </div>
                  <div className={styles.comparisonGrid}>
                    <div>
                      <small>我</small>
                      <strong data-testid="profile-comparison-me">
                        {formatNumber(data.comparison.viewer_xp)}
                      </strong>
                      <span>XP</span>
                    </div>
                    <div>
                      <small>差值</small>
                      <strong data-testid="profile-comparison-diff">
                        {data.comparison.xp_diff > 0
                          ? '+'
                          : data.comparison.xp_diff < 0
                            ? '-'
                            : ''}
                        {formatNumber(Math.abs(data.comparison.xp_diff))}
                      </strong>
                      <span>XP</span>
                    </div>
                    <div>
                      <small>{data.display_name}</small>
                      <strong data-testid="profile-comparison-them">
                        {formatNumber(data.comparison.target_xp)}
                      </strong>
                      <span>XP</span>
                    </div>
                  </div>
                </section>
              ) : null}

              {follow.error ? (
                <p className={styles.error} role="alert">
                  {describeApiError(follow.error)}
                </p>
              ) : null}

              <button
                type="button"
                className={[
                  'button',
                  'button--full',
                  data.is_following
                    ? 'button--secondary'
                    : 'button--primary',
                  styles.followButton,
                ].join(' ')}
                onClick={toggleFollow}
                disabled={follow.isPending}
                data-testid="profile-follow"
                aria-pressed={data.is_following}
              >
                {data.is_following ? (
                  <UserCheck size={18} aria-hidden="true" />
                ) : (
                  <UserPlus size={18} aria-hidden="true" />
                )}
                {follow.isPending
                  ? '正在处理…'
                  : data.is_following
                    ? '已关注'
                    : '关注'}
                {data.is_following && !follow.isPending ? (
                  <Check size={16} aria-hidden="true" />
                ) : null}
              </button>
            </>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
