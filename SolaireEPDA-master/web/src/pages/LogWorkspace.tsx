import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { Clipboard, ScrollText, Trash2 } from "lucide-react";
import {
  clearLogs,
  copyLogsAsText,
  getLogSnapshot,
  subscribeLogs,
  type LogEntry,
  type LogLevel,
} from "../lib/appLog";
import { useAgentContext } from "../contexts/AgentContext";
import { formatLocaleTime } from "../lib/locale";
import { cn } from "../lib/utils";

function useLogs() {
  return useSyncExternalStore(subscribeLogs, getLogSnapshot, getLogSnapshot);
}

export function LogWorkspace() {
  const { t } = useTranslation(["log", "common"]);
  const { setPageContext } = useAgentContext();
  const entries = useLogs();
  const [levelFilter, setLevelFilter] = useState<LogLevel | "all">("all");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setPageContext({
      current_page: "log",
      summary: t("log:pageSummary"),
    });
    return () => setPageContext(null);
  }, [setPageContext, t]);

  const filtered = useMemo(() => {
    if (levelFilter === "all") {
      return [...entries].reverse();
    }
    return [...entries].filter((e) => e.level === levelFilter).reverse();
  }, [entries, levelFilter]);

  function handleCopy() {
    const clip = copyLogsAsText();
    void navigator.clipboard.writeText(clip).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-50">
      <div className="shrink-0 border-b border-slate-200 bg-white px-6 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 text-slate-800">
            <ScrollText className="h-5 w-5" strokeWidth={1.75} />
            <h1 className="text-lg font-semibold">{t("log:title")}</h1>
          </div>
          <span className="text-xs text-slate-500">{t("log:intro")}</span>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-slate-600">
            {t("log:level")}
            <select
              className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
              value={levelFilter}
              onChange={(e) => setLevelFilter(e.target.value as LogLevel | "all")}
            >
              <option value="all">{t("common:all")}</option>
              <option value="error">error</option>
              <option value="warn">warn</option>
              <option value="info">info</option>
            </select>
          </label>
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
            onClick={() => handleCopy()}
          >
            <Clipboard className="h-3.5 w-3.5" />
            {copied ? t("log:copied") : t("log:copyAll")}
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded border border-red-200 bg-white px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
            onClick={() => clearLogs()}
          >
            <Trash2 className="h-3.5 w-3.5" />
            {t("log:clear")}
          </button>
          <span className="text-xs text-slate-400">{t("log:count", { n: entries.length })}</span>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">
        {filtered.length === 0 ? (
          <p className="text-sm text-slate-500">{t("log:empty")}</p>
        ) : (
          <ul className="space-y-2">
            {filtered.map((e) => (
              <LogRow key={e.id} entry={e} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function LogRow({ entry: e }: { entry: LogEntry }) {
  const time = formatLocaleTime(new Date(e.ts), {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  return (
    <li
      className={cn(
        "rounded-lg border px-3 py-2 font-mono text-xs shadow-sm",
        e.level === "error" && "border-red-200 bg-red-50/80 text-red-950",
        e.level === "warn" && "border-amber-200 bg-amber-50/80 text-amber-950",
        e.level === "info" && "border-slate-200 bg-white text-slate-800",
      )}
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="text-[10px] text-slate-500">{time}</span>
        <span className="font-semibold uppercase">{e.level}</span>
        <span className="text-slate-500">[{e.source}]</span>
      </div>
      <p className="mt-1 whitespace-pre-wrap break-words text-[11px] leading-snug">{e.message}</p>
      {e.detail ? (
        <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-black/5 p-2 text-[10px] leading-snug text-slate-700">
          {e.detail}
        </pre>
      ) : null}
    </li>
  );
}
