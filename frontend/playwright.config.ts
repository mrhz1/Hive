import { defineConfig, devices } from '@playwright/test'

/**
 * Runs against the real dev server and a real API. Serial, because the
 * tests create and delete records in a shared Hive database and Hive
 * writes are slow enough that parallel runs would interleave badly.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  // Hive round trips are seconds, not milliseconds.
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    actionTimeout: 20_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
