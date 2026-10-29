import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import App from './App'
import { AppProvider } from './store'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppProvider>
      <TooltipPrimitive.Provider delayDuration={120} skipDelayDuration={0}>
        <App />
      </TooltipPrimitive.Provider>
    </AppProvider>
  </StrictMode>,
)
