"""Load per-file question YAML from each library; index by qualified id (namespace/root_id)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import yaml

from solaire.exam_compiler.models import BankRecord, parse_bank_root


@dataclass
class LoadedQuestions:
    """qualified_id -> standalone question or whole group record; namespace -> library root for assets."""

    by_qualified: dict[str, BankRecord] = field(default_factory=dict)
    library_roots: dict[str, Path] = field(default_factory=dict)


def _iter_question_files(library_root: Path) -> Iterator[Path]:
    """
    Every ``*.yaml`` under the library except ``questions.yaml`` at the library root
    (merged pack is import-only, not part of discovery).
    """
    merged_res = (library_root / "questions.yaml").resolve()
    merged_exists = (library_root / "questions.yaml").is_file()
    seen: set[Path] = set()
    for p in sorted(library_root.rglob("*.yaml")):
        if not p.is_file():
            continue
        rp = p.resolve()
        if merged_exists and rp == merged_res:
            continue
        if rp in seen:
            continue
        seen.add(rp)
        yield p


def iter_question_files(library_root: Path) -> Iterator[Path]:
    """Public iterator over per-file question YAML under a library (see :func:`_iter_question_files`)."""
    yield from _iter_question_files(library_root)


def _load_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_questions_from_yaml_file(path: Path, namespace: str) -> list[BankRecord]:
    """Load one YAML file: single root object or list of roots. Legacy ``{questions,groups}`` is rejected."""
    del namespace  # reserved for future path-relative rules
    raw = _load_yaml(path)
    if raw is None:
        return []
    if isinstance(raw, dict) and ("questions" in raw or "groups" in raw):
        raise ValueError(
            f"Legacy merged format not supported in {path}; use per-question files or the import pipeline."
        )
    if isinstance(raw, list):
        return [parse_bank_root(x) for x in raw]
    if isinstance(raw, dict):
        return [parse_bank_root(raw)]
    raise ValueError(f"Invalid YAML root in {path}")


def load_all_questions(exam_yaml: Path, question_libraries: list[tuple[str, str]]) -> LoadedQuestions:
    """
    question_libraries: list of (namespace, path_str relative to exam or absolute).

    Qualified id: ``namespace/root_id`` where ``root_id`` is the file's ``id`` (standalone or group).
    """
    exam_dir = exam_yaml.resolve().parent
    out = LoadedQuestions()
    seen_short: dict[tuple[str, str], Path] = {}

    for namespace, path_str in question_libraries:
        root = Path(path_str)
        if not root.is_absolute():
            root = (exam_dir / root).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Question library not a directory: {root}")
        out.library_roots[namespace] = root

        for qfile in _iter_question_files(root):
            try:
                records = load_questions_from_yaml_file(qfile, namespace)
            except Exception as e:
                raise ValueError(f"Invalid questions file {qfile}: {e}") from e
            for rec in records:
                key_ns = (namespace, rec.id)
                if key_ns in seen_short:
                    raise ValueError(
                        f"Duplicate question id '{rec.id}' in namespace '{namespace}' "
                        f"(files: {seen_short[key_ns]} and {qfile})"
                    )
                seen_short[key_ns] = qfile
                qid = f"{namespace}/{rec.id}"
                if qid in out.by_qualified:
                    raise ValueError(f"Internal error: duplicate qualified id {qid}")
                out.by_qualified[qid] = rec

    return out
