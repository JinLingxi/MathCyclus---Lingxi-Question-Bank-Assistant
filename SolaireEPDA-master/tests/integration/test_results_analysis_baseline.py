"""Pre-migration black-box baseline tests for /api/results flow."""

from __future__ import annotations

from pathlib import Path

from ._helpers import write_exam_yaml


def test_results_full_flow_baseline(web_client, tmp_path: Path) -> None:
    # Arrange exam result directory
    exam_id = "baseline-exam"
    exam_dir = tmp_path / "result" / exam_id
    exam_dir.mkdir(parents=True)
    write_exam_yaml(exam_dir, exam_id, [("选择题", 2, 5.0), ("填空题", 1, 10.0)])

    # 1) list exams
    r_list = web_client.get("/api/results")
    assert r_list.status_code == 200
    exams = r_list.json()["exams"]
    target = next(x for x in exams if x["exam_id"] == exam_id)
    assert target["question_count"] == 3
    assert target["score_batch_count"] == 0

    # 2) summary
    r_summary = web_client.get(f"/api/results/{exam_id}/summary")
    assert r_summary.status_code == 200
    summary = r_summary.json()
    assert summary["question_count"] == 3
    assert summary["questions"][0]["header"] == "1.1"
    assert summary["questions"][2]["score_per_item"] == 10.0

    # 3) import scores
    csv_text = "姓名,学号,1.1,1.2,2.1\n甲,001,5,3,8\n乙,002,4,5,10\n"
    files = {"file": ("scores.csv", csv_text.encode("utf-8"), "text/csv")}
    r_import = web_client.post(f"/api/results/{exam_id}/scores", files=files)
    assert r_import.status_code == 200
    imported = r_import.json()
    batch_id = imported["batch_id"]
    assert imported["student_count"] == 2
    assert imported["question_count"] == 3

    # 4) recompute first, then fetch analysis
    r_recompute = web_client.post(f"/api/results/{exam_id}/scores/{batch_id}/recompute", json={})
    assert r_recompute.status_code == 200

    r_analysis = web_client.get(f"/api/results/{exam_id}/scores/{batch_id}")
    assert r_analysis.status_code == 200
    analysis = r_analysis.json()
    assert analysis["student_count"] == 2
    assert "question_stats" in analysis
    assert "student_stats" in analysis
    q11 = next(q for q in analysis["question_stats"] if q["header"] == "1.1")
    assert q11["avg_raw_score"] == 4.5
    assert "class_avg_ratio" in analysis

    # 5) recompute response keeps contract shape
    recomputed = r_recompute.json()
    assert set(recomputed.keys()) >= {"question_stats", "student_stats", "node_stats", "warnings"}

    # 6) delete score batch
    r_del_batch = web_client.delete(f"/api/results/{exam_id}/scores/{batch_id}")
    assert r_del_batch.status_code == 200
    assert r_del_batch.json()["ok"] is True

    r_batches = web_client.get(f"/api/results/{exam_id}/scores")
    assert r_batches.status_code == 200
    assert r_batches.json()["batches"] == []

    # 7) delete exam
    r_del_exam = web_client.delete(f"/api/results/{exam_id}")
    assert r_del_exam.status_code == 200
    assert r_del_exam.json()["ok"] is True

    r_list2 = web_client.get("/api/results")
    assert r_list2.status_code == 200
    assert all(x["exam_id"] != exam_id for x in r_list2.json()["exams"])


def test_results_error_baseline(web_client, tmp_path: Path) -> None:
    exam_id = "baseline-error"
    exam_dir = tmp_path / "result" / exam_id
    exam_dir.mkdir(parents=True)
    write_exam_yaml(exam_dir, exam_id, [("选择题", 1, 5.0)])

    # missing score batch
    r_missing_batch = web_client.get(f"/api/results/{exam_id}/scores/missing-batch")
    assert r_missing_batch.status_code == 404

    # invalid import with no student rows
    bad_csv = "姓名,学号,1.1\n"
    files = {"file": ("bad.csv", bad_csv.encode("utf-8"), "text/csv")}
    r_import = web_client.post(f"/api/results/{exam_id}/scores", files=files)
    assert r_import.status_code == 400
