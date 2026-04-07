"""Tests for GET /api/help/index and GET /api/help/page/{id}."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from solaire.web.app import app


def _write_minimal_help_doc(root: Path) -> None:
    manifest = {
        "pages": [
            {
                "id": "hello",
                "title": "Hello",
                "path": "user/hello.md",
                "audience": "user",
            }
        ]
    }
    (root / "help-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (root / "user").mkdir(parents=True, exist_ok=True)
    (root / "user" / "hello.md").write_text("# Hi\n\nBody **text**.\n", encoding="utf-8")


def test_help_index_and_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc_root = tmp_path / "solaire_doc"
    doc_root.mkdir(parents=True)
    _write_minimal_help_doc(doc_root)
    monkeypatch.setenv("SOLAIRE_HELP_DOC_ROOT", str(doc_root))

    client = TestClient(app)
    r = client.get("/api/help/index")
    assert r.status_code == 200
    data = r.json()
    assert "pages" in data
    assert len(data["pages"]) == 1
    assert data["pages"][0]["id"] == "hello"
    assert data["pages"][0]["title"] == "Hello"
    assert data["pages"][0].get("section") == "guide"

    r2 = client.get("/api/help/page/hello")
    assert r2.status_code == 200
    page = r2.json()
    assert page["id"] == "hello"
    assert "Body" in page["markdown"]
    assert "text" in page["markdown"]


def test_help_asset_svg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc_root = tmp_path / "solaire_doc"
    doc_root.mkdir(parents=True)
    _write_minimal_help_doc(doc_root)
    asset_dir = doc_root / "assets" / "primebrush"
    asset_dir.mkdir(parents=True)
    (asset_dir / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    monkeypatch.setenv("SOLAIRE_HELP_DOC_ROOT", str(doc_root))

    client = TestClient(app)
    r = client.get("/api/help/asset/primebrush/demo.svg")
    assert r.status_code == 200
    assert "svg" in r.text.lower()


def test_help_asset_path_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc_root = tmp_path / "solaire_doc"
    doc_root.mkdir(parents=True)
    _write_minimal_help_doc(doc_root)
    monkeypatch.setenv("SOLAIRE_HELP_DOC_ROOT", str(doc_root))

    client = TestClient(app)
    r = client.get("/api/help/asset/../help-manifest.json")
    assert r.status_code in (400, 403, 404)


def test_help_page_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc_root = tmp_path / "solaire_doc"
    doc_root.mkdir(parents=True)
    _write_minimal_help_doc(doc_root)
    monkeypatch.setenv("SOLAIRE_HELP_DOC_ROOT", str(doc_root))

    client = TestClient(app)
    r = client.get("/api/help/page/missing")
    assert r.status_code == 404
