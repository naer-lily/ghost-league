import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget =
    process.env.GHOST_LEAGUE_API_PROXY ??
    env.GHOST_LEAGUE_API_PROXY ??
    'http://127.0.0.1:8095'

  const proxy = {
    '/v1': { target: apiTarget, changeOrigin: true },
    '/avatars': { target: apiTarget, changeOrigin: true },
  }

  return {
    plugins: [react()],
    build: {
      // Keep the legacy `web/` entry untouched; the next frontend is published
      // separately until the production cut-over.
      outDir: '../web-next',
      emptyOutDir: true,
      sourcemap: false,
    },
    server: {
      host: '127.0.0.1',
      port: 4174,
      strictPort: true,
      proxy,
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      css: true,
      include: ['src/**/*.test.{ts,tsx}'],
      restoreMocks: true,
    },
  }
})
