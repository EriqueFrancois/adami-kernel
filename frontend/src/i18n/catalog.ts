import type { CatalogLocale } from './normalizeLocale';
import en from '../locales/en.json';
import zhHans from '../locales/zh-Hans.json';

const CATALOGS: Record<CatalogLocale, Record<string, string>> = {
  en: en as Record<string, string>,
  'zh-Hans': zhHans as Record<string, string>,
};

export function messagesFor(locale: CatalogLocale): Record<string, string> {
  return CATALOGS[locale] ?? CATALOGS.en;
}

export function translate(
  locale: CatalogLocale,
  key: string,
  params?: Record<string, string | number | undefined>,
): string {
  const table = messagesFor(locale);
  const fallback = messagesFor('en');
  const raw = table[key] ?? fallback[key] ?? key;
  if (!params) return raw;
  return raw.replace(/\{(\w+)\}/g, (_, k: string) => {
    const v = params[k];
    return v === undefined ? `{${k}}` : String(v);
  });
}
