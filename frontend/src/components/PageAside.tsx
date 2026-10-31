import { CalendarDays, Flame, Sparkles, Timer, Users } from 'lucide-react'
import { formatNumber, type HomeView } from '../lib/home'
import styles from './PageAside.module.css'

interface PageAsideProps {
  view: HomeView
}

export function PageAside({ view }: PageAsideProps) {
  return (
    <aside className={styles.aside} aria-label="本周概览">
      <section className={styles.card}>
        <div className={styles.head}>
          <span className={styles.icon} aria-hidden="true">
            <CalendarDays size={18} />
          </span>
          <div>
            <p className="eyebrow">本周</p>
            <h2>节奏</h2>
          </div>
        </div>
        <dl className={styles.stats}>
          <div>
            <dt>小组</dt>
            <dd>{view.groupLabel}</dd>
          </div>
          <div>
            <dt>组内人数</dt>
            <dd>
              <Users size={14} aria-hidden="true" />
              {view.groupSize || '—'} 人
            </dd>
          </div>
          <div>
            <dt>本周累计</dt>
            <dd>{formatNumber(view.weekXp)} XP</dd>
          </div>
          <div>
            <dt>最长连胜</dt>
            <dd>
              <Flame size={14} aria-hidden="true" />
              {view.longestStreak} 天
            </dd>
          </div>
          <div>
            <dt>余烬</dt>
            <dd>
              <Sparkles size={14} aria-hidden="true" />
              {view.embersBalance} / {view.embersCap}
            </dd>
          </div>
        </dl>
      </section>

      <section className={styles.card}>
        <div className={styles.head}>
          <span className={styles.icon} aria-hidden="true">
            <Timer size={18} />
          </span>
          <div>
            <p className="eyebrow">赛程</p>
            <h2>本轮</h2>
          </div>
        </div>
        <dl className={styles.stats}>
          <div>
            <dt>开始</dt>
            <dd>{view.weekStartLabel}</dd>
          </div>
          <div>
            <dt>结算</dt>
            <dd className={styles.highlight}>{view.settlementLabel}</dd>
          </div>
        </dl>
      </section>

      <section className={styles.ruleCard} aria-labelledby="rule-title">
        <p className="eyebrow" id="rule-title">
          计分
        </p>
        <p>
          每 6 秒{view.activityLabel} = 1 XP，每日 {view.goalXp} XP 完成目标。
        </p>
        <p className={styles.muted}>
          小组按本周 XP 排名，组内前 3 名显示在首页榜单。
        </p>
      </section>
    </aside>
  )
}
