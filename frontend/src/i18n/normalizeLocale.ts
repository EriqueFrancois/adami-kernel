/** Match kernel ``adami_kernel.i18n.locale_utils.normalize_locale`` for tags the console cares about. */

export function normalizeLocale(raw: string | undefined | null): string {
  if (raw == null) return 'en';
  const s = String(raw).trim().replaceAll('_', '-');
  if (!s) return 'en';
  const parts = s.split('-');
  parts[0] = parts[0].toLowerCase();
  const s2 = parts.join('-');
  const low = s2.toLowerCase();
  if (low === 'zh-cn' || low === 'zhcn') return 'zh-Hans';
  return s2;
}

export type CatalogLocale = 'en' | 'zh-Hans';

/** Map kernel ``ui_locale`` to a shipped frontend catalog (only ``en`` / ``zh-Hans``). */
export function pickCatalogLocale(raw: string | undefined | null): CatalogLocale {
  const n = normalizeLocale(raw ?? '');
  if (n === 'en') return 'en';
  if (n === 'zh-Hans' || n.toLowerCase().startsWith('zh')) return 'zh-Hans';
  return 'en';
}

/** Before ``/dashboard``: env override, else same default as ``ADAMI_SYSTEM_UI_LOCALE`` (``zh-Hans``). */
export function initialCatalogLocale(): CatalogLocale {
  const env = import.meta.env.VITE_ADAMI_UI_LOCALE;
  if (env != null && String(env).trim()) return pickCatalogLocale(String(env));
  return 'zh-Hans';
}
