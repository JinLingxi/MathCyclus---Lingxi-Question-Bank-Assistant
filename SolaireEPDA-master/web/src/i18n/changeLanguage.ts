import i18n from "./i18n";
import { tauriSetLocale, writeStoredLocale, type AppLang } from "./tauriLocale";

export async function changeAppLanguage(lang: AppLang) {
  await i18n.changeLanguage(lang);
  writeStoredLocale(lang);
  await tauriSetLocale(lang);
}
