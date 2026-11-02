import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useId } from 'react'
import type { Star } from '../api/types'
import {
  formatAcquiredAt,
  formatSeasonKey,
  rarityColor,
  rarityLabel,
} from '../lib/shop'
import { StarArt } from './StarArt'
import styles from './StarDialog.module.css'

interface StarDialogProps {
  reveal: Star | null
  detail: Star | null
  onClose: () => void
}

export function StarDialog({ reveal, detail, onClose }: StarDialogProps) {
  const titleId = useId()
  const descriptionId = useId()
  const star = reveal ?? detail
  const mode = reveal ? 'reveal' : 'detail'
  const open = Boolean(star)

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        {star ? (
          <Dialog.Content
            className={styles.content}
            aria-labelledby={titleId}
            aria-describedby={descriptionId}
            data-testid={mode === 'reveal' ? 'star-reveal' : 'star-detail'}
          >
            <div className={styles.head}>
              <div className={styles.headText}>
                <p className="eyebrow">
                  {mode === 'reveal' ? '抽取结果' : '星星详情'}
                </p>
                <Dialog.Title id={titleId} className={styles.title}>
                  {mode === 'reveal' ? '获得新星' : star.name}
                </Dialog.Title>
              </div>
              <Dialog.Close asChild>
                <button
                  type="button"
                  className={styles.close}
                  aria-label="关闭星星对话框"
                >
                  <X size={20} aria-hidden="true" />
                </button>
              </Dialog.Close>
            </div>

            <Dialog.Description id={descriptionId} className={styles.description}>
              {mode === 'reveal'
                ? '这颗星已经放进物品栏，收下后可以随时查看。'
                : `${star.type_label} · ${star.rarity_label}`}
            </Dialog.Description>

            <div className={styles.art}>
              <StarArt star={star} className={styles.artFrame} />
            </div>

            <div className={styles.summary}>
              <h3 className={styles.starName}>{star.name}</h3>
              <p className={styles.starMeta}>
                <span>{star.type_label}</span>
                <span aria-hidden="true">·</span>
                <span
                  className={styles.rarity}
                  style={{ color: rarityColor(star.rarity) }}
                >
                  {star.rarity_label || rarityLabel(star.rarity)}
                </span>
                {star.kind === 'seasonal' ? (
                  <span className={styles.season}>
                    {formatSeasonKey(star.season_key) || '季节限定'}
                  </span>
                ) : null}
              </p>
              {mode === 'reveal' ? (
                <p className={styles.catalog}>
                  目录编号 {star.catalog_code || '—'}
                </p>
              ) : null}
            </div>

            {mode === 'detail' ? (
              <dl className={styles.details}>
                <div className={styles.detailRow}>
                  <dt>目录编号</dt>
                  <dd>{star.catalog_code || '—'}</dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>获得时间</dt>
                  <dd>{formatAcquiredAt(star.acquired_at)}</dd>
                </div>
                <div className={styles.detailRow}>
                  <dt>季节</dt>
                  <dd>{formatSeasonKey(star.season_key) || '常驻'}</dd>
                </div>
              </dl>
            ) : (
              <div className={styles.revealActions}>
                <Dialog.Close asChild>
                  <button type="button" className="button button--primary button--full">
                    收下
                  </button>
                </Dialog.Close>
              </div>
            )}
          </Dialog.Content>
        ) : null}
      </Dialog.Portal>
    </Dialog.Root>
  )
}
