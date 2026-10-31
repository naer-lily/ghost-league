import * as Dialog from '@radix-ui/react-dialog'
import type { UseQueryResult } from '@tanstack/react-query'
import { Check, LogOut, X } from 'lucide-react'
import { useUpdateIconTheme } from '../api/queries'
import type { HomeSnapshot } from '../api/types'
import { describeApiError } from '../lib/home'
import { playClick } from '../lib/sound'
import { useSignOut } from '../store/useSession'
import { useUiStore } from '../store/useUiStore'
import styles from './SettingsDialog.module.css'

const THEMES = [
  { key: 'classic', label: '经典', hint: '线性描边' },
  { key: 'material', label: 'Material', hint: '实心描边' },
] as const

interface SettingsDialogProps {
  home: UseQueryResult<HomeSnapshot, Error>
}

export function SettingsDialog({ home }: SettingsDialogProps) {
  const open = useUiStore((state) => state.settingsOpen)
  const setOpen = useUiStore((state) => state.setSettingsOpen)
  const soundEnabled = useUiStore((state) => state.soundEnabled)
  const toggleSound = useUiStore((state) => state.toggleSound)
  const notify = useUiStore((state) => state.notify)
  const updateTheme = useUpdateIconTheme()
  const signOut = useSignOut()

  const profile = home.data?.profile
  const currentTheme = profile?.icon_theme ?? 'classic'

  function onOpenChange(next: boolean) {
    setOpen(next)
    if (next) playClick(soundEnabled, 760)
  }

  function chooseTheme(key: string) {
    if (key === currentTheme || updateTheme.isPending) return
    playClick(soundEnabled, 880)
    updateTheme.mutate(key, {
      onSuccess: () => notify('外观已更新。'),
      onError: (error) => notify(describeApiError(error), 'error'),
    })
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content className={styles.content}>
          <div className={styles.head}>
            <div>
              <p className="eyebrow">偏好</p>
              <Dialog.Title className={styles.title}>设置</Dialog.Title>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className={styles.close}
                aria-label="关闭设置"
              >
                <X size={20} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </div>
          <Dialog.Description className={styles.description}>
            这些选项沿用现有账号能力，不会改动联赛数据。
          </Dialog.Description>

          <section className={styles.section} aria-labelledby="setting-sound">
            <div className={styles.sectionHead}>
              <div>
                <h3 id="setting-sound">声音</h3>
                <p>按钮和刷新时的轻提示音。</p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={soundEnabled}
                aria-label={soundEnabled ? '关闭声音' : '开启声音'}
                className={styles.switch}
                onClick={() => {
                  const next = toggleSound()
                  playClick(next, 820)
                }}
              >
                <span className={styles.switchThumb} aria-hidden="true" />
              </button>
            </div>
          </section>

          <section className={styles.section} aria-labelledby="setting-theme">
            <div className={styles.sectionHead}>
              <div>
                <h3 id="setting-theme">外观</h3>
                <p>图标风格会保存到当前账号。</p>
              </div>
            </div>
            <div
              className={styles.themeGrid}
              role="group"
              aria-label="图标风格"
            >
              {THEMES.map((theme) => {
                const active = currentTheme === theme.key
                return (
                  <button
                    key={theme.key}
                    type="button"
                    aria-pressed={active}
                    className={[
                      styles.themeOption,
                      active ? styles.themeActive : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    onClick={() => chooseTheme(theme.key)}
                    disabled={updateTheme.isPending}
                  >
                    <span className={styles.themeLabel}>
                      {theme.label}
                      {active ? <Check size={15} aria-hidden="true" /> : null}
                    </span>
                    <span className={styles.themeHint}>{theme.hint}</span>
                  </button>
                )
              })}
            </div>
            {updateTheme.isPending ? (
              <p className={styles.inlineNote}>正在保存外观…</p>
            ) : null}
            {updateTheme.error ? (
              <p className={styles.inlineError} role="alert">
                {describeApiError(updateTheme.error)}
              </p>
            ) : null}
          </section>

          <section className={styles.section} aria-labelledby="setting-data">
            <div className={styles.sectionHead}>
              <div>
                <h3 id="setting-data">数据</h3>
                <p>首页每 30 秒自动更新，也可以点顶栏刷新。</p>
              </div>
            </div>
          </section>

          <section className={styles.section} aria-labelledby="setting-account">
            <div className={styles.sectionHead}>
              <div>
                <h3 id="setting-account">账号</h3>
                <p className={styles.accountName}>
                  {profile?.display_name ?? '—'}
                  <span>{profile?.user_id ?? '—'}</span>
                </p>
              </div>
            </div>
            <button
              type="button"
              className={`${styles.signOut} button button--danger`}
              onClick={() => signOut()}
            >
              <LogOut size={17} aria-hidden="true" />
              退出登录
            </button>
          </section>

          <Dialog.Close asChild>
            <button type="button" className="button button--primary button--full">
              完成
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
