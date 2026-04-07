"""Question bank CRUD and import — files under project resource/."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from solaire.exam_compiler.facade import (
    BankRecord,
    QuestionGroupRecord,
    QuestionItem,
    expand_diagram_fences_in_text,
    iter_question_files,
    load_questions_from_yaml_file,
    parse_bank_root,
    question_group_to_author_dict,
    question_item_to_author_dict,
    strip_hydrate_fields,
    strip_primebrush_fences_for_preview,
)

from solaire.web.library_discovery import discover_question_library_refs, library_root_for_namespace, split_qualified_id
from solaire.web.security import assert_within_project


def _rel_to_resource(project_root: Path, path: Path) -> str:
    resource = (project_root / "resource").resolve()
    return path.resolve().relative_to(resource).as_posix()


def _preview(content: str, n: int = 200) -> str:
    t = strip_primebrush_fences_for_preview(content or "", max_len=10_000)
    t = t.replace("\n", " ")
    return t if len(t) <= n else t[: n - 3] + "..."


def _subject_collection_from_namespace(ns: str) -> tuple[str, str]:
    if ns == "main":
        return ("main", "main")
    parts = ns.split("/", 1)
    if len(parts) == 2:
        return (parts[0], parts[1])
    return (parts[0], "")


def list_bank_entries(project_root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ref in discover_question_library_refs(project_root):
        ns = ref["namespace"]
        subj, coll = _subject_collection_from_namespace(ns)
        lib = library_root_for_namespace(project_root, ns)
        if not lib.is_dir():
            continue
        for ypath in iter_question_files(lib):
            assert_within_project(project_root, ypath)
            try:
                records = load_questions_from_yaml_file(ypath, ns)
            except Exception:
                continue
            rel = _rel_to_resource(project_root, ypath)
            for rec in records:
                if isinstance(rec, QuestionItem):
                    q = strip_hydrate_fields(rec)
                    preview = _preview(q.content)
                    typ = q.type
                    meta = dict(q.metadata) if q.metadata else {}
                else:
                    assert isinstance(rec, QuestionGroupRecord)
                    preview = _preview(rec.material)
                    u = rec.unified
                    typ = u if isinstance(u, str) else "group"
                    meta = {}
                out.append(
                    {
                        "qualified_id": f"{ns}/{rec.id}",
                        "collection": ns,
                        "namespace": ns,
                        "subject": subj,
                        "collection_name": coll,
                        "id": rec.id,
                        "type": typ,
                        "content_preview": preview,
                        "metadata": meta,
                        "storage_path": rel,
                        "storage_kind": "single",
                        "group_id": None,
                        "group_member_qualified_ids": [],
                        "group_material": rec.material if isinstance(rec, QuestionGroupRecord) else None,
                    }
                )
    out.sort(key=lambda x: x["qualified_id"])
    return out


def _expand_group_record_for_web(project_root: Path, namespace: str, group: QuestionGroupRecord) -> dict[str, Any]:
    lib = library_root_for_namespace(project_root, namespace)
    image_dir = lib / "image"
    pi, mi = 0, 0
    mat, pi, mi = expand_diagram_fences_in_text(
        group.material or "", image_dir=image_dir, mode="web", project_root=project_root, primebrush_start=pi, mermaid_start=mi
    )
    items_out: list[dict[str, Any]] = []
    if group.unified is False:
        for row in group.items:
            d = row.model_dump(mode="json")
            c, pi, mi = expand_diagram_fences_in_text(
                d["content"], image_dir=image_dir, mode="web", project_root=project_root, primebrush_start=pi, mermaid_start=mi
            )
            ans, pi, mi = expand_diagram_fences_in_text(
                d["answer"], image_dir=image_dir, mode="web", project_root=project_root, primebrush_start=pi, mermaid_start=mi
            )
            ana, pi, mi = expand_diagram_fences_in_text(
                d.get("analysis") or "", image_dir=image_dir, mode="web", project_root=project_root, primebrush_start=pi, mermaid_start=mi
            )
            opts_out: dict[str, str] | None = None
            if d.get("options"):
                opts_out = {}
                for ok, ov in d["options"].items():
                    ev, pi, mi = expand_diagram_fences_in_text(
                        ov, image_dir=image_dir, mode="web", project_root=project_root, primebrush_start=pi, mermaid_start=mi
                    )
                    opts_out[ok] = ev
            items_out.append(
                {
                    "type": d["type"],
                    "content": c,
                    "options": opts_out,
                    "answer": ans,
                    "analysis": ana,
                    "metadata": d.get("metadata") or {},
                }
            )
    else:
        for body in group.items:
            d = body.model_dump(mode="json")
            c, pi, mi = expand_diagram_fences_in_text(
                d["content"], image_dir=image_dir, mode="web", project_root=project_root, primebrush_start=pi, mermaid_start=mi
            )
            ans, pi, mi = expand_diagram_fences_in_text(
                d["answer"], image_dir=image_dir, mode="web", project_root=project_root, primebrush_start=pi, mermaid_start=mi
            )
            ana, pi, mi = expand_diagram_fences_in_text(
                d.get("analysis") or "", image_dir=image_dir, mode="web", project_root=project_root, primebrush_start=pi, mermaid_start=mi
            )
            opts_out: dict[str, str] | None = None
            if d.get("options"):
                opts_out = {}
                for ok, ov in d["options"].items():
                    ev, pi, mi = expand_diagram_fences_in_text(
                        ov, image_dir=image_dir, mode="web", project_root=project_root, primebrush_start=pi, mermaid_start=mi
                    )
                    opts_out[ok] = ev
            items_out.append(
                {
                    "content": c,
                    "options": opts_out,
                    "answer": ans,
                    "analysis": ana,
                    "metadata": d.get("metadata") or {},
                }
            )
    return {"material": mat, "items": items_out, "unified": group.unified}


def get_question_detail(project_root: Path, qualified_id: str) -> dict[str, Any]:
    ns, qid = split_qualified_id(qualified_id)
    subj, coll = _subject_collection_from_namespace(ns)
    lib = library_root_for_namespace(project_root, ns)
    if not lib.is_dir():
        raise FileNotFoundError(f"Library not found: {ns}")
    for ypath in iter_question_files(lib):
        assert_within_project(project_root, ypath)
        records = load_questions_from_yaml_file(ypath, ns)
        for rec in records:
            if rec.id != qid:
                continue
            raw = ypath.read_text(encoding="utf-8")
            if isinstance(rec, QuestionItem):
                q = strip_hydrate_fields(rec)
                q_web = expand_question_for_web(project_root, ns, q)
                return {
                    "qualified_id": qualified_id,
                    "collection": ns,
                    "namespace": ns,
                    "subject": subj,
                    "collection_name": coll,
                    "question": q.model_dump(mode="json"),
                    "question_display": q_web.model_dump(mode="json"),
                    "storage_path": _rel_to_resource(project_root, ypath),
                    "storage_kind": "single",
                    "file_yaml": raw,
                    "question_group": None,
                    "question_group_preview": None,
                }
            assert isinstance(rec, QuestionGroupRecord)
            return {
                "qualified_id": qualified_id,
                "collection": ns,
                "namespace": ns,
                "subject": subj,
                "collection_name": coll,
                "question": None,
                "question_display": None,
                "storage_path": _rel_to_resource(project_root, ypath),
                "storage_kind": "single",
                "file_yaml": raw,
                "question_group": rec.model_dump(mode="json"),
                "question_group_preview": _expand_group_record_for_web(project_root, ns, rec),
            }
    raise FileNotFoundError(f"Question not found: {qualified_id}")


def _text_has_diagram_fence(text: str | None) -> bool:
    if not text:
        return False
    return "```primebrush" in text or "```mermaid" in text


def _question_has_diagram_fence(q: QuestionItem) -> bool:
    if _text_has_diagram_fence(q.content) or _text_has_diagram_fence(q.analysis) or _text_has_diagram_fence(q.answer):
        return True
    if q.options:
        for v in q.options.values():
            if _text_has_diagram_fence(v):
                return True
    return False


def expand_question_for_web(project_root: Path, namespace: str, q: QuestionItem) -> QuestionItem:
    """Replace ```primebrush``` / ```mermaid``` with Web markers; ensure files under library image/."""
    if not _question_has_diagram_fence(q):
        return q
    lib = library_root_for_namespace(project_root, namespace)
    image_dir = lib / "image"
    pi, mi = 0, 0
    content, pi, mi = expand_diagram_fences_in_text(
        q.content, image_dir=image_dir, mode="web", project_root=project_root, primebrush_start=pi, mermaid_start=mi
    )
    answer, pi, mi = expand_diagram_fences_in_text(
        q.answer or "", image_dir=image_dir, mode="web", project_root=project_root, primebrush_start=pi, mermaid_start=mi
    )
    analysis, pi, mi = expand_diagram_fences_in_text(
        q.analysis or "", image_dir=image_dir, mode="web", project_root=project_root, primebrush_start=pi, mermaid_start=mi
    )
    update: dict[str, Any] = {"content": content, "answer": answer, "analysis": analysis}
    if q.options is not None:
        opts_out: dict[str, str] = {}
        for ok, ov in q.options.items():
            ev, pi, mi = expand_diagram_fences_in_text(
                ov, image_dir=image_dir, mode="web", project_root=project_root, primebrush_start=pi, mermaid_start=mi
            )
            opts_out[ok] = ev
        update["options"] = opts_out
    return q.model_copy(update=update)


def question_exists(project_root: Path, qualified_id: str) -> bool:
    try:
        get_question_detail(project_root, qualified_id)
        return True
    except FileNotFoundError:
        return False


_ALLOWED_BANK_IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})
_MAX_BANK_IMAGE_BYTES = 5 * 1024 * 1024


def upload_bank_image(
    project_root: Path,
    qualified_id: str,
    file_bytes: bytes,
    original_filename: str,
) -> dict[str, str]:
    """Save image under library ``image/``; return resource-relative path and text marker."""
    ns, _qid = split_qualified_id(qualified_id)
    lib = library_root_for_namespace(project_root, ns)
    if not lib.is_dir():
        raise FileNotFoundError(f"Library not found: {ns}")
    image_dir = lib / "image"
    image_dir.mkdir(parents=True, exist_ok=True)
    assert_within_project(project_root, image_dir)
    if len(file_bytes) > _MAX_BANK_IMAGE_BYTES:
        raise ValueError("图片超过 5MB 限制")
    suf = Path(original_filename or "image.png").suffix.lower()
    if not suf:
        suf = ".png"
    if suf not in _ALLOWED_BANK_IMAGE_EXT:
        raise ValueError(f"不支持的图片格式: {suf}")
    digest = hashlib.sha256(file_bytes).hexdigest()[:16]
    dest = image_dir / f"{digest}{suf}"
    assert_within_project(project_root, dest)
    dest.write_bytes(file_bytes)
    rel = _rel_to_resource(project_root, dest)
    marker = f":::EMBED_IMG:{rel}:::\n"
    return {"resource_rel": rel, "marker": marker}


def _safe_filename_id(qid: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", qid.strip())
    return s or "question"


def _dump_record_yaml(rec: BankRecord) -> dict[str, Any]:
    if isinstance(rec, QuestionGroupRecord):
        return question_group_to_author_dict(rec)
    return question_item_to_author_dict(rec)


def save_bank_record(project_root: Path, qualified_id: str, body: BankRecord) -> dict[str, str]:
    ns, qid = split_qualified_id(qualified_id)
    if body.id != qid:
        raise ValueError("Resource id in body must match URL")
    lib = library_root_for_namespace(project_root, ns)
    lib.mkdir(parents=True, exist_ok=True)

    for ypath in iter_question_files(lib):
        assert_within_project(project_root, ypath)
        records = load_questions_from_yaml_file(ypath, ns)
        for rec in records:
            if rec.id != qid:
                continue
            data = _dump_record_yaml(body)
            with ypath.open("w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
            return {"storage_path": _rel_to_resource(project_root, ypath)}

    path = lib / f"{_safe_filename_id(qid)}.yaml"
    if path.exists():
        raise FileExistsError(str(path))
    data = _dump_record_yaml(body)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    return {"storage_path": _rel_to_resource(project_root, path)}


def save_question(project_root: Path, qualified_id: str, item: QuestionItem) -> dict[str, str]:
    return save_bank_record(project_root, qualified_id, strip_hydrate_fields(item))


def delete_question(project_root: Path, qualified_id: str, storage_path: str | None = None) -> None:
    """删除题目。若提供 ``storage_path``（列表/详情中的 resource 相对路径），只删该文件，避免仅靠题号在过大目录下误删。"""
    ns, qid = split_qualified_id(qualified_id)
    if storage_path:
        resource = (project_root / "resource").resolve()
        rel = storage_path.strip().replace("\\", "/").lstrip("/")
        ypath = (resource / rel).resolve()
        assert_within_project(project_root, ypath)
        lib = library_root_for_namespace(project_root, ns)
        try:
            ypath.resolve().relative_to(lib.resolve())
        except ValueError as e:
            raise ValueError("题目路径与当前题集不一致，已拒绝删除") from e
        if not ypath.is_file():
            raise FileNotFoundError(qualified_id)
        records = load_questions_from_yaml_file(ypath, ns)
        for rec in records:
            if rec.id != qid:
                continue
            if len(records) == 1:
                ypath.unlink()
                return
            raise ValueError("无法删除：文件含多条记录时请手动编辑 YAML")
        raise FileNotFoundError(qualified_id)
    lib = library_root_for_namespace(project_root, ns)
    for ypath in iter_question_files(lib):
        assert_within_project(project_root, ypath)
        records = load_questions_from_yaml_file(ypath, ns)
        for rec in records:
            if rec.id != qid:
                continue
            if len(records) == 1:
                ypath.unlink()
                return
            raise ValueError("无法删除：文件含多条记录时请手动编辑 YAML")
    raise FileNotFoundError(qualified_id)


def import_merged_yaml(
    project_root: Path,
    yaml_text: str,
    target_subject: str,
    target_collection: str,
) -> dict[str, Any]:
    """Parse legacy merged YAML and write one file per standalone question or per group (new format)."""
    ts = target_subject.strip()
    tc = target_collection.strip()
    if not ts or not tc:
        raise ValueError("必须提供 target_subject 与 target_collection")
    ns = f"{ts}/{tc}"
    raw = yaml.safe_load(yaml_text)
    if raw is None:
        raise ValueError("Empty YAML")
    if not isinstance(raw, dict):
        raise ValueError("Merged import expects a mapping with optional questions: and groups:")
    target = library_root_for_namespace(project_root, ns)
    assert_within_project(project_root, target)
    target.mkdir(parents=True, exist_ok=True)
    written = 0
    for q in raw.get("questions") or []:
        qi = QuestionItem.model_validate(q)
        path = target / f"{_safe_filename_id(qi.id)}.yaml"
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(question_item_to_author_dict(qi), f, allow_unicode=True, sort_keys=False)
        written += 1
    for g in raw.get("groups") or []:
        gid = str(g.get("group_id") or "").strip()
        if not gid:
            raise ValueError("group without group_id")
        inner_type = g.get("type")
        if inner_type not in ("choice", "fill", "judge", "short_answer", "reasoning", "essay"):
            raise ValueError(f"invalid group inner type: {inner_type!r}")
        items_raw = g.get("items") or []
        rec = QuestionGroupRecord(
            id=gid,
            type="group",
            material=str(g.get("material") or ""),
            unified=inner_type,
            items=items_raw,
        )
        path = target / f"{_safe_filename_id(gid)}.yaml"
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(question_group_to_author_dict(rec), f, allow_unicode=True, sort_keys=False)
        written += 1
    return {"written": written, "namespace": ns, "subject": ts, "collection": tc}


def collections_list(project_root: Path) -> list[dict[str, str]]:
    """题集 list for UI（含科目、题集拆分）。"""
    out: list[dict[str, str]] = []
    for ref in discover_question_library_refs(project_root):
        ns = ref["namespace"]
        subj, coll = _subject_collection_from_namespace(ns)
        if ns == "main":
            label = "main（resource 根）"
        else:
            label = f"{subj} · {coll}"
        out.append(
            {
                "id": ns,
                "namespace": ns,
                "subject": subj,
                "collection": coll,
                "label": label,
            }
        )
    return out


def list_subjects(project_root: Path) -> list[str]:
    """resource 下含 YAML 题集的科目目录名。"""
    resource = project_root / "resource"
    if not resource.is_dir():
        return []
    subs: set[str] = set()
    for subject_dir in sorted(resource.iterdir()):
        if not subject_dir.is_dir():
            continue
        for coll_dir in subject_dir.iterdir():
            if coll_dir.is_dir() and any(coll_dir.rglob("*.yaml")):
                subs.add(subject_dir.name)
                break
    return sorted(subs)
