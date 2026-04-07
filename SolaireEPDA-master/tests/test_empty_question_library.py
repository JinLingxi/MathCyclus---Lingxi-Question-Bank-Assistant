"""Empty project / no YAML: discovery and /api/questions return empty, no placeholder dirs required."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from solaire.web import state
from solaire.web.library_discovery import discover_question_library_refs
from solaire.web.project_layout import ensure_project_layout


def test_discover_question_library_refs_empty_when_no_yaml(tmp_path: Path) -> None:
    ensure_project_layout(tmp_path)
    assert discover_question_library_refs(tmp_path) == []


def test_ensure_project_layout_no_placeholder_file(tmp_path: Path) -> None:
    ensure_project_layout(tmp_path)
    ph = tmp_path / "resource" / "默认" / "默认" / "_placeholder.yaml"
    assert not ph.is_file()


def test_api_questions_empty_200(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from solaire.web.app import app

    root = tmp_path.resolve()
    ensure_project_layout(root)
    monkeypatch.setattr(state, "get_root", lambda: root)
    client = TestClient(app)
    r = client.get("/api/questions")
    assert r.status_code == 200
    assert r.json() == {"questions": []}


def test_api_questions_expand_failure_returns_200_with_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """插图展开失败时不应导致整表 500（回退为未展开题干）。"""
    from solaire.exam_compiler.models import QuestionItem
    from solaire.web.app import app
    from solaire.web import bank_service as bs

    root = tmp_path.resolve()
    ensure_project_layout(root)
    lib = root / "resource" / "数学" / "题库"
    lib.mkdir(parents=True)
    (lib / "q1.yaml").write_text(
        'id: q1\ntype: choice\ncontent: "题干"\noptions:\n  A: "a"\n  B: "b"\nanswer: A\n',
        encoding="utf-8",
    )

    def _boom(*_a: object, **_k: object) -> QuestionItem:
        raise RuntimeError("simulated expand failure")

    monkeypatch.setattr(state, "get_root", lambda: root)
    monkeypatch.setattr(bs, "expand_question_for_web", _boom)
    client = TestClient(app)
    r = client.get("/api/questions")
    assert r.status_code == 200
    body = r.json()
    assert len(body["questions"]) == 1
    assert body["questions"][0]["qualified_id"] == "数学/题库/q1"
