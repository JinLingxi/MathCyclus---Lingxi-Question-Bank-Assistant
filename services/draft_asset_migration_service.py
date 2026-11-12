"""Audited relocation of unapproved draft images; no original files are deleted."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from services.database_service import connect_existing_database, resolve_database_path
from services.draft_asset_storage_service import plan_draft_asset_storage, copy_planned_draft_asset
from services.asset_service import file_hash

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg"}
ASSET_FIELDS = ("source_path", "planned_file_path", "file_hash")
DRAFT_FIELDS = ("content_hash", "updated_at")


def build_draft_asset_relocation_plan(db_path: str) -> dict:
    conn = connect_existing_database(db_path, readonly=True)
    assets, drafts, skipped = [], {}, []
    try:
        rows = conn.execute("SELECT * FROM question_import_draft_asset ORDER BY draft_asset_id").fetchall()
        for row in rows:
            asset = dict(row)
            draft_id = asset["draft_id"]
            draft = dict(conn.execute("SELECT * FROM question_import_draft WHERE draft_id=?", (draft_id,)).fetchone())
            reason = ""
            if draft["review_status"] in {"committed", "approved", "sample", "rejected"}:
                reason = "protected_status_" + draft["review_status"]
            elif draft.get("approved_content_hash"):
                reason = "existing_approval"
            elif Path(asset["source_path"]).suffix.lower() not in IMAGE_SUFFIXES:
                reason = "not_an_image"
            elif any("includegraphics" in str(draft.get(key) or "")
                     for key in ("stem_tex", "choices_json", "answer_tex", "solution_tex", "normalized_tex")):
                reason = "direct_tex_image_path_requires_review"
            if reason:
                skipped.append({"draft_asset_id": asset["draft_asset_id"], "reason": reason})
                continue
            try:
                plan = plan_draft_asset_storage(asset, db_path)
            except (OSError, ValueError) as exc:
                skipped.append({"draft_asset_id": asset["draft_asset_id"], "reason": str(exc)})
                continue
            if plan is None:
                skipped.append({"draft_asset_id": asset["draft_asset_id"],
                                "reason": "already_stable_or_missing_or_distinct_planned_path"})
                continue
            after = {key: plan[key] for key in ("source_path", "planned_file_path")}
            after["file_hash"] = plan["sha256"]
            assets.append({"before": asset, "after": {**asset, **after},
                           "copy": {**plan, "source": str(plan["source"]), "target": str(plan["target"])}})
            drafts[draft_id] = draft
    finally:
        conn.close()
    conn = connect_existing_database(db_path, readonly=True)
    try:
        asset_sets = {draft_id: [dict(row) for row in conn.execute(
            "SELECT * FROM question_import_draft_asset WHERE draft_id=? ORDER BY draft_asset_id", (draft_id,))]
            for draft_id in drafts}
    finally:
        conn.close()
    return {"version": 1, "database": resolve_database_path(db_path), "assets": assets,
            "drafts_before": drafts, "asset_sets_before": asset_sets, "skipped": skipped, "deleted_files": 0}


def _backup(conn, backup_path):
    path = Path(backup_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    destination = sqlite3.connect(path)
    try:
        conn.backup(destination)
    finally:
        destination.close()


def apply_draft_asset_relocation(plan: dict, *, backup_path: str | Path) -> dict:
    from services.import_service import _draft_content_hash_from_conn, _get_draft_question_from_conn, _record_draft_review_event_conn

    conn = connect_existing_database(plan["database"])
    try:
        _backup(conn, backup_path)
        conn.execute("BEGIN IMMEDIATE")
        for draft_id, before in plan["drafts_before"].items():
            current = conn.execute("SELECT * FROM question_import_draft WHERE draft_id=?", (draft_id,)).fetchone()
            if current is None or dict(current) != before:
                raise ValueError("草稿在预演后发生变化，请重新预演：" + draft_id)
        # Verify the complete attachment set, not only selected rows.
        for draft_id, expected in plan["asset_sets_before"].items():
            current = [dict(row) for row in conn.execute(
                "SELECT * FROM question_import_draft_asset WHERE draft_id=? ORDER BY draft_asset_id", (draft_id,))]
            if current != expected:
                raise ValueError("草稿的图片集合在预演后发生变化")
        for item in plan["assets"]:
            before = item["before"]
            current = conn.execute("SELECT * FROM question_import_draft_asset WHERE draft_asset_id=?",
                                   (before["draft_asset_id"],)).fetchone()
            if current is None or dict(current) != before:
                raise ValueError("图片记录在预演后发生变化")
            copy = {**item["copy"], "source": Path(item["copy"]["source"]), "target": Path(item["copy"]["target"])}
            if file_hash(copy["source"]) != copy["sha256"]:
                raise ValueError("来源图片在预演后发生变化")
            copy_planned_draft_asset(copy)
            after = item["after"]
            conn.execute("UPDATE question_import_draft_asset SET source_path=?,planned_file_path=?,file_hash=? WHERE draft_asset_id=?",
                         tuple(after[field] for field in ASSET_FIELDS) + (before["draft_asset_id"],))
        after_drafts = {}
        for draft_id in plan["drafts_before"]:
            draft = _get_draft_question_from_conn(conn, draft_id)
            digest = _draft_content_hash_from_conn(conn, draft)
            conn.execute("UPDATE question_import_draft SET content_hash=?,updated_at=CURRENT_TIMESTAMP WHERE draft_id=?",
                         (digest, draft_id))
            draft["content_hash"] = digest
            _record_draft_review_event_conn(conn, draft, stage="asset_storage_migration",
                from_status=draft["review_status"], to_status=draft["review_status"],
                decision="relocate", content_hash=digest, operator="draft_asset_migration",
                reason="图片字节不变，迁入稳定资源目录；原文件保留",
                detail={"asset_count": sum(1 for item in plan["assets"] if item["before"]["draft_id"] == draft_id)})
            after_drafts[draft_id] = dict(conn.execute("SELECT * FROM question_import_draft WHERE draft_id=?", (draft_id,)).fetchone())
        after_asset_sets = {draft_id: [dict(row) for row in conn.execute(
            "SELECT * FROM question_import_draft_asset WHERE draft_id=? ORDER BY draft_asset_id", (draft_id,))]
            for draft_id in plan["drafts_before"]}
        conn.commit()
        return {**plan, "applied": True, "backup_path": str(backup_path), "drafts_after": after_drafts,
                "asset_sets_after": after_asset_sets}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rollback_draft_asset_relocation(manifest: dict, *, backup_path: str | Path) -> dict:
    """Restore references only when affected records still match the applied state."""
    from services.import_service import _record_draft_review_event_conn

    if not manifest.get("applied"):
        raise ValueError("不是已执行的迁移清单")
    conn = connect_existing_database(manifest["database"])
    try:
        _backup(conn, backup_path)
        conn.execute("BEGIN IMMEDIATE")
        for draft_id, after in manifest["drafts_after"].items():
            current = conn.execute("SELECT * FROM question_import_draft WHERE draft_id=?", (draft_id,)).fetchone()
            if current is None or dict(current) != after:
                raise ValueError("迁移后草稿已被编辑或审核，拒绝覆盖：" + draft_id)
            current_assets = [dict(row) for row in conn.execute(
                "SELECT * FROM question_import_draft_asset WHERE draft_id=? ORDER BY draft_asset_id", (draft_id,))]
            if current_assets != manifest["asset_sets_after"][draft_id]:
                raise ValueError("迁移后图片集合已变化，拒绝覆盖")
        for item in manifest["assets"]:
            after, before = item["after"], item["before"]
            current = conn.execute("SELECT * FROM question_import_draft_asset WHERE draft_asset_id=?",
                                   (after["draft_asset_id"],)).fetchone()
            if current is None or dict(current) != after:
                raise ValueError("迁移后图片记录已发生变化")
            if file_hash(Path(item["copy"]["source"])) != item["copy"]["sha256"]:
                raise ValueError("原图已丢失或变化，不能回退引用")
            conn.execute("UPDATE question_import_draft_asset SET source_path=?,planned_file_path=?,file_hash=? WHERE draft_asset_id=?",
                         tuple(before[field] for field in ASSET_FIELDS) + (before["draft_asset_id"],))
        for draft_id, before in manifest["drafts_before"].items():
            conn.execute("UPDATE question_import_draft SET content_hash=?,updated_at=? WHERE draft_id=?",
                         tuple(before[field] for field in DRAFT_FIELDS) + (draft_id,))
            _record_draft_review_event_conn(conn, before, stage="asset_storage_migration",
                from_status=before["review_status"], to_status=before["review_status"],
                decision="rollback_relocation", content_hash=before["content_hash"],
                operator="draft_asset_migration", reason="按迁移清单回退资源引用；两份文件均保留")
        conn.commit()
        return {"rolled_back": True, "asset_count": len(manifest["assets"]), "deleted_files": 0}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
