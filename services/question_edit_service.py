"""Safe write helpers for editing questions in the structured SQLite database."""

from __future__ import annotations

import json
from typing import Any

from services.database_service import existing_database_connection, row_to_dict
from services.revision_service import (
    TRACKED_QUESTION_FIELDS,
    changed_fields,
    compact_json,
    insert_question_revision_from_conn,
)


QUESTION_EDITABLE_FIELDS = set(TRACKED_QUESTION_FIELDS)
JSON_LIST_FIELDS = {"choices_json", "tags_json"}
TEXT_FIELDS = {
    "stem_tex",
    "answer_tex",
    "solution_tex",
    "note",
    "canonical_tex",
    "raw_source_tex",
    "normalized_status",
}
VISIBLE_QUESTION_EDIT_FIELDS = (
    "question_type_id",
    "stem_tex",
    "choices_text",
    "answer_tex",
    "solution_tex",
    "difficulty",
    "tags_text",
    "note",
    "official_flag",
)


class QuestionEditError(ValueError):
    """Raised when a requested question edit is invalid."""


def editable_question_fields() -> tuple[str, ...]:
    """Return question fields that may be changed through the edit service."""
    return tuple(TRACKED_QUESTION_FIELDS)


def visible_question_edit_fields() -> tuple[str, ...]:
    """Return fields planned for the first Streamlit edit form."""
    return VISIBLE_QUESTION_EDIT_FIELDS


def _json_list_to_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
    else:
        parsed = value
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _split_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        text = "" if value is None else str(value)
        raw_items = []
        for line in text.replace("，", "\n").replace(",", "\n").splitlines():
            raw_items.append(line)
    return [str(item).strip() for item in raw_items if str(item).strip()]


def question_to_edit_form(question: dict[str, Any]) -> dict[str, Any]:
    """Convert a database question row to a Streamlit-friendly edit payload."""
    return {
        "question_id": question.get("question_id") or "",
        "question_type_id": question.get("question_type_id"),
        "stem_tex": question.get("stem_tex") or "",
        "choices_text": "\n".join(_json_list_to_list(question.get("choices_json"))),
        "answer_tex": question.get("answer_tex") or "",
        "solution_tex": question.get("solution_tex") or "",
        "difficulty": question.get("difficulty"),
        "tags_text": "，".join(_json_list_to_list(question.get("tags_json"))),
        "note": question.get("note") or "",
        "official_flag": bool(question.get("official_flag") or 0),
    }


def edit_form_to_question_updates(form_values: dict[str, Any]) -> dict[str, Any]:
    """Convert first-stage edit-form values to normalized question updates."""
    if not isinstance(form_values, dict):
        raise QuestionEditError("form_values 必须是字典")

    updates: dict[str, Any] = {}
    passthrough_fields = [
        "question_type_id",
        "stem_tex",
        "answer_tex",
        "solution_tex",
        "difficulty",
        "note",
        "official_flag",
    ]
    for field in passthrough_fields:
        if field in form_values:
            updates[field] = form_values[field]
    if "choices_text" in form_values:
        updates["choices_json"] = _split_text_list(form_values.get("choices_text"))
    if "tags_text" in form_values:
        updates["tags_json"] = _split_text_list(form_values.get("tags_text"))
    return normalize_question_updates(updates)


def _updates_change_visible_fields(question: dict[str, Any], updates: dict[str, Any]) -> bool:
    current_values = normalize_question_updates({
        field: question.get(field)
        for field in updates
    })
    return any(current_values.get(field) != value for field, value in updates.items())


def edit_form_to_question_updates_with_canonical(
    question: dict[str, Any],
    form_values: dict[str, Any],
) -> dict[str, Any]:
    """Convert edit-form values and refresh canonical TeX when visible fields changed."""
    from services.export_service import question_to_legacy_tex

    updates = edit_form_to_question_updates(form_values)
    if not _updates_change_visible_fields(question, updates):
        return updates

    draft_question = dict(question)
    draft_question.update(updates)
    updates["canonical_tex"] = question_to_legacy_tex(draft_question)
    return updates


def get_question_edit_state(
    db_path: str | None,
    question_id: str,
    *,
    revision_limit: int = 20,
) -> dict[str, Any]:
    """Return all read-only data needed to render a future question edit form."""
    from services.question_db_service import get_question, list_question_filter_options
    from services.revision_service import list_question_revisions

    safe_question_id = str(question_id or "").strip()
    if not safe_question_id:
        raise QuestionEditError("question_id 不能为空")

    question = get_question(db_path, safe_question_id)
    if not question:
        raise QuestionEditError(f"题目不存在：{safe_question_id}")

    options = list_question_filter_options(db_path)
    return {
        "question_id": safe_question_id,
        "form": question_to_edit_form(question),
        "visible_fields": visible_question_edit_fields(),
        "question_types": options.get("question_types", []),
        "revisions": list_question_revisions(db_path, question_id=safe_question_id, limit=revision_limit),
    }


def _normalize_json_list_field(field: str, value: Any) -> str:
    if value is None or value == "":
        return "[]"
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise QuestionEditError(f"{field} 不是合法 JSON：{exc}") from exc
    else:
        parsed = value

    if not isinstance(parsed, list):
        raise QuestionEditError(f"{field} 必须是 JSON 数组")
    return compact_json([item for item in parsed if str(item).strip()])


def _normalize_question_field(field: str, value: Any) -> Any:
    if field not in QUESTION_EDITABLE_FIELDS:
        raise QuestionEditError(f"不允许编辑字段：{field}")

    if field in JSON_LIST_FIELDS:
        return _normalize_json_list_field(field, value)

    if field == "question_type_id":
        if value in (None, ""):
            return None
        return int(value)

    if field == "difficulty":
        if value in (None, ""):
            return None
        difficulty = int(value)
        if difficulty < 1 or difficulty > 5:
            raise QuestionEditError("difficulty 必须在 1 到 5 之间")
        return difficulty

    if field == "official_flag":
        if isinstance(value, str):
            return 1 if value.strip().lower() in {"1", "true", "yes", "y", "是"} else 0
        return 1 if bool(value) else 0

    if field in TEXT_FIELDS:
        return "" if value is None else str(value)

    return value


def normalize_question_updates(updates: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize requested question-field updates."""
    if not isinstance(updates, dict):
        raise QuestionEditError("updates 必须是字典")
    return {
        field: _normalize_question_field(field, value)
        for field, value in updates.items()
    }


def update_question_fields(
    db_path: str | None,
    question_id: str,
    updates: dict[str, Any],
    *,
    operator: str = "",
    note: str = "",
    change_source: str = "manual_edit",
) -> dict[str, Any]:
    """Update one question and record a revision in the same transaction."""
    safe_question_id = str(question_id or "").strip()
    if not safe_question_id:
        raise QuestionEditError("question_id 不能为空")

    normalized_updates = normalize_question_updates(updates)
    if not normalized_updates:
        return {
            "question_id": safe_question_id,
            "changed_fields": [],
            "revision_id": "",
            "before": {},
            "after": {},
        }

    with existing_database_connection(db_path) as conn:
        before = row_to_dict(
            conn.execute(
                "SELECT * FROM question WHERE question_id = ?",
                (safe_question_id,),
            ).fetchone()
        )
        if not before:
            raise QuestionEditError(f"题目不存在：{safe_question_id}")

        fields = [
            field
            for field, value in normalized_updates.items()
            if _normalize_question_field(field, before.get(field)) != value
        ]
        if not fields:
            return {
                "question_id": safe_question_id,
                "changed_fields": [],
                "revision_id": "",
                "before": before,
                "after": before,
            }

        candidate_after = dict(before)
        candidate_after.update({field: normalized_updates[field] for field in fields})
        assignments = ", ".join(f"{field} = ?" for field in fields)
        params = [candidate_after[field] for field in fields]
        params.append(safe_question_id)
        conn.execute(
            f"""
            UPDATE question
            SET {assignments},
                updated_at = CURRENT_TIMESTAMP,
                last_manual_edit_at = CURRENT_TIMESTAMP
            WHERE question_id = ?
            """,
            params,
        )

        after = row_to_dict(
            conn.execute(
                "SELECT * FROM question WHERE question_id = ?",
                (safe_question_id,),
            ).fetchone()
        )
        revision_id = insert_question_revision_from_conn(
            conn,
            question_id=safe_question_id,
            change_source=change_source,
            before=before,
            after=after,
            operator=operator,
            note=note,
        )

    return {
        "question_id": safe_question_id,
        "changed_fields": fields,
        "revision_id": revision_id,
        "before": before,
        "after": after,
    }
