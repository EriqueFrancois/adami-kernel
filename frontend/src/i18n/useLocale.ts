import { useContext } from 'react';

import { LocaleContext, type LocaleContextValue } from './localeContextValue';

export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error('useLocale must be used within LocaleProvider');
  return ctx;
}
