"""Web-layer path safety wrappers.

核心逻辑已迁移到 solaire.common.security（不依赖 FastAPI）。
此模块保留向后兼容接口，将 ValueError 包装为 FastAPI HTTPException(400)。

外部核心模块（edu_analysis、knowledge_forge 等）请改为直接使用
solaire.common.security，不要从此模块导入。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from solaire.common.security import (
    PathEscapesProjectRoot,
    assert_within_project as _assert_within_project,
    content_disposition_attachment,
    export_slug,
    safe_filename_component,
    safe_project_name as _safe_project_name,
    unique_child_dir,
)

__all__ = [
    "assert_within_project",
    "safe_project_name",
    "safe_filename_component",
    "content_disposition_attachment",
    "export_slug",
    "unique_child_dir",
]


def assert_within_project(project_root: Path, path: Path) -> Path:
    """Resolve path and ensure it is under project_root.

    Raises HTTPException(400) if path escapes the project root.
    """
    try:
        return _assert_within_project(project_root, path)
    except PathEscapesProjectRoot as e:
        raise HTTPException(status_code=400, detail="Path escapes project root") from e


def safe_project_name(name: str) -> str:
    """Validate project name, raising HTTPException(400) on failure."""
    try:
        return _safe_project_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
