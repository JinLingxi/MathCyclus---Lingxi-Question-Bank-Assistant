import i18n from "../i18n/i18n";

/** BCP 47 locale for Intl APIs (dates, sorting). */
export function getAppLocale(): string {
  const lng = i18n.language || "zh";
  if (lng.startsWith("en")) {
    return "en-US";
  }
  return "zh-CN";
}

export function localeCompareStrings(a: string, b: string): number {
  return a.localeCompare(b, getAppLocale());
}

export function formatLocaleDate(isoOrDate: string | Date, options?: Intl.DateTimeFormatOptions): string {
  const d = typeof isoOrDate === "string" ? new Date(isoOrDate) : isoOrDate;
  return d.toLocaleDateString(getAppLocale(), options);
}

export function formatLocaleTime(isoOrDate: string | Date, options?: Intl.DateTimeFormatOptions): string {
  const d = typeof isoOrDate === "string" ? new Date(isoOrDate) : isoOrDate;
  return d.toLocaleTimeString(getAppLocale(), options);
}

export function formatLocaleDateTime(isoOrDate: string | Date, options?: Intl.DateTimeFormatOptions): string {
  const d = typeof isoOrDate === "string" ? new Date(isoOrDate) : isoOrDate;
  return d.toLocaleString(getAppLocale(), options);
}
