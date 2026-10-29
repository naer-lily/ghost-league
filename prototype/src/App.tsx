import { Ghost, RotateCcw } from 'lucide-react'
import { useApp } from './store'
import { NavRail, BottomNav } from './components/Nav'
import { TopBar } from './components/TopBar'
import { Toast } from './components/Toast'
import { SheetHost } from './components/SheetHost'
import { PageAside } from './components/PageAside'
import { HomePage } from './pages/HomePage'
import { LeaguePage } from './pages/LeaguePage'
import { EmbersPage } from './pages/EmbersPage'
import { HistoryPage } from './pages/HistoryPage'
import { MePage } from './pages/MePage'

function LoginScreen() {
  const { login } = useApp()
  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <span className="login-card__mark" aria-hidden="true">
          <Ghost className="icon-40" />
        </span>
        <h1 className="login-card__title" id="login-title">
          已退出
        </h1>
        <p className="login-card__body">火焰没灭。</p>
        <button type="button" className="button button--primary button--full" onClick={login}>
          <RotateCcw className="icon-20" aria-hidden="true" />
          重新进入
        </button>
      </section>
    </main>
  )
}

export default function App() {
  const { page, iconTheme, loggedOut, toast } = useApp()

  if (loggedOut) {
    return (
      <div className={`app icon-theme-${iconTheme}`}>
        <LoginScreen />
        <Toast toast={toast} />
      </div>
    )
  }

  return (
    <div className={`app icon-theme-${iconTheme}`} data-page={page}>
      <a className="skip-link" href="#main">
        跳到主内容
      </a>
      <NavRail />
      <div className="app-main">
        <TopBar />
        <div className="page-shell">
          <main className="page" id="main" tabIndex={-1} key={page} data-page={page}>
            {page === 'home' ? <HomePage /> : null}
            {page === 'league' ? <LeaguePage /> : null}
            {page === 'embers' ? <EmbersPage /> : null}
            {page === 'history' ? <HistoryPage /> : null}
            {page === 'me' ? <MePage /> : null}
          </main>
          <PageAside />
        </div>
      </div>
      <BottomNav />
      <Toast toast={toast} />
      <SheetHost />
    </div>
  )
}
