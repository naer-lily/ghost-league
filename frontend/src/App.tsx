import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { HomePage } from './pages/HomePage'
import { LeaguePage } from './pages/LeaguePage'
import { LoginPage } from './pages/LoginPage'
import { MePage } from './pages/MePage'
import { HistoryPage, NotFoundPage } from './pages/Placeholders'
import { RivalPage } from './pages/RivalPage'
import { ShopPage } from './pages/ShopPage'
import { useUiStore } from './store/useUiStore'

export default function App() {
  const token = useUiStore((state) => state.token)

  if (!token) return <LoginPage />

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="league" element={<LeaguePage />} />
        <Route path="rival" element={<RivalPage />} />
        <Route path="shop" element={<ShopPage />} />
        <Route path="embers" element={<Navigate to="/shop" replace />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="me" element={<MePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
