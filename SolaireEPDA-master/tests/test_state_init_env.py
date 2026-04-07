"""Tests for startup binding from SOLAIRE_PROJECT_ROOT (opt-in)."""

from __future__ import annotations

import pytest

from solaire.web import state


@pytest.fixture(autouse=True)
def _reset_project_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOLAIRE_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("SOLAIRE_BIND_PROJECT_FROM_ENV", raising=False)
    state.clear_root()
    yield
    state.clear_root()


def test_init_from_env_ignores_root_without_flag(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv("SOLAIRE_PROJECT_ROOT", str(root))
    monkeypatch.delenv("SOLAIRE_BIND_PROJECT_FROM_ENV", raising=False)
    state.clear_root()
    state.init_from_env()
    assert state.get_root() is None


def test_init_from_env_binds_when_flag_set(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv("SOLAIRE_PROJECT_ROOT", str(root))
    monkeypatch.setenv("SOLAIRE_BIND_PROJECT_FROM_ENV", "1")
    state.clear_root()
    state.init_from_env()
    assert state.get_root() == root.resolve()
