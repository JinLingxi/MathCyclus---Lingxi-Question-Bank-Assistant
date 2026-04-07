export const LOCALE_STORAGE_KEY = "soleedu.locale";

export type AppLang = "zh" | "en";

export async function tauriGetLocale(): Promise<AppLang | null> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const v = await invoke<string>("get_app_locale");
    if (v === "zh" || v === "en") {
      return v;
    }
    if (typeof v === "string" && v.startsWith("en")) {
      return "en";
    }
    return "zh";
  } catch {
    return null;
  }
}

export async function tauriSetLocale(lang: AppLang): Promise<void> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("set_app_locale", { lang });
  } catch {
    /* 浏览器或非 Tauri 环境 */
  }
}

export function readStoredLocale(): AppLang | null {
  try {
    const v = localStorage.getItem(LOCALE_STORAGE_KEY);
    if (v === "zh" || v === "en") {
      return v;
    }
  } catch {
    /* private mode 等 */
  }
  return null;
}

export function writeStoredLocale(lang: AppLang): void {
  try {
    localStorage.setItem(LOCALE_STORAGE_KEY, lang);
  } catch {
    /* ignore */
  }
}
