"""Filesystem helpers for exam / template / output paths."""

from __future__ import annotations

from pathlib import Path


def exam_parent_dir(exam_yaml: Path) -> Path:
    return exam_yaml.resolve().parent


def work_dir_for_exam(exam_yaml: Path) -> Path:
    """Temporary build folder: same parent as exam, folder named stem (no extension)."""
    p = exam_yaml.resolve()
    return p.parent / p.stem


def resolve_relative_to_exam(exam_yaml: Path, rel: str | Path) -> Path:
    base = exam_parent_dir(exam_yaml)
    return (base / Path(rel)).resolve()
