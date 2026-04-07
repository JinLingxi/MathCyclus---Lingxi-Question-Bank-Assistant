"""题组：详情 API 含 question_group（type: group 单文件）。"""

from __future__ import annotations

from pathlib import Path

import yaml

from solaire.exam_compiler.models import QuestionGroupRecord
from solaire.web.bank_service import delete_question, get_question_detail, save_bank_record


def _write_group_file(root: Path) -> None:
    lib = root / "resource" / "数学" / "高考真题"
    lib.mkdir(parents=True)
    text = """id: demo_context_choice
type: group
unified: choice
material: |
  共用材料
items:
  - content: "第一问"
    options:
      A: "1"
      B: "2"
    answer: A
    analysis: ""
    metadata: {}
  - content: "第二问"
    options:
      A: "3"
      B: "4"
    answer: B
    analysis: ""
    metadata: {}
"""
    (lib / "math_022.yaml").write_text(text, encoding="utf-8")


def test_get_question_detail_includes_question_group(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    _write_group_file(root)
    qid = "数学/高考真题/demo_context_choice"
    d = get_question_detail(root, qid)
    assert d["question_group"] is not None
    assert d["question_group"]["id"] == "demo_context_choice"
    assert d["question_group"]["type"] == "group"
    assert len(d["question_group"]["items"]) == 2
    assert d["question_group_preview"] is not None
    assert "共用材料" in d["question_group_preview"]["material"]


def test_save_group_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    _write_group_file(root)
    qid = "数学/高考真题/demo_context_choice"
    d = get_question_detail(root, qid)
    payload = dict(d["question_group"])
    payload["items"][0]["content"] = "已改第一问"
    g = QuestionGroupRecord.model_validate(payload)
    save_bank_record(root, qid, g)
    d2 = get_question_detail(root, qid)
    assert d2["question_group"]["items"][0]["content"] == "已改第一问"


def test_delete_group_removes_file(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    _write_group_file(root)
    qid = "数学/高考真题/demo_context_choice"
    delete_question(root, qid)
    p = root / "resource" / "数学" / "高考真题" / "math_022.yaml"
    assert not p.is_file()


def test_delete_by_storage_path_only_removes_target_file(tmp_path: Path) -> None:
    """相同题号在不同题集各有一份时，带 storage_path 只删对应 YAML。"""
    root = tmp_path / "proj"
    qyaml = """id: Q1
type: choice
content: "x"
options:
  A: "a"
  B: "b"
  C: "c"
  D: "d"
answer: A
analysis: ""
metadata: {}
"""
    mid = root / "resource" / "数学" / "期中"
    final = root / "resource" / "数学" / "期末"
    mid.mkdir(parents=True)
    final.mkdir(parents=True)
    (mid / "q.yaml").write_text(qyaml, encoding="utf-8")
    (final / "q.yaml").write_text(qyaml, encoding="utf-8")
    delete_question(root, "数学/期中/Q1", storage_path="数学/期中/q.yaml")
    assert not (mid / "q.yaml").is_file()
    assert (final / "q.yaml").is_file()
