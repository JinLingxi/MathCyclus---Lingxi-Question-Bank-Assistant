"""学情诊断 API 与 edu_analysis.diagnosis 模块。"""
from __future__ import annotations

from pathlib import Path

from tests.integration._helpers import write_exam_yaml


def test_diagnosis_api_after_bind_and_recompute(web_client, tmp_path: Path) -> None:
    exam_id = "diag-api-exam"
    exam_dir = tmp_path / "result" / exam_id
    exam_dir.mkdir(parents=True)
    write_exam_yaml(exam_dir, exam_id, [("选择题", 1, 5.0)])

    csv_text = "姓名,学号,1.1\n甲,,5\n乙,,2\n"
    files = {"file": ("scores.csv", csv_text.encode("utf-8"), "text/csv")}
    r_import = web_client.post(f"/api/results/{exam_id}/scores", files=files)
    assert r_import.status_code == 200, r_import.text
    batch_id = r_import.json()["batch_id"]

    r0 = web_client.get(f"/api/results/{exam_id}/scores/{batch_id}")
    assert r0.status_code == 200
    qid = r0.json()["question_stats"][0]["question_id"]

    node_id = "math/diag/node_x"
    assert web_client.post(
        "/api/graph/nodes",
        json={"id": node_id, "canonical_name": "诊断点", "subject": "数学", "aliases": []},
    ).status_code == 200
    assert web_client.post(
        "/api/graph/bindings",
        json={"question_qualified_id": qid, "node_id": node_id},
    ).status_code == 200

    assert web_client.post(f"/api/results/{exam_id}/scores/{batch_id}/recompute", json={}).status_code == 200

    r = web_client.get("/api/analysis/diagnosis/knowledge", params={"exam_id": exam_id, "batch_id": batch_id})
    assert r.status_code == 200, r.text
    assert r.json().get("nodes")

    h = web_client.get("/api/analysis/diagnosis/class-heatmap", params={"exam_id": exam_id, "batch_id": batch_id})
    assert h.status_code == 200, h.text
    hm = h.json()
    assert len(hm.get("matrix", [])) == 2

    s = web_client.get("/api/analysis/diagnosis/suggestions", params={"exam_id": exam_id, "batch_id": batch_id})
    assert s.status_code == 200, s.text
    assert "retell_priority" in s.json()


def test_diagnosis_module_direct(tmp_path: Path) -> None:
    from solaire.edu_analysis.diagnosis import class_heatmap_v1, knowledge_diagnosis_v1
    from solaire.edu_analysis.ports import configure
    from solaire.web.app import ensure_project_layout
    from solaire.web.graph_service import bind_question_to_node, create_concept_node
    from solaire.web.result_service import ResultServiceAdapter, compute_statistics, import_scores

    configure(result_port=ResultServiceAdapter())

    root = tmp_path / "proj"
    ensure_project_layout(root)
    exam_id = "e-diag"
    exam_dir = root / "result" / exam_id
    exam_dir.mkdir(parents=True)
    write_exam_yaml(exam_dir, exam_id, [("选择题", 1, 5.0)])

    csv_data = "姓名,学号,1.1\n甲,,5\n乙,,3\n"
    res = import_scores(root, exam_id, csv_data.encode("utf-8"), "scores.csv")
    batch_id = res["batch_id"]

    r0 = compute_statistics(root, exam_id, batch_id)
    qid = r0["question_stats"][0]["question_id"]

    create_concept_node(root, {"id": "n1", "canonical_name": "N", "aliases": []})
    bind_question_to_node(root, {"question_qualified_id": qid, "node_id": "n1"})

    compute_statistics(root, exam_id, batch_id)

    kd = knowledge_diagnosis_v1(root, exam_id, batch_id)
    assert kd["nodes"]
    hm = class_heatmap_v1(root, exam_id, batch_id)
    assert len(hm["rows"]) == 2
