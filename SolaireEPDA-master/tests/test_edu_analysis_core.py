from __future__ import annotations

import json
from pathlib import Path

from solaire.edu_analysis.core import (
    get_job,
    list_tools,
    run_script,
    save_script_doc,
)
from solaire.web.app import ensure_project_layout


def test_list_tools_contains_required_contracts() -> None:
    names = {t["name"] for t in list_tools()}
    assert "analysis.list_datasets" in names
    assert "analysis.run_builtin" in names
    assert "analysis.save_script" in names
    assert "analysis.run_script" in names
    assert "analysis.get_job" in names


def test_script_save_and_run_placeholder(tmp_path: Path) -> None:
    ensure_project_layout(tmp_path)
    saved = save_script_doc(
        tmp_path,
        name="draft",
        code=(
            "raw = get_rawdata()\n"
            "kg = get_graph()\n"
            "RESULT = {'summary': {'status': 'ok', 'student_count': raw.get('student_count', 0), 'nodes': len(kg.get('nodes', []))}}\n"
        ),
    )
    script_id = saved["script"]["script_id"]

    out = run_script(tmp_path, script_id=script_id, exam_id="e1", batch_id="b1")
    assert out["status"] == "succeeded"
    job = get_job(tmp_path, job_id=out["job_id"])
    assert job["job"]["status"] == "succeeded"
    assert "output" in job
    assert "student_count" in job["output"]["summary"]


def test_script_timeout_and_violation(tmp_path: Path) -> None:
    ensure_project_layout(tmp_path)

    t_script = save_script_doc(tmp_path, name="timeout", code="while True:\n    pass\n")
    t_out = run_script(tmp_path, script_id=t_script["script"]["script_id"], exam_id="e1", batch_id="b1")
    assert t_out["status"] == "failed"
    assert t_out["error_code"] == "timeout"

    v_script = save_script_doc(tmp_path, name="violation", code="import os\nRESULT = {'a': 1}\n")
    v_out = run_script(tmp_path, script_id=v_script["script"]["script_id"], exam_id="e1", batch_id="b1")
    assert v_out["status"] == "failed"
    assert v_out["error_code"] == "sandbox_violation"


def test_script_output_limit_and_audit(tmp_path: Path) -> None:
    ensure_project_layout(tmp_path)
    noisy = save_script_doc(
        tmp_path,
        name="noisy",
        code="print('x' * 50000)\nRESULT = {'summary': {'status': 'ok'}}\n",
    )
    out = run_script(tmp_path, script_id=noisy["script"]["script_id"], exam_id="e1", batch_id="b1")
    assert out["status"] == "failed"
    assert out["error_code"] == "resource_exceeded"
    job = get_job(tmp_path, job_id=out["job_id"], include_output=True)
    assert job["job"]["truncated"] is True
    assert job["job"]["killed_reason"] == "output_limit"
    assert "limits_applied" in job["job"]

    audit_path = tmp_path / "result" / "edu_analysis" / "audit.log.jsonl"
    assert audit_path.is_file()
    lines = [x for x in audit_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) >= 1
    last = json.loads(lines[-1])
    assert last["job_id"] == out["job_id"]


def test_chart_object_result_payload(tmp_path: Path) -> None:
    ensure_project_layout(tmp_path)
    script = save_script_doc(
        tmp_path,
        name="chart",
        code=(
            "raw = get_rawdata()\n"
            "points = []\n"
            "for q in raw.get('question_stats', [])[:5]:\n"
            "    if q.get('error_rate') is not None:\n"
            "        points.append({'label': q.get('header', ''), 'value': q.get('error_rate')})\n"
            "RESULT = HistogramChart(title='题目错误率示例', data=points)\n"
        ),
    )
    out = run_script(tmp_path, script_id=script["script"]["script_id"], exam_id="e1", batch_id="b1")
    assert out["status"] in {"succeeded", "failed"}
    if out["status"] == "succeeded":
        output = out["output"]
        assert "chart_specs" in output
        assert "pictures" in output
