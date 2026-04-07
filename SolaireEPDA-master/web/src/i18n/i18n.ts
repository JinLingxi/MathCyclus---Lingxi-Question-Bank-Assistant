import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import { resources, type AppLang } from "./resources";
import { applyDocumentLocale } from "./syncDocument";

const namespaces = [
  "common",
  "app",
  "compose",
  "welcome",
  "settings",
  "help",
  "bank",
  "graph",
  "template",
  "analysis",
  "log",
  "agent",
  "components",
  "lib",
] as const;

export async function initI18n(initialLng: AppLang) {
  await i18n.use(initReactI18next).init({
    resources: {
      zh: resources.zh,
      en: resources.en,
    },
    lng: initialLng,
    fallbackLng: "zh",
    interpolation: { escapeValue: false },
    defaultNS: "common",
    ns: [...namespaces],
  });
  applyDocumentLocale(initialLng);
  i18n.on("languageChanged", (lng) => {
    applyDocumentLocale(lng);
  });
}

export default i18n;
