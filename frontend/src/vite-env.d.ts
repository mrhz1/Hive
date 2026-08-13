/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  /** Set to have the dev server front the API on its own origin. */
  readonly VITE_API_PROXY_TARGET?: string
  readonly VITE_DEV_USERNAME?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
