/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  /** Set to have the dev server front the API on its own origin. */
  readonly VITE_API_PROXY_TARGET?: string
  readonly VITE_DEV_USERNAME?: string
  /** Show live page counts while a file de-identifies. Default on. */
  readonly VITE_DEID_PROGRESS_ENABLED?: string
  /** How often to ask for those counts, ms. 0 turns the poller off. */
  readonly VITE_DEID_PROGRESS_POLL_MS?: string
  /** How often the file list re-checks for a finished run, ms. 0 is off. */
  readonly VITE_DEID_LIST_REFRESH_MS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
