import { defineConfig } from '@playwright/test'
import { loadEnv } from 'vite'

const env = loadEnv('development', process.cwd(), '')
const api =
  process.env.GHOST_LEAGUE_API_PROXY ??
  env.GHOST_LEAGUE_API_PROXY ??
  'http://127.0.0.1:8095'

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    headless: true,
    ignoreHTTPSErrors: true,
    launchOptions: {
      executablePath: process.env.CHROME_PATH ?? '/usr/bin/google-chrome',
      args: ['--no-sandbox'],
    },
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://127.0.0.1:4174',
    reuseExistingServer: true,
    timeout: 60_000,
    env: {
      ...process.env,
      GHOST_LEAGUE_API_PROXY: api,
    },
  },
})
