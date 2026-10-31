import type { LucideIcon } from 'lucide-react'
import { ArrowLeft, Compass } from 'lucide-react'
import { Link } from 'react-router-dom'
import styles from './PlaceholderPage.module.css'

interface PlaceholderPageProps {
  eyebrow: string
  title: string
  description: string
  icon: LucideIcon
}

export function PlaceholderPage({
  eyebrow,
  title,
  description,
  icon: Icon,
}: PlaceholderPageProps) {
  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <span className={styles.icon} aria-hidden="true">
          <Icon size={24} />
        </span>
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
        </div>
      </header>

      <section className={styles.card} aria-labelledby="placeholder-title">
        <span className={styles.compass} aria-hidden="true">
          <Compass size={30} />
        </span>
        <h2 id="placeholder-title">入口已接好，内容随后迁移</h2>
        <p>{description}</p>
        <p className={styles.note}>
          这一轮先完成新前端地基和真实首页，其他页面保持可导航，不展示占位数字。
        </p>
        <Link className="button button--secondary" to="/">
          <ArrowLeft size={18} aria-hidden="true" />
          回到首页
        </Link>
      </section>
    </div>
  )
}
