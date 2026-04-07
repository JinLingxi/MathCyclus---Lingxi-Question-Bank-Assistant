from __future__ import annotations

from pathlib import Path

from tests.integration._helpers import write_exam_yaml


def _prepare_exam_batch(web_client, tmp_path: Path, exam_id: str) -> str:
    exam_dir = tmp_path / "result" / exam_id
    exam_dir.mkdir(parents=True)
    write_exam_yaml(exam_dir, exam_id, [("选择题", 2, 5.0)])
    csv_text = "姓名,学号,1.1,1.2\n甲,001,5,4\n乙,002,3,1\n"
    files = {"file": ("scores.csv", csv_text.encode("utf-8"), "text/csv")}
    r = web_client.post(f"/api/results/{exam_id}/scores", files=files)
    assert r.status_code == 200
    return r.json()["batch_id"]


def test_analysis_tools_and_script_crud(web_client) -> None:
    r_tools = web_client.get("/api/analysis/tools")
    assert r_tools.status_code == 200
    names = {x["name"] for x in r_tools.json()["tools"]}
    assert "analysis.list_datasets" in names

    r_save = web_client.post(
        "/api/analysis/scripts",
        json={"name": "draft", "language": "python", "code": "print('ok')"},
    )
    assert r_save.status_code == 200
    script_id = r_save.json()["script"]["script_id"]

    r_list = web_client.get("/api/analysis/scripts")
    assert r_list.status_code == 200
    assert any(s["script_id"] == script_id for s in r_list.json()["scripts"])

    r_get = web_client.get(f"/api/analysis/scripts/{script_id}")
    assert r_get.status_code == 200
    assert r_get.json()["script"]["name"] == "draft"

    r_del = web_client.delete(f"/api/analysis/scripts/{script_id}")
    assert r_del.status_code == 200
    assert r_del.json()["ok"] is True


def test_analysis_builtin_and_job_endpoints(web_client, tmp_path: Path) -> None:
    exam_id = "api-exam"
    batch_id = _prepare_exam_batch(web_client, tmp_path, exam_id)

    r_builtin = web_client.post(
        "/api/analysis/jobs/builtin",
        json={
            "builtin_id": "builtin:exam_stats_v1",
            "exam_id": exam_id,
            "batch_id": batch_id,
            "recompute": True,
        },
    )
    assert r_builtin.status_code == 200
    data = r_builtin.json()
    assert data["status"] == "succeeded"
    assert "job_id" in data
    job_id = data["job_id"]

    r_job = web_client.get(f"/api/analysis/jobs/{job_id}")
    assert r_job.status_code == 200
    assert r_job.json()["job"]["job_id"] == job_id
    assert "output" in r_job.json()

    r_jobs = web_client.get("/api/analysis/jobs")
    assert r_jobs.status_code == 200
    assert any(j["job_id"] == job_id for j in r_jobs.json()["jobs"])


def test_analysis_tool_invoke(web_client, tmp_path: Path) -> None:
    exam_id = "invoke-exam"
    batch_id = _prepare_exam_batch(web_client, tmp_path, exam_id)

    r_invoke = web_client.post(
        "/api/analysis/tools/analysis.run_builtin",
        json={"arguments": {"builtin_id": "builtin:exam_stats_v1", "exam_id": exam_id, "batch_id": batch_id, "recompute": True}},
    )
    assert r_invoke.status_code == 200
    assert r_invoke.json()["status"] == "succeeded"


def test_analysis_script_job_endpoint_runtime(web_client) -> None:
    r_save = web_client.post(
        "/api/analysis/scripts",
        json={
            "name": "rt",
            "language": "python",
            "code": (
                "raw = get_rawdata()\n"
                "RESULT = HistogramChart(title='demo', data=[{'label': '人数', 'value': raw.get('student_count', 0)}])\n"
            ),
        },
    )
    assert r_save.status_code == 200
    script_id = r_save.json()["script"]["script_id"]

    r_run = web_client.post(
        "/api/analysis/jobs/script",
        json={"script_id": script_id, "exam_id": "e1", "batch_id": "b1"},
    )
    assert r_run.status_code == 200
    assert r_run.json()["status"] in {"succeeded", "failed"}
    if r_run.json()["status"] == "failed":
        assert r_run.json()["error_code"] in {"timeout", "sandbox_violation", "runtime_error", "resource_exceeded"}
    else:
        assert "chart_specs" in r_run.json()["output"]


def test_analysis_tools_schema_version_and_idempotency(web_client, tmp_path: Path) -> None:
    tools = web_client.get("/api/analysis/tools")
    assert tools.status_code == 200
    assert all("schema_version" in t for t in tools.json()["tools"])

    exam_id = "idem-exam"
    batch_id = _prepare_exam_batch(web_client, tmp_path, exam_id)
    request_id = "req-001"
    r1 = web_client.post(
        "/api/analysis/jobs/builtin",
        json={
            "builtin_id": "builtin:exam_stats_v1",
            "exam_id": exam_id,
            "batch_id": batch_id,
            "recompute": True,
            "request_id": request_id,
        },
    )
    assert r1.status_code == 200
    r2 = web_client.post(
        "/api/analysis/jobs/builtin",
        json={
            "builtin_id": "builtin:exam_stats_v1",
            "exam_id": exam_id,
            "batch_id": batch_id,
            "recompute": True,
            "request_id": request_id,
        },
    )
    assert r2.status_code == 200
    assert r1.json()["job_id"] == r2.json()["job_id"]


def test_agent_function_calling_end_to_end(web_client) -> None:
    r_tools = web_client.get("/api/analysis/tools")
    assert r_tools.status_code == 200
    tool_names = {t["name"] for t in r_tools.json()["tools"]}
    assert "analysis.save_script" in tool_names
    assert "analysis.run_script" in tool_names
    assert "analysis.get_job" in tool_names

    r_save = web_client.post(
        "/api/analysis/tools/analysis.save_script",
        json={"arguments": {"name": "agent-script", "language": "python", "code": "RESULT = {'summary': {'status': 'ok'}}"}},
    )
    assert r_save.status_code == 200
    script_id = r_save.json()["script"]["script_id"]

    r_run = web_client.post(
        "/api/analysis/tools/analysis.run_script",
        json={"arguments": {"script_id": script_id, "exam_id": "e1", "batch_id": "b1", "request_id": "agent-e2e-1"}},
    )
    assert r_run.status_code == 200
    job_id = r_run.json()["job_id"]

    r_job = web_client.post(
        "/api/analysis/tools/analysis.get_job",
        json={"arguments": {"job_id": job_id, "include_output": True}},
    )
    assert r_job.status_code == 200
    assert r_job.json()["job"]["job_id"] == job_id
    assert "output" in r_job.json()
    assert "duration_ms" in r_job.json()["job"]


def test_analysis_folder_script_endpoints(web_client, tmp_path: Path) -> None:
    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "demo.py").write_text("RESULT = {'summary': {'status': 'ok'}}\n", encoding="utf-8")

    listed = web_client.get("/api/analysis/folder-scripts")
    assert listed.status_code == 200
    assert any(x["path"] == "demo.py" for x in listed.json()["scripts"])

    run = web_client.post(
        "/api/analysis/jobs/script-from-folder",
        json={"script_path": "demo.py", "exam_id": "e1", "batch_id": "b1"},
    )
    assert run.status_code == 200
    assert run.json()["status"] in {"succeeded", "failed"}
