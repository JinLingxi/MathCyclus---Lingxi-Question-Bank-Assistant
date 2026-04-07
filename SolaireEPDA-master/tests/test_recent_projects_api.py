"""Tests for /api/recent-projects."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from solaire.web import bundled_paths, recent_projects
from solaire.web.app import app


def test_recent_projects_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(recent_projects, "app_data_dir", lambda: tmp_path)
    client = TestClient(app)
    r = client.get("/api/recent-projects")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_recent_projects_after_open(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(recent_projects, "app_data_dir", lambda: tmp_path)
    root = tmp_path / "proj_a"
    root.mkdir()
    (root / "templates").mkdir()
    (root / "resource").mkdir()
    (root / "result").mkdir()

    client = TestClient(app)
    r = client.post("/api/project/open", json={"root": str(root)})
    assert r.status_code == 200

    listed = client.get("/api/recent-projects").json()["items"]
    assert len(listed) >= 1
    assert listed[0]["path"] == str(root.resolve())

    data_file = tmp_path / "recent_projects.json"
    assert data_file.is_file()
    raw = json.loads(data_file.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    assert raw[0]["path"] == str(root.resolve())


def test_recent_projects_remove(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(recent_projects, "app_data_dir", lambda: tmp_path)
    root_a = tmp_path / "proj_a"
    root_b = tmp_path / "proj_b"
    for r in (root_a, root_b):
        r.mkdir()
        (r / "templates").mkdir()
        (r / "resource").mkdir()
        (r / "result").mkdir()

    client = TestClient(app)
    assert client.post("/api/project/open", json={"root": str(root_a)}).status_code == 200
    assert client.post("/api/project/open", json={"root": str(root_b)}).status_code == 200

    items = client.get("/api/recent-projects").json()["items"]
    assert len(items) == 2

    r = client.post("/api/recent-projects/remove", json={"path": str(root_a)})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "removed": True}

    listed = client.get("/api/recent-projects").json()["items"]
    paths = {x["path"] for x in listed}
    assert str(root_a.resolve()) not in paths
    assert str(root_b.resolve()) in paths

    r2 = client.post("/api/recent-projects/remove", json={"path": str(root_a)})
    assert r2.json()["removed"] is False


def test_project_close_unbinds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(recent_projects, "app_data_dir", lambda: tmp_path)
    root = tmp_path / "proj_x"
    root.mkdir()
    (root / "templates").mkdir()
    (root / "resource").mkdir()
    (root / "result").mkdir()

    client = TestClient(app)
    assert client.post("/api/project/open", json={"root": str(root)}).status_code == 200
    assert client.get("/api/project/info").json()["bound"] is True

    r = client.post("/api/project/close")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert client.get("/api/project/info").json()["bound"] is False


def test_project_create_empty_default_template(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(recent_projects, "app_data_dir", lambda: tmp_path)
    parent = tmp_path / "parents"
    parent.mkdir()
    client = TestClient(app)
    r = client.post("/api/project/create", json={"parent": str(parent), "name": "empty_proj"})
    assert r.status_code == 200
    root = Path(r.json()["root"])
    assert (root / "templates" / "README.txt").is_file()
    assert client.post("/api/project/close").status_code == 200


def test_project_create_math_copies_template(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(recent_projects, "app_data_dir", lambda: tmp_path)
    parent = tmp_path / "parents"
    parent.mkdir()
    tmpl = tmp_path / "tmpl"
    (tmpl / "templates").mkdir(parents=True)
    (tmpl / "templates" / "template.yaml").write_text("exam_title: x\n", encoding="utf-8")
    (tmpl / "resource").mkdir()
    (tmpl / "resource" / ".keep").write_text("", encoding="utf-8")
    monkeypatch.setattr(bundled_paths, "resolve_math_project_template_dir", lambda: tmpl)

    client = TestClient(app)
    r = client.post(
        "/api/project/create",
        json={"parent": str(parent), "name": "math_proj", "template": "math"},
    )
    assert r.status_code == 200
    root = Path(r.json()["root"])
    assert (root / "templates" / "template.yaml").read_text(encoding="utf-8").strip() == "exam_title: x"
    assert client.post("/api/project/close").status_code == 200


def test_project_create_math_template_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(recent_projects, "app_data_dir", lambda: tmp_path)
    parent = tmp_path / "parents"
    parent.mkdir()
    monkeypatch.setattr(bundled_paths, "resolve_math_project_template_dir", lambda: None)
    client = TestClient(app)
    r = client.post(
        "/api/project/create",
        json={"parent": str(parent), "name": "x", "template": "math"},
    )
    assert r.status_code == 503

