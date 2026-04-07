import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useTranslation } from "react-i18next";
import { FolderOpen, X } from "lucide-react";
import { apiPost, ensureApiBase } from "../api/client";
import { pickFolderCanceledMessage } from "../lib/pickFolder";
import { cn } from "../lib/utils";

type TemplateKind = "empty" | "math";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onProjectReady: () => void;
  onError: (msg: string | null) => void;
};

export function NewProjectDialog({ open, onOpenChange, onProjectReady, onError }: Props) {
  const { t } = useTranslation(["welcome"]);
  const [parentPath, setParentPath] = useState("");
  const [name, setName] = useState("");
  const [template, setTemplate] = useState<TemplateKind>("empty");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setParentPath("");
      setName(t("welcome:defaultNewProjectName"));
      setTemplate("empty");
      onError(null);
    }
  }, [open, onError, t]);

  const pickParent = async () => {
    onError(null);
    try {
      await ensureApiBase();
      const w = typeof window !== "undefined" ? window : undefined;
      const isTauri =
        w &&
        ("__TAURI_INTERNALS__" in w ||
          (w as unknown as { __TAURI__?: unknown }).__TAURI__ !== undefined);
      if (isTauri) {
        const { open: openDlg } = await import("@tauri-apps/plugin-dialog");
        const sel = await openDlg({
          directory: true,
          multiple: false,
          title: t("welcome:pickParentTitle"),
        });
        const path = Array.isArray(sel) ? sel[0] : sel;
        if (typeof path === "string" && path) {
          setParentPath(path);
        }
      } else {
        const res = await apiPost<{ ok: boolean; path: string }>("/api/project/pick-parent", {});
        setParentPath(res.path);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (pickFolderCanceledMessage(msg)) {
        onError(null);
      } else {
        onError(msg);
      }
    }
  };

  const handleSubmit = async () => {
    const trimmedName = name.trim();
    const trimmedParent = parentPath.trim();
    if (!trimmedParent) {
      onError(t("welcome:newProjectLocationRequired"));
      return;
    }
    if (!trimmedName) {
      onError(t("welcome:newProjectNameRequired"));
      return;
    }
    setSubmitting(true);
    onError(null);
    try {
      await ensureApiBase();
      await apiPost("/api/project/create", {
        parent: trimmedParent,
        name: trimmedName,
        template,
      });
      onOpenChange(false);
      onProjectReady();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[100] bg-black/55 backdrop-blur-[2px]" />
        <Dialog.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-[101] w-[min(100vw-2rem,28rem)] max-h-[min(90vh,40rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border border-slate-600 bg-slate-900 p-6 text-slate-100 shadow-2xl outline-none",
          )}
          onPointerDownOutside={(e) => {
            if (submitting) e.preventDefault();
          }}
          onEscapeKeyDown={(e) => {
            if (submitting) e.preventDefault();
          }}
        >
          <div className="mb-4 flex items-start justify-between gap-3">
            <Dialog.Title className="text-lg font-semibold leading-tight text-white">
              {t("welcome:newProjectDialogTitle")}
            </Dialog.Title>
            <Dialog.Close asChild>
              <button
                type="button"
                disabled={submitting}
                className="rounded-lg p-1 text-slate-400 transition hover:bg-slate-800 hover:text-slate-200 disabled:opacity-40"
                aria-label={t("welcome:newProjectDialogClose")}
              >
                <X className="h-5 w-5" />
              </button>
            </Dialog.Close>
          </div>
          <Dialog.Description className="mb-5 text-sm text-slate-400">
            {t("welcome:newProjectDialogIntro")}
          </Dialog.Description>

          <div className="space-y-5">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-300">
                {t("welcome:newProjectLocationLabel")}
              </label>
              <div className="flex flex-wrap gap-2">
                <div className="min-h-[2.5rem] min-w-0 flex-1 rounded-lg border border-slate-600 bg-slate-950/80 px-3 py-2 text-xs text-slate-300">
                  {parentPath ? (
                    <span className="break-all">{parentPath}</span>
                  ) : (
                    <span className="text-slate-500">{t("welcome:newProjectLocationPlaceholder")}</span>
                  )}
                </div>
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => void pickParent()}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-500 bg-slate-800 px-3 py-2 text-sm font-medium text-slate-100 transition hover:bg-slate-700 disabled:opacity-50"
                >
                  <FolderOpen className="h-4 w-4" />
                  {t("welcome:browseFolder")}
                </button>
              </div>
            </div>

            <div>
              <label htmlFor="new-project-name" className="mb-1.5 block text-xs font-medium text-slate-300">
                {t("welcome:newProjectNameLabel")}
              </label>
              <input
                id="new-project-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={submitting}
                autoComplete="off"
                className="w-full rounded-lg border border-slate-600 bg-slate-950/80 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:opacity-50"
                placeholder={t("welcome:newProjectNamePlaceholder")}
              />
            </div>

            <fieldset>
              <legend className="mb-2 text-xs font-medium text-slate-300">{t("welcome:templateLabel")}</legend>
              <div className="grid gap-2 sm:grid-cols-2">
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => setTemplate("empty")}
                  className={cn(
                    "rounded-lg border px-3 py-3 text-left text-sm transition",
                    template === "empty"
                      ? "border-indigo-500 bg-indigo-950/50 text-white ring-1 ring-indigo-500/40"
                      : "border-slate-600 bg-slate-950/40 text-slate-200 hover:border-slate-500",
                  )}
                >
                  <span className="font-medium">{t("welcome:templateEmpty")}</span>
                  <span className="mt-1 block text-xs font-normal text-slate-400">
                    {t("welcome:templateEmptyDesc")}
                  </span>
                </button>
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => setTemplate("math")}
                  className={cn(
                    "rounded-lg border px-3 py-3 text-left text-sm transition",
                    template === "math"
                      ? "border-indigo-500 bg-indigo-950/50 text-white ring-1 ring-indigo-500/40"
                      : "border-slate-600 bg-slate-950/40 text-slate-200 hover:border-slate-500",
                  )}
                >
                  <span className="font-medium">{t("welcome:templateMath")}</span>
                  <span className="mt-1 block text-xs font-normal text-slate-400">
                    {t("welcome:templateMathDesc")}
                  </span>
                </button>
              </div>
            </fieldset>
          </div>

          <div className="mt-6 flex flex-wrap justify-end gap-2 border-t border-slate-700/80 pt-4">
            <Dialog.Close asChild>
              <button
                type="button"
                disabled={submitting}
                className="rounded-lg border border-slate-600 px-4 py-2 text-sm font-medium text-slate-200 transition hover:bg-slate-800 disabled:opacity-50"
              >
                {t("welcome:newProjectCancel")}
              </button>
            </Dialog.Close>
            <button
              type="button"
              disabled={submitting}
              onClick={() => void handleSubmit()}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-indigo-900/30 transition hover:bg-indigo-500 disabled:opacity-50"
            >
              {submitting ? t("welcome:newProjectCreating") : t("welcome:newProjectConfirm")}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
