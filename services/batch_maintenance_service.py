"""Transactional bulk maintenance helpers for the SQLite question bank."""

from __future__ import annotations

import json
from typing import Any

from services.database_service import existing_database_connection, readonly_database_connection, row_to_dict
from services.revision_service import insert_question_revision_from_conn


BULK_EDITABLE_FIELDS = {
    "difficulty",
    "tags_json",
    "note",
    "question_type_id",
    "official_flag",
}


def _normalize_value(field: str, value: Any) -> Any:
    if field == "difficulty":
        if value in (None, "", "全部难度"):
            return None
        return int(value)
    if field == "question_type_id":
        if value in (None, "", "__all__"):
            return None
        return int(value)
    if field == "official_flag":
        return 1 if value else 0
    if field == "tags_json":
        if isinstance(value, str):
            items = value.replace("，", "\n").replace(",", "\n").splitlines()
        else:
            items = value or []
        return json.dumps([str(item).strip() for item in items if str(item).strip()], ensure_ascii=False, separators=(",", ":"))
    if field == "note":
        return "" if value is None else str(value)
    raise ValueError(f"不允许批量修改字段：{field}")


def normalize_bulk_updates(updates: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(updates, dict):
        raise ValueError("updates 必须是字典")
    unknown = set(updates) - BULK_EDITABLE_FIELDS
    if unknown:
        raise ValueError(f"不允许批量修改字段：{', '.join(sorted(unknown))}")
    return {field: _normalize_value(field, value) for field, value in updates.items()}


def preview_question_bulk_updates(db_path: str | None, question_ids: list[str], updates: dict[str, Any]) -> dict[str, Any]:
    normalized_ids = list(dict.fromkeys(str(item).strip() for item in question_ids if str(item).strip()))
    normalized_updates = normalize_bulk_updates(updates)
    if not normalized_ids:
        return {"total": 0, "changed": 0, "unchanged": 0, "items": [], "updates": normalized_updates}
    placeholders = ",".join("?" for _ in normalized_ids)
    with readonly_database_connection(db_path) as conn:
        rows = [dict(row) for row in conn.execute(
            f"SELECT * FROM question WHERE question_id IN ({placeholders}) ORDER BY question_id",
            normalized_ids,
        ).fetchall()]
    items = []
    for before in rows:
        after = dict(before)
        after.update(normalized_updates)
        changed_fields = [field for field in normalized_updates if before.get(field) != after.get(field)]
        items.append({"question_id": before.get("question_id", ""), "changed_fields": changed_fields, "before": before, "after": after})
    return {
        "total": len(items),
        "changed": sum(bool(item["changed_fields"]) for item in items),
        "unchanged": sum(not item["changed_fields"] for item in items),
        "missing": len(normalized_ids) - len(items),
        "items": items,
        "updates": normalized_updates,
    }


def apply_question_bulk_updates(
    db_path: str | None,
    plan: dict[str, Any],
    *,
    operator: str = "bulk_maintenance",
    note: str = "",
) -> dict[str, Any]:
    updates = normalize_bulk_updates(plan.get("updates") or {})
    items = plan.get("items") or []
    changed_count = 0
    revision_ids = []
    with existing_database_connection(db_path) as conn:
        for item in items:
            question_id = str(item.get("question_id") or "").strip()
            if not question_id or not item.get("changed_fields"):
                continue
            before = row_to_dict(conn.execute("SELECT * FROM question WHERE question_id = ?", (question_id,)).fetchone())
            if not before:
                continue
            changed_fields = [field for field in updates if before.get(field) != updates[field]]
            if not changed_fields:
                continue
            assignments = ", ".join(f"{field} = ?" for field in changed_fields)
            params = [updates[field] for field in changed_fields] + [question_id]
            conn.execute(f"UPDATE question SET {assignments}, updated_at = CURRENT_TIMESTAMP, last_manual_edit_at = CURRENT_TIMESTAMP WHERE question_id = ?", params)
            after = row_to_dict(conn.execute("SELECT * FROM question WHERE question_id = ?", (question_id,)).fetchone())
            revision_ids.append(insert_question_revision_from_conn(
                conn,
                question_id=question_id,
                change_source="bulk_question_update",
                before=before,
                after=after,
                operator=operator,
                note=note or "SQLite 批量维护",
            ))
            changed_count += 1
    return {"changed": changed_count, "revision_ids": revision_ids, "skipped": max(0, len(items) - changed_count)}
