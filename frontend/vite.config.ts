import { tanstackRouter } from '@tanstack/router-plugin/vite'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

const PROXY_TARGET_VAR = 'VITE_API_PROXY_TARGET'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env[PROXY_TARGET_VAR]?.trim()

  return {
    plugins: [
      tanstackRouter({ target: 'react', autoCodeSplitting: true }),
      react(),
      tailwindcss(),
    ],
    resolve: {
      alias: { '@': new URL('./src', import.meta.url).pathname },
    },
    server: {
      port: 5173,
      ...(target
        ? {
            proxy: {
              '/api': {
                target,
                changeOrigin: true,

                secure: env.VITE_API_PROXY_INSECURE !== 'true',
                rewrite: (path) => path.replace(/^\/api/, ''),
              },
            },
          }
        : {}),
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.{test,spec}.{ts,tsx}'],

      coverage: { exclude: ['**/routeTree.gen.ts', '**/*.config.*', 'src/test/**'] },
    },
  }
})
