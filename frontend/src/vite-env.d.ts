/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string

  readonly VITE_API_PROXY_TARGET?: string
  readonly VITE_DEV_USERNAME?: string
  readonly VITE_APP_NAME?: string
  readonly VITE_APP_LOGO?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
