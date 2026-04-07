import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, beforeAll } from "vitest";

import { AgentProvider } from "../../contexts/AgentContext";
import { setupTestI18n, TestI18nProvider } from "../../test/i18nTestUtils";
import { AnalysisWorkspace } from "../AnalysisWorkspace";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPostFormData: vi.fn(),
  apiDelete: vi.fn(),
  apiAnalysisListScripts: vi.fn(),
  apiAnalysisListFolderScripts: vi.fn(),
  apiAnalysisListJobs: vi.fn(),
  apiAnalysisListTools: vi.fn(),
  apiAnalysisRunFolderScript: vi.fn(),
  apiAnalysisRunBuiltin: vi.fn(),
}));

vi.mock("../../api/client", () => ({
  apiGet: mocks.apiGet,
  apiPost: mocks.apiPost,
  apiPostFormData: mocks.apiPostFormData,
  apiDelete: mocks.apiDelete,
  apiAnalysisListScripts: mocks.apiAnalysisListScripts,
  apiAnalysisListFolderScripts: mocks.apiAnalysisListFolderScripts,
  apiAnalysisListJobs: mocks.apiAnalysisListJobs,
  apiAnalysisListTools: mocks.apiAnalysisListTools,
  apiAnalysisRunFolderScript: mocks.apiAnalysisRunFolderScript,
  apiAnalysisRunBuiltin: mocks.apiAnalysisRunBuiltin,
  ensureApiBase: vi.fn().mockResolvedValue(undefined),
  resolveApiUrl: async (path: string) => path,
}));

function primeDefaultApi() {
  mocks.apiGet.mockImplementation(async (path: string) => {
    if (path === "/api/results") {
      return {
        exams: [
          {
            exam_id: "e1",
            exam_title: "期末考试",
            subject: "数学",
            question_count: 3,
            section_count: 1,
            score_batch_count: 1,
            has_score: true,
            latest_batch_id: "b1",
            result_dir: "e1",
            mtime: new Date().toISOString(),
          },
        ],
      };
    }
    if (path === "/api/results/e1/summary") {
      return {
        exam_id: "e1",
        exam_title: "期末考试",
        subject: "数学",
        question_count: 3,
        section_count: 1,
        score_batch_count: 1,
        has_score: true,
        latest_batch_id: "b1",
        result_dir: "e1",
        mtime: new Date().toISOString(),
        questions: [],
        score_batches: [
          {
            batch_id: "b1",
            imported_at: new Date().toISOString(),
            student_count: 2,
            question_count: 3,
          },
        ],
      };
    }
    if (path === "/api/results/e1/scores/b1") {
      return {
        batch_id: "b1",
        exam_id: "e1",
        student_count: 2,
        question_count: 3,
        warnings: [],
        question_stats: [],
        node_stats: [],
        student_stats: [],
        class_avg_ratio: 0.7,
        class_avg_fuzzy: 0.65,
      };
    }
    throw new Error(`unexpected apiGet path: ${path}`);
  });
  mocks.apiAnalysisListScripts.mockResolvedValue({ scripts: [] });
  mocks.apiAnalysisListFolderScripts.mockResolvedValue({
    scripts: [{ path: "demo.py", name: "demo.py", updated_at: Date.now() }],
  });
  mocks.apiAnalysisListJobs.mockResolvedValue({ jobs: [] });
  mocks.apiAnalysisListTools.mockResolvedValue({ tools: [{ name: "analysis.run_builtin" }] });
  mocks.apiAnalysisRunBuiltin.mockResolvedValue({ job_id: "j1", status: "succeeded", output: { ok: true } });
  mocks.apiAnalysisRunFolderScript.mockResolvedValue({ job_id: "j2", status: "succeeded", output: { ok: false } });
  mocks.apiPost.mockResolvedValue({});
  mocks.apiPostFormData.mockResolvedValue({});
  mocks.apiDelete.mockResolvedValue({ ok: true });
}

describe("AnalysisWorkspace", () => {
  beforeAll(async () => {
    await setupTestI18n("zh");
  });

  beforeEach(() => {
    vi.clearAllMocks();
    primeDefaultApi();
  });

  function renderWs() {
    return render(
      <TestI18nProvider>
        <AgentProvider>
          <AnalysisWorkspace />
        </AgentProvider>
      </TestI18nProvider>,
    );
  }

  it("shows empty state before exam is selected", async () => {
    renderWs();
    expect(await screen.findByText("从左侧选择一个历史考试")).toBeInTheDocument();
  });

  it("runs builtin analysis from right panel", async () => {
    renderWs();

    const examButton = await screen.findByRole("button", { name: /期末考试/ });
    fireEvent.click(examButton);

    const runBuiltinBtn = await screen.findByRole("button", { name: "运行内置分析（exam_stats_v1）" });
    fireEvent.click(runBuiltinBtn);
    await waitFor(() => expect(mocks.apiAnalysisRunBuiltin).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/工具数量：1/)).toBeInTheDocument();
  });

  it("shows error message when folder script run fails", async () => {
    mocks.apiAnalysisRunFolderScript.mockRejectedValueOnce(new Error("运行失败"));
    renderWs();

    const examButton = await screen.findByRole("button", { name: /期末考试/ });
    fireEvent.click(examButton);
    const runBtn = await screen.findByRole("button", { name: "运行选中脚本" });
    fireEvent.click(runBtn);

    expect(await screen.findByText("运行失败")).toBeInTheDocument();
  });
});
