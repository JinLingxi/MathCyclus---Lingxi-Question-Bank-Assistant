"""Persisted exam composition drafts under .solaire/drafts/."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from solaire.common.security import assert_within_project
from solaire.exam_compiler.facade import ExamConfig, SelectedSection


def _drafts_root(project_root: Path) -> Path:
    d = project_root / ".solaire" / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def template_path_to_project_relative(template_path: str | None) -> str:
    """Normalize exam.yaml template_path (often ../templates/x.yaml) to project-relative."""
    if not template_path:
        return ""
    s = template_path.replace("\\", "/").strip()
    if s.startswith("../"):
        return s[3:].lstrip("/")
    return s


def _section_dump(s: SelectedSection) -> dict[str, Any]:
    d: dict[str, Any] = {
        "section_id": s.section_id,
        "question_ids": list(s.question_ids),
    }
    if s.score_per_item is not None:
        d["score_per_item"] = s.score_per_item
    if s.score_overrides:
        d["score_overrides"] = dict(s.score_overrides)
    return d


def _sections_from_raw(items: list[dict[str, Any]] | None) -> list[SelectedSection]:
    if not items:
        return []
    out: list[SelectedSection] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("section_id") or "").strip()
        qids = raw.get("question_ids") or []
        if not sid or not isinstance(qids, list):
            continue
        spi = raw.get("score_per_item")
        score_per_item = float(spi) if spi is not None else None
        so = raw.get("score_overrides")
        score_overrides: dict[str, float] | None = None
        if isinstance(so, dict) and so:
            score_overrides = {str(k): float(v) for k, v in so.items()}
        out.append(
            SelectedSection(
                section_id=sid,
                question_ids=[str(x) for x in qids],
                score_per_item=score_per_item,
                score_overrides=score_overrides,
            )
        )
    return out


def list_drafts(project_root: Path) -> list[dict[str, Any]]:
    """Return draft summaries, newest updated first."""
    root = _drafts_root(project_root)
    rows: list[tuple[float, dict[str, Any]]] = []
    for p in root.glob("*.yaml"):
        if not p.is_file():
            continue
        try:
            with p.open(encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            if not isinstance(raw, dict):
                continue
            draft_id = str(raw.get("draft_id") or p.stem)
            updated = str(raw.get("updated_at") or "")
            mtime = p.stat().st_mtime
            rows.append(
                (
                    mtime,
                    {
                        "draft_id": draft_id,
                        "name": raw.get("name") or draft_id,
                        "subject": raw.get("subject"),
                        "export_label": raw.get("export_label"),
                        "template_ref": raw.get("template_ref"),
                        "template_path": raw.get("template_path"),
                        "updated_at": updated,
                    },
                )
            )
        except OSError:
            continue
    rows.sort(key=lambda x: x[0], reverse=True)
    return [r[1] for r in rows]


def load_draft(project_root: Path, draft_id: str) -> dict[str, Any]:
    """Load full draft payload for the compose UI."""
    assert draft_id.strip(), "draft_id required"
    safe_id = Path(draft_id).name
    path = _drafts_root(project_root) / f"{safe_id}.yaml"
    assert_within_project(project_root, path)
    if not path.is_file():
        raise FileNotFoundError(f"Draft not found: {draft_id}")
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError("Invalid draft file")
    return raw


def delete_draft(project_root: Path, draft_id: str) -> None:
    safe_id = Path(draft_id).name
    path = _drafts_root(project_root) / f"{safe_id}.yaml"
    assert_within_project(project_root, path)
    if path.is_file():
        path.unlink()


def normalize_draft_name(s: str) -> str:
    return " ".join((s or "").strip().split())


def _draft_name_entries(project_root: Path) -> list[tuple[str, str]]:
    """(draft_id, display name) from each draft file."""
    root = _drafts_root(project_root)
    out: list[tuple[str, str]] = []
    for p in root.glob("*.yaml"):
        if not p.is_file():
            continue
        try:
            with p.open(encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            if not isinstance(raw, dict):
                continue
            did = str(raw.get("draft_id") or p.stem)
            nm = str(raw.get("name") or "")
            out.append((did, nm))
        except OSError:
            continue
    return out


def draft_name_is_taken(project_root: Path, name: str, exclude_draft_id: str | None) -> bool:
    target = normalize_draft_name(name)
    if not target:
        return False
    excl = Path(exclude_draft_id).name if exclude_draft_id else None
    for did, nm in _draft_name_entries(project_root):
        if excl and did == excl:
            continue
        if normalize_draft_name(nm) == target:
            return True
    return False


def ensure_unique_draft_name(project_root: Path, desired: str) -> str:
    base = normalize_draft_name(desired)
    if not base:
        base = "未命名草稿"
    existing = {normalize_draft_name(nm) for _, nm in _draft_name_entries(project_root)}
    if base not in existing:
        return base
    n = 2
    while True:
        cand = f"{base} ({n})"
        if cand not in existing:
            return cand
        n += 1


def save_draft_after_export_failure(
    project_root: Path,
    *,
    template_ref: str,
    template_path: str,
    export_label: str,
    subject: str,
    selected_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist current selection when export fails; display name is unique (suffix if needed)."""
    base = f"{export_label.strip()} · {subject.strip()}".strip(" ·")
    if not base:
        base = "试卷草稿"
    unique_name = ensure_unique_draft_name(project_root, f"{base}（导出失败）")
    return save_draft(
        project_root,
        draft_id=None,
        name=unique_name,
        subject=subject,
        export_label=export_label,
        template_ref=template_ref,
        template_path=template_path,
        selected_items=selected_items,
    )


def save_draft(
    project_root: Path,
    *,
    draft_id: str | None,
    name: str | None,
    subject: str,
    export_label: str,
    template_ref: str,
    template_path: str,
    selected_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create or update a draft; returns full stored document."""
    tpl_rel = template_path.replace("\\", "/").strip().lstrip("/")
    sections = _sections_from_raw(selected_items)
    now = _utc_now_iso()
    root = _drafts_root(project_root)

    explicit_raw = (name or "").strip()
    default_name = f"{export_label or '试卷'} · {subject or ''}".strip(" ·")
    if not default_name:
        default_name = "未命名草稿"
    if explicit_raw:
        final_name = normalize_draft_name(explicit_raw)
        if not final_name:
            final_name = ensure_unique_draft_name(project_root, default_name)
        else:
            excl = Path(draft_id).name if draft_id else None
            if draft_name_is_taken(project_root, final_name, excl):
                raise ValueError("草稿名称已存在")
    else:
        final_name = ensure_unique_draft_name(project_root, default_name)

    if draft_id:
        safe_id = Path(draft_id).name
        path = root / f"{safe_id}.yaml"
        assert_within_project(project_root, path)
        created = now
        if path.is_file():
            with path.open(encoding="utf-8") as f:
                old = yaml.safe_load(f)
            if isinstance(old, dict) and old.get("created_at"):
                created = str(old["created_at"])
        new_id = safe_id
    else:
        new_id = uuid.uuid4().hex[:12]
        path = root / f"{new_id}.yaml"
        assert_within_project(project_root, path)
        created = now

    doc: dict[str, Any] = {
        "draft_id": new_id,
        "name": final_name,
        "subject": subject.strip(),
        "export_label": export_label.strip(),
        "template_ref": template_ref.strip(),
        "template_path": tpl_rel,
        "selected_items": [_section_dump(s) for s in sections],
        "created_at": created,
        "updated_at": now,
    }
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
    return doc


def draft_from_result(project_root: Path, exam_id: str) -> dict[str, Any]:
    """Build a new draft document from result/{exam_id}/exam.yaml (does not write file)."""
    result_root = (project_root / "result").resolve()
    dir_path = (result_root / exam_id).resolve()
    assert_within_project(project_root, dir_path)
    exam_yaml = dir_path / "exam.yaml"
    if not exam_yaml.is_file():
        raise FileNotFoundError(f"exam.yaml not found for result: {exam_id}")
    with exam_yaml.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    exam = ExamConfig.model_validate(raw)
    meta = exam.metadata or {}
    tpl_rel = template_path_to_project_relative(exam.template_path)
    now = _utc_now_iso()
    new_id = uuid.uuid4().hex[:12]
    title = str(meta.get("title") or meta.get("export_label") or exam_id)
    doc: dict[str, Any] = {
        "draft_id": new_id,
        "name": title,
        "subject": str(meta.get("subject") or ""),
        "export_label": str(meta.get("export_label") or title),
        "template_ref": exam.template_ref,
        "template_path": tpl_rel,
        "selected_items": [_section_dump(s) for s in exam.selected_items],
        "created_at": now,
        "updated_at": now,
        "source_result_id": exam_id,
    }
    return doc


def persist_draft_document(project_root: Path, doc: dict[str, Any]) -> dict[str, Any]:
    """Write a full draft dict (e.g. from draft_from_result) to .solaire/drafts/."""
    draft_id = str(doc.get("draft_id") or "")
    if not draft_id:
        raise ValueError("draft_id required")
    doc = dict(doc)
    base = str(doc.get("name") or "").strip()
    doc["name"] = ensure_unique_draft_name(project_root, base or "未命名草稿")
    path = _drafts_root(project_root) / f"{Path(draft_id).name}.yaml"
    assert_within_project(project_root, path)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
    return doc
