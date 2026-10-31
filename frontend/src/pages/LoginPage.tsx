import { Eye, EyeOff, Flame, LogIn } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { apiFetch, ApiError } from '../api/client'
import type { Profile } from '../api/types'
import { playClick } from '../lib/sound'
import { useUiStore } from '../store/useUiStore'
import styles from './LoginPage.module.css'

export function LoginPage() {
  const signIn = useUiStore((state) => state.signIn)
  const soundEnabled = useUiStore((state) => state.soundEnabled)
  const [token, setToken] = useState('')
  const [visible, setVisible] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const value = token.trim()
    if (!value) {
      setError('请粘贴你的个人访问令牌。')
      return
    }
    setError('')
    setBusy(true)
    playClick(soundEnabled, 720)
    try {
      await apiFetch<Profile>('/v1/me/profile', { token: value })
      signIn(value)
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        setError('令牌无效或已过期，请重新输入。')
      } else if (caught instanceof ApiError && caught.status === 0) {
        setError('网络连接失败，请检查网络后重试。')
      } else {
        setError('暂时无法连接服务，请稍后重试。')
      }
      setBusy(false)
    }
  }

  return (
    <main className={styles.page}>
      <div className={styles.glow} aria-hidden="true" />
      <section className={styles.card} aria-labelledby="login-title">
        <span className={styles.mark} aria-hidden="true">
          <Flame size={30} />
        </span>
        <p className="eyebrow">本周联赛</p>
        <h1 id="login-title" className={styles.title}>
          点燃今天的火焰
        </h1>
        <p className={styles.body}>
          沿用现有个人访问令牌进入，不会新建账号。
        </p>

        <form className={styles.form} onSubmit={(event) => void submit(event)}>
          <label className={styles.label} htmlFor="token">
            个人访问令牌
          </label>
          <div className={styles.inputWrap}>
            <input
              id="token"
              name="token"
              type={visible ? 'text' : 'password'}
              value={token}
              onChange={(event) => setToken(event.target.value)}
              className={styles.input}
              placeholder="粘贴令牌"
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              aria-describedby={error ? 'login-error' : 'login-hint'}
            />
            <button
              type="button"
              className={styles.reveal}
              aria-label={visible ? '隐藏令牌' : '显示令牌'}
              onClick={() => setVisible((current) => !current)}
            >
              {visible ? (
                <EyeOff size={19} aria-hidden="true" />
              ) : (
                <Eye size={19} aria-hidden="true" />
              )}
            </button>
          </div>
          <p id="login-hint" className={styles.hint}>
            令牌只保存在本机浏览器，不会上传到别处。
          </p>
          {error ? (
            <p id="login-error" className={styles.error} role="alert">
              {error}
            </p>
          ) : null}
          <button
            type="submit"
            className={`${styles.submit} button button--primary button--full`}
            disabled={busy}
          >
            <LogIn size={19} aria-hidden="true" />
            {busy ? '正在验证…' : '进入联赛'}
          </button>
        </form>

        <p className={styles.footnote}>
          没有令牌？在现有页面的「我的 → 集成」里查看。
        </p>
      </section>
    </main>
  )
}
