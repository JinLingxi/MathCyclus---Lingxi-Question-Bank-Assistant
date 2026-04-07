import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ensureApiBase } from "./api/client";
import { initI18n } from "./i18n/i18n";
import { readStoredLocale, tauriGetLocale, writeStoredLocale, type AppLang } from "./i18n/tauriLocale";
import { installGlobalLogging } from "./lib/appLog";
import { isTauriShell } from "./lib/tauriEnv";
import "./index.css";

if (typeof document !== "undefined" && isTauriShell()) {
  document.documentElement.classList.add("tauri-shell");
}

installGlobalLogging();

void (async () => {
  const fromTauri = await tauriGetLocale();
  let lng: AppLang = "zh";
  if (fromTauri) {
    lng = fromTauri;
    writeStoredLocale(fromTauri);
  } else {
    const stored = readStoredLocale();
    lng = stored ?? (typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("en") ? "en" : "zh");
  }
  await initI18n(lng);
  await ensureApiBase();
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
})();
