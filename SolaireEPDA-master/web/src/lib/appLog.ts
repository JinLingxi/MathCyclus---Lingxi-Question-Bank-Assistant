/**
 * 应用内日志环形缓冲：控制台、未捕获异常、API 摘要。供 Log 页与排障使用。
 */

export type LogLevel = "error" | "warn" | "info";
export type LogSource = "console" | "network" | "app";

export type LogEntry = {
  id: string;
  ts: number;
  level: LogLevel;
  source: LogSource;
  message: string;
  detail?: string;
};

const MAX_ENTRIES = 400;
let buffer: LogEntry[] = [];
let seq = 0;
const listeners = new Set<() => void>();

function notify() {
  for (const cb of listeners) {
    cb();
  }
}

function push(entry: Omit<LogEntry, "id" | "ts"> & { id?: string; ts?: number }) {
  const full: LogEntry = {
    id: entry.id ?? `log-${++seq}`,
    ts: entry.ts ?? Date.now(),
    level: entry.level,
    source: entry.source,
    message: entry.message,
    detail: entry.detail,
  };
  buffer = buffer.length >= MAX_ENTRIES ? [...buffer.slice(-(MAX_ENTRIES - 1)), full] : [...buffer, full];
  notify();
}

export function subscribeLogs(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function getLogSnapshot(): LogEntry[] {
  return buffer;
}

export function clearLogs() {
  buffer = [];
  notify();
}

export function copyLogsAsText(): string {
  return buffer
    .map((e) => {
      const t = new Date(e.ts).toISOString();
      const d = e.detail ? `\n  ${e.detail.replace(/\n/g, "\n  ")}` : "";
      return `[${t}] ${e.level.toUpperCase()} [${e.source}] ${e.message}${d}`;
    })
    .join("\n\n");
}

function formatArgs(args: unknown[]): string {
  return args
    .map((a) => {
      if (typeof a === "string") {
        return a;
      }
      if (a instanceof Error) {
        return a.stack ?? a.message;
      }
      try {
        return JSON.stringify(a);
      } catch {
        return String(a);
      }
    })
    .join(" ");
}

let installed = false;

/** 在应用入口调用一次：劫持 console.error/warn、window.onerror、unhandledrejection */
export function installGlobalLogging() {
  if (installed || typeof window === "undefined") {
    return;
  }
  installed = true;

  const origErr = console.error.bind(console);
  const origWarn = console.warn.bind(console);

  console.error = (...args: unknown[]) => {
    push({ level: "error", source: "console", message: formatArgs(args) });
    origErr(...args);
  };
  console.warn = (...args: unknown[]) => {
    push({ level: "warn", source: "console", message: formatArgs(args) });
    origWarn(...args);
  };

  window.addEventListener("error", (ev) => {
    const msg = ev.message || "error";
    const where = ev.filename ? `${ev.filename}:${ev.lineno}` : "";
    push({
      level: "error",
      source: "app",
      message: `window.onerror: ${msg}${where ? ` @ ${where}` : ""}`,
      detail: ev.error instanceof Error ? ev.error.stack : undefined,
    });
  });

  window.addEventListener("unhandledrejection", (ev) => {
    const r = ev.reason;
    const msg = r instanceof Error ? r.message : String(r);
    push({
      level: "error",
      source: "app",
      message: `unhandledrejection: ${msg}`,
      detail: r instanceof Error ? r.stack : typeof r === "string" ? r : undefined,
    });
  });
}

const HEAVY_PATH_PREFIXES = [
  "/api/exam/export",
  "/api/exam/validate",
  "/api/bank/import-bundle",
  "/api/bank/import",
];

function isHeavyApiPath(path: string): boolean {
  const p = path.split("?")[0] ?? path;
  return HEAVY_PATH_PREFIXES.some((prefix) => p === prefix || p.startsWith(`${prefix}?`));
}

/** 由 api/client 在请求完成后调用 */
export function logApiCall(args: {
  path: string;
  method: string;
  ok: boolean;
  status: number;
  ms: number;
  detail?: string;
}) {
  const { path, method, ok, status, ms, detail } = args;
  if (ok) {
    if (method === "GET" && !isHeavyApiPath(path)) {
      return;
    }
    push({
      level: "info",
      source: "network",
      message: `${method} ${path} → ${status} (${ms}ms)`,
    });
    return;
  }
  push({
    level: "error",
    source: "network",
    message: `${method} ${path} → ${status || "—"} (${ms}ms)`,
    detail,
  });
}
