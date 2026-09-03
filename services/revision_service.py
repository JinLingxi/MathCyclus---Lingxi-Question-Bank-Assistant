"""Revision helpers for question changes in the structured database."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from services.database_service import BASE_DIR, database_connection, readonly_database_connection, row_to_dict


PROJECT_ROOT = Path(BASE_DIR)
TRACKED_QUESTION_FIELDS = (
    "question_type_id",
    "stem_tex",
    "choices_json",
    "answer_tex",
    "solution_tex",
    "difficulty",
    "tags_json",
    "note",
    "official_flag",
    "canonical_tex",
    "raw_source_tex",
    "normalized_status",
)


def stable_id(prefix: str, *values: object, length: int = 14) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def question_snapshot(db_path: str | None, question_id: str) -> dict:
    """Return the current persisted question snapshot."""
    with readonly_database_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM question WHERE question_id = ?",
            (question_id,),
        ).fetchone()
    return row_to_dict(row)


def changed_fields(before: dict, after: dict) -> list[str]:
    """Return tracked fields whose values changed."""
    return [
        field
        for field in TRACKED_QUESTION_FIELDS
        if before.get(field) != after.get(field)
    ]


def insert_question_revision(
    db_path: str | None,
    question_id: str,
    change_source: str,
    before: dict,
    after: dict,
    operator: str = "",
    note: str = "",
) -> str:
    """Insert a revision row and return its ID."""
    revision_id = stable_id("REV", question_id, change_source, compact_json(before), compact_json(after), note)
    with database_connection(db_path) as conn:
        insert_question_revision_from_conn(
            conn,
            question_id=question_id,
            change_source=change_source,
            before=before,
            after=after,
            operator=operator,
            note=note,
            revision_id=revision_id,
        )
    return revision_id


def insert_question_revision_from_conn(
    conn,
    question_id: str,
    change_source: str,
    before: dict,
    after: dict,
    operator: str = "",
    note: str = "",
    revision_id: str = "",
    changed_field_names: list[str] | None = None,
) -> str:
    """Insert a revision row using the caller's transaction."""
    final_revision_id = revision_id or stable_id(
        "REV",
        question_id,
        change_source,
        compact_json(before),
        compact_json(after),
        note,
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO question_revision(
            revision_id, question_id, change_source, changed_fields_json,
            before_json, after_json, operator, note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            final_revision_id,
            question_id,
            change_source,
            compact_json(changed_field_names if changed_field_names is not None else changed_fields(before, after)),
            compact_json(before),
            compact_json(after),
            operator,
            note,
        ),
    )
    return final_revision_id


def list_question_revisions(
    db_path: str | None = None,
    question_id: str = "",
    limit: int = 50,
) -> list[dict]:
    """List revision records."""
    safe_limit = max(1, min(int(limit or 50), 200))
    if question_id:
        sql = """
            SELECT *
            FROM question_revision
            WHERE question_id = ?
            ORDER BY created_at DESC, revision_id DESC
            LIMIT ?
        """
        params: tuple[object, ...] = (question_id, safe_limit)
    else:
        sql = """
            SELECT *
            FROM question_revision
            ORDER BY created_at DESC, revision_id DESC
            LIMIT ?
        """
        params = (safe_limit,)
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]
