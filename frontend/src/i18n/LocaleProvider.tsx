import { useCallback, useMemo, useState, type ReactNode } from 'react';

import { translate } from './catalog';
import { LocaleContext } from './localeContextValue';
import { initialCatalogLocale, pickCatalogLocale, type CatalogLocale } from './normalizeLocale';

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<CatalogLocale>(initialCatalogLocale);

  const setLocaleFromServer = useCallback((uiLocale: string | undefined) => {
    setLocale(pickCatalogLocale(uiLocale));
  }, []);

  const t = useCallback(
    (key: string, params?: Record<string, string | number | undefined>) => translate(locale, key, params),
    [locale],
  );

  const value = useMemo(
    () => ({ locale, setLocaleFromServer, t }),
    [locale, setLocaleFromServer, t],
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}
