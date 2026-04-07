import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

export type AgentWorkspacePage =
  | "compose"
  | "bank"
  | "template"
  | "graph"
  | "analysis"
  | "help"
  | "log"
  | "settings";

export type AgentPageContextPayload = {
  current_page: AgentWorkspacePage;
  selected_resource_type?: string | null;
  selected_resource_id?: string | null;
  summary?: string | null;
};

type AgentToast = {
  id: number;
  message: string;
  variant: "info" | "warning" | "success";
};

export type AgentContextValue = {
  sidebarOpen: boolean;
  setSidebarOpen: (v: boolean) => void;
  toggleSidebar: () => void;
  pageContext: AgentPageContextPayload | null;
  setPageContext: (p: AgentPageContextPayload | null) => void;
  notifyAgentBackground: (message: string, variant?: AgentToast["variant"]) => void;
};

const AgentContext = createContext<AgentContextValue | null>(null);

function AgentToastLayer({
  toasts,
  dismissToast,
  onOpenSidebar,
}: {
  toasts: AgentToast[];
  dismissToast: (id: number) => void;
  onOpenSidebar: () => void;
}) {
  const { t } = useTranslation("agent");
  return (
    <div
      className="pointer-events-none fixed bottom-4 right-4 z-[100] flex max-w-sm flex-col gap-2"
      aria-live="polite"
    >
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role="status"
          className={`pointer-events-auto flex items-start justify-between gap-2 rounded-lg border px-3 py-2 text-sm shadow-lg ${
            toast.variant === "warning"
              ? "border-amber-200 bg-amber-50 text-amber-950"
              : toast.variant === "success"
                ? "border-emerald-200 bg-emerald-50 text-emerald-950"
                : "border-slate-200 bg-white text-slate-800"
          }`}
        >
          <span className="min-w-0 flex-1">{toast.message}</span>
          <div className="flex shrink-0 gap-1">
            <button
              type="button"
              className="rounded px-2 py-0.5 text-xs font-medium text-violet-700 hover:bg-violet-50"
              onClick={() => {
                onOpenSidebar();
                dismissToast(toast.id);
              }}
            >
              {t("openSidebar")}
            </button>
            <button
              type="button"
              className="rounded px-1.5 text-slate-500 hover:bg-slate-100"
              aria-label={t("closeAria")}
              onClick={() => dismissToast(toast.id)}
            >
              ×
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

export function AgentProvider({ children }: { children: ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [pageContext, setPageContext] = useState<AgentPageContextPayload | null>(null);
  const [toasts, setToasts] = useState<AgentToast[]>([]);
  const toastSeq = useRef(0);

  const dismissToast = useCallback((id: number) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  const notifyAgentBackground = useCallback(
    (message: string, variant: AgentToast["variant"] = "info") => {
      const id = ++toastSeq.current;
      setToasts((t) => [...t, { id, message, variant }]);
      window.setTimeout(() => {
        dismissToast(id);
      }, 10_000);
    },
    [dismissToast],
  );

  const toggleSidebar = useCallback(() => setSidebarOpen((o) => !o), []);

  const value = useMemo(
    () => ({
      sidebarOpen,
      setSidebarOpen,
      toggleSidebar,
      pageContext,
      setPageContext,
      notifyAgentBackground,
    }),
    [sidebarOpen, toggleSidebar, pageContext, notifyAgentBackground],
  );

  return (
    <AgentContext.Provider value={value}>
      {children}
      <AgentToastLayer
        toasts={toasts}
        dismissToast={dismissToast}
        onOpenSidebar={() => setSidebarOpen(true)}
      />
    </AgentContext.Provider>
  );
}

export function useAgentContext(): AgentContextValue {
  const v = useContext(AgentContext);
  if (!v) {
    throw new Error("useAgentContext 须在 AgentProvider 内使用");
  }
  return v;
}
