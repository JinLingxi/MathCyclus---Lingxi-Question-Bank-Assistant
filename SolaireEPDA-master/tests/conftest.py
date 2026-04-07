"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from solaire.web.app import app, ensure_project_layout


@pytest.fixture
def web_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """FastAPI client with project root bound to tmp_path."""
    import solaire.web.state as st

    root = tmp_path.resolve()
    ensure_project_layout(root)
    monkeypatch.setattr(st, "get_root", lambda: root)
    return TestClient(app)
