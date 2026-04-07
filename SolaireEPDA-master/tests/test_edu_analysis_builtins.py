from __future__ import annotations

from pathlib import Path

from solaire.edu_analysis.core import run_builtin
from solaire.web.app import ensure_project_layout
from solaire.web.result_service import import_scores

from tests.integration._helpers import write_exam_yaml


def test_builtin_exam_stats_v1(tmp_path: Path) -> None:
    ensure_project_layout(tmp_path)
    exam_id = "builtin-exam"
    exam_dir = tmp_path / "result" / exam_id
    exam_dir.mkdir(parents=True)
    write_exam_yaml(exam_dir, exam_id, [("选择题", 2, 5.0)])
    csv_text = "姓名,学号,1.1,1.2\n甲,001,5,4\n乙,002,3,1\n"
    imported = import_scores(tmp_path, exam_id, csv_text.encode("utf-8"), "scores.csv")

    res = run_builtin(
        tmp_path,
        builtin_id="builtin:exam_stats_v1",
        exam_id=exam_id,
        batch_id=imported["batch_id"],
        recompute=True,
    )
    assert res["status"] == "succeeded"
    assert res["output"]["summary"]["student_count"] == 2
    assert "tables" in res["output"]
    assert "chart_specs" in res["output"]
