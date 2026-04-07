import { useCallback, useEffect, useRef, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import {
  Bot,
  BookMarked,
  ChevronDown,
  ChevronRight,
  History,
  Loader2,
  PanelRightClose,
  Paperclip,
  Send,
  Sparkles,
  AlertCircle,
  Square,
  X,
  FileText,
  Play,
  Pencil,
} from "lucide-react";
import {
  apiAgentChatStream,
  apiAgentConfig,
  apiAgentCreateSession,
  apiAgentMemoryIndexGet,
  apiAgentMemoryIndexPut,
  apiAgentMemoryTopicGet,
  apiAgentMemoryTopicList,
  apiAgentMemoryTopicPut,
  apiAgentSessionCancel,
  apiAgentSessionGet,
  apiAgentSessionsList,
  apiAgentSkillsList,
  apiPostFormData,
  type AgentConfig,
  type AgentSessionListItem,
  type AgentSkillInfo,
} from "../api/client";
import { useAgentContext } from "../contexts/AgentContext";
import i18n from "../i18n/i18n";

type FileAttachment = { path: string; mime_type: string | null; original_name: string };

type ChatLine =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string }
  | { kind: "tool"; tool_name: string; summary: string; subagent?: boolean }
  | { kind: "tool_pending"; tool_name: string; label: string; key: string }
  | {
      kind: "confirm";
      action_id: string;
      tool_name: string;
      description: string;
      resolved?: "accepted" | "rejected";
    }
  | {
      kind: "plan_ready";
      plan_file_path: string;
      content: string;
      resolved?: "execute" | "modify" | "cancel";
    }
  | { kind: "system"; text: string };

type TaskStep = { title: string; status: string };

function formatToolLineLabel(raw: string): string {
  const p = (k: string) => i18n.t(`agent:toolPrefix.${k}`);
  return raw
    .replace(/^analysis\./, p("analysis"))
    .replace(/^exam\./, p("exam"))
    .replace(/^graph\./, p("graph"))
    .replace(/^bank\./, p("bank"))
    .replace(/^memory\./, p("memory"))
    .replace(/^file\./, p("file"))
    .replace(/^doc\./, p("doc"))
    .replace(/^agent\./, p("agent"));
}

function mapSessionMessagesToLines(
  messages: Array<{
    role: string;
    content?: string | null;
    tool_calls?: unknown;
    name?: string | null;
  }>,
): ChatLine[] {
  const out: ChatLine[] = [];
  for (const m of messages) {
    if (m.role === "user") {
      const t = (m.content || "").trim();
      if (t) out.push({ kind: "user", text: t });
    } else if (m.role === "assistant") {
      const c = (m.content || "").trim();
      if (c) out.push({ kind: "assistant", text: c });
    } else if (m.role === "tool") {
      const name = formatToolLineLabel(m.name || i18n.t("agent:toolOp"));
      const raw = (m.content || "").trim();
      const summary =
        raw.length > 180 ? `${raw.slice(0, 177)}…` : raw || i18n.t("agent:toolDone");
      out.push({ kind: "tool", tool_name: name, summary });
    }
  }
  return out;
}

export function AgentChatPanel({
  projectBound = false,
  onRequestCollapse,
}: {
  projectBound?: boolean;
  onRequestCollapse?: () => void;
} = {}) {
  const { t } = useTranslation("agent");
  const { pageContext, sidebarOpen, notifyAgentBackground } = useAgentContext();
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [taskSteps, setTaskSteps] = useState<TaskStep[] | null>(null);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [memoryTab, setMemoryTab] = useState<"index" | "topic">("index");
  const [indexDraft, setIndexDraft] = useState("");
  const [topicDraft, setTopicDraft] = useState("");
  const [topicPick, setTopicPick] = useState("");
  const [topicOptions, setTopicOptions] = useState<string[]>([]);
  const [memoryBusy, setMemoryBusy] = useState(false);
  const [memoryMsg, setMemoryMsg] = useState<string | null>(null);
  const [thinkingText, setThinkingText] = useState<string | null>(null);
  const [skills, setSkills] = useState<AgentSkillInfo[]>([]);
  const [activeSkillId, setActiveSkillId] = useState<string | null>(null);
  const [sessionList, setSessionList] = useState<AgentSessionListItem[]>([]);
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [currentFocus, setCurrentFocus] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const assistantSegmentClosedRef = useRef(false);
  const streamAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    void apiAgentConfig()
      .then(setConfig)
      .catch(() => setConfig(null));
    void apiAgentSkillsList()
      .then((r) => setSkills(r.skills || []))
      .catch(() => setSkills([]));
  }, [projectBound]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines, busy, thinkingText]);

  const refreshSessionList = useCallback(async () => {
    try {
      const { sessions } = await apiAgentSessionsList();
      setSessionList(sessions || []);
    } catch {
      setSessionList([]);
    }
  }, []);

  useEffect(() => {
    void refreshSessionList();
  }, [refreshSessionList]);

  const refreshMemoryIndex = useCallback(async () => {
    setMemoryBusy(true);
    setMemoryMsg(null);
    try {
      const { content } = await apiAgentMemoryIndexGet();
      setIndexDraft(content);
    } catch (e) {
      setMemoryMsg(e instanceof Error ? e.message : t("memoryIndexLoadErr"));
    } finally {
      setMemoryBusy(false);
    }
  }, [t]);

  const refreshTopicList = useCallback(async () => {
    try {
      const { topics } = await apiAgentMemoryTopicList();
      setTopicOptions(topics);
      setTopicPick((prev) => prev || topics[0] || "");
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (!memoryOpen) return;
    void refreshMemoryIndex();
    void refreshTopicList();
  }, [memoryOpen, refreshMemoryIndex, refreshTopicList]);

  const ensureSession = useCallback(async () => {
    if (sessionId) return sessionId;
    const { session_id } = await apiAgentCreateSession();
    setSessionId(session_id);
    void refreshSessionList();
    return session_id;
  }, [sessionId, refreshSessionList]);

  const buildChatBody = useCallback(
    (body: Parameters<typeof apiAgentChatStream>[0]): Parameters<typeof apiAgentChatStream>[0] => {
      let next = { ...body };
      if (activeSkillId) {
        next = { ...next, skill_id: activeSkillId };
      }
      if (!pageContext) return next;
      return {
        ...next,
        page_context: {
          current_page: pageContext.current_page,
          ...(pageContext.selected_resource_type != null
            ? { selected_resource_type: pageContext.selected_resource_type }
            : {}),
          ...(pageContext.selected_resource_id != null
            ? { selected_resource_id: pageContext.selected_resource_id }
            : {}),
          ...(pageContext.summary ? { summary: pageContext.summary } : {}),
        },
      };
    },
    [pageContext, activeSkillId],
  );

  const runStream = useCallback(
    async (body: Parameters<typeof apiAgentChatStream>[0]) => {
      setBusy(true);
      setThinkingText(null);
      const ac = new AbortController();
      streamAbortRef.current = ac;
      const payload = buildChatBody(body);
      try {
        await apiAgentChatStream(payload, (ev, data) => {
          if (ev === "session" && typeof data.session_id === "string") {
            setSessionId(data.session_id);
          }
          if (ev === "thinking" && typeof data.message === "string") {
            setThinkingText(data.message);
          }
          if (ev === "text_delta" && typeof data.text === "string") {
            const chunk = data.text;
            setThinkingText(null);
            setLines((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last?.kind === "assistant" && !assistantSegmentClosedRef.current) {
                next[next.length - 1] = { kind: "assistant", text: last.text + chunk };
              } else {
                assistantSegmentClosedRef.current = false;
                next.push({ kind: "assistant", text: chunk });
              }
              return next;
            });
          }
          if (ev === "tool_start") {
            assistantSegmentClosedRef.current = true;
            setThinkingText(null);
            const tool_name = String(data.tool_name ?? "");
            const label =
              typeof data.label === "string" ? data.label : formatToolLineLabel(tool_name);
            const key = `${tool_name}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
            setLines((prev) => [...prev, { kind: "tool_pending", tool_name, label, key }]);
          }
          if (ev === "tool_result") {
            assistantSegmentClosedRef.current = true;
            setThinkingText(null);
            const tool_name = String(data.tool_name ?? "");
            const summary = String(data.summary ?? data.status ?? "");
            const subagent = Boolean(data.subagent);
            setLines((prev) => {
              const next = [...prev];
              const idx = next.findIndex((l) => l.kind === "tool_pending" && l.tool_name === tool_name);
              if (idx >= 0) next.splice(idx, 1);
              next.push({ kind: "tool", tool_name, summary, subagent });
              return next;
            });
          }
          if (ev === "task_update") {
            const raw = data.steps;
            if (Array.isArray(raw)) {
              setTaskSteps(
                raw.map((s) => ({
                  title: String((s as { title?: string }).title ?? ""),
                  status: String((s as { status?: string }).status ?? ""),
                })),
              );
            }
          }
          if (ev === "memory_updated") {
            setLines((prev) => [...prev, { kind: "system", text: i18n.t("agent:memoryUpdatedRound") }]);
            if (!sidebarOpen) {
              notifyAgentBackground(i18n.t("agent:memoryUpdatedSidebar"), "success");
            }
          }
          if (ev === "memory_update_failed") {
            const msg = String(data.message ?? i18n.t("agent:memoryUpdateFail"));
            setLines((prev) => [...prev, { kind: "system", text: msg }]);
            if (!sidebarOpen) {
              notifyAgentBackground(i18n.t("agent:memoryWriteWarn", { msg: msg.slice(0, 80) }), "warning");
            }
          }
          if (ev === "confirm_needed") {
            const action_id = String(data.action_id ?? "");
            const tool_name = String(data.tool_name ?? "");
            const description = String(data.description ?? "");
            setLines((prev) => [...prev, { kind: "confirm", action_id, tool_name, description }]);
            if (!sidebarOpen) {
              notifyAgentBackground(i18n.t("agent:confirmOpenSidebar"), "warning");
            }
          }
          if (ev === "error") {
            const msg = String(data.message ?? i18n.t("agent:unknownErr"));
            setLines((prev) => [...prev, { kind: "system", text: msg }]);
            if (!sidebarOpen) {
              notifyAgentBackground(i18n.t("agent:assistantHint", { msg: msg.slice(0, 100) }), "warning");
            }
          }
          if (ev === "done") {
            setThinkingText(null);
            void refreshSessionList();
            if (!sidebarOpen) {
              notifyAgentBackground(i18n.t("agent:roundEnd"));
            }
          }
          if (ev === "focus_changed") {
            const focus = String(data.focus ?? "general");
            setCurrentFocus(focus);
            const label = i18n.t(`agent:focusLabels.${focus}`, { defaultValue: focus });
            setLines((prev) => [
              ...prev,
              { kind: "system", text: i18n.t("agent:switchedFocus", { label }) },
            ]);
          }
          if (ev === "plan_ready") {
            assistantSegmentClosedRef.current = true;
            const plan_file_path = String(data.plan_file_path ?? "");
            const content = String(data.content ?? "");
            setLines((prev) => [...prev, { kind: "plan_ready", plan_file_path, content }]);
            if (!sidebarOpen) {
              notifyAgentBackground(i18n.t("agent:planReady"), "warning");
            }
          }
          if (ev === "subagent_start" || ev === "subagent_done") {
            const line =
              ev === "subagent_start"
                ? i18n.t("agent:subtaskStart", {
                    text: `${String(data.task_description ?? "").slice(0, 120)}…`,
                  })
                : i18n.t("agent:subtaskDone", {
                    text: `${String(data.summary ?? "").slice(0, 200)}…`,
                  });
            setLines((prev) => [...prev, { kind: "system", text: line }]);
          }
        }, { signal: ac.signal });
      } catch (e) {
        const aborted = e instanceof Error && e.name === "AbortError";
        if (aborted) {
          setLines((prev) => [...prev, { kind: "system", text: i18n.t("agent:stopped") }]);
        } else {
          const msg = e instanceof Error ? e.message : String(e);
          setLines((prev) => [...prev, { kind: "system", text: msg }]);
        }
      } finally {
        streamAbortRef.current = null;
        setBusy(false);
        setThinkingText(null);
      }
    },
    [buildChatBody, notifyAgentBackground, refreshSessionList, sidebarOpen],
  );

  const send = useCallback(async () => {
    const msgText = input.trim();
    if (!msgText || busy) return;
    setInput("");
    const filesToUpload = [...pendingFiles];
    setPendingFiles([]);
    setLines((prev) => [...prev, { kind: "user", text: msgText }]);
    const sid = await ensureSession();

    let attachments: FileAttachment[] | undefined;
    if (filesToUpload.length > 0) {
      attachments = [];
      for (const f of filesToUpload) {
        try {
          const fd = new FormData();
          fd.append("file", f);
          fd.append("session_id", sid);
          const res = await apiPostFormData<{
            ok: boolean; path: string; mime_type: string | null; original_name: string;
          }>("/api/agent/upload", fd);
          attachments.push({ path: res.path, mime_type: res.mime_type, original_name: res.original_name });
        } catch (e) {
          setLines((prev) => [
            ...prev,
            { kind: "system", text: i18n.t("agent:uploadFail", { name: f.name }) },
          ]);
        }
      }
    }

    await runStream({
      session_id: sid,
      message: msgText,
      mode: "execute",
      ...(attachments && attachments.length > 0 ? { file_attachments: attachments } : {}),
    } as Parameters<typeof apiAgentChatStream>[0]);
  }, [busy, ensureSession, input, pendingFiles, runStream]);

  const confirm = useCallback(
    async (action_id: string, accepted: boolean) => {
      if (busy) return;
      setLines((prev) =>
        prev.map((ln) =>
          ln.kind === "confirm" && ln.action_id === action_id
            ? { ...ln, resolved: accepted ? "accepted" : "rejected" }
            : ln,
        ),
      );
      const sid = await ensureSession();
      await runStream({
        session_id: sid,
        message: "",
        confirm_action_id: action_id,
        confirm_accepted: accepted,
      });
    },
    [busy, ensureSession, runStream],
  );

  const planAction = useCallback(
    async (action: "execute" | "modify" | "cancel", planPath: string) => {
      if (busy) return;
      setLines((prev) =>
        prev.map((ln) =>
          ln.kind === "plan_ready" && ln.plan_file_path === planPath
            ? { ...ln, resolved: action }
            : ln,
        ),
      );
      const sid = await ensureSession();
      if (action === "execute") {
        await runStream({
          session_id: sid,
          message: i18n.t("agent:executePlanMsg", { path: planPath }),
          mode: "execute",
          execution_plan_path: planPath,
        });
      } else if (action === "modify") {
        const feedback = window.prompt(i18n.t("agent:modifyPrompt"));
        if (feedback?.trim()) {
          await runStream({
            session_id: sid,
            message: i18n.t("agent:modifyPlanMsg", { feedback }),
            mode: "execute",
          });
        }
      }
    },
    [busy, ensureSession, runStream],
  );

  const newChat = useCallback(async () => {
    streamAbortRef.current?.abort();
    setSessionId(null);
    setLines([]);
    setTaskSteps(null);
    setActiveSkillId(null);
    const { session_id } = await apiAgentCreateSession();
    setSessionId(session_id);
    void refreshSessionList();
  }, [refreshSessionList]);

  const stopStream = useCallback(async () => {
    const sid = sessionId;
    streamAbortRef.current?.abort();
    if (sid) {
      try {
        await apiAgentSessionCancel(sid);
      } catch {
        /* ignore */
      }
    }
  }, [sessionId]);

  const loadHistorySession = useCallback(
    async (id: string) => {
      if (busy) return;
      setSessionMenuOpen(false);
      try {
        const snap = await apiAgentSessionGet(id);
        const msgs = snap.session?.messages ?? [];
        setSessionId(id);
        setLines(mapSessionMessagesToLines(msgs));
        setTaskSteps(null);
      } catch (e) {
        setMemoryMsg(e instanceof Error ? e.message : t("sessionLoadErr"));
      }
    },
    [busy, t],
  );

  const pickSkill = useCallback((s: AgentSkillInfo) => {
    setActiveSkillId(s.id);
    setInput(s.suggested_user_input);
  }, []);

  return (
    <div className="flex h-full min-h-[320px] flex-col border-t border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-100 px-2 py-1.5">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-700">
          <Sparkles className="h-3.5 w-3.5 text-violet-500" />
          {t("title")}
        </div>
        <div className="flex items-center gap-1">
          {onRequestCollapse && (
            <button
              type="button"
              title={t("collapseSidebar")}
              aria-label={t("collapseSidebar")}
              onClick={() => onRequestCollapse()}
              className="rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-800"
            >
              <PanelRightClose className="h-3.5 w-3.5" />
            </button>
          )}
          <div className="relative">
            <button
              type="button"
              onClick={() => setSessionMenuOpen((o) => !o)}
              className="flex items-center gap-0.5 rounded px-2 py-0.5 text-[11px] text-slate-600 hover:bg-slate-100"
            >
              <History className="h-3 w-3" />
              {t("history")}
              {sessionMenuOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            </button>
            {sessionMenuOpen && (
              <div className="absolute right-0 top-full z-20 mt-0.5 max-h-48 w-52 overflow-y-auto rounded border border-slate-200 bg-white py-1 text-[11px] shadow-md">
                {sessionList.length === 0 && <div className="px-2 py-1 text-slate-400">{t("noHistory")}</div>}
                {sessionList.map((s) => (
                  <button
                    key={s.session_id}
                    type="button"
                    className="block w-full truncate px-2 py-1 text-left hover:bg-violet-50"
                    title={s.title}
                    onClick={() => void loadHistorySession(s.session_id)}
                  >
                    {s.title}
                  </button>
                ))}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={() => setMemoryOpen((o) => !o)}
            className="flex items-center gap-0.5 rounded px-2 py-0.5 text-[11px] text-slate-600 hover:bg-slate-100"
          >
            <BookMarked className="h-3 w-3" />
            {t("longTermMemory")}
            {memoryOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </button>
          <button
            type="button"
            onClick={() => void newChat()}
            className="rounded px-2 py-0.5 text-[11px] text-slate-500 hover:bg-slate-100"
          >
            {t("newChat")}
          </button>
        </div>
      </div>
      {memoryOpen && (
        <div className="border-b border-slate-100 px-2 py-2 text-[11px] text-slate-700">
          <div className="mb-1 flex gap-1">
            <button
              type="button"
              className={`rounded px-2 py-0.5 ${memoryTab === "index" ? "bg-violet-100 text-violet-900" : "bg-slate-100"}`}
              onClick={() => setMemoryTab("index")}
            >
              {t("memoryIndex")}
            </button>
            <button
              type="button"
              className={`rounded px-2 py-0.5 ${memoryTab === "topic" ? "bg-violet-100 text-violet-900" : "bg-slate-100"}`}
              onClick={() => setMemoryTab("topic")}
            >
              {t("topicNotes")}
            </button>
          </div>
          {memoryMsg && <p className="mb-1 text-red-600">{memoryMsg}</p>}
          {memoryTab === "index" && (
            <div className="space-y-1">
              <textarea
                value={indexDraft}
                onChange={(e) => setIndexDraft(e.target.value)}
                rows={5}
                disabled={memoryBusy}
                className="w-full resize-y rounded border border-slate-200 px-1.5 py-1 font-mono text-[10px]"
              />
              <button
                type="button"
                disabled={memoryBusy}
                onClick={() => void apiAgentMemoryIndexPut(indexDraft).then(() => setMemoryMsg(t("indexSaved")))}
                className="rounded bg-violet-600 px-2 py-0.5 text-white hover:bg-violet-700 disabled:opacity-50"
              >
                {t("saveIndex")}
              </button>
            </div>
          )}
          {memoryTab === "topic" && (
            <div className="space-y-1">
              <div className="flex flex-wrap gap-1">
                <select
                  value={topicPick}
                  onChange={(e) => setTopicPick(e.target.value)}
                  className="max-w-[10rem] rounded border border-slate-200 px-1 py-0.5 text-[10px]"
                >
                  {topicOptions.map((topic) => (
                    <option key={topic} value={topic}>
                      {topic}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  disabled={memoryBusy || !topicPick}
                  onClick={() =>
                    void apiAgentMemoryTopicGet(topicPick).then((r) => {
                      setTopicDraft(r.content);
                      setMemoryMsg(null);
                    })
                  }
                  className="rounded border border-slate-200 px-2 py-0.5 hover:bg-slate-50 disabled:opacity-50"
                >
                  {t("load")}
                </button>
              </div>
              <textarea
                value={topicDraft}
                onChange={(e) => setTopicDraft(e.target.value)}
                rows={5}
                placeholder={t("topicDraftPh")}
                className="w-full resize-y rounded border border-slate-200 px-1.5 py-1 font-mono text-[10px]"
              />
              <button
                type="button"
                disabled={memoryBusy || !topicPick}
                onClick={() =>
                  void apiAgentMemoryTopicPut(topicPick, topicDraft).then(() => setMemoryMsg(t("topicSaved")))
                }
                className="rounded bg-violet-600 px-2 py-0.5 text-white hover:bg-violet-700 disabled:opacity-50"
              >
                {t("saveTopic")}
              </button>
            </div>
          )}
        </div>
      )}
      {config && !config.llm_configured && (
        <div className="mx-2 mt-2 flex gap-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] text-amber-900">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>
            <Trans
              ns="agent"
              i18nKey="noLlmConfig"
              components={{
                code1: <code className="rounded bg-amber-100 px-0.5" />,
                code2: <code className="rounded bg-amber-100 px-0.5" />,
                code3: <code className="rounded bg-amber-100 px-0.5" />,
                code4: <code className="rounded bg-amber-100 px-0.5" />,
              }}
            />
          </span>
        </div>
      )}
      <div className="flex-1 space-y-2 overflow-y-auto px-2 py-2 text-sm">
        {currentFocus && currentFocus !== "general" && (
          <div className="rounded border border-blue-100 bg-blue-50/60 px-2 py-1 text-[11px] text-blue-900">
            {t("currentFocus")}
            {t(`focusLabels.${currentFocus}`, { defaultValue: currentFocus })}
          </div>
        )}
        {activeSkillId && (
          <div className="rounded border border-violet-100 bg-violet-50/60 px-2 py-1 text-[11px] text-violet-900">
            {t("quickAssist")}
            {skills.find((x) => x.id === activeSkillId)?.label ?? activeSkillId}
            <button
              type="button"
              className="ml-2 text-violet-600 underline"
              onClick={() => setActiveSkillId(null)}
            >
              {t("clear")}
            </button>
          </div>
        )}
        {taskSteps && taskSteps.length > 0 && (
          <div className="rounded border border-violet-100 bg-violet-50/80 px-2 py-1.5 text-[11px] text-violet-950">
            <div className="font-medium text-violet-900">{t("currentSteps")}</div>
            <ol className="mt-1 list-decimal pl-4 text-violet-900">
              {taskSteps.map((s, j) => (
                <li key={j}>
                  <span className="text-violet-600">[{s.status}]</span> {s.title}
                </li>
              ))}
            </ol>
          </div>
        )}
        {pageContext?.summary && (
          <div className="rounded border border-slate-100 bg-slate-50/80 px-2 py-1.5 text-[11px] text-slate-600">
            {t("currentUi", { summary: pageContext.summary })}
          </div>
        )}
        {lines.length === 0 && skills.length > 0 && (
          <div className="space-y-1">
            <p className="text-[11px] text-slate-500">{t("quickStart")}</p>
            <div className="flex flex-wrap gap-1">
              {skills.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  title={s.description}
                  onClick={() => pickSkill(s)}
                  className="rounded-full border border-violet-200 bg-white px-2 py-0.5 text-[11px] text-violet-800 hover:bg-violet-50"
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        )}
        {lines.length === 0 && (
          <p className="text-xs text-slate-500">{t("freeformHint")}</p>
        )}
        {lines.map((ln, i) => (
          <div key={ln.kind === "tool_pending" ? ln.key : i}>
            {ln.kind === "user" && (
              <div className="ml-6 rounded-lg bg-blue-50 px-2 py-1.5 text-slate-800">{ln.text}</div>
            )}
            {ln.kind === "assistant" && ln.text && (
              <div className="mr-4 flex gap-2">
                <Bot className="mt-0.5 h-4 w-4 shrink-0 text-violet-500" />
                <div className="prose prose-sm max-w-none text-slate-800 prose-p:my-1 prose-headings:my-2">
                  <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                    {ln.text}
                  </ReactMarkdown>
                </div>
              </div>
            )}
            {ln.kind === "tool_pending" && (
              <div className="ml-6 flex items-center gap-2 rounded border border-dashed border-violet-200 bg-violet-50/50 px-2 py-1.5 text-[11px] text-violet-900">
                <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-violet-500" />
                <span>{ln.label}</span>
              </div>
            )}
            {ln.kind === "tool" && (
              <div
                className={`ml-6 rounded border px-2 py-1 text-[11px] ${
                  ln.subagent
                    ? "border-indigo-200 bg-indigo-50/90 text-indigo-950"
                    : "border-slate-200 bg-slate-50 text-slate-600"
                }`}
              >
                <span className="font-medium text-slate-600">
                  {ln.subagent ? t("subtaskPrefix") : ""}
                  {formatToolLineLabel(ln.tool_name)}
                </span>
                <div className="mt-0.5 text-slate-700">{ln.summary}</div>
              </div>
            )}
            {ln.kind === "confirm" && (
              <div className="ml-6 rounded-md border border-orange-200 bg-orange-50 p-2 text-[11px] text-orange-950">
                <div className="font-medium">{t("needConfirm", { name: ln.tool_name })}</div>
                <div className="mt-1 text-orange-900">{ln.description}</div>
                {ln.resolved ? (
                  <div className="mt-2 font-medium text-orange-900">
                    {ln.resolved === "accepted" ? t("accepted") : t("rejected")}
                  </div>
                ) : (
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void confirm(ln.action_id, true)}
                      className="rounded bg-orange-600 px-2 py-1 text-white hover:bg-orange-700 disabled:opacity-50"
                    >
                      {t("confirmBtn")}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void confirm(ln.action_id, false)}
                      className="rounded border border-orange-300 bg-white px-2 py-1 hover:bg-orange-100 disabled:opacity-50"
                    >
                      {t("cancelBtn")}
                    </button>
                  </div>
                )}
              </div>
            )}
            {ln.kind === "plan_ready" && (
              <div className="ml-6 rounded-md border border-emerald-200 bg-emerald-50 p-2 text-[11px] text-emerald-950">
                <div className="font-medium">{t("planGenerated")}</div>
                {ln.content && (
                  <pre className="mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap rounded bg-white/60 p-1.5 text-[10px] text-emerald-900">
                    {ln.content.slice(0, 3000)}
                  </pre>
                )}
                {ln.resolved ? (
                  <div className="mt-2 font-medium text-emerald-900">
                    {ln.resolved === "execute"
                      ? t("planExecute")
                      : ln.resolved === "modify"
                        ? t("planModify")
                        : t("planCancelled")}
                  </div>
                ) : (
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void planAction("execute", ln.plan_file_path)}
                      className="flex items-center gap-1 rounded bg-emerald-600 px-2 py-1 text-white hover:bg-emerald-700 disabled:opacity-50"
                    >
                      <Play className="h-3 w-3" /> {t("execute")}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void planAction("modify", ln.plan_file_path)}
                      className="flex items-center gap-1 rounded border border-emerald-300 bg-white px-2 py-1 hover:bg-emerald-100 disabled:opacity-50"
                    >
                      <Pencil className="h-3 w-3" /> {t("modify")}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void planAction("cancel", ln.plan_file_path)}
                      className="rounded border border-emerald-300 bg-white px-2 py-1 hover:bg-emerald-100 disabled:opacity-50"
                    >
                      {t("cancelBtn")}
                    </button>
                  </div>
                )}
              </div>
            )}
            {ln.kind === "system" && (
              <div className="text-center text-[11px] text-slate-500">{ln.text}</div>
            )}
          </div>
        ))}
        {thinkingText && (
          <div className="flex items-center gap-2 overflow-hidden text-xs text-violet-600">
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
            <span className="animate-pulse">{thinkingText}</span>
          </div>
        )}
        {busy && !thinkingText && (
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("processing")}
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="border-t border-slate-100 p-2">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          accept=".txt,.md,.yaml,.yml,.csv,.json,.xml,.docx,.doc,.pdf,.png,.jpg,.jpeg,.gif"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            if (files.length > 0) setPendingFiles((prev) => [...prev, ...files]);
            e.target.value = "";
          }}
        />
        {pendingFiles.length > 0 && (
          <div className="mb-1.5 flex flex-wrap gap-1">
            {pendingFiles.map((f, i) => (
              <div
                key={`${f.name}-${i}`}
                className="flex items-center gap-1 rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-700"
              >
                <FileText className="h-3 w-3 text-slate-400" />
                <span className="max-w-[120px] truncate">{f.name}</span>
                <button
                  type="button"
                  onClick={() => setPendingFiles((prev) => prev.filter((_, j) => j !== i))}
                  className="ml-0.5 text-slate-400 hover:text-red-500"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="flex gap-1">
          <button
            type="button"
            title={t("addAttachment")}
            aria-label={t("addAttachment")}
            onClick={() => fileInputRef.current?.click()}
            className="self-end rounded-md border border-slate-300 bg-white p-2 text-slate-500 hover:bg-slate-50 hover:text-slate-700"
          >
            <Paperclip className="h-4 w-4" />
          </button>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            onDrop={(e) => {
              e.preventDefault();
              const files = Array.from(e.dataTransfer.files);
              if (files.length > 0) setPendingFiles((prev) => [...prev, ...files]);
            }}
            onDragOver={(e) => e.preventDefault()}
            rows={2}
            placeholder={t("inputPh")}
            className="min-h-[44px] flex-1 resize-none rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          />
          {busy ? (
            <button
              type="button"
              title={t("stop")}
              aria-label={t("stop")}
              onClick={() => void stopStream()}
              className="self-end rounded-md border border-slate-300 bg-white p-2 text-slate-700 hover:bg-slate-50"
            >
              <Square className="h-4 w-4 fill-current" />
            </button>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() => void send()}
              className="self-end rounded-md bg-violet-600 p-2 text-white hover:bg-violet-700 disabled:opacity-50"
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
