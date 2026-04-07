"""Path safety and filename utilities for project-bound filesystem access.

这里的函数抛出标准 ValueError / TypeError，不依赖 FastAPI。
web 层可在异常处理器中将 ValueError 转换为 HTTPException(400)。
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote


class PathEscapesProjectRoot(ValueError):
    """Path is outside the allowed project root."""


def assert_within_project(project_root: Path, path: Path) -> Path:
    """Resolve *path* and ensure it is under *project_root*.

    Raises:
        PathEscapesProjectRoot: if the resolved path is outside the project root.
    """
    root = project_root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as e:
        raise PathEscapesProjectRoot(
            f"Path {resolved!r} escapes project root {root!r}"
        ) from e
    return resolved


def safe_project_name(name: str) -> str:
    """Validate and return a sanitized project name.

    Raises:
        ValueError: if the name is empty, too long, or contains illegal characters.
    """
    s = name.strip()
    if not s or len(s) > 200:
        raise ValueError("Invalid project name: must be 1-200 characters")
    if ".." in s or "/" in s or "\\" in s or ":" in s:
        raise ValueError("Project name must not contain path separators")
    return s


def safe_filename_component(s: str) -> str:
    """Sanitize a single path component for PDF / folder names."""
    t = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s.strip())
    return t or "export"


def content_disposition_attachment(filename: str) -> str:
    """Build a ``Content-Disposition`` header value for file downloads.

    Emits both ASCII ``filename`` and RFC 5987 ``filename*=UTF-8''…`` to handle
    non-ASCII characters without triggering latin-1 encode errors in Starlette.
    """
    if any(ord(c) > 127 for c in filename):
        ascii_name = "bank-export.bank.zip"
    else:
        ascii_name = "".join(
            c if 32 <= ord(c) < 127 and c not in '\\"<>;'
            else "_"
            for c in filename
        )
        ascii_name = re.sub(r"_+", "_", ascii_name).strip("._") or "bank-export.bank.zip"
        if not ascii_name.lower().endswith(".zip"):
            ascii_name = f"{ascii_name}.bank.zip"
    q = quote(filename, safe="")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{q}'


def export_slug(label: str) -> str:
    """Return a filesystem-safe folder name from a user-supplied label."""
    base = safe_filename_component(label)
    return base[:120] if len(base) > 120 else base


def unique_child_dir(parent: Path, base_name: str) -> Path:
    """Return ``parent / base_name`` or ``parent / base_name_2`` etc. if taken."""
    candidate = parent / base_name
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        alt = parent / f"{base_name}_{n}"
        if not alt.exists():
            return alt
        n += 1
