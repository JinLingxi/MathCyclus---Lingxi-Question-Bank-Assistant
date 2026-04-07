import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Minus, Square, SquareStack, X } from "lucide-react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { cn } from "../lib/utils";
import { isTauriShell } from "../lib/tauriEnv";

function titleBarButtonClass(extra?: string) {
  return cn(
    "inline-flex h-full w-11 items-center justify-center text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-100",
    "[-webkit-app-region:no-drag] [app-region:no-drag]",
    "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-slate-500",
    extra,
  );
}

export function DesktopTitleBar() {
  const { t } = useTranslation(["app"]);
  const [maximized, setMaximized] = useState(false);

  const syncMaximized = useCallback(async () => {
    try {
      const m = await getCurrentWindow().isMaximized();
      setMaximized(m);
    } catch {
      /* 忽略 */
    }
  }, []);

  useEffect(() => {
    if (!isTauriShell()) return;
    void syncMaximized();
    let unlisten: (() => void) | undefined;
    void getCurrentWindow()
      .onResized(() => {
        void syncMaximized();
      })
      .then((fn) => {
        unlisten = fn;
      })
      .catch(() => {});
    return () => {
      unlisten?.();
    };
  }, [syncMaximized]);

  if (!isTauriShell()) return null;

  const appWindow = getCurrentWindow();

  return (
    <header
      className="flex h-8 shrink-0 select-none items-stretch border-b border-slate-800 bg-slate-900"
      role="banner"
    >
      <div
        className="flex min-w-0 flex-1 items-center gap-2 px-3"
        data-tauri-drag-region
        onDoubleClick={() => {
          void appWindow.toggleMaximize();
        }}
      >
        <span className="truncate text-xs font-semibold tracking-tight text-slate-200">{t("app:brand")}</span>
      </div>
      <div className="flex shrink-0" data-tauri-drag-region="false">
        <button
          type="button"
          className={titleBarButtonClass()}
          title={t("app:titleBar.minimize")}
          aria-label={t("app:titleBar.minimize")}
          onClick={() => void appWindow.minimize()}
        >
          <Minus className="h-3.5 w-3.5" strokeWidth={2.25} />
        </button>
        <button
          type="button"
          className={titleBarButtonClass()}
          title={maximized ? t("app:titleBar.restore") : t("app:titleBar.maximize")}
          aria-label={maximized ? t("app:titleBar.restore") : t("app:titleBar.maximize")}
          onClick={() => void appWindow.toggleMaximize()}
        >
          {maximized ? (
            <SquareStack className="h-3.5 w-3.5" strokeWidth={2.25} />
          ) : (
            <Square className="h-3 w-3" strokeWidth={2.25} />
          )}
        </button>
        <button
          type="button"
          className={titleBarButtonClass("hover:bg-red-700 hover:text-white")}
          title={t("app:titleBar.close")}
          aria-label={t("app:titleBar.close")}
          onClick={() => void appWindow.close()}
        >
          <X className="h-3.5 w-3.5" strokeWidth={2.25} />
        </button>
      </div>
    </header>
  );
}
