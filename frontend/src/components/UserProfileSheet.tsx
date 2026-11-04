import * as Dialog from '@radix-ui/react-dialog'
import {
  ArrowLeft,
  Check,
  Flame,
  Medal,
  RotateCcw,
  Sparkles,
  Trophy,
  UserCheck,
  UserPlus,
  Users,
  Zap,
} from 'lucide-react'
import { useId } from 'react'
import type { RecentXp } from '../api/types'
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

function seven(values: number[]): number[] {
  return Array.from({ length: 7 }, (_, index) => values[index] ?? 0)
}

function chartCeiling(data: RecentXp): number {
  const peak = Math.max(0, ...seven(data.target), ...seven(data.viewer))
  return peak > 0 ? Math.ceil(peak / 50) * 50 : 100
}

function chartPoints(values: number[], ceiling: number): string {
  const left = 40
  const right = 326
  const top = 14
  const bottom = 144
  const width = right - left
  const height = bottom - top
  return seven(values)
    .map((value, index) => {
      const x = left + (width * index) / 6
      const y = bottom - (Math.max(0, value) / ceiling) * height
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function RecentXpChart({ data }: { data: RecentXp }) {
  const headingId = useId()
  const ceiling = chartCeiling(data)
  const labels = Array.from(
    { length: 7 },
    (_, index) => data.labels[index] ?? '',
  )
  const targetTotal = seven(data.target).reduce((total, value) => total + value, 0)
  const viewerTotal = seven(data.viewer).reduce((total, value) => total + value, 0)
  const top = 14
  const bottom = 144
  const plotHeight = bottom - top
  const gridValues = Array.from(
    { length: 4 },
    (_, index) => (ceiling * index) / 3,
  )
  const xAt = (index: number) => 40 + ((326 - 40) * index) / 6

  return (
    <section className={styles.chartCard} aria-labelledby={headingId}>
      <div className={styles.sectionHead}>
        <h2 id={headingId} className={styles.sectionTitle}>
          最近 7 天
        </h2>
        <span className={styles.sectionHint}>每天 XP</span>
      </div>
      <svg
        className={styles.chart}
        viewBox="0 0 340 180"
        role="img"
        aria-label="最近 7 天每天 XP 对比"
        data-testid="profile-recent-chart"
      >
        {gridValues.map((value, index) => {
          const y = bottom - (value / ceiling) * plotHeight
          return (
            <g key={`grid-${index}`}>
              <line
                x1="40"
                x2="326"
                y1={y}
                y2={y}
                className={styles.gridLine}
              />
              <text
                x="33"
                y={y + 4}
                textAnchor="end"
                className={styles.axisLabel}
              >
                {formatNumber(Math.round(value))}
              </text>
            </g>
          )
        })}
        {labels.map((label, index) => (
          <text
            key={`label-${index}`}
            x={xAt(index)}
            y="168"
            textAnchor="middle"
            className={styles.axisLabel}
          >
            {label}
          </text>
        ))}
        <polyline
          points={chartPoints(data.viewer, ceiling)}
          className={styles.viewerLine}
          data-testid="profile-recent-viewer"
        />
        <polyline
          points={chartPoints(data.target, ceiling)}
          className={styles.targetLine}
          data-testid="profile-recent-target"
        />
        {seven(data.viewer).map((value, index) => (
          <circle
            key={`viewer-${index}`}
            cx={xAt(index)}
            cy={bottom - (Math.max(0, value) / ceiling) * plotHeight}
            r="4"
            className={styles.viewerPoint}
          />
        ))}
        {seven(data.target).map((value, index) => (
          <circle
            key={`target-${index}`}
            cx={xAt(index)}
            cy={bottom - (Math.max(0, value) / ceiling) * plotHeight}
            r="4"
            className={styles.targetPoint}
          />
        ))}
      </svg>
      <div className={styles.legend}>
        <div className={styles.legendRow}>
          <span className={styles.legendName}>
            <span className={`${styles.legendDot} ${styles.legendDotTarget}`} />
            他
          </span>
          <strong>{formatNumber(targetTotal)} XP</strong>
        </div>
        <div className={styles.legendRow}>
          <span className={styles.legendName}>
            <span className={`${styles.legendDot} ${styles.legendDotViewer}`} />
            你
          </span>
          <strong>{formatNumber(viewerTotal)} XP</strong>
        </div>
      </div>
    </section>
  )
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

  const loadout = data
    ? [
        data.equipped_title ? `称号 · ${data.equipped_title}` : null,
        data.frame ? `边框 · ${data.frame}` : null,
        data.backdrop ? `背景 · ${data.backdrop}` : null,
        data.badge_accent ? `徽章 · ${data.badge_accent}` : null,
      ].filter((item): item is string => Boolean(item))
    : []

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={styles.content}
          aria-describedby={undefined}
          data-testid="user-profile-sheet"
        >
          <header className={styles.topbar}>
            <Dialog.Close asChild>
              <button type="button" className={styles.back} aria-label="返回">
                <ArrowLeft size={22} aria-hidden="true" />
              </button>
            </Dialog.Close>
            <Dialog.Title className={styles.topTitle}>
              {data?.display_name ?? '选手资料'}
            </Dialog.Title>
            <span className={styles.topSpacer} aria-hidden="true" />
          </header>

          <div className={styles.scroll}>
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
                <p className={styles.stateCopy}>
                  {describeApiError(profile.error)}
                </p>
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
                <section className={styles.hero} aria-label="选手身份">
                  <Avatar
                    src={data.avatar_url}
                    name={data.display_name}
                    size={144}
                    className={styles.avatarRing ?? ''}
                    loading="eager"
                  />
                  <span className={styles.tierBadge}>
                    <TierIcon
                      tier={data.tier}
                      theme="classic"
                      size={18}
                      decorative
                    />
                    {data.tier ? tierMeta(data.tier).label : '暂无段位'}
                  </span>
                  {data.handle ? (
                    <p className={styles.handle} data-testid="profile-handle">
                      @{data.handle}
                    </p>
                  ) : null}
                </section>

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
                    styles.followButton,
                    data.is_following ? styles.following : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onClick={toggleFollow}
                  disabled={follow.isPending}
                  data-testid="profile-follow"
                  aria-pressed={data.is_following}
                >
                  {data.is_following ? (
                    <UserCheck size={19} aria-hidden="true" />
                  ) : (
                    <UserPlus size={19} aria-hidden="true" />
                  )}
                  {follow.isPending
                    ? '正在处理…'
                    : data.is_following
                      ? '已关注'
                      : '关注'}
                  {data.is_following && !follow.isPending ? (
                    <Check size={17} aria-hidden="true" />
                  ) : null}
                </button>

                <dl className={styles.stats}>
                  <div>
                    <dt>本周 XP</dt>
                    <dd data-testid="profile-xp">{formatNumber(data.xp)}</dd>
                  </div>
                  <div>
                    <dt>战力</dt>
                    <dd data-testid="profile-power">
                      {data.power === null ? '—' : formatNumber(data.power)}
                    </dd>
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

                {data.recent_xp ? (
                  <RecentXpChart data={data.recent_xp} />
                ) : null}

                <section
                  className={styles.overview}
                  aria-labelledby="profile-overview-title"
                >
                  <div className={styles.sectionHead}>
                    <h2
                      id="profile-overview-title"
                      className={styles.sectionTitle}
                    >
                      概览
                    </h2>
                  </div>
                  <div className={styles.overviewGrid}>
                    <div className={styles.overviewCell}>
                      <span className={styles.overviewLabel}>
                        <Flame size={15} aria-hidden="true" />
                        连胜
                      </span>
                      <strong data-testid="profile-streak">
                        {data.streak} 天
                      </strong>
                    </div>
                    <div className={styles.overviewCell}>
                      <span className={styles.overviewLabel}>
                        <Zap size={15} aria-hidden="true" />
                        本周 XP
                      </span>
                      <strong data-testid="profile-overview-xp">
                        {formatNumber(data.xp)}
                      </strong>
                    </div>
                    <div className={styles.overviewCell}>
                      <span className={styles.overviewLabel}>
                        <Trophy size={15} aria-hidden="true" />
                        段位
                      </span>
                      <strong
                        className={styles.overviewTier}
                        data-testid="profile-tier"
                      >
                        <TierIcon
                          tier={data.tier}
                          theme="classic"
                          size={18}
                          decorative
                        />
                        {data.tier ? tierMeta(data.tier).label : '—'}
                      </strong>
                    </div>
                    <div className={styles.overviewCell}>
                      <span className={styles.overviewLabel}>
                        <Medal size={15} aria-hidden="true" />
                        组内排名
                      </span>
                      <strong data-testid="profile-rank">
                        {rankLabel(data.rank, data.group_size)}
                      </strong>
                    </div>
                  </div>
                </section>

                {loadout.length > 0 ? (
                  <section
                    className={styles.loadout}
                    aria-labelledby="profile-loadout-title"
                    data-testid="profile-loadout"
                  >
                    <div className={styles.sectionHead}>
                      <h2
                        id="profile-loadout-title"
                        className={styles.sectionTitle}
                      >
                        装备
                      </h2>
                    </div>
                    <div className={styles.loadoutRow}>
                      {loadout.map((item) => (
                        <span key={item} className={styles.loadoutChip}>
                          <Sparkles size={14} aria-hidden="true" />
                          {item}
                        </span>
                      ))}
                    </div>
                  </section>
                ) : null}
              </>
            ) : null}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
