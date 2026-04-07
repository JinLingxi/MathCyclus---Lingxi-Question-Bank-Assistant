"""Resolve bundled on-disk assets for the web layer (project templates, etc.)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_MAX_ANCESTOR_WALK = 28


def _math_template_valid(p: Path) -> bool:
    """Require a real math starter tree, not an empty templates/ placeholder."""
    if not p.is_dir():
        return False
    if not (p / "templates" / "template.yaml").is_file():
        return False
    if not (p / "resource").is_dir():
        return False
    return True


def _candidate_paths() -> list[Path]:
    """Ordered search locations (deduped by resolve)."""
    seen: set[str] = set()
    out: list[Path] = []

    def add(p: Path) -> None:
        try:
            key = p.resolve().as_posix().lower()
        except OSError:
            return
        if key in seen:
            return
        seen.add(key)
        out.append(p)

    override = os.environ.get("SOLAIRE_MATH_TEMPLATE_SRC")
    if override:
        add(Path(override).expanduser())

    here = Path(__file__).resolve().parent
    add(here / "bundled_project_templates" / "math")

    for chain in (Path(__file__).resolve().parents, Path.cwd().resolve().parents):
        for i, base in enumerate(chain):
            if i >= _MAX_ANCESTOR_WALK:
                break
            add(base / "src" / "solaire" / "web" / "bundled_project_templates" / "math")
            add(base / "bundled_project_templates" / "math")

    try:
        exe = Path(sys.executable).resolve()
        add(exe.parent.parent / "sample_project")
    except OSError:
        pass

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            add(Path(meipass) / "sample_project")
        try:
            exe_dir = Path(sys.executable).resolve().parent
            add(exe_dir / "sample_project")
            add(exe_dir.parent / "sample_project")
        except OSError:
            pass

    return out


def resolve_math_project_template_dir() -> Path | None:
    """Directory whose contents are copied for «数学» new-project template."""
    for cand in _candidate_paths():
        try:
            resolved = cand.expanduser().resolve()
        except OSError:
            continue
        if _math_template_valid(resolved):
            return resolved
    return None
