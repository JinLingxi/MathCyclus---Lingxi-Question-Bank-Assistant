import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  apiAnalysisDiagnosisHeatmap,
  apiAnalysisDiagnosisKnowledge,
  apiAnalysisDiagnosisStudent,
  apiAnalysisDiagnosisSuggestions,
  apiAnalysisListJobs,
  apiAnalysisListFolderScripts,
  apiAnalysisListTools,
  apiAnalysisRunFolderScript,
  apiAnalysisRunBuiltin,
  apiDelete,
  apiGet,
  apiPost,
  apiPostFormData,
  resolveApiUrl,
  type AnalysisFolderScript,
  type AnalysisJob,
} from "../api/client";
import { useAgentContext } from "../contexts/AgentContext";
import { formatLocaleDate } from "../lib/locale";
import { cn } from "../lib/utils";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle,
  Download,
  FileSpreadsheet,
  RefreshCw,
  TrendingUp,
  Trash2,
  Upload,
  XCircle,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ExamResult = {
  exam_id: string;
  exam_title: string;
  subject: string | null;
  question_count: number;
  section_count: number;
  score_batch_count: number;
  has_score: boolean;
  latest_batch_id: string | null;
  result_dir: string;
  mtime: string;
};

type ScoreBatch = {
  batch_id: string;
  imported_at: string;
  student_count: number;
  question_count: number;
};

type ExamSummary = ExamResult & {
  questions: ExamQuestion[];
  score_batches: ScoreBatch[];
};

type ExamQuestion = {
  idx: number;
  header: string;
  section_id: string;
  question_id: string;
  question_in_section: number;
  score_per_item: number;
};

type ImportResult = {
  batch_id: string;
  student_count: number;
  question_count: number;
  warnings: Array<{ question_id: string; header: string; message: string }>;
  missing_headers: string[];
};

type QuestionStat = {
  question_id: string;
  header: string;
  section_id: string;
  score_per_item: number;
  answered_count: number;
  error_rate: number | null;
  avg_score_ratio: number | null;
  avg_raw_score: number | null;
};

type NodeStat = {
  node_id: string;
  bound_question_count: number;
  bound_questions: string[];
  mastery_fuzzy: number;
  error_rate: number;
};

type StudentStat = {
  name: string;
  student_id: string;
  raw_total: number;
  score_ratio: number;
  fuzzy_score: number;
  rank: number;
  class_rank: number;
  total_in_class: number;
};

type ScoreAnalysis = {
  batch_id: string;
  exam_id: string;
  student_count: number;
  question_count: number;
  warnings: Array<{ question_id: string; header: string; section_id: string; message: string }>;
  question_stats: QuestionStat[];
  node_stats: NodeStat[];
  student_stats: StudentStat[];
  class_avg_ratio: number;
  class_avg_fuzzy: number;
};

type ToolSpec = { name: string; description?: string };
type ChartSpec = { id: string; type: string; title?: string; series_id?: string; x?: string; y?: string };
type ChartSeries = { id: string; points?: Array<{ label: string; value: number }> };

// ---------------------------------------------------------------------------
// SVG Bar Chart (browser-native, zero deps)
// ---------------------------------------------------------------------------

function SvgBarChart({
  data,
  title,
  colorFn,
  maxVal = 1,
  formatVal,
  warning,
}: {
  data: { label: string; value: number; warning?: boolean }[];
  title: string;
  colorFn: (v: number, warning?: boolean) => string;
  maxVal?: number;
  formatVal: (v: number) => string;
  warning?: string;
}) {
  if (!data.length) return null;
  const W = 600, H = 200, PAD = 40;
  const chartW = W - PAD * 2;
  const barW = Math.max(4, (chartW / data.length) - 4);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h4 className="mb-3 text-sm font-semibold text-slate-700">{title}</h4>
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          style={{ width: "100%", maxWidth: W, height: "auto", display: "block" }}
          fontSize="11"
          fontFamily="ui-sans-serif, system-ui, sans-serif"
        >
          {/* X axis */}
          <line x1={PAD} y1={H - PAD + 4} x2={W - PAD} y2={H - PAD + 4} stroke="#cbd5e1" strokeWidth={1} />
          {data.map((d, i) => {
            const bx = PAD + i * (chartW / data.length) + 2;
            const bh = (d.value / maxVal) * (H - PAD * 2 - 20);
            const barY = H - PAD + 4 - bh;
            return (
              <g key={i}>
                <rect
                  x={bx}
                  y={barY}
                  width={barW}
                  height={Math.max(2, bh)}
                  fill={colorFn(d.value, d.warning)}
                  rx={2}
                />
                <text
                  x={bx + barW / 2}
                  y={H - PAD + 16}
                  textAnchor="middle"
                  fill="#64748b"
                  fontSize="9"
                >
                  {d.label.length > 6 ? d.label.slice(0, 6) + "…" : d.label}
                </text>
                {bh > 14 && (
                  <text x={bx + barW / 2} y={barY + 10} textAnchor="middle" fill="white" fontSize="9">
                    {formatVal(d.value)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      {warning && (
        <p className="mt-2 text-xs text-amber-600">
          <AlertTriangle className="mr-1 inline h-3 w-3" />
          {warning}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AnalysisWorkspace() {
  const { t } = useTranslation("analysis");
  const [exams, setExams] = useState<ExamResult[]>([]);
  const [selectedExamId, setSelectedExamId] = useState<string | null>(null);
  const [examSummary, setExamSummary] = useState<ExamSummary | null>(null);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<ScoreAnalysis | null>(null);
  const [loadingExams, setLoadingExams] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [browsePdfBusyId, setBrowsePdfBusyId] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importWarnings, setImportWarnings] = useState<ImportResult["warnings"]>([]);
  const [tab, setTab] = useState<"overview" | "questions" | "nodes" | "students" | "diagnosis">("overview");
  const [diagLoading, setDiagLoading] = useState(false);
  const [diagKd, setDiagKd] = useState<any | null>(null);
  const [diagHeat, setDiagHeat] = useState<any | null>(null);
  const [diagSug, setDiagSug] = useState<any | null>(null);
  const [diagStudents, setDiagStudents] = useState<any[]>([]);
  const [diagStudentPick, setDiagStudentPick] = useState<string>("");
  const [folderScripts, setFolderScripts] = useState<AnalysisFolderScript[]>([]);
  const [jobs, setJobs] = useState<AnalysisJob[]>([]);
  const [tools, setTools] = useState<ToolSpec[]>([]);
  const [selectedFolderScriptPath, setSelectedFolderScriptPath] = useState<string>("");
  const [jobOutput, setJobOutput] = useState<any | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [leftWidth, setLeftWidth] = useState<56 | 64 | 72>(56);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const rightChartRef = useRef<HTMLDivElement>(null);
  const { setPageContext } = useAgentContext();

  useEffect(() => {
    if (selectedExamId && examSummary) {
      setPageContext({
        current_page: "analysis",
        selected_resource_type: "exam",
        selected_resource_id: selectedExamId,
        summary: t("pageSummaryWithExam", { title: examSummary.exam_title || examSummary.exam_id }),
      });
    } else {
      setPageContext({
        current_page: "analysis",
        summary: t("pageSummaryPick"),
      });
    }
    return () => setPageContext(null);
  }, [selectedExamId, examSummary, setPageContext, t]);

  const loadExams = useCallback(async () => {
    setLoadingExams(true);
    try {
      const data = await apiGet<{ exams: ExamResult[] }>("/api/results");
      setExams(data.exams ?? []);
    } catch (e) {
      console.error("loadExams failed", e);
    } finally {
      setLoadingExams(false);
    }
  }, []);

  useEffect(() => {
    void loadExams();
  }, [loadExams]);

  const loadExamDetail = useCallback(async (examId: string) => {
    setLoadingDetail(true);
    setAnalysis(null);
    setSelectedBatchId(null);
    try {
      const data = await apiGet<ExamSummary>(`/api/results/${encodeURIComponent(examId)}/summary`);
      setExamSummary(data);
      if (data.latest_batch_id) {
        setSelectedBatchId(data.latest_batch_id);
      }
    } catch (e) {
      console.error("loadExamDetail failed", e);
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  const loadAnalysis = useCallback(
    async (examId: string, batchId: string) => {
      try {
        const data = await apiGet<ScoreAnalysis>(
          `/api/results/${encodeURIComponent(examId)}/scores/${encodeURIComponent(batchId)}`,
        );
        setAnalysis(data);
        setImportWarnings([]);
      } catch (e) {
        console.error("loadAnalysis failed", e);
      }
    },
    [],
  );

  const handleExamSelect = useCallback(
    async (examId: string) => {
      setSelectedExamId(examId);
      await loadExamDetail(examId);
    },
    [loadExamDetail],
  );

  const openExamPdfWithDefaultApp = useCallback(async (examId: string) => {
    setBrowsePdfBusyId(examId);
    try {
      await apiPost<{ ok?: boolean }>(`/api/results/${encodeURIComponent(examId)}/open-pdf`, {
        variant: "student",
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      window.alert(msg);
    } finally {
      setBrowsePdfBusyId(null);
    }
  }, []);

  useEffect(() => {
    if (selectedExamId && selectedBatchId) {
      void loadAnalysis(selectedExamId, selectedBatchId);
    }
  }, [selectedExamId, selectedBatchId, loadAnalysis]);

  const loadDiagnosis = useCallback(async (examId: string, batchId: string) => {
    setDiagLoading(true);
    setDiagKd(null);
    setDiagHeat(null);
    setDiagSug(null);
    setDiagStudents([]);
    try {
      const [kd, hm, sg, st] = await Promise.all([
        apiAnalysisDiagnosisKnowledge(examId, batchId),
        apiAnalysisDiagnosisHeatmap(examId, batchId),
        apiAnalysisDiagnosisSuggestions(examId, batchId),
        apiAnalysisDiagnosisStudent(examId, batchId),
      ]);
      setDiagKd(kd);
      setDiagHeat(hm);
      setDiagSug(sg);
      const studs = st.students ?? [];
      setDiagStudents(studs);
      setDiagStudentPick((prev) => {
        if (!studs.length) return "";
        const ids = studs.map((s: { student_id?: string }) => String(s.student_id ?? ""));
        if (prev && ids.includes(prev)) return prev;
        return ids[0] ?? "";
      });
    } catch (e) {
      console.error("loadDiagnosis failed", e);
    } finally {
      setDiagLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab !== "diagnosis" || !selectedExamId || !selectedBatchId) {
      return;
    }
    void loadDiagnosis(selectedExamId, selectedBatchId);
  }, [tab, selectedExamId, selectedBatchId, loadDiagnosis]);

  const loadEduAnalysisMeta = useCallback(async () => {
    try {
      const [s, j, t] = await Promise.all([
        apiAnalysisListFolderScripts(),
        apiAnalysisListJobs(),
        apiAnalysisListTools(),
      ]);
      setFolderScripts(s.scripts ?? []);
      setJobs(j.jobs ?? []);
      setTools((t.tools as ToolSpec[]) ?? []);
      if (!selectedFolderScriptPath && (s.scripts ?? []).length > 0) {
        setSelectedFolderScriptPath((s.scripts ?? [])[0].path);
      }
    } catch (e) {
      console.error("loadEduAnalysisMeta failed", e);
    }
  }, [selectedFolderScriptPath]);

  useEffect(() => {
    void loadEduAnalysisMeta();
  }, [loadEduAnalysisMeta]);

  const handleDownloadTemplate = useCallback(
    async (examId: string) => {
      try {
        const resp = await fetch(await resolveApiUrl(`/api/results/${encodeURIComponent(examId)}/score-template`));
        if (!resp.ok) throw new Error(await resp.text());
        const blob = await resp.blob();
        const cd = resp.headers.get("Content-Disposition") ?? "";
        const match =
          /filename\*=UTF-8''([^;]+)/i.exec(cd) ??
          /filename="([^"]+)"/.exec(cd);
        const filename = decodeURIComponent(match?.[1] ?? "scores.csv");
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        console.error("download template failed", e);
      }
    },
    [],
  );

  const handleImport = useCallback(
    async (examId: string, file: File) => {
      setImporting(true);
      setImportError(null);
      setImportWarnings([]);
      try {
        const fd = new FormData();
        fd.append("file", file);
        const result = await apiPostFormData<ImportResult>(
          `/api/results/${encodeURIComponent(examId)}/scores`,
          fd,
        );
        if (result.warnings?.length) {
          setImportWarnings(result.warnings);
        }
        await loadExamDetail(examId);
        setSelectedBatchId(result.batch_id);
      } catch (e) {
        setImportError(e instanceof Error ? e.message : String(e));
      } finally {
        setImporting(false);
      }
    },
    [loadExamDetail],
  );

  const handleRecompute = useCallback(async () => {
    if (!selectedExamId || !selectedBatchId) return;
    try {
      const data = await apiPost<ScoreAnalysis>(
        `/api/results/${encodeURIComponent(selectedExamId)}/scores/${encodeURIComponent(selectedBatchId)}/recompute`,
        {},
      );
      setAnalysis(data);
    } catch (e) {
      console.error("recompute failed", e);
    }
  }, [selectedExamId, selectedBatchId]);

  const handleDeleteBatch = useCallback(async () => {
    if (!selectedExamId || !selectedBatchId) return;
    const ok = window.confirm(t("confirmDeleteBatch"));
    if (!ok) return;
    try {
      await apiDelete<{ ok: boolean }>(
        `/api/results/${encodeURIComponent(selectedExamId)}/scores/${encodeURIComponent(selectedBatchId)}`,
      );
      await loadExamDetail(selectedExamId);
    } catch (e) {
      setImportError(e instanceof Error ? e.message : String(e));
    }
  }, [selectedExamId, selectedBatchId, loadExamDetail, t]);

  const handleDeleteExam = useCallback(async () => {
    if (!selectedExamId) return;
    const ok = window.confirm(t("confirmDeleteExam"));
    if (!ok) return;
    try {
      await apiDelete<{ ok: boolean }>(`/api/results/${encodeURIComponent(selectedExamId)}`);
      setSelectedExamId(null);
      setExamSummary(null);
      setSelectedBatchId(null);
      setAnalysis(null);
      await loadExams();
    } catch (e) {
      setImportError(e instanceof Error ? e.message : String(e));
    }
  }, [selectedExamId, loadExams, t]);

  const handleRunBuiltinStudio = useCallback(async () => {
    if (!selectedExamId || !selectedBatchId) return;
    try {
      setJobError(null);
      const res = await apiAnalysisRunBuiltin({
        builtin_id: "builtin:exam_stats_v1",
        exam_id: selectedExamId,
        batch_id: selectedBatchId,
        recompute: true,
      });
      if (res.output) setJobOutput(res.output);
      if ((res as { error?: string }).error) setJobError(String((res as { error?: string }).error));
      await loadEduAnalysisMeta();
    } catch (e) {
      setImportError(e instanceof Error ? e.message : String(e));
    }
  }, [selectedExamId, selectedBatchId, loadEduAnalysisMeta]);

  const handleRunFolderScriptStudio = useCallback(async () => {
    if (!selectedExamId || !selectedBatchId || !selectedFolderScriptPath) return;
    try {
      setJobError(null);
      const res = await apiAnalysisRunFolderScript({
        script_path: selectedFolderScriptPath,
        exam_id: selectedExamId,
        batch_id: selectedBatchId,
      });
      if (res.output) setJobOutput(res.output);
      if (res.error) setJobError(String(res.error));
      await loadEduAnalysisMeta();
    } catch (e) {
      setImportError(e instanceof Error ? e.message : String(e));
    }
  }, [selectedExamId, selectedBatchId, selectedFolderScriptPath, loadEduAnalysisMeta]);

  // SVG chart helpers
  const errorColorFn = (v: number, _warn?: boolean) => {
    if (v < 0.2) return "#22c55e";
    if (v < 0.5) return "#eab308";
    return "#ef4444";
  };

  const formatPct = (v: number) => `${(v * 100).toFixed(0)}%`;
  const normalizedOutput = jobOutput && typeof jobOutput === "object" ? (jobOutput as Record<string, unknown>) : null;
  const outputSummary =
    normalizedOutput && typeof normalizedOutput.summary === "object"
      ? (normalizedOutput.summary as Record<string, unknown>)
      : null;
  const outputChartSpecs = Array.isArray(normalizedOutput?.chart_specs) ? (normalizedOutput!.chart_specs as ChartSpec[]) : [];
  const outputSeries = Array.isArray(normalizedOutput?.series) ? (normalizedOutput!.series as ChartSeries[]) : [];
  const firstBarSpec = outputChartSpecs.find((s) => s.type === "bar" && s.series_id);
  const firstBarSeries = firstBarSpec ? outputSeries.find((s) => s.id === firstBarSpec.series_id) : null;
  const firstBarPoints = firstBarSeries?.points ?? [];
  const handleDownloadMetadata = useCallback(() => {
    if (!jobOutput) return;
    const blob = new Blob([JSON.stringify(jobOutput, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "analysis-metadata.json";
    a.click();
    URL.revokeObjectURL(url);
  }, [jobOutput]);

  const handleDownloadChartImage = useCallback(() => {
    const svg = rightChartRef.current?.querySelector("svg");
    if (!svg) return;
    const serializer = new XMLSerializer();
    const source = serializer.serializeToString(svg);
    const blob = new Blob([source], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "analysis-chart.svg";
    a.click();
    URL.revokeObjectURL(url);
  }, []);

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left sidebar: exam history */}
      <div className={cn("flex shrink-0 flex-col border-r border-slate-200 bg-slate-50", leftWidth === 56 ? "w-56" : leftWidth === 64 ? "w-64" : "w-72")}>
        <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
          <h3 className="text-sm font-semibold text-slate-700">{t("historyTitle")}</h3>
          <div className="flex items-center gap-1">
            <button onClick={() => setLeftWidth(56)} className={cn("rounded px-1.5 py-0.5 text-xs", leftWidth === 56 ? "bg-blue-100 text-blue-700" : "text-slate-500 hover:bg-slate-200")}>S</button>
            <button onClick={() => setLeftWidth(64)} className={cn("rounded px-1.5 py-0.5 text-xs", leftWidth === 64 ? "bg-blue-100 text-blue-700" : "text-slate-500 hover:bg-slate-200")}>M</button>
            <button onClick={() => setLeftWidth(72)} className={cn("rounded px-1.5 py-0.5 text-xs", leftWidth === 72 ? "bg-blue-100 text-blue-700" : "text-slate-500 hover:bg-slate-200")}>L</button>
            <button onClick={() => void loadExams()} className="rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-600" title={t("refresh")}>
              <RefreshCw className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loadingExams ? (
            <div className="p-4 text-sm text-slate-400">{t("loading")}</div>
          ) : exams.length === 0 ? (
            <div className="p-4 text-sm text-slate-400">{t("noExams")}</div>
          ) : (
            <ul className="divide-y divide-slate-200">
              {exams.map((exam) => (
                <li key={exam.exam_id} className="flex items-stretch">
                  <button
                    type="button"
                    onClick={() => void handleExamSelect(exam.exam_id)}
                    className={cn(
                      "min-w-0 flex-1 px-3 py-2.5 text-left transition-colors",
                      selectedExamId === exam.exam_id
                        ? "bg-blue-50 text-blue-700"
                        : "hover:bg-slate-100 text-slate-700",
                    )}
                  >
                    <div className="truncate text-sm font-medium">
                      {exam.exam_title || exam.exam_id}
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-400">
                      {exam.subject && <span>{exam.subject}</span>}
                      <span>{t("questionCount", { n: exam.question_count })}</span>
                      {exam.score_batch_count > 0 && (
                        <span className="flex items-center gap-0.5 text-green-600">
                          <BarChart3 className="h-3 w-3" />
                          {t("batchCount", { n: exam.score_batch_count })}
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 truncate text-xs text-slate-400">
                      {formatLocaleDate(exam.mtime)}
                    </div>
                  </button>
                  <button
                    type="button"
                    className="shrink-0 self-stretch border-l border-slate-200 px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 disabled:opacity-50"
                    disabled={browsePdfBusyId === exam.exam_id}
                    onClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      void openExamPdfWithDefaultApp(exam.exam_id);
                    }}
                  >
                    {browsePdfBusyId === exam.exam_id ? "…" : t("browse")}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Middle: results only */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden border-r border-slate-200 bg-white">
        {!selectedExamId ? (
          <div className="flex h-full items-center justify-center text-slate-400">
            <div className="text-center">
              <BarChart3 className="mx-auto mb-3 h-12 w-12 text-slate-300" />
              <p className="text-sm">{t("emptyBeforeSelect")}</p>
            </div>
          </div>
        ) : loadingDetail ? (
          <div className="flex h-full items-center justify-center text-slate-400">
            <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
            {t("loading")}
          </div>
        ) : examSummary ? (
          <>
            {/* Exam header */}
            <div className="shrink-0 border-b border-slate-200 bg-white px-6 py-4">
              <h2 className="text-lg font-semibold text-slate-800">
                {examSummary.exam_title}
              </h2>
              <div className="mt-1 flex flex-wrap items-center gap-3 text-sm text-slate-500">
                {examSummary.subject && <span>{examSummary.subject}</span>}
                <span>{t("questionCount", { n: examSummary.question_count })}</span>
                <span>{t("sectionCount", { n: examSummary.section_count })}</span>
                {examSummary.score_batch_count > 0 && (
                  <span className="text-green-600">
                    <CheckCircle className="mr-1 inline h-3.5 w-3.5" />
                    {t("importCount", { n: examSummary.score_batch_count })}
                  </span>
                )}
              </div>
              {jobOutput && (
                <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
                  {t("lastOutput", {
                    title: String(outputSummary?.title ?? t("defaultOutputTitle")),
                    status: String(outputSummary?.status ?? t("statusUnknown")),
                  })}
                </div>
              )}
              {jobError && (
                <div className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{jobError}</div>
              )}

              {/* Import error */}
              {importError && (
                <div className="mt-2 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  <XCircle className="h-4 w-4 shrink-0" />
                  {importError}
                </div>
              )}

              {/* Import warnings (unbound questions) */}
              {importWarnings.length > 0 && (
                <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm">
                  <div className="mb-1 flex items-center gap-2 font-medium text-amber-700">
                    <AlertTriangle className="h-4 w-4" />
                    {t("unboundWarning", { n: importWarnings.length })}
                  </div>
                  <ul className="space-y-0.5 text-amber-600">
                    {importWarnings.map((w) => (
                      <li key={w.question_id} className="text-xs">
                        <span className="font-mono font-semibold">{w.header}</span>
                        {": "}
                        {w.message}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {/* Batch selector */}
            {examSummary.score_batches.length > 0 && (
              <div className="shrink-0 border-b border-slate-200 bg-slate-50 px-6 py-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-500">{t("batchLabel")}</span>
                  <div className="flex gap-1">
                    {examSummary.score_batches.map((b) => (
                      <button
                        key={b.batch_id}
                        onClick={() => setSelectedBatchId(b.batch_id)}
                        className={cn(
                          "flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors",
                          selectedBatchId === b.batch_id
                            ? "bg-blue-600 text-white"
                            : "bg-white text-slate-600 hover:bg-slate-200",
                        )}
                      >
                        <FileSpreadsheet className="h-3 w-3" />
                        {formatLocaleDate(b.imported_at)}
                        <span className="opacity-70">({t("students", { n: b.student_count })})</span>
                      </button>
                    ))}
                  </div>
                  {selectedBatchId && (
                    <button
                      onClick={() => void handleDeleteBatch()}
                      className="ml-2 flex items-center gap-1 rounded border border-red-200 bg-white px-2 py-1 text-xs text-red-600 transition-colors hover:bg-red-50"
                    >
                      <Trash2 className="h-3 w-3" />
                      {t("deleteBatch")}
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* Stats tabs */}
            {!selectedBatchId ? (
              <div className="flex flex-1 items-center justify-center text-slate-400">
                <div className="text-center">
                  <TrendingUp className="mx-auto mb-3 h-12 w-12 text-slate-300" />
                  <p className="text-sm">{t("importToSee")}</p>
                </div>
              </div>
            ) : analysis ? (
              <div className="min-h-0 flex-1 overflow-y-auto p-6">
                {/* Summary cards */}
                <div className="mb-4 grid grid-cols-3 gap-4">
                  <div className="rounded-lg border border-slate-200 bg-white p-4 text-center">
                    <div className="text-2xl font-bold text-slate-800">{analysis.student_count}</div>
                    <div className="text-xs text-slate-500">{t("studentCount")}</div>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-white p-4 text-center">
                    <div className="text-2xl font-bold text-blue-600">
                      {(analysis.class_avg_ratio * 100).toFixed(1)}%
                    </div>
                    <div className="text-xs text-slate-500">{t("classAvgRatio")}</div>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-white p-4 text-center">
                    <div className="text-2xl font-bold text-purple-600">
                      {(analysis.class_avg_fuzzy * 100).toFixed(1)}%
                    </div>
                    <div className="text-xs text-slate-500">{t("classAvgFuzzy")}</div>
                  </div>
                </div>

                {/* Tab nav */}
                <div className="mb-4 flex flex-wrap gap-1 border-b border-slate-200">
                  {(["overview", "questions", "nodes", "students", "diagnosis"] as const).map((tabKey) => (
                    <button
                      key={tabKey}
                      onClick={() => setTab(tabKey)}
                      className={cn(
                        "border-b-2 px-4 py-1.5 text-sm transition-colors",
                        tab === tabKey
                          ? "border-blue-600 font-medium text-blue-600"
                          : "border-transparent text-slate-500 hover:text-slate-700",
                      )}
                    >
                      {tabKey === "overview"
                        ? t("tabOverview")
                        : tabKey === "questions"
                          ? t("tabQuestionErr")
                          : tabKey === "nodes"
                            ? t("tabKnowledge")
                            : tabKey === "students"
                              ? t("tabRanking")
                              : t("tabDiagnosis")}
                    </button>
                  ))}
                </div>

                {/* Tab content */}
                {tab === "overview" && (
                  <div className="space-y-4">
                    <SvgBarChart
                      data={analysis.question_stats
                        .filter((q) => q.error_rate !== null)
                        .slice(0, 20)
                        .map((q) => ({
                          label: q.header,
                          value: q.error_rate ?? 0,
                        }))}
                      title={t("chartQuestionErr")}
                      colorFn={(v) => errorColorFn(v)}
                      maxVal={1}
                      formatVal={formatPct}
                    />
                    {analysis.node_stats.length > 0 && (
                      <SvgBarChart
                        data={analysis.node_stats.map((n) => ({
                          label: n.node_id.split("/").pop() ?? n.node_id,
                          value: n.error_rate,
                        }))}
                        title={t("chartKnowledgeErr")}
                        colorFn={(v) => errorColorFn(v)}
                        maxVal={1}
                        formatVal={formatPct}
                        warning={t("knowledgeBindHint")}
                      />
                    )}
                    {analysis.warnings.length > 0 && (
                      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
                        <h4 className="mb-2 flex items-center gap-2 font-semibold text-amber-700">
                          <AlertTriangle className="h-4 w-4" />
                          {t("knowledgeMissingTitle")}
                        </h4>
                        <ul className="space-y-1 text-sm text-amber-700">
                          {analysis.warnings.map((w) => (
                            <li key={w.question_id}>
                              <span className="font-mono font-semibold">{w.header}</span>
                              {" — "}{w.message}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}

                {tab === "questions" && (
                  <div className="overflow-x-auto rounded-lg border border-slate-200">
                    <table className="w-full text-sm">
                      <thead className="bg-slate-50 text-xs text-slate-500">
                        <tr>
                          <th className="px-3 py-2 text-left font-medium">{t("thQid")}</th>
                          <th className="px-3 py-2 text-left font-medium">{t("thSection")}</th>
                          <th className="px-3 py-2 text-right font-medium">{t("thFullScore")}</th>
                          <th className="px-3 py-2 text-right font-medium">{t("thAnswered")}</th>
                          <th className="px-3 py-2 text-right font-medium">{t("thAvgScore")}</th>
                          <th className="px-3 py-2 text-right font-medium">{t("thErrRate")}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {analysis.question_stats.map((q) => (
                          <tr key={q.question_id} className="hover:bg-slate-50">
                            <td className="px-3 py-2 font-mono font-semibold text-slate-700">{q.header}</td>
                            <td className="px-3 py-2 text-slate-500">{q.section_id}</td>
                            <td className="px-3 py-2 text-right text-slate-600">{q.score_per_item}</td>
                            <td className="px-3 py-2 text-right text-slate-600">{q.answered_count}</td>
                            <td className="px-3 py-2 text-right text-slate-600">
                              {q.avg_raw_score !== null ? q.avg_raw_score.toFixed(2) : "—"}
                            </td>
                            <td className="px-3 py-2 text-right">
                              {q.error_rate !== null ? (
                                <span
                                  className="rounded px-1.5 py-0.5 text-xs font-semibold"
                                  style={{
                                    backgroundColor: errorColorFn(q.error_rate) + "22",
                                    color: errorColorFn(q.error_rate),
                                  }}
                                >
                                  {formatPct(q.error_rate)}
                                </span>
                              ) : (
                                <span className="text-slate-400">—</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {tab === "nodes" && (
                  <div>
                    {analysis.node_stats.length === 0 ? (
                      <div className="rounded-lg border border-amber-200 bg-amber-50 p-6 text-center text-sm text-amber-700">
                        <AlertTriangle className="mx-auto mb-2 h-8 w-8 text-amber-400" />
                        <p>
                          {t("noKnowledgeStats")}
                          <br />
                          {t("bindInGraph")}
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-4">
                        <SvgBarChart
                          data={analysis.node_stats.map((n) => ({
                            label: n.node_id.split("/").pop() ?? n.node_id,
                            value: n.error_rate,
                          }))}
                          title={t("chartKnowledgeTitle")}
                          colorFn={(v) => errorColorFn(v)}
                          maxVal={1}
                          formatVal={formatPct}
                        />
                        <div className="overflow-x-auto rounded-lg border border-slate-200">
                          <table className="w-full text-sm">
                            <thead className="bg-slate-50 text-xs text-slate-500">
                              <tr>
                                <th className="px-3 py-2 text-left font-medium">{t("thNode")}</th>
                                <th className="px-3 py-2 text-right font-medium">{t("thBoundQ")}</th>
                                <th className="px-3 py-2 text-right font-medium">{t("thFuzzy")}</th>
                                <th className="px-3 py-2 text-right font-medium">{t("thErrRate")}</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100">
                              {analysis.node_stats.map((n) => (
                                <tr key={n.node_id} className="hover:bg-slate-50">
                                  <td className="px-3 py-2 font-mono text-slate-700">{n.node_id}</td>
                                  <td className="px-3 py-2 text-right text-slate-600">{n.bound_question_count}</td>
                                  <td className="px-3 py-2 text-right text-slate-600">
                                    {(n.mastery_fuzzy * 100).toFixed(1)}%
                                  </td>
                                  <td className="px-3 py-2 text-right">
                                    <span
                                      className="rounded px-1.5 py-0.5 text-xs font-semibold"
                                      style={{
                                        backgroundColor: errorColorFn(n.error_rate) + "22",
                                        color: errorColorFn(n.error_rate),
                                      }}
                                    >
                                      {formatPct(n.error_rate)}
                                    </span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {tab === "students" && (
                  <div className="overflow-x-auto rounded-lg border border-slate-200">
                    <table className="w-full text-sm">
                      <thead className="bg-slate-50 text-xs text-slate-500">
                        <tr>
                          <th className="px-3 py-2 text-right font-medium">{t("thRank")}</th>
                          <th className="px-3 py-2 text-left font-medium">{t("thName")}</th>
                          <th className="px-3 py-2 text-left font-medium">{t("thStudentId")}</th>
                          <th className="px-3 py-2 text-right font-medium">{t("thRawTotal")}</th>
                          <th className="px-3 py-2 text-right font-medium">{t("thScoreRate")}</th>
                          <th className="px-3 py-2 text-right font-medium">{t("thFuzzyScore")}</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {[...analysis.student_stats]
                          .sort((a, b) => a.rank - b.rank)
                          .map((s) => (
                            <tr key={`${s.name}-${s.student_id}`} className="hover:bg-slate-50">
                              <td className="px-3 py-2 text-right">
                                <span
                                  className={cn(
                                    "inline-flex h-5 w-5 items-center justify-center rounded-full text-xs font-bold",
                                    s.rank <= 3
                                      ? "bg-amber-100 text-amber-700"
                                      : "bg-slate-100 text-slate-500",
                                  )}
                                >
                                  {s.rank}
                                </span>
                              </td>
                              <td className="px-3 py-2 font-medium text-slate-700">{s.name}</td>
                              <td className="px-3 py-2 text-slate-500">{s.student_id}</td>
                              <td className="px-3 py-2 text-right font-mono text-slate-600">
                                {s.raw_total}
                              </td>
                              <td className="px-3 py-2 text-right">
                                <span className="rounded px-1.5 py-0.5 text-xs font-semibold bg-blue-100 text-blue-700">
                                  {formatPct(s.score_ratio)}
                                </span>
                              </td>
                              <td className="px-3 py-2 text-right">
                                <span className="rounded px-1.5 py-0.5 text-xs font-semibold bg-purple-100 text-purple-700">
                                  {formatPct(s.fuzzy_score)}
                                </span>
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {tab === "diagnosis" && (
                  <div className="space-y-6">
                    {diagLoading ? (
                      <p className="text-sm text-slate-500">{t("loadingDiagnosis")}</p>
                    ) : (
                      <>
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            type="button"
                            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700"
                            onClick={() =>
                              selectedExamId &&
                              selectedBatchId &&
                              void loadDiagnosis(selectedExamId, selectedBatchId)
                            }
                          >
                            {t("refreshDiagnosis")}
                          </button>
                          <span className="text-xs text-slate-500">{t("diagnosisDeps")}</span>
                        </div>

                        {diagKd?.nodes?.length ? (
                          <SvgBarChart
                            data={(diagKd.nodes as any[]).map((n) => ({
                              label: String(n.canonical_name ?? n.node_id).slice(0, 12),
                              value: Number(n.error_rate ?? 0),
                            }))}
                            title={t("classWeakTitle")}
                            colorFn={(v) => errorColorFn(v)}
                            maxVal={1}
                            formatVal={formatPct}
                          />
                        ) : (
                          <p className="text-sm text-amber-700">{t("noDiagnosisData")}</p>
                        )}

                        {diagHeat?.matrix?.length && diagHeat?.columns?.length ? (
                          <div className="rounded-lg border border-slate-200 bg-white p-4">
                            <h4 className="mb-2 text-sm font-semibold text-slate-700">{t("heatmapTitle")}</h4>
                            <div className="max-h-[360px] overflow-auto">
                              <table className="border-collapse text-[10px]">
                                <thead>
                                  <tr>
                                    <th className="sticky left-0 z-10 border border-slate-200 bg-slate-100 px-1 py-1 text-left">
                                      {t("studentCol")}
                                    </th>
                                    {(diagHeat.columns as any[]).map((c) => (
                                      <th
                                        key={c.node_id}
                                        className="min-w-[3rem] max-w-[4rem] border border-slate-200 bg-slate-50 px-0.5 py-1 text-center font-normal leading-tight text-slate-600"
                                        title={c.canonical_name}
                                      >
                                        {String(c.canonical_name ?? c.node_id).slice(0, 4)}
                                      </th>
                                    ))}
                                  </tr>
                                </thead>
                                <tbody>
                                  {(diagHeat.matrix as (number | null)[][]).map((row, ri) => {
                                    const rinfo = (diagHeat.rows as any[])[ri];
                                    return (
                                      <tr key={ri}>
                                        <td className="sticky left-0 z-10 border border-slate-200 bg-white px-1 py-0.5 text-slate-700">
                                          {rinfo?.name ?? ri}
                                        </td>
                                        {row.map((cell, ci) => (
                                          <td
                                            key={ci}
                                            className="border border-slate-200 px-0 py-0 text-center"
                                            style={{
                                              backgroundColor:
                                                cell == null
                                                  ? "#e2e8f0"
                                                  : `hsl(${cell * 120}, 65%, ${45 + (1 - cell) * 15}%)`,
                                            }}
                                            title={cell == null ? t("noCellData") : `${(cell * 100).toFixed(0)}%`}
                                          >
                                            {cell == null ? "·" : ""}
                                          </td>
                                        ))}
                                      </tr>
                                    );
                                  })}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        ) : null}

                        <div className="rounded-lg border border-slate-200 bg-white p-4">
                          <h4 className="mb-2 text-sm font-semibold text-slate-700">{t("studentProfileTitle")}</h4>
                          {diagStudents.length ? (
                            <>
                              <label className="mb-2 block text-xs text-slate-600">
                                {t("pickStudent")}
                                <select
                                  className="ml-2 rounded border border-slate-300 px-2 py-1 text-sm"
                                  value={diagStudentPick}
                                  onChange={(e) => setDiagStudentPick(e.target.value)}
                                >
                                  {diagStudents.map((s) => (
                                    <option key={`${s.student_id}-${s.name}`} value={String(s.student_id ?? "")}>
                                      {s.name} ({s.student_id || t("noStudentId")})
                                    </option>
                                  ))}
                                </select>
                              </label>
                              {(() => {
                                const st = diagStudents.find(
                                  (s) => String(s.student_id ?? "") === diagStudentPick,
                                );
                                const bn = st?.by_node as Record<string, { mastery: number; canonical_name: string }> | undefined;
                                const pts = bn
                                  ? Object.values(bn).map((v) => ({
                                      label: String(v.canonical_name).slice(0, 10),
                                      value: 1 - v.mastery,
                                    }))
                                  : [];
                                return pts.length ? (
                                  <SvgBarChart
                                    data={pts}
                                    title={t("lossChartTitle")}
                                    colorFn={(v) => errorColorFn(v)}
                                    maxVal={1}
                                    formatVal={formatPct}
                                  />
                                ) : (
                                  <p className="text-xs text-slate-500">{t("noStudentKData")}</p>
                                );
                              })()}
                            </>
                          ) : (
                            <p className="text-xs text-slate-500">{t("noStudentData")}</p>
                          )}
                        </div>

                        {diagSug?.retell_priority?.length ? (
                          <div className="rounded-lg border border-indigo-200 bg-indigo-50/50 p-4">
                            <h4 className="mb-2 text-sm font-semibold text-indigo-900">{t("retitleTitle")}</h4>
                            <ol className="list-decimal space-y-1 pl-5 text-sm text-indigo-950">
                              {(diagSug.retell_priority as any[]).map((x) => (
                                <li key={x.node_id}>
                                  <span className="font-medium">{x.canonical_name}</span>
                                  <span className="text-indigo-700">
                                    {t("errRateParen", { rate: formatPct(Number(x.error_rate ?? 0)) })}
                                  </span>
                                </li>
                              ))}
                            </ol>
                          </div>
                        ) : null}

                        {diagSug?.practice_drafts?.length ? (
                          <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-4">
                            <h4 className="mb-2 text-sm font-semibold text-emerald-900">{t("practiceDraftTitle")}</h4>
                            <ul className="space-y-3 text-sm text-emerald-950">
                              {(diagSug.practice_drafts as any[]).map((d) => (
                                <li key={d.node_id}>
                                  <div className="font-medium">{d.canonical_name}</div>
                                  <div className="mt-1 font-mono text-xs text-emerald-800">
                                    {(d.suggested_question_ids as string[]).join(" · ") || t("noLinkedQuestions")}
                                  </div>
                                </li>
                              ))}
                            </ul>
                            <p className="mt-2 text-[11px] text-emerald-800">{t("practiceHint")}</p>
                          </div>
                        ) : null}
                      </>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-1 items-center justify-center text-slate-400">
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                {t("computing")}
              </div>
            )}
          </>
        ) : null}
      </div>

      {/* Right: analysis controls + agent */}
      {selectedExamId && examSummary && (
        <div className="flex w-[22rem] shrink-0 flex-col bg-slate-50">
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="border-b border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700">{t("quickActions")}</div>
          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
            <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
              <button onClick={() => void handleDownloadTemplate(examSummary.exam_id)} className="flex w-full items-center justify-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50">
                <Download className="h-4 w-4" />
                {t("downloadTemplate")}
              </button>
              <button onClick={() => fileInputRef.current?.click()} disabled={importing} className="flex w-full items-center justify-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                {importing ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                {importing ? t("importing") : t("importScores")}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.xlsx,.xls"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleImport(examSummary.exam_id, file);
                  e.target.value = "";
                }}
              />
              <button onClick={() => void handleRecompute()} disabled={!selectedBatchId} className="flex w-full items-center justify-center gap-1.5 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                <RefreshCw className="h-4 w-4" />
                {t("recompute")}
              </button>
              <button onClick={() => void handleDeleteBatch()} disabled={!selectedBatchId} className="flex w-full items-center justify-center gap-1.5 rounded-md border border-red-200 bg-white px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50">
                <Trash2 className="h-4 w-4" />
                {t("deleteCurrentBatch")}
              </button>
              <button onClick={() => void handleDeleteExam()} className="flex w-full items-center justify-center gap-1.5 rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm text-red-700 hover:bg-red-50">
                <Trash2 className="h-4 w-4" />
                {t("deleteExam")}
              </button>
            </div>

            <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
              <div className="text-xs font-semibold text-slate-600">{t("scriptPickTitle")}</div>
              <select
                value={selectedFolderScriptPath}
                onChange={(e) => setSelectedFolderScriptPath(e.target.value)}
                className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              >
                {folderScripts.length === 0 && <option value="">{t("noPyScripts")}</option>}
                {folderScripts.map((s) => (
                  <option key={s.path} value={s.path}>
                    {s.path}
                  </option>
                ))}
              </select>
              <button
                onClick={() => void handleRunFolderScriptStudio()}
                disabled={!selectedBatchId || !selectedFolderScriptPath}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                {t("runSelectedScript")}
              </button>
              <button
                onClick={() => void handleRunBuiltinStudio()}
                disabled={!selectedBatchId}
                className="w-full rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                {t("runBuiltin")}
              </button>
              <div className="text-[11px] text-slate-500">
                {t("toolScriptCount", { tools: tools.length, scripts: folderScripts.length })}
              </div>
            </div>

            <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
              <div className="text-xs font-semibold text-slate-600">{t("scriptCharts")}</div>
              <div ref={rightChartRef}>
                {firstBarSpec && firstBarPoints.length > 0 ? (
                  <SvgBarChart
                    data={firstBarPoints.map((p) => ({ label: p.label, value: p.value }))}
                    title={firstBarSpec.title ?? t("chartFallback")}
                    colorFn={(v) => errorColorFn(v)}
                    maxVal={1}
                    formatVal={formatPct}
                  />
                ) : (
                  <div className="rounded bg-slate-50 p-3 text-xs text-slate-500">{t("noChart")}</div>
                )}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <button onClick={handleDownloadMetadata} disabled={!jobOutput} className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                  {t("downloadMeta")}
                </button>
                <button onClick={handleDownloadChartImage} disabled={!firstBarSpec || firstBarPoints.length === 0} className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                  {t("downloadImage")}
                </button>
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 bg-white p-3 text-xs text-slate-600">
              <div className="mb-1 font-semibold text-slate-700">{t("recentJobs")}</div>
              <div className="max-h-28 overflow-y-auto space-y-1">
                {jobs.slice(0, 5).map((j) => (
                  <div key={j.job_id} className="rounded bg-slate-50 px-2 py-1">
                    <span className="font-mono">{j.job_id.slice(0, 8)}</span> · {j.kind} · {j.status}
                  </div>
                ))}
                {jobs.length === 0 && <div className="text-slate-400">{t("noJobs")}</div>}
              </div>
            </div>
          </div>
          </div>
        </div>
      )}
    </div>
  );
}
