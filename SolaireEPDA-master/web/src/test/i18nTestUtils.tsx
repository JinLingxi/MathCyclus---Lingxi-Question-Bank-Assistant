import { type ReactNode } from "react";
import { I18nextProvider } from "react-i18next";
import { initReactI18next } from "react-i18next";
import i18n from "../i18n/i18n";
import { resources } from "../i18n/resources";

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

export async function setupTestI18n(lng: "zh" | "en" = "zh") {
  if (!i18n.isInitialized) {
    await i18n.use(initReactI18next).init({
      lng,
      fallbackLng: "zh",
      resources: {
        zh: resources.zh,
        en: resources.en,
      },
      interpolation: { escapeValue: false },
      defaultNS: "common",
      ns: [...namespaces],
    });
  } else {
    await i18n.changeLanguage(lng);
  }
}

export function TestI18nProvider({ children }: { children: ReactNode }) {
  return <I18nextProvider i18n={i18n}>{children}</I18nextProvider>;
}
