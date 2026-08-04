import { tanstackRouter } from '@tanstack/router-plugin/vite'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [
    // Must precede the react plugin: it generates routeTree.gen.ts from
    // src/routes before react transforms anything.
    tanstackRouter({ target: 'react', autoCodeSplitting: true }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: { '@': new URL('./src', import.meta.url).pathname },
  },
  server: {
    port: 5173,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Unit tests only. e2e/ is Playwright and would fail under vitest,
    // which cannot supply its fixtures.
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    // routeTree.gen.ts is generated; nothing to test in it.
    coverage: { exclude: ['**/routeTree.gen.ts', '**/*.config.*', 'src/test/**'] },
  },
})
