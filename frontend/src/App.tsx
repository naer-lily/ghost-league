import { Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import {
  EmbersPage,
  HistoryPage,
  LeaguePage,
  MePage,
  NotFoundPage,
} from './pages/Placeholders'
import { useUiStore } from './store/useUiStore'

export default function App() {
  const token = useUiStore((state) => state.token)

  if (!token) return <LoginPage />

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="league" element={<LeaguePage />} />
        <Route path="embers" element={<EmbersPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="me" element={<MePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
