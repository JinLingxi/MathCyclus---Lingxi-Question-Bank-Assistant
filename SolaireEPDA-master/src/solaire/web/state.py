"""In-memory project root binding (per process)."""

from __future__ import annotations

import os
from pathlib import Path

_project_root: Path | None = None


def init_from_env() -> None:
    global _project_root
    raw = os.environ.get("SOLAIRE_PROJECT_ROOT")
    if not raw:
        return
    # 默认不根据环境变量自动绑定项目（启动后始终先进入欢迎页）。
    # 仅在显式设置 SOLAIRE_BIND_PROJECT_FROM_ENV=1（或 true/yes/on）时预绑定。
    flag = os.environ.get("SOLAIRE_BIND_PROJECT_FROM_ENV", "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return
    p = Path(raw).expanduser().resolve()
    if p.is_dir():
        _project_root = p


def set_root(root: Path) -> None:
    global _project_root
    _project_root = root.resolve()


def clear_root() -> None:
    """取消当前项目绑定（回到未打开项目状态）。"""
    global _project_root
    _project_root = None


def get_root() -> Path | None:
    return _project_root
