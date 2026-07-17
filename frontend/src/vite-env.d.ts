/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the FastAPI backend. Defaults to the local dev server. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
