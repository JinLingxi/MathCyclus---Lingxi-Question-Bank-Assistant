import i18n from "../i18n/i18n";
import { logApiCall } from "../lib/appLog";

let apiBaseResolved: string | null = null;
let apiBasePromise: Promise<string> | null = null;

async function resolveApiBase(): Promise<string> {
  if (apiBaseResolved !== null) return apiBaseResolved;
  const w = typeof window !== "undefined" ? window : undefined;
  const isTauri =
    w &&
    ("__TAURI_INTERNALS__" in w ||
      (w as unknown as { __TAURI__?: unknown }).__TAURI__ !== undefined);
  if (isTauri) {
    const { invoke } = await import("@tauri-apps/api/core");
    const port = await invoke<number>("get_backend_port");
    apiBaseResolved = `http://127.0.0.1:${port}`;
    return apiBaseResolved;
  }
  apiBaseResolved = "";
  return apiBaseResolved;
}

/** 桌面壳（Tauri）下解析后端端口；浏览器开发环境为空字符串（走 Vite 代理）。 */
export async function ensureApiBase(): Promise<void> {
  if (!apiBasePromise) {
    apiBasePromise = resolveApiBase();
  }
  await apiBasePromise;
}

function joinApi(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  const base = apiBaseResolved ?? "";
  if (!base) return path;
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

/** 用于少数直接 `fetch` 的场景（如下载流）。 */
export async function resolveApiUrl(path: string): Promise<string> {
  await ensureApiBase();
  return joinApi(path);
}

/**
 * `resource/` 下文件的 HTTP 路径（桌面壳下需带后端 origin，见 main.tsx 中 `ensureApiBase` 已先完成）。
 */
export function resourceApiUrl(resourceRel: string): string {
  const rel = resourceRel
    .split("/")
    .map((s) => encodeURIComponent(s))
    .join("/");
  return joinApi(`/api/resource/${rel}`);
}

/**
 * 手册 Markdown、富文本里以 `/api/...` 开头的绝对路径（如 `/api/help/asset/...`），
 * 在 Tauri 壳下需拼上后端 origin，否则图片会请求到 WebView 自身页面而显示损坏。
 */
export function apiAbsoluteUrl(path: string): string {
  const p = path.trim();
  if (!p) return p;
  if (
    p.startsWith("http://") ||
    p.startsWith("https://") ||
    p.startsWith("data:") ||
    p.startsWith("blob:")
  ) {
    return p;
  }
  if (p.startsWith("//")) return p;
  const normalized = p.startsWith("/") ? p : `/${p}`;
  return joinApi(normalized);
}

/** Prefer RFC 5987 filename* (UTF-8) so non-ASCII names from the backend are preserved. */
function filenameFromContentDisposition(cd: string | null): string | null {
  if (!cd) {
    return null;
  }
  const star = /filename\*=UTF-8''([^;\s]+)/i.exec(cd);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1]);
    } catch {
      /* fall through */
    }
  }
  const m = /filename="([^"]+)"/.exec(cd);
  return m?.[1] ?? null;
}

export type DraftSavedPayload = { draft_id: string; name: string };

export class ApiError extends Error {
  readonly status: number;
  readonly draftSaved?: DraftSavedPayload;

  constructor(message: string, status: number, opts?: { draftSaved?: DraftSavedPayload }) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.draftSaved = opts?.draftSaved;
  }
}

async function parseDetailFromResponse(r: Response): Promise<{
  message: string;
  draftSaved?: DraftSavedPayload;
}> {
  try {
    const j = (await r.json()) as { detail?: unknown };
    if (typeof j.detail === "string") {
      return { message: j.detail };
    }
    if (Array.isArray(j.detail)) {
      return {
        message: j.detail
          .map((x: { msg?: string }) => x?.msg)
          .filter(Boolean)
          .join("; "),
      };
    }
    if (j.detail && typeof j.detail === "object" && !Array.isArray(j.detail)) {
      const d = j.detail as Record<string, unknown>;
      const msg =
        typeof d.message === "string" && d.message.trim()
          ? d.message
          : r.statusText || "Request failed";
      const raw = d.draft_saved;
      let draftSaved: DraftSavedPayload | undefined;
      if (raw && typeof raw === "object" && raw !== null) {
        const o = raw as Record<string, unknown>;
        if (typeof o.draft_id === "string") {
          draftSaved = { draft_id: o.draft_id, name: typeof o.name === "string" ? o.name : "" };
        }
      }
      return { message: msg, draftSaved };
    }
  } catch {
    /* ignore */
  }
  return { message: r.statusText || "Request failed" };
}

function isHeavyApiPath(path: string): boolean {
  const p = path.split("?")[0] ?? "";
  return (
    p === "/api/exam/export" ||
    p === "/api/exam/validate" ||
    p === "/api/bank/import-bundle" ||
    p === "/api/bank/import" ||
    p === "/api/bank/export-bundle"
  );
}

async function fetchWithLog(path: string, init?: RequestInit): Promise<Response> {
  await ensureApiBase();
  const url = joinApi(path);
  const t0 = performance.now();
  const method = init?.method ?? "GET";
  let r: Response;
  try {
    r = await fetch(url, init);
  } catch (e) {
    const ms = Math.round(performance.now() - t0);
    const msg = e instanceof Error ? e.message : String(e);
    logApiCall({
      path,
      method,
      ok: false,
      status: 0,
      ms,
      detail: i18n.t("networkError", { ns: "common", detail: msg }),
    });
    throw e instanceof Error ? e : new Error(msg);
  }
  const ms = Math.round(performance.now() - t0);
  if (!r.ok) {
    const parsed = await parseDetailFromResponse(r);
    logApiCall({ path, method, ok: false, status: r.status, ms, detail: parsed.message });
    throw new ApiError(parsed.message, r.status, { draftSaved: parsed.draftSaved });
  }
  if (method !== "GET" || isHeavyApiPath(path)) {
    logApiCall({ path, method, ok: true, status: r.status, ms });
  }
  return r;
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetchWithLog(path);
  return r.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetchWithLog(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json() as Promise<T>;
}

/** multipart/form-data POST — do not set Content-Type (browser sets boundary). */
export async function apiPostFormData<T>(path: string, formData: FormData): Promise<T> {
  const r = await fetchWithLog(path, { method: "POST", body: formData });
  return r.json() as Promise<T>;
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const r = await fetchWithLog(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json() as Promise<T>;
}

export async function apiDelete<T>(path: string): Promise<T> {
  const r = await fetchWithLog(path, { method: "DELETE" });
  return r.json() as Promise<T>;
}

/** Download strict bank exchange ZIP (POST /api/bank/export-bundle — 避免 GET 查询串中 namespace 含 / 时的编码问题). */
export async function downloadBankExportBundle(namespace: string): Promise<void> {
  const path = `/api/bank/export-bundle`;
  await ensureApiBase();
  const requestUrl = joinApi(path);
  const t0 = performance.now();
  let r: Response;
  try {
    r = await fetch(requestUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ namespace }),
    });
  } catch (e) {
    const ms = Math.round(performance.now() - t0);
    const msg = e instanceof Error ? e.message : String(e);
    logApiCall({
      path,
      method: "POST",
      ok: false,
      status: 0,
      ms,
      detail: i18n.t("networkError", { ns: "common", detail: msg }),
    });
    throw e instanceof Error ? e : new Error(msg);
  }
  const ms = Math.round(performance.now() - t0);
  if (!r.ok) {
    const parsed = await parseDetailFromResponse(r);
    logApiCall({ path, method: "POST", ok: false, status: r.status, ms, detail: parsed.message });
    throw new ApiError(parsed.message, r.status, { draftSaved: parsed.draftSaved });
  }
  logApiCall({ path, method: "POST", ok: true, status: r.status, ms });
  const cd = r.headers.get("Content-Disposition");
  const filename = filenameFromContentDisposition(cd) ?? "bank-export.bank.zip";
  const blob = await r.blob();
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objectUrl;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(objectUrl);
}

/** 知识点 id 中可含 `/`，需按段编码后再拼到路径。 */
export function encodeGraphNodePathSegment(nodeId: string): string {
  return nodeId.split("/").map(encodeURIComponent).join("/");
}

export async function apiGraphListNodes(
  nodeKind?: string,
): Promise<{ nodes: any[]; kind_counts?: Record<string, number> }> {
  const qs = nodeKind ? `?node_kind=${encodeURIComponent(nodeKind)}` : "";
  return apiGet<{ nodes: any[]; kind_counts?: Record<string, number> }>(`/api/graph/nodes${qs}`);
}

export async function apiGraphCreateNode(body: unknown): Promise<{ ok: boolean; node_id: string }> {
  return apiPost<{ ok: boolean; node_id: string }>("/api/graph/nodes", body);
}

export async function apiGraphUpdateNode(nodeId: string, body: unknown): Promise<{ ok: boolean }> {
  return apiPut<{ ok: boolean }>(`/api/graph/nodes/${encodeGraphNodePathSegment(nodeId)}`, body);
}

export async function apiGraphDeleteNode(nodeId: string): Promise<{ ok: boolean }> {
  return apiDelete<{ ok: boolean }>(`/api/graph/nodes/${encodeGraphNodePathSegment(nodeId)}`);
}

export async function apiGraphCreateRelation(body: unknown): Promise<{ ok: boolean; relation_id: string }> {
  return apiPost<{ ok: boolean; relation_id: string }>("/api/graph/relations", body);
}

export async function apiGraphCreateBinding(body: unknown): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>("/api/graph/bindings", body);
}

export async function apiGraphUnbindBinding(body: unknown): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>("/api/graph/bindings/unbind", body);
}

export async function apiGraphListQuestionsForNode(nodeId: string): Promise<{ questions: any[] }> {
  return apiGet<{ questions: any[] }>(`/api/graph/nodes/${encodeGraphNodePathSegment(nodeId)}/questions`);
}

export async function apiGraphQuestionNodes(
  qualifiedId: string,
): Promise<{ nodes: { id: string; canonical_name: string; node_kind: string; subject: string | null }[] }> {
  return apiGet(`/api/graph/question-nodes?qualified_id=${encodeURIComponent(qualifiedId)}`);
}

export async function apiGraphQuestionBindingsIndex(): Promise<{
  index: Record<string, { id: string; canonical_name: string; node_kind: string }[]>;
}> {
  return apiGet("/api/graph/question-bindings-index");
}

export async function apiGraphBindBatch(
  nodeId: string,
  qualifiedIds: string[],
): Promise<{ added: number; skipped: number }> {
  return apiPost(`/api/graph/nodes/${encodeGraphNodePathSegment(nodeId)}/bind-batch`, {
    qualified_ids: qualifiedIds,
  });
}

export async function apiGraphUnbindBatch(
  nodeId: string,
  qualifiedIds: string[],
): Promise<{ removed: number }> {
  const path = `/api/graph/nodes/${encodeGraphNodePathSegment(nodeId)}/unbind-batch`;
  const r = await fetchWithLog(path, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ qualified_ids: qualifiedIds }),
  });
  return r.json() as Promise<{ removed: number }>;
}

export async function apiGraphListRelations(): Promise<{ relations: any[] }> {
  return apiGet<{ relations: any[] }>("/api/graph/relations");
}

export async function apiGraphDeleteRelation(relationId: string): Promise<{ ok: boolean }> {
  return apiDelete<{ ok: boolean }>(`/api/graph/relations/${encodeURIComponent(relationId)}`);
}

export async function apiGraphGetTaxonomy(): Promise<{ subjects: string[]; levels: string[] }> {
  return apiGet<{ subjects: string[]; levels: string[] }>("/api/graph/taxonomy");
}

export async function apiGraphPutTaxonomy(body: { subjects: string[]; levels: string[] }): Promise<{ ok: boolean }> {
  return apiPut<{ ok: boolean }>("/api/graph/taxonomy", body);
}

export async function apiGraphListResourceFiles(q: string, limit?: number): Promise<{ files: { path: string; size: number }[] }> {
  const p = new URLSearchParams();
  if (q) p.set("q", q);
  if (limit != null) p.set("limit", String(limit));
  const qs = p.toString();
  return apiGet<{ files: { path: string; size: number }[] }>(`/api/graph/resource-files${qs ? `?${qs}` : ""}`);
}

export async function apiGraphListNodeFiles(nodeId: string): Promise<{ links: { id: string; node_id: string; relative_path: string }[] }> {
  return apiGet(`/api/graph/nodes/${encodeGraphNodePathSegment(nodeId)}/files`);
}

export async function apiGraphAttachFile(body: { node_id: string; relative_path: string }): Promise<{ ok: boolean; link_id: string }> {
  return apiPost<{ ok: boolean; link_id: string }>("/api/graph/file-links", body);
}

export async function apiGraphDetachFile(linkId: string): Promise<{ ok: boolean }> {
  return apiDelete<{ ok: boolean }>(`/api/graph/file-links/${encodeURIComponent(linkId)}`);
}

export async function apiGraphUploadMaterial(file: File): Promise<{ ok: boolean; relative_path: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetchWithLog("/api/graph/upload", { method: "POST", body: fd });
  return r.json() as Promise<{ ok: boolean; relative_path: string }>;
}

export type AnalysisScript = {
  script_id: string;
  name: string;
  language: string;
  code: string;
  created_at?: string;
  updated_at?: string;
};

export type AnalysisFolderScript = {
  path: string;
  name: string;
  updated_at: number;
};

export type AnalysisJob = {
  job_id: string;
  kind: string;
  status: string;
  error?: string | null;
  output_ref?: string | null;
  created_at?: string;
  updated_at?: string;
};

export async function apiAnalysisListTools(): Promise<{ tools: any[] }> {
  return apiGet<{ tools: any[] }>("/api/analysis/tools");
}

export async function apiAnalysisDiagnosisKnowledge(examId: string, batchId: string): Promise<any> {
  const q = new URLSearchParams({ exam_id: examId, batch_id: batchId });
  return apiGet(`/api/analysis/diagnosis/knowledge?${q}`);
}

export async function apiAnalysisDiagnosisStudent(
  examId: string,
  batchId: string,
  studentId?: string,
): Promise<any> {
  const q = new URLSearchParams({ exam_id: examId, batch_id: batchId });
  if (studentId) q.set("student_id", studentId);
  return apiGet(`/api/analysis/diagnosis/student?${q}`);
}

export async function apiAnalysisDiagnosisHeatmap(examId: string, batchId: string): Promise<any> {
  const q = new URLSearchParams({ exam_id: examId, batch_id: batchId });
  return apiGet(`/api/analysis/diagnosis/class-heatmap?${q}`);
}

export async function apiAnalysisDiagnosisSuggestions(examId: string, batchId: string): Promise<any> {
  const q = new URLSearchParams({ exam_id: examId, batch_id: batchId });
  return apiGet(`/api/analysis/diagnosis/suggestions?${q}`);
}

export async function apiAnalysisInvokeTool(toolName: string, argumentsBody: Record<string, unknown>): Promise<any> {
  return apiPost(`/api/analysis/tools/${encodeURIComponent(toolName)}`, { arguments: argumentsBody });
}

export async function apiAnalysisListScripts(): Promise<{ scripts: AnalysisScript[] }> {
  return apiGet<{ scripts: AnalysisScript[] }>("/api/analysis/scripts");
}

export async function apiAnalysisSaveScript(payload: {
  script_id?: string;
  name: string;
  language?: string;
  code: string;
}): Promise<{ script: AnalysisScript }> {
  return apiPost<{ script: AnalysisScript }>("/api/analysis/scripts", payload);
}

export async function apiAnalysisDeleteScript(scriptId: string): Promise<{ ok: boolean }> {
  return apiDelete<{ ok: boolean }>(`/api/analysis/scripts/${encodeURIComponent(scriptId)}`);
}

export async function apiAnalysisRunBuiltin(payload: {
  builtin_id: string;
  exam_id: string;
  batch_id: string;
  recompute?: boolean;
  request_id?: string;
}): Promise<{ job_id: string; status: string; output?: any }> {
  return apiPost<{ job_id: string; status: string; output?: any }>("/api/analysis/jobs/builtin", payload);
}

export async function apiAnalysisRunScript(payload: {
  script_id: string;
  exam_id: string;
  batch_id: string;
  request_id?: string;
}): Promise<{ job_id: string; status: string; output?: any }> {
  return apiPost<{ job_id: string; status: string; output?: any }>("/api/analysis/jobs/script", payload);
}

export async function apiAnalysisListFolderScripts(): Promise<{ scripts: AnalysisFolderScript[] }> {
  return apiGet<{ scripts: AnalysisFolderScript[] }>("/api/analysis/folder-scripts");
}

export async function apiAnalysisRunFolderScript(payload: {
  script_path: string;
  exam_id: string;
  batch_id: string;
  request_id?: string;
}): Promise<{ job_id: string; status: string; output?: any; error?: string; error_code?: string }> {
  return apiPost("/api/analysis/jobs/script-from-folder", payload);
}

export async function apiAnalysisListJobs(limit = 50): Promise<{ jobs: AnalysisJob[] }> {
  return apiGet<{ jobs: AnalysisJob[] }>(`/api/analysis/jobs?limit=${encodeURIComponent(String(limit))}`);
}

export async function apiAnalysisGetJob(jobId: string, includeOutput = true): Promise<{ job: AnalysisJob; output?: any }> {
  const p = includeOutput ? "true" : "false";
  return apiGet<{ job: AnalysisJob; output?: any }>(
    `/api/analysis/jobs/${encodeURIComponent(jobId)}?include_output=${p}`,
  );
}

export async function apiBankSubjects(): Promise<{ subjects: string[] }> {
  return apiGet<{ subjects: string[] }>("/api/bank/subjects");
}

export async function apiBankCollections(): Promise<{ collections: any[] }> {
  return apiGet<{ collections: any[] }>("/api/bank/collections");
}

export async function apiBankItems(): Promise<{ items: any[] }> {
  return apiGet<{ items: any[] }>("/api/bank/items");
}

// --- Agent (M3) ---
export type AgentConfig = {
  llm_configured: boolean;
  main_model: string;
  fast_model: string;
  base_url_set: boolean;
  safety_mode?: string;
};

export async function apiAgentConfig(): Promise<AgentConfig> {
  return apiGet<AgentConfig>("/api/agent/config");
}

export type AgentLlmSettingsResponse = {
  persist_available: boolean;
  main_model: string;
  fast_model: string;
  base_url: string;
  llm_configured: boolean;
  api_key_masked: string | null;
  has_project_api_key_override: boolean;
};

export async function apiAgentLlmSettingsGet(): Promise<AgentLlmSettingsResponse> {
  return apiGet<AgentLlmSettingsResponse>("/api/agent/llm-settings");
}

export async function apiAgentLlmSettingsPut(body: {
  main_model?: string | null;
  fast_model?: string | null;
  base_url?: string | null;
  api_key?: string | null;
  clear_api_key_override?: boolean;
}): Promise<{ ok: boolean }> {
  return apiPut<{ ok: boolean }>("/api/agent/llm-settings", body);
}

export type AgentSafetyModeOption = {
  id: string;
  label: string;
  description: string;
};

export type AgentSafetyModeResponse = {
  persist_available: boolean;
  mode: string;
  options: AgentSafetyModeOption[];
};

export async function apiAgentSafetyModeGet(): Promise<AgentSafetyModeResponse> {
  return apiGet<AgentSafetyModeResponse>("/api/agent/safety-mode");
}

export async function apiAgentSafetyModePut(mode: string): Promise<{ ok: boolean }> {
  return apiPut<{ ok: boolean }>("/api/agent/safety-mode", { mode });
}

export async function apiAgentCreateSession(): Promise<{ session_id: string }> {
  return apiPost<{ session_id: string }>("/api/agent/sessions", {});
}

export type AgentSessionListItem = {
  session_id: string;
  updated_at: string;
  message_count: number;
  title: string;
};

export async function apiAgentSessionsList(): Promise<{ sessions: AgentSessionListItem[] }> {
  return apiGet<{ sessions: AgentSessionListItem[] }>("/api/agent/sessions");
}

export type AgentSessionSnapshot = {
  session: {
    session_id: string;
    messages: Array<{
      role: string;
      content?: string | null;
      tool_calls?: unknown;
      tool_call_id?: string | null;
      name?: string | null;
    }>;
  };
};

export async function apiAgentSessionGet(sessionId: string): Promise<AgentSessionSnapshot> {
  return apiGet<AgentSessionSnapshot>(`/api/agent/sessions/${encodeURIComponent(sessionId)}`);
}

export async function apiAgentSessionCancel(sessionId: string): Promise<{ ok: boolean }> {
  return apiPost<{ ok: boolean }>(`/api/agent/sessions/${encodeURIComponent(sessionId)}/cancel`, {});
}

export type AgentSkillInfo = {
  id: string;
  label: string;
  description: string;
  suggested_user_input: string;
};

export async function apiAgentSkillsList(): Promise<{ skills: AgentSkillInfo[] }> {
  return apiGet<{ skills: AgentSkillInfo[] }>("/api/agent/skills");
}

export async function apiAgentMemoryIndexGet(): Promise<{ content: string }> {
  return apiGet<{ content: string }>("/api/agent/memory");
}

export async function apiAgentMemoryIndexPut(content: string): Promise<{ ok: boolean }> {
  return apiPut<{ ok: boolean }>("/api/agent/memory", { content });
}

export async function apiAgentMemoryTopicList(): Promise<{ topics: string[] }> {
  return apiGet<{ topics: string[] }>("/api/agent/memory/topics");
}

export async function apiAgentMemoryTopicGet(topic: string): Promise<{ topic: string; content: string }> {
  const t = topic.endsWith(".md") ? topic : `${topic}.md`;
  return apiGet<{ topic: string; content: string }>(`/api/agent/memory/${encodeURIComponent(t)}`);
}

export async function apiAgentMemoryTopicPut(topic: string, content: string): Promise<{ ok: boolean }> {
  const t = topic.endsWith(".md") ? topic : `${topic}.md`;
  return apiPut<{ ok: boolean }>(`/api/agent/memory/${encodeURIComponent(t)}`, { content });
}

export type AgentPageContextForApi = {
  current_page: string;
  selected_resource_type?: string | null;
  selected_resource_id?: string | null;
  summary?: string | null;
};

export type AgentFileAttachment = {
  path: string;
  mime_type: string | null;
  original_name: string;
};

export type AgentChatStreamBody = {
  session_id?: string | null;
  message?: string | null;
  mode?: string;
  confirm_action_id?: string | null;
  confirm_accepted?: boolean | null;
  /** 教师当前界面与选中资源，供助手理解上下文 */
  page_context?: AgentPageContextForApi | null;
  /** 内置技能，收窄助手能力范围 */
  skill_id?: string | null;
  /** 附件文件列表 */
  file_attachments?: AgentFileAttachment[] | null;
  /** 教师批准执行的计划文件项目内相对路径 */
  execution_plan_path?: string | null;
};

/** Parse SSE lines; invokes onEvent(eventName, dataObj) for each complete event. */
export async function apiAgentChatStream(
  body: AgentChatStreamBody,
  onEvent: (event: string, data: Record<string, unknown>) => void,
  options?: { signal?: AbortSignal },
): Promise<void> {
  await ensureApiBase();
  const r = await fetch(joinApi("/api/agent/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal: options?.signal,
  });
  if (!r.ok) {
    const parsed = await parseDetailFromResponse(r);
    throw new ApiError(parsed.message, r.status, { draftSaved: parsed.draftSaved });
  }
  const reader = r.body?.getReader();
  if (!reader) throw new Error(i18n.t("noResponseStream", { ns: "common" }));
  const dec = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let ev = "message";
        const dataLines: string[] = [];
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) ev = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (dataLines.length === 0) continue;
        try {
          const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
          onEvent(ev, data);
        } catch {
          onEvent(ev, { raw: dataLines.join("\n") });
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
