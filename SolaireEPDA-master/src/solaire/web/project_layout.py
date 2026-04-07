"""Ensure project directory layout (resource / result / templates / .solaire)."""

from __future__ import annotations

from pathlib import Path


def ensure_project_layout(root: Path) -> None:
    (root / "resource").mkdir(parents=True, exist_ok=True)
    (root / "result").mkdir(parents=True, exist_ok=True)
    (root / "templates").mkdir(parents=True, exist_ok=True)
    (root / ".solaire").mkdir(parents=True, exist_ok=True)
