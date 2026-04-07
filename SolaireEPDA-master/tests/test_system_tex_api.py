"""Tests for /api/system/tex-status and /api/system/tex-install."""

from __future__ import annotations

import sys
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from solaire.web.app import app
from solaire.web import exam_service


def test_tex_status_returns_keys() -> None:
    client = TestClient(app)
    r = client.get("/api/system/tex-status")
    assert r.status_code == 200
    data = r.json()
    assert "platform" in data
    assert "latexmk_on_path" in data
    assert "xelatex_on_path" in data
    assert "pdf_engine_ready" in data
    assert isinstance(data["pdf_engine_ready"], bool)


def test_exam_export_error_friendly_when_latexmk_missing() -> None:
    exc = RuntimeError(
        "PDF 编译失败（XeLaTeX / latexmk）。以下为输出摘要：\n\n"
        "latexmk not found. Install TeX Live or MiKTeX and ensure latexmk is on PATH."
    )
    msg = exam_service.exam_export_error_detail_short(exc)
    assert "未检测到" in msg or "排版组件" in msg
    assert "latexmk not found" not in msg


@pytest.mark.skipif(sys.platform != "win32", reason="tex-install is Windows-only")
def test_tex_install_calls_winget(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    class DummyPopen:
        def __init__(self, *args: object, **kwargs: object) -> None:
            called["args"] = args
            called["kwargs"] = kwargs

    monkeypatch.setattr("solaire.web.system_tools.shutil.which", lambda x: "C:\\winget.exe" if x == "winget" else None)
    monkeypatch.setattr("solaire.web.system_tools.subprocess.Popen", DummyPopen)

    client = TestClient(app)
    r = client.post("/api/system/tex-install")
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True
    assert "args" in called
