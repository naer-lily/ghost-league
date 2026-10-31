import { AlertTriangle, RotateCcw } from 'lucide-react'
import styles from './PageState.module.css'

export function PageLoading() {
  return (
    <div className={styles.page} aria-busy="true">
      <span className="visually-hidden">正在读取本周联赛…</span>
      <div className={styles.column}>
        <div className={`${styles.hero} ${styles.bone}`} />
        <div className={styles.grid}>
          <div className={styles.boneCard} />
          <div className={styles.boneCard} />
        </div>
        <div className={styles.boneBoard} />
      </div>
    </div>
  )
}

interface PageErrorProps {
  message: string
  retrying: boolean
  onRetry: () => void
}

export function PageError({ message, retrying, onRetry }: PageErrorProps) {
  return (
    <div className={styles.page}>
      <div className={styles.column}>
        <section className={styles.errorCard} role="alert">
          <span className={styles.errorIcon} aria-hidden="true">
            <AlertTriangle size={30} />
          </span>
          <p className="eyebrow">本周数据</p>
          <h1>数据没有加载出来</h1>
          <p>{message}</p>
          <button
            type="button"
            className="button button--primary"
            onClick={onRetry}
            disabled={retrying}
          >
            <RotateCcw size={18} aria-hidden="true" />
            {retrying ? '正在重试…' : '重试'}
          </button>
        </section>
      </div>
    </div>
  )
}
