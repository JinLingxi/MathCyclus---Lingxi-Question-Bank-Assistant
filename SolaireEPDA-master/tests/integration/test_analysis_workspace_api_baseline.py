"""Baseline contract/perf tests for analysis workspace APIs before migration."""

from __future__ import annotations

import time
from pathlib import Path

from ._helpers import write_exam_yaml


def _prepare_batch(web_client, tmp_path: Path, exam_id: str) -> str:
    exam_dir = tmp_path / "result" / exam_id
    exam_dir.mkdir(parents=True)
    write_exam_yaml(exam_dir, exam_id, [("选择题", 3, 5.0)])
    csv_text = "姓名,学号,1.1,1.2,1.3\n甲,001,5,4,2\n乙,002,4,5,0\n"
    files = {"file": ("scores.csv", csv_text.encode("utf-8"), "text/csv")}
    r = web_client.post(f"/api/results/{exam_id}/scores", files=files)
    assert r.status_code == 200
    return r.json()["batch_id"]


def test_analysis_workspace_contract_baseline(web_client, tmp_path: Path) -> None:
    exam_id = "workspace-baseline"
    batch_id = _prepare_batch(web_client, tmp_path, exam_id)

    r_summary = web_client.get(f"/api/results/{exam_id}/summary")
    assert r_summary.status_code == 200
    summary = r_summary.json()
    assert set(summary.keys()) >= {
        "exam_id",
        "exam_title",
        "question_count",
        "score_batches",
        "questions",
    }
    assert summary["score_batches"][0]["batch_id"] == batch_id

    # Pre-recompute response can be placeholder; lock this behavior too.
    r_analysis_before = web_client.get(f"/api/results/{exam_id}/scores/{batch_id}")
    assert r_analysis_before.status_code == 200
    before = r_analysis_before.json()
    assert set(before.keys()) >= {
        "batch_id",
        "exam_id",
        "student_count",
        "question_count",
        "warnings",
        "question_stats",
        "node_stats",
        "student_stats",
    }

    r_recompute = web_client.post(f"/api/results/{exam_id}/scores/{batch_id}/recompute", json={})
    assert r_recompute.status_code == 200
    data = r_recompute.json()
    assert set(data.keys()) >= {
        "batch_id",
        "exam_id",
        "student_count",
        "question_count",
        "warnings",
        "question_stats",
        "node_stats",
        "student_stats",
        "class_avg_ratio",
        "class_avg_fuzzy",
    }
    # field semantic baseline
    assert all("avg_raw_score" in q for q in data["question_stats"])
    assert all("error_rate" in q for q in data["question_stats"])


def test_analysis_workspace_perf_baseline(web_client, tmp_path: Path) -> None:
    exam_id = "workspace-perf"
    batch_id = _prepare_batch(web_client, tmp_path, exam_id)

    # Ensure computed payload is present before measuring read path.
    warmup = web_client.post(f"/api/results/{exam_id}/scores/{batch_id}/recompute", json={})
    assert warmup.status_code == 200

    t0 = time.perf_counter()
    r_analysis = web_client.get(f"/api/results/{exam_id}/scores/{batch_id}")
    elapsed_get = time.perf_counter() - t0
    assert r_analysis.status_code == 200

    t1 = time.perf_counter()
    r_recompute = web_client.post(f"/api/results/{exam_id}/scores/{batch_id}/recompute", json={})
    elapsed_recompute = time.perf_counter() - t1
    assert r_recompute.status_code == 200

    # Baseline guardrail: keep generous limits to avoid CI noise.
    assert elapsed_get < 2.0
    assert elapsed_recompute < 2.0
