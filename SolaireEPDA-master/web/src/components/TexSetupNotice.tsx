import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertCircle, CheckCircle2, ExternalLink, RefreshCw } from "lucide-react";
import { apiGet, apiPost, ensureApiBase } from "../api/client";
import { cn } from "../lib/utils";

type TexStatus = {
  platform: string;
  latexmk_on_path: boolean;
  xelatex_on_path: boolean;
  winget_on_path: boolean | null;
  pdf_engine_ready: boolean;
};

type Props = {
  onError: (msg: string | null) => void;
};

const MIKTEX_DOWNLOAD = "https://miktex.org/download";

export function TexSetupNotice({ onError }: Props) {
  const { t } = useTranslation(["compose", "common"]);
  const [status, setStatus] = useState<TexStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [installMsg, setInstallMsg] = useState<string | null>(null);
  const [installBusy, setInstallBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    onError(null);
    try {
      await ensureApiBase();
      const data = await apiGet<TexStatus>("/api/system/tex-status");
      setStatus(data);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleInstall = async () => {
    setInstallBusy(true);
    setInstallMsg(null);
    onError(null);
    try {
      await ensureApiBase();
      const r = await apiPost<{ ok: boolean; message: string }>("/api/system/tex-install", {});
      setInstallMsg(r.message);
      if (!r.ok) {
        onError(r.message);
      }
    } catch (e) {
      const m = e instanceof Error ? e.message : String(e);
      setInstallMsg(m);
      onError(m);
    } finally {
      setInstallBusy(false);
    }
  };

  if (loading || !status) {
    return null;
  }

  if (status.pdf_engine_ready) {
    return (
      <div className="flex shrink-0 items-center gap-2 border-b border-emerald-100 bg-emerald-50/90 px-4 py-2 text-xs text-emerald-900">
        <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-700" />
        <span>{t("compose:texNoticeReady")}</span>
      </div>
    );
  }

  const showOneClick = status.platform === "win32" && status.winget_on_path;

  return (
    <div className="flex shrink-0 flex-col gap-2 border-b border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
      <div className="flex items-start gap-2">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
        <div className="min-w-0 flex-1">
          <p className="font-medium">{t("compose:texNoticeTitle")}</p>
          <p className="mt-1 text-xs leading-relaxed text-amber-900/90">{t("compose:texNoticeBody")}</p>
          {installMsg ? <p className="mt-2 text-xs text-amber-900">{installMsg}</p> : null}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 pl-6">
        <a
          href={MIKTEX_DOWNLOAD}
          target="_blank"
          rel="noopener noreferrer"
          className={cn(
            "inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-2.5 py-1.5 text-xs font-medium text-amber-950",
            "hover:bg-amber-100",
          )}
        >
          <ExternalLink className="h-3.5 w-3.5" />
          {t("compose:texNoticeOpenGuide")}
        </a>
        {showOneClick ? (
          <button
            type="button"
            disabled={installBusy}
            onClick={() => void handleInstall()}
            className="rounded-md border border-amber-400 bg-amber-100 px-2.5 py-1.5 text-xs font-medium text-amber-950 hover:bg-amber-200 disabled:opacity-50"
          >
            {installBusy ? t("common:loading") : t("compose:texNoticeOneClick")}
          </button>
        ) : null}
        <button
          type="button"
          disabled={loading}
          onClick={() => void load()}
          className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-2.5 py-1.5 text-xs font-medium text-amber-950 hover:bg-amber-100 disabled:opacity-50"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {t("compose:texNoticeRecheck")}
        </button>
      </div>
    </div>
  );
}
