from __future__ import annotations

import ast
import inspect
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

from solaire.edu_analysis.ports import get_result_port

from . import charts as charts_module


def _truncate_text(s: str, limit: int = 20000) -> tuple[str, bool]:
    if len(s) <= limit:
        return s, False
    return s[:limit] + "\n...[truncated]", True


def build_graph_slice(rawdata: dict[str, Any]) -> dict[str, Any]:
    node_stats = rawdata.get("node_stats", [])
    if not isinstance(node_stats, list):
        return {"nodes": [], "edges": []}
    node_ids = set()
    edges: list[dict[str, Any]] = []
    for item in node_stats:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or "")
        if not node_id:
            continue
        node_ids.add(node_id)
        parent = node_id.rsplit("/", 1)[0] if "/" in node_id else ""
        if parent and parent in node_ids:
            edges.append({"from": parent, "to": node_id, "type": "part_of"})
    nodes = [{"id": nid} for nid in sorted(node_ids)]
    return {"nodes": nodes, "edges": edges}


def build_runtime_dataset(project_root: Path, exam_id: str, batch_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        port = get_result_port()
        raw = port.get_score_analysis(project_root, exam_id, batch_id)
        if not raw.get("question_stats"):
            raw = port.compute_statistics(project_root, exam_id, batch_id)
    except Exception:
        raw = {
            "exam_id": exam_id,
            "batch_id": batch_id,
            "student_count": 0,
            "question_count": 0,
            "question_stats": [],
            "node_stats": [],
            "student_stats": [],
            "warnings": [],
            "class_avg_ratio": 0.0,
            "class_avg_fuzzy": 0.0,
        }
    graph = build_graph_slice(raw)
    return raw, graph


def _validate_script_ast(
    code: str,
    *,
    blocked_import_prefixes: tuple[str, ...],
    allowed_imports: set[str],
) -> str | None:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"syntax error: {e.msg}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in blocked_import_prefixes:
                    return f"import '{alias.name}' is blocked"
                if root not in allowed_imports:
                    return f"import '{alias.name}' is not allowed"
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in blocked_import_prefixes:
                return f"import from '{node.module}' is blocked"
            if mod and mod not in allowed_imports:
                return f"import from '{node.module}' is not allowed"
    return None


def _sandbox_runner() -> None:
    import builtins
    import contextlib
    import importlib.util
    import io
    import json
    import traceback
    from pathlib import Path

    policy = json.load(open("runtime_policy.json", "r", encoding="utf-8"))
    allowed_imports = set(policy.get("allowed_imports", []))
    safe_builtin_names = list(policy.get("safe_builtins", []))
    missing = [name for name in safe_builtin_names if not hasattr(builtins, name)]
    if missing:
        raise RuntimeError(f"safe builtins not found: {missing}")
    safe_builtins = {name: getattr(builtins, name) for name in safe_builtin_names}

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        if root not in allowed_imports:
            raise PermissionError(f"import '{name}' is not allowed")
        return __import__(name, globals, locals, fromlist, level)

    safe_builtins["__import__"] = guarded_import

    rawdata = json.load(open("runtime_rawdata.json", "r", encoding="utf-8"))
    graph = json.load(open("runtime_graph.json", "r", encoding="utf-8"))
    charts_path = Path("runtime_charts.py").resolve()
    charts_spec = importlib.util.spec_from_file_location("runtime_charts", charts_path)
    if charts_spec is None or charts_spec.loader is None:
        raise RuntimeError("failed to load runtime_charts module")
    charts_mod = importlib.util.module_from_spec(charts_spec)
    charts_spec.loader.exec_module(charts_mod)
    base_chart = charts_mod.BaseChart
    histogram_chart = charts_mod.HistogramChart
    pie_chart = charts_mod.PieChart

    ns = {"__builtins__": safe_builtins, "RESULT": None, "__name__": "__main__"}
    ns["BaseChart"] = base_chart
    ns["HistogramChart"] = histogram_chart
    ns["PieChart"] = pie_chart

    def get_rawdata():
        return rawdata

    def get_graph():
        return graph

    ns["get_rawdata"] = get_rawdata
    ns["get_graph"] = get_graph
    out = io.StringIO()
    err = io.StringIO()
    code = open("user_script.py", "r", encoding="utf-8").read()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            exec(compile(code, "<user_script>", "exec"), ns, ns)
        result = ns.get("RESULT")
        payload = result
        picture = None
        result_kind = "value"
        if hasattr(result, "to_payload") and hasattr(result, "get_picture"):
            payload = result.to_payload()
            picture = result.get_picture()
            result_kind = "chart"
        elif isinstance(result, dict):
            result_kind = "dict"
        print(
            json.dumps(
                {
                    "status": "succeeded",
                    "result": payload,
                    "result_kind": result_kind,
                    "picture": picture,
                    "stdout": out.getvalue(),
                    "stderr": err.getvalue(),
                },
                ensure_ascii=False,
            )
        )
    except PermissionError as e:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_code": "sandbox_violation",
                    "error": str(e),
                    "stdout": out.getvalue(),
                    "stderr": err.getvalue(),
                },
                ensure_ascii=False,
            )
        )
    except Exception as e:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_code": "runtime_error",
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                    "stdout": out.getvalue(),
                    "stderr": err.getvalue(),
                },
                ensure_ascii=False,
            )
        )


def _build_runner_source() -> str:
    function_source = inspect.getsource(_sandbox_runner)
    return f'{function_source}\n\nif __name__ == "__main__":\n    _sandbox_runner()\n'


def execute_python_script(
    code: str,
    *,
    rawdata: dict[str, Any],
    graph: dict[str, Any],
    timeout_seconds: int,
    max_output_bytes: int,
    max_cpu_seconds: int,
    max_memory_mb: int,
    safe_builtins: tuple[str, ...],
    allowed_imports: set[str],
    blocked_import_prefixes: tuple[str, ...],
) -> dict[str, Any]:
    ast_error = _validate_script_ast(
        code,
        blocked_import_prefixes=blocked_import_prefixes,
        allowed_imports=allowed_imports,
    )
    if ast_error:
        return {
            "status": "failed",
            "error_code": "sandbox_violation",
            "error": ast_error,
            "stdout": "",
            "stderr": "",
            "truncated": False,
            "killed_reason": "policy_violation",
            "limits_applied": {
                "timeout_seconds": timeout_seconds,
                "max_output_bytes": max_output_bytes,
                "max_cpu_seconds": max_cpu_seconds,
                "max_memory_mb": max_memory_mb,
            },
        }

    runner = _build_runner_source()

    with tempfile.TemporaryDirectory(prefix="edu_analysis_") as td:
        temp_dir = Path(td)
        (temp_dir / "runner.py").write_text(runner, encoding="utf-8")
        (temp_dir / "user_script.py").write_text(code, encoding="utf-8")
        shutil.copyfile(Path(charts_module.__file__), temp_dir / "runtime_charts.py")
        (temp_dir / "runtime_policy.json").write_text(
            json.dumps(
                {
                    "allowed_imports": sorted(allowed_imports),
                    "safe_builtins": list(safe_builtins),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (temp_dir / "runtime_rawdata.json").write_text(json.dumps(rawdata, ensure_ascii=False), encoding="utf-8")
        (temp_dir / "runtime_graph.json").write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
        try:
            p = subprocess.run(
                [sys.executable, "-I", "runner.py"],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "failed",
                "error_code": "timeout",
                "error": f"Script execution exceeded {timeout_seconds}s timeout",
                "stdout": "",
                "stderr": "",
                "truncated": False,
                "killed_reason": "timeout",
                "limits_applied": {
                    "timeout_seconds": timeout_seconds,
                    "max_output_bytes": max_output_bytes,
                    "max_cpu_seconds": max_cpu_seconds,
                    "max_memory_mb": max_memory_mb,
                },
            }

    raw = (p.stdout or "").strip()
    if not raw:
        return {
            "status": "failed",
            "error_code": "runtime_error",
            "error": "No output returned by runner",
            "stdout": "",
            "stderr": (p.stderr or ""),
            "truncated": False,
            "killed_reason": "runner_no_output",
            "limits_applied": {
                "timeout_seconds": timeout_seconds,
                "max_output_bytes": max_output_bytes,
                "max_cpu_seconds": max_cpu_seconds,
                "max_memory_mb": max_memory_mb,
            },
        }
    last_line = raw.splitlines()[-1]
    try:
        data = json.loads(last_line)
        if isinstance(data, dict):
            data["limits_applied"] = {
                "timeout_seconds": timeout_seconds,
                "max_output_bytes": max_output_bytes,
                "max_cpu_seconds": max_cpu_seconds,
                "max_memory_mb": max_memory_mb,
            }
            s_out = str(data.get("stdout", ""))
            s_err = str(data.get("stderr", ""))
            s_tb = str(data.get("traceback", "")) if "traceback" in data else ""
            merged = "\n".join([s_out, s_err, s_tb])
            if len(merged.encode("utf-8", errors="ignore")) > max_output_bytes:
                data["status"] = "failed"
                data["error_code"] = "resource_exceeded"
                data["error"] = f"output exceeds {max_output_bytes} bytes limit"
                data["killed_reason"] = "output_limit"
                data["truncated"] = True
            o1, t1 = _truncate_text(s_out, max_output_bytes)
            o2, t2 = _truncate_text(s_err, max_output_bytes)
            data["stdout"] = o1
            data["stderr"] = o2
            data["truncated"] = bool(data.get("truncated")) or t1 or t2
            if "traceback" in data:
                tb, tt = _truncate_text(str(data["traceback"]), max_output_bytes)
                data["traceback"] = tb
                data["truncated"] = bool(data.get("truncated")) or tt
            data.setdefault("killed_reason", None)
            return data
    except Exception:
        pass
    return {
        "status": "failed",
        "error_code": "runtime_error",
        "error": "Invalid runner output",
        "stdout": raw,
        "stderr": p.stderr or "",
        "truncated": False,
        "killed_reason": "runner_output_parse_error",
        "limits_applied": {
            "timeout_seconds": timeout_seconds,
            "max_output_bytes": max_output_bytes,
            "max_cpu_seconds": max_cpu_seconds,
            "max_memory_mb": max_memory_mb,
        },
    }
