import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { BookOpen, Clock, FolderOpen, FolderPlus, Trash2 } from "lucide-react";
import welcomeLogo from "../assets/welcome-logo.png";
import { NewProjectDialog } from "../components/NewProjectDialog";
import { apiGet, apiPost, ensureApiBase } from "../api/client";
import { cn } from "../lib/utils";

type RecentItem = { name: string; path: string; last_opened: string };

type Props = {
  onProjectReady: () => void;
  onError: (msg: string | null) => void;
};

export function WelcomeWorkspace({ onProjectReady, onError }: Props) {
  const { t } = useTranslation(["welcome", "app"]);
  const [recent, setRecent] = useState<RecentItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [newProjectOpen, setNewProjectOpen] = useState(false);

  const loadRecent = useCallback(async () => {
    try {
      onError(null);
      await ensureApiBase();
      const data = await apiGet<{ items: RecentItem[] }>("/api/recent-projects");
      setRecent(data.items ?? []);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  }, [onError]);

  useEffect(() => {
    void loadRecent();
  }, [loadRecent]);

  const openByPath = useCallback(
    async (root: string) => {
      setLoading(true);
      onError(null);
      try {
        await apiPost("/api/project/open", { root });
        onProjectReady();
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    [onError, onProjectReady],
  );

  const removeFromRecent = useCallback(
    async (root: string) => {
      onError(null);
      try {
        await ensureApiBase();
        await apiPost<{ ok: boolean; removed: boolean }>("/api/recent-projects/remove", { path: root });
        await loadRecent();
      } catch (e) {
        onError(e instanceof Error ? e.message : String(e));
      }
    },
    [loadRecent, onError],
  );

  const handleOpenFolder = useCallback(async () => {
    setLoading(true);
    onError(null);
    try {
      const w = typeof window !== "undefined" ? window : undefined;
      const isTauri =
        w &&
        ("__TAURI_INTERNALS__" in w ||
          (w as unknown as { __TAURI__?: unknown }).__TAURI__ !== undefined);
      if (isTauri) {
        const { open } = await import("@tauri-apps/plugin-dialog");
        const sel = await open({ directory: true, multiple: false, title: t("welcome:pickFolderTitle") });
        const path = Array.isArray(sel) ? sel[0] : sel;
        if (typeof path === "string" && path) {
          await openByPath(path);
        }
      } else {
        await apiPost("/api/project/pick-open", {});
        onProjectReady();
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [onError, onProjectReady, openByPath, t]);

  return (
    <div className="flex h-full min-h-0 min-w-0 w-full bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 text-slate-100">
      <NewProjectDialog
        open={newProjectOpen}
        onOpenChange={setNewProjectOpen}
        onProjectReady={() => {
          void loadRecent();
          onProjectReady();
        }}
        onError={onError}
      />
      <aside className="flex w-[min(28%,360px)] shrink-0 flex-col border-r border-slate-700/80 bg-slate-950/40 p-8">
        <div className="mb-8 flex flex-col gap-3">
          <div className="flex w-full max-w-[11rem] items-center justify-center rounded-xl p-2">
            <img
              src={welcomeLogo}
              alt=""
              className="h-auto w-full object-contain object-center"
              aria-hidden
            />
          </div>
          <p className="text-sm font-semibold leading-snug tracking-tight text-slate-100">
            {t("welcome:brand")}
          </p>
        </div>
        <div className="mt-auto space-y-3 text-xs leading-relaxed text-slate-500">
          <p>{t("welcome:hint1")}</p>
          <p className="flex items-center gap-1.5">
            <BookOpen className="h-3.5 w-3.5 shrink-0" />
            {t("welcome:hint2")}
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col overflow-x-hidden overflow-y-auto p-10">
        <div className="mx-auto w-full max-w-2xl">
          <h1 className="mb-2 text-2xl font-semibold tracking-tight text-white">{t("welcome:title")}</h1>
          <p className="mb-8 text-sm text-slate-400">{t("welcome:intro")}</p>

          <div className="mb-10 flex flex-wrap gap-3">
            <button
              type="button"
              disabled={loading}
              onClick={() => setNewProjectOpen(true)}
              className={cn(
                "inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white shadow-lg shadow-indigo-900/40 transition hover:bg-indigo-500",
                loading && "cursor-not-allowed opacity-60",
              )}
            >
              <FolderPlus className="h-4 w-4" />
              {t("welcome:newProject")}
            </button>
            <button
              type="button"
              disabled={loading}
              onClick={() => void handleOpenFolder()}
              className={cn(
                "inline-flex items-center gap-2 rounded-lg border border-slate-600 bg-slate-800/80 px-5 py-2.5 text-sm font-medium text-slate-100 transition hover:bg-slate-700",
                loading && "cursor-not-allowed opacity-60",
              )}
            >
              <FolderOpen className="h-4 w-4" />
              {t("welcome:openProject")}
            </button>
          </div>

          <div>
            <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-300">
              <Clock className="h-4 w-4 text-slate-500" />
              {t("welcome:recent")}
            </div>
            {recent.length === 0 ? (
              <p className="rounded-lg border border-dashed border-slate-700 bg-slate-900/50 px-4 py-8 text-center text-sm text-slate-500">
                {t("welcome:recentEmpty")}
              </p>
            ) : (
              <ul className="min-w-0 space-y-2">
                {recent.map((item) => (
                  <li key={item.path} className="group flex min-w-0 items-stretch gap-1">
                    <button
                      type="button"
                      disabled={loading}
                      onClick={() => void openByPath(item.path)}
                      className="flex min-w-0 flex-1 flex-col items-start rounded-lg border border-slate-700/80 bg-slate-900/60 px-4 py-3 text-left transition hover:border-indigo-500/50 hover:bg-slate-800/80"
                    >
                      <span className="font-medium text-slate-100">{item.name}</span>
                      <span className="mt-0.5 break-all text-xs text-slate-500" title={item.path}>
                        {item.path}
                      </span>
                    </button>
                    <button
                      type="button"
                      disabled={loading}
                      title={t("welcome:removeFromRecentTitle")}
                      aria-label={t("welcome:removeFromRecentAria")}
                      onClick={(e) => {
                        e.stopPropagation();
                        void removeFromRecent(item.path);
                      }}
                      className={cn(
                        "flex shrink-0 items-center justify-center self-stretch rounded-lg border border-transparent px-2.5 text-slate-500 transition",
                        "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100",
                        "hover:border-red-500/40 hover:bg-red-950/50 hover:text-red-200",
                        "focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-red-500/40",
                        loading && "pointer-events-none",
                      )}
                    >
                      <Trash2 className="h-4 w-4" strokeWidth={1.75} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
