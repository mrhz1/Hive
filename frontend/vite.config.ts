import { tanstackRouter } from '@tanstack/router-plugin/vite'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

/**
 * Point this at the API to have the dev server forward `/api` to it,
 * the way scripts/serve_frontend.py does in a deployment. Set it and
 * the page talks only to the dev server's own origin, so there is no
 * cross-origin request for a browser to refuse and no CORS_ORIGINS to
 * keep in step -- which is the only way that works when something
 * (Knox, an SSO proxy) sits in front of the API and answers the
 * preflight itself with a redirect the browser will not follow.
 *
 * Use it with VITE_API_BASE_URL=/api.
 */
const PROXY_TARGET_VAR = 'VITE_API_PROXY_TARGET'

export default defineConfig(({ mode }) => {
  // '' loads every variable, not just the VITE_-prefixed ones. This
  // config runs in Node, so nothing here reaches the bundle.
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
                // A workspace certificate signed by an internal CA would
                // otherwise stop the proxy dead. Opt in, and only here:
                // this server never runs anywhere but a developer's
                // machine.
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
      // routeTree.gen.ts is generated; nothing to test in it.
      coverage: { exclude: ['**/routeTree.gen.ts', '**/*.config.*', 'src/test/**'] },
    },
  }
})
