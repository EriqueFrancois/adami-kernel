import { createContext } from 'react';

import type { CatalogLocale } from './normalizeLocale';

export type LocaleContextValue = {
  locale: CatalogLocale;
  /** After ``GET /dashboard`` — matches ``settings.effective_ui_default_locale()`` from ``ui_locale``. */
  setLocaleFromServer: (uiLocale: string | undefined) => void;
  t: (key: string, params?: Record<string, string | number | undefined>) => string;
};

export const LocaleContext = createContext<LocaleContextValue | null>(null);
