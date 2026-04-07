from __future__ import annotations

import json
import time
import threading
import uuid
from pathlib import Path
from typing import Any

from solaire.edu_analysis.ports import get_result_port

from .diagnosis import (
    class_heatmap_v1,
    knowledge_diagnosis_v1,
    student_knowledge_diagnosis_v1,
    teaching_suggestions_v1,
)
from .contracts import (
    EXECUTOR_ALLOWED_IMPORTS,
    EXECUTOR_BLOCKED_IMPORT_PREFIXES,
    EXECUTOR_DEFAULT_LIMITS,
    EXECUTOR_SAFE_BUILTINS,
    TOOL_SPECS,
)
from .registry import list_builtins as registry_list_builtins
from .executor import build_runtime_dataset, execute_python_script
from .storage import (
    append_audit_record,
    bind_request_to_job,
    delete_script,
    get_job_for_request,
    list_jobs,
    list_scripts,
    load_job,
    load_output,
    load_script,
    save_job,
    save_output,
    save_script,
)

_EXECUTOR_SEMAPHORE = threading.BoundedSemaphore(EXECUTOR_DEFAULT_LIMITS["max_concurrent_jobs"])

_DIAGNOSIS_BUILTIN_FNS: dict[str, Any] = {
    "builtin:knowledge_diagnosis_v1": knowledge_diagnosis_v1,
    "builtin:student_diagnosis_v1": lambda pr, e, b: student_knowledge_diagnosis_v1(pr, e, b, student_id=None),
    "builtin:class_heatmap_v1": class_heatmap_v1,
    "builtin:teaching_suggestions_v1": teaching_suggestions_v1,
}


def list_tools() -> list[dict[str, Any]]:
    return TOOL_SPECS


def list_datasets(project_root: Path) -> dict[str, Any]:
    exams = get_result_port().list_exam_results(project_root)
    return {"datasets": exams}


def _builtin_to_protocol(raw: dict[str, Any], exam_id: str, batch_id: str) -> dict[str, Any]:
    question_stats = raw.get("question_stats", [])
    student_stats = raw.get("student_stats", [])
    header_labels = [q.get("header", "") for q in question_stats if q.get("error_rate") is not None][:20]
    error_values = [float(q.get("error_rate") or 0.0) for q in question_stats if q.get("error_rate") is not None][:20]

    output = {
        "summary": {
            "title": "内置考试统计分析",
            "status": "succeeded",
            "student_count": raw.get("student_count", 0),
            "question_count": raw.get("question_count", 0),
            "class_avg_ratio": raw.get("class_avg_ratio", 0),
            "class_avg_fuzzy": raw.get("class_avg_fuzzy", 0),
        },
        "tables": [
            {"id": "question_stats", "title": "题目统计", "rows": question_stats},
            {"id": "student_stats", "title": "学生统计", "rows": student_stats},
            {"id": "node_stats", "title": "知识点统计", "rows": raw.get("node_stats", [])},
        ],
        "chart_specs": [
            {
                "id": "question_error_rate_top20",
                "type": "bar",
                "title": "题目错误率（前20）",
                "series_id": "question_error_rate_series",
                "x": "label",
                "y": "value",
            }
        ],
        "series": [
            {
                "id": "question_error_rate_series",
                "points": [{"label": label, "value": val} for label, val in zip(header_labels, error_values)],
            }
        ],
        "logs": [],
        "warnings": [w.get("message", "") for w in raw.get("warnings", []) if isinstance(w, dict)],
        "context": {"exam_id": exam_id, "batch_id": batch_id, "source": "builtin:exam_stats_v1"},
        "raw": raw,
    }
    # Default analysis is aligned with script chart protocol.
    points = output["series"][0]["points"] if output.get("series") else []
    if points:
        bars = "".join(
            f"<rect x='{20 + i * 12}' y='{200 - int(float(p.get('value', 0.0)) * 160)}' width='8' height='{max(2, int(float(p.get('value', 0.0)) * 160))}' fill='#3b82f6'/>"
            for i, p in enumerate(points[:30])
        )
        output["pictures"] = [
            {
                "id": "builtin_exam_stats_picture",
                "type": "svg",
                "content": f"<svg xmlns='http://www.w3.org/2000/svg' width='640' height='220'><rect width='100%' height='100%' fill='white'/><text x='12' y='18' font-size='14' fill='#0f172a'>题目错误率（前20）</text>{bars}</svg>",
            }
        ]
    return output


def run_builtin(
    project_root: Path,
    *,
    builtin_id: str,
    exam_id: str,
    batch_id: str,
    recompute: bool = False,
    request_id: str | None = None,
) -> dict[str, Any]:
    if request_id:
        existing_job_id = get_job_for_request(project_root, request_id)
        if existing_job_id:
            existing = get_job(project_root, job_id=existing_job_id, include_output=True)
            out: dict[str, Any] = {
                "job_id": existing_job_id,
                "status": str(existing["job"].get("status", "unknown")),
            }
            if "output" in existing:
                out["output"] = existing["output"]
            if existing["job"].get("error"):
                out["error"] = existing["job"]["error"]
            if existing["job"].get("error_code"):
                out["error_code"] = existing["job"]["error_code"]
            return out

    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "kind": "builtin",
        "builtin_id": builtin_id,
        "exam_id": exam_id,
        "batch_id": batch_id,
        "status": "running",
        "error": None,
        "output_ref": None,
    }
    save_job(project_root, job)
    if request_id:
        bind_request_to_job(project_root, request_id, job_id)
    start = time.perf_counter()
    try:
        if builtin_id == "builtin:exam_stats_v1":
            port = get_result_port()
            raw = port.compute_statistics(project_root, exam_id, batch_id) if recompute else port.get_score_analysis(project_root, exam_id, batch_id)
            output = _builtin_to_protocol(raw, exam_id, batch_id)
        elif builtin_id in _DIAGNOSIS_BUILTIN_FNS:
            raw = _DIAGNOSIS_BUILTIN_FNS[builtin_id](project_root, exam_id, batch_id)
            rows = raw.get("nodes") or raw.get("students") or raw.get("rows") or []
            output = {
                "summary": {
                    "title": builtin_id,
                    "status": "succeeded",
                    "exam_id": exam_id,
                    "batch_id": batch_id,
                },
                "tables": [{"id": "diagnosis_main", "title": "诊断结果", "rows": rows if isinstance(rows, list) else []}],
                "chart_specs": [],
                "series": [],
                "logs": [],
                "warnings": [],
                "context": {"exam_id": exam_id, "batch_id": batch_id, "source": builtin_id},
                "raw": raw,
            }
        else:
            raise ValueError(f"Unknown builtin_id: {builtin_id}")
        output_ref = save_output(project_root, job_id, output)
        job["status"] = "succeeded"
        job["output_ref"] = output_ref
        job["duration_ms"] = int((time.perf_counter() - start) * 1000)
        save_job(project_root, job)
        append_audit_record(
            project_root,
            {
                "job_id": job_id,
                "script_id": None,
                "request_id": request_id,
                "status": "succeeded",
                "error_code": None,
                "duration_ms": job["duration_ms"],
            },
        )
        return {"job_id": job_id, "status": "succeeded", "output": output}
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        job["error_code"] = "runtime_error"
        job["duration_ms"] = int((time.perf_counter() - start) * 1000)
        save_job(project_root, job)
        append_audit_record(
            project_root,
            {
                "job_id": job_id,
                "script_id": None,
                "request_id": request_id,
                "status": "failed",
                "error_code": "runtime_error",
                "duration_ms": job["duration_ms"],
            },
        )
        raise


def save_script_doc(
    project_root: Path,
    *,
    name: str,
    code: str,
    script_id: str | None = None,
    language: str = "python",
) -> dict[str, Any]:
    sid = script_id or uuid.uuid4().hex
    payload = {
        "script_id": sid,
        "name": name,
        "language": language,
        "code": code,
    }
    if script_id:
        old = load_script(project_root, sid)
        payload["created_at"] = old.get("created_at")
    script = save_script(project_root, payload)
    return {"script": script}


def _normalize_protocol_output(execution_result: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    result_payload = execution_result.get("result")
    picture = execution_result.get("picture")
    if isinstance(result_payload, dict):
        output = dict(result_payload)
    else:
        output = {
            "summary": {"title": "脚本分析结果", "status": execution_result.get("status", "unknown")},
            "tables": [],
            "chart_specs": [],
            "series": [],
        }
        if result_payload is not None:
            output["result"] = result_payload
    output.setdefault("summary", {"title": "脚本分析结果", "status": execution_result.get("status", "unknown")})
    output.setdefault("tables", [])
    output.setdefault("chart_specs", [])
    output.setdefault("series", [])
    output.setdefault("logs", [])
    output.setdefault("warnings", [])
    output.setdefault("context", context)
    std_out = execution_result.get("stdout")
    if std_out:
        output["logs"] = [*output.get("logs", []), std_out]
    std_err = execution_result.get("stderr")
    if std_err:
        output["warnings"] = [*output.get("warnings", []), std_err]
    output["limits_applied"] = execution_result.get("limits_applied", {})
    output["truncated"] = bool(execution_result.get("truncated", False))
    output["killed_reason"] = execution_result.get("killed_reason")
    if picture:
        output["pictures"] = [{"id": "script_picture_1", "type": "svg", "content": picture}]
    return output


def run_script(project_root: Path, *, script_id: str, exam_id: str, batch_id: str) -> dict[str, Any]:
    return run_script_with_request_id(project_root, script_id=script_id, exam_id=exam_id, batch_id=batch_id, request_id=None)


def run_script_with_request_id(
    project_root: Path,
    *,
    script_id: str,
    exam_id: str,
    batch_id: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    if request_id:
        existing_job_id = get_job_for_request(project_root, request_id)
        if existing_job_id:
            existing = get_job(project_root, job_id=existing_job_id, include_output=True)
            out: dict[str, Any] = {
                "job_id": existing_job_id,
                "status": str(existing["job"].get("status", "unknown")),
            }
            if "output" in existing:
                out["output"] = existing["output"]
            if existing["job"].get("error"):
                out["error"] = existing["job"]["error"]
            if existing["job"].get("error_code"):
                out["error_code"] = existing["job"]["error_code"]
            return out

    script = load_script(project_root, script_id)
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "kind": "script",
        "script_id": script_id,
        "exam_id": exam_id,
        "batch_id": batch_id,
        "status": "running",
        "error": None,
        "error_code": None,
        "output_ref": None,
        "limits_applied": {
            "timeout_seconds": EXECUTOR_DEFAULT_LIMITS["timeout_seconds"],
            "max_output_bytes": EXECUTOR_DEFAULT_LIMITS["max_output_bytes"],
            "max_cpu_seconds": EXECUTOR_DEFAULT_LIMITS["max_cpu_seconds"],
            "max_memory_mb": EXECUTOR_DEFAULT_LIMITS["max_memory_mb"],
        },
        "truncated": False,
        "killed_reason": None,
    }
    save_job(project_root, job)
    if request_id:
        bind_request_to_job(project_root, request_id, job_id)
    start = time.perf_counter()
    acquired = _EXECUTOR_SEMAPHORE.acquire(timeout=EXECUTOR_DEFAULT_LIMITS["timeout_seconds"])
    if not acquired:
        execution = {
            "status": "failed",
            "error_code": "resource_exceeded",
            "error": "executor concurrency limit reached",
            "stdout": "",
            "stderr": "",
            "truncated": False,
            "killed_reason": "queue_timeout",
            "limits_applied": job["limits_applied"],
        }
    else:
        try:
            rawdata, graph = build_runtime_dataset(project_root, exam_id, batch_id)
            execution = execute_python_script(
                str(script.get("code", "")),
                rawdata=rawdata,
                graph=graph,
                timeout_seconds=EXECUTOR_DEFAULT_LIMITS["timeout_seconds"],
                max_output_bytes=EXECUTOR_DEFAULT_LIMITS["max_output_bytes"],
                max_cpu_seconds=EXECUTOR_DEFAULT_LIMITS["max_cpu_seconds"],
                max_memory_mb=EXECUTOR_DEFAULT_LIMITS["max_memory_mb"],
                safe_builtins=EXECUTOR_SAFE_BUILTINS,
                allowed_imports=EXECUTOR_ALLOWED_IMPORTS,
                blocked_import_prefixes=EXECUTOR_BLOCKED_IMPORT_PREFIXES,
            )
        finally:
            _EXECUTOR_SEMAPHORE.release()
    duration_ms = int((time.perf_counter() - start) * 1000)
    context = {"exam_id": exam_id, "batch_id": batch_id, "script_id": script_id}
    output = _normalize_protocol_output(execution, context)
    output_ref = save_output(project_root, job_id, output)

    if execution.get("status") == "succeeded":
        job["status"] = "succeeded"
        job["output_ref"] = output_ref
        job["truncated"] = bool(execution.get("truncated", False))
        job["killed_reason"] = execution.get("killed_reason")
        job["duration_ms"] = duration_ms
        save_job(project_root, job)
        append_audit_record(
            project_root,
            {
                "job_id": job_id,
                "script_id": script_id,
                "request_id": request_id,
                "status": "succeeded",
                "error_code": None,
                "duration_ms": duration_ms,
            },
        )
        return {"job_id": job_id, "status": "succeeded", "output": output}

    job["status"] = "failed"
    job["output_ref"] = output_ref
    job["error"] = str(execution.get("error", "Script execution failed"))
    job["error_code"] = str(execution.get("error_code", "runtime_error"))
    job["truncated"] = bool(execution.get("truncated", False))
    job["killed_reason"] = execution.get("killed_reason")
    job["duration_ms"] = duration_ms
    save_job(project_root, job)
    append_audit_record(
        project_root,
        {
            "job_id": job_id,
            "script_id": script_id,
            "request_id": request_id,
            "status": "failed",
            "error_code": job["error_code"],
            "duration_ms": duration_ms,
        },
    )
    return {
        "job_id": job_id,
        "status": "failed",
        "error": job["error"],
        "error_code": job["error_code"],
        "output": output,
    }


def get_job(project_root: Path, *, job_id: str, include_output: bool = True) -> dict[str, Any]:
    job = load_job(project_root, job_id)
    out: dict[str, Any] = {"job": job}
    if include_output and job.get("output_ref"):
        out["output"] = load_output(project_root, job["output_ref"])
    return out


def invoke_tool(project_root: Path, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "analysis.list_datasets":
        return list_datasets(project_root)
    if tool_name == "analysis.list_builtins":
        return {"builtins": registry_list_builtins()}
    if tool_name == "analysis.run_builtin":
        return run_builtin(
            project_root,
            builtin_id=str(args["builtin_id"]),
            exam_id=str(args["exam_id"]),
            batch_id=str(args["batch_id"]),
            recompute=bool(args.get("recompute", False)),
            request_id=str(args["request_id"]) if args.get("request_id") else None,
        )
    if tool_name == "analysis.save_script":
        return save_script_doc(
            project_root,
            script_id=args.get("script_id"),
            name=str(args["name"]),
            language=str(args.get("language", "python")),
            code=str(args["code"]),
        )
    if tool_name == "analysis.run_script":
        return run_script_with_request_id(
            project_root,
            script_id=str(args["script_id"]),
            exam_id=str(args["exam_id"]),
            batch_id=str(args["batch_id"]),
            request_id=str(args["request_id"]) if args.get("request_id") else None,
        )
    if tool_name == "analysis.get_job":
        return get_job(project_root, job_id=str(args["job_id"]), include_output=bool(args.get("include_output", True)))
    raise ValueError(f"Unknown tool: {tool_name}")


def list_scripts_api(project_root: Path) -> dict[str, Any]:
    return {"scripts": list_scripts(project_root)}


def get_script_api(project_root: Path, script_id: str) -> dict[str, Any]:
    return {"script": load_script(project_root, script_id)}


def delete_script_api(project_root: Path, script_id: str) -> dict[str, Any]:
    delete_script(project_root, script_id)
    return {"ok": True, "script_id": script_id}


def list_jobs_api(project_root: Path, limit: int = 50) -> dict[str, Any]:
    return {"jobs": list_jobs(project_root, limit=limit)}
