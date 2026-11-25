/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_SNAPSHOT_TIMEOUT_MS?: string;
  readonly NEXT_PUBLIC_TELEGRAM_BOT_USERNAME?: string;
  readonly NEXT_PUBLIC_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
