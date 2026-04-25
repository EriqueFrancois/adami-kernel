/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional; aligns with kernel ``ADAMI_UI_LOCALE`` / ``effective_ui_default_locale()`` before first ``/dashboard`` fetch. */
  readonly VITE_ADAMI_UI_LOCALE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module '*.json' {
  const value: Record<string, string>;
  export default value;
}
