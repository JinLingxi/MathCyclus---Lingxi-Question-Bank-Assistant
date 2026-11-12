"""Stable SQLite basket references; materialize TeX only for typesetting/export."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from services.database_service import readonly_database_connection, existing_database_connection, resolve_database_path
from services.question_db_service import get_question
from services.smart_exam_service import question_ref, ref_question_id
from services.asset_service import list_assets


def upgrade_basket_refs(db_path, refs, project_root, *, return_mapping=False):
    """Convert unambiguous old bridge paths without changing selected questions."""
    if not refs or all(ref_question_id(ref) for ref in refs):
        result = list(dict.fromkeys(refs))
        return (result, dict(zip(refs, refs))) if return_mapping else result
    root = str(project_root)
    def normalized(path):
        return os.path.normpath(os.path.abspath(os.path.join(root, str(path)))).casefold()
    with readonly_database_connection(db_path) as conn:
        paths = {}
        ambiguous = set()
        for row in conn.execute("SELECT question_id,legacy_file_path FROM legacy_question_map WHERE legacy_file_path<>''"):
            path = normalized(row["legacy_file_path"])
            if path in paths and paths[path] != row["question_id"]:
                ambiguous.add(path)
            paths[path] = row["question_id"]
    result, mapping = [], {}
    for ref in refs:
        key = normalized(ref) if not ref_question_id(ref) else ""
        updated = question_ref(paths[key]) if key in paths and key not in ambiguous else ref
        mapping[ref] = updated
        if updated not in result:
            result.append(updated)
    return (result, mapping) if return_mapping else result


def reference_label(db_path, ref):
    qid = ref_question_id(ref)
    if not qid:
        return Path(ref).stem
    q = get_question(db_path, qid)
    if not q:
        return qid + "（已移除）"
    return " · ".join(str(v) for v in (qid, q.get("detected_year"), q.get("detected_source"),
                                    q.get("detected_question_number")) if v not in (None, ""))


def materialize_sqlite_question(db_path, question_id, project_root, output_dir):
    from services.export_service import question_to_legacy_tex, copy_graphics_for_export, copy_questionassets_for_export
    q = get_question(db_path, question_id)
    if not q:
        raise ValueError("题目不存在：" + question_id)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", question_id):
        raise ValueError("题目ID不能用于安全的导出文件名")
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    tex = question_to_legacy_tex(q)
    tex, graphics = copy_graphics_for_export(q, tex, target_dir, project_root, figures_dir_name="figures")
    tex, assets = copy_questionassets_for_export(q, tex, target_dir, project_root, db_path, figures_dir_name="figures")
    missing = [r["ref"] for r in graphics + assets if r.get("status") == "missing"]
    if missing:
        raise ValueError(question_id + " 图片资源无法导出：" + "、".join(missing))
    # Templates concatenate question sources from multiple directories. Use
    # absolute paths in this compatibility copy to retain figure resolution.
    figures = (target_dir / "figures").resolve().as_posix()
    tex = tex.replace("{figures/", "{" + figures + "/")
    target = target_dir / (question_id + ".tex")
    target.write_text(tex, encoding="utf-8")
    return str(target)


def materialize_exam_blocks(db_path, blocks, project_root, output_root=None):
    root = Path(project_root)
    base = Path(output_root) if output_root else root / "data" / "cache" / "exam_typesetting"
    result = []
    type_codes = {}
    if any(block.get("type") == "question" and ref_question_id(block.get("selection_ref") or block.get("path", "")) for block in blocks):
        with readonly_database_connection(db_path) as conn:
            type_codes = {r["question_type_id"]: r["code"] for r in conn.execute("SELECT question_type_id,code FROM question_type")}
    for original in blocks:
        block = dict(original)
        ref = block.get("selection_ref") or block.get("path", "")
        qid = ref_question_id(ref)
        if block.get("type") == "question" and qid:
            q = get_question(db_path, qid)
            if not q:
                raise ValueError("试题篮中的题目已被移除：" + qid)
            assets = list_assets(db_path, question_id=qid)
            digest = hashlib.sha256(json.dumps([q, assets], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
            target = base / qid / digest / (qid + ".tex")
            block["path"] = str(target) if target.is_file() else materialize_sqlite_question(db_path, qid, root, target.parent)
            block["selection_ref"], block["question_id"] = ref, qid
            block["question_type_code"] = type_codes.get(q.get("question_type_id"), "other")
        result.append(block)
    return result


def increment_sqlite_exam_usage(db_path, question_ids):
    """Called only after a user generates a new exam; preserve a DB snapshot."""
    ids = list(dict.fromkeys(question_ids))
    if not ids:
        return 0
    database = Path(resolve_database_path(db_path))
    backup = database.parent / "backups" / ("before_exam_usage_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".sqlite3")
    backup.parent.mkdir(parents=True, exist_ok=True)
    with readonly_database_connection(db_path) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    with existing_database_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        for qid in ids:
            if not conn.execute("SELECT 1 FROM question WHERE question_id=?", (qid,)).fetchone():
                raise ValueError("引用计数目标不存在：" + qid)
            conn.execute("UPDATE question SET usage_count=COALESCE(usage_count,0)+1 WHERE question_id=?", (qid,))
    return len(ids)
