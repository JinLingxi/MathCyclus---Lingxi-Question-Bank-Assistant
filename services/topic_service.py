"""Topic/module helpers for the structured question-bank database."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from services.database_service import existing_database_connection, readonly_database_connection, row_to_dict
from services.revision_service import insert_question_revision_from_conn


@dataclass(frozen=True)
class TopicListFilters:
    module_id: str = ""
    keyword: str = ""
    limit: int = 50
    offset: int = 0


def _safe_limit(value: int) -> int:
    return max(1, min(int(value or 50), 200))


def _safe_offset(value: int) -> int:
    return max(0, int(value or 0))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or "{}"
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


def stable_id(prefix: str, *values: object, length: int = 12) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def coerce_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _ensure_topic_extra_columns(conn) -> None:
    columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(topic)").fetchall()}
    required = {
        "problem_intro_tex": "TEXT NOT NULL DEFAULT ''",
        "answer_intro_tex": "TEXT NOT NULL DEFAULT ''",
        "export_note": "TEXT NOT NULL DEFAULT ''",
        "extra_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    missing = [name for name in required if name not in columns]
    if missing:
        raise RuntimeError(
            "专题引言字段尚未迁移，请先在工具箱 → 本地维护与升级中应用数据库升级："
            + "，".join(missing)
        )


def _question_exists(conn, question_id: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM question WHERE question_id = ?", (question_id,)).fetchone())


def _topic_link_snapshot(conn, topic_question_id: str) -> dict[str, Any]:
    return row_to_dict(
        conn.execute(
            """
            SELECT
                tq.*,
                t.name AS topic_name,
                t.file_name,
                tm.name AS module_name
            FROM topic_question tq
            JOIN topic t ON t.topic_id = tq.topic_id
            LEFT JOIN topic_module tm ON tm.module_id = t.module_id
            WHERE tq.topic_question_id = ?
            """,
            (topic_question_id,),
        ).fetchone()
    )


def _record_topic_link_revision(
    conn,
    *,
    question_id: str,
    before: dict[str, Any],
    after: dict[str, Any],
    operator: str,
    note: str,
) -> str:
    return insert_question_revision_from_conn(
        conn,
        question_id=question_id,
        change_source="topic_collection",
        before={"topic_question": before},
        after={"topic_question": after},
        operator=operator,
        note=note,
        changed_field_names=["topic_question"],
    )


def list_topic_modules(db_path: str | None = None) -> list[dict]:
    """Return topic modules with topic and question counts."""
    sql = """
        SELECT
            tm.*,
            COUNT(DISTINCT t.topic_id) AS topic_count,
            COUNT(DISTINCT tq.topic_question_id) AS question_link_count
        FROM topic_module tm
        LEFT JOIN topic t ON t.module_id = tm.module_id
        LEFT JOIN topic_question tq ON tq.topic_id = t.topic_id
        GROUP BY tm.module_id
        ORDER BY tm.sort_order, tm.name
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(row) for row in rows]


def _build_topic_where(filters: TopicListFilters) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if filters.module_id:
        clauses.append("t.module_id = ?")
        params.append(filters.module_id)
    if filters.keyword:
        clauses.append("(t.name LIKE ? OR t.file_name LIKE ? OR t.description LIKE ? OR tm.name LIKE ?)")
        like = f"%{filters.keyword}%"
        params.extend([like, like, like, like])
    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(f"({clause})" for clause in clauses), params


def list_topics(db_path: str | None = None, filters: TopicListFilters | None = None) -> list[dict]:
    """Return topics with module names and question counts."""
    filters = filters or TopicListFilters()
    where_sql, params = _build_topic_where(filters)
    params.extend([_safe_limit(filters.limit), _safe_offset(filters.offset)])
    sql = f"""
        SELECT
            t.*,
            tm.name AS module_name,
            COUNT(tq.topic_question_id) AS question_link_count
        FROM topic t
        LEFT JOIN topic_module tm ON tm.module_id = t.module_id
        LEFT JOIN topic_question tq ON tq.topic_id = t.topic_id
        {where_sql}
        GROUP BY t.topic_id
        ORDER BY tm.sort_order, t.name
        LIMIT ? OFFSET ?
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def count_topics(db_path: str | None = None, filters: TopicListFilters | None = None) -> int:
    """Count topics matching filters."""
    filters = filters or TopicListFilters()
    where_sql, params = _build_topic_where(filters)
    sql = f"""
        SELECT COUNT(*)
        FROM topic t
        LEFT JOIN topic_module tm ON tm.module_id = t.module_id
        {where_sql}
    """
    with readonly_database_connection(db_path) as conn:
        return int(conn.execute(sql, params).fetchone()[0])


def get_topic(db_path: str | None, topic_id: str) -> dict:
    """Return one topic by ID."""
    sql = """
        SELECT
            t.*,
            tm.name AS module_name,
            COUNT(tq.topic_question_id) AS question_link_count
        FROM topic t
        LEFT JOIN topic_module tm ON tm.module_id = t.module_id
        LEFT JOIN topic_question tq ON tq.topic_id = t.topic_id
        WHERE t.topic_id = ?
        GROUP BY t.topic_id
    """
    with readonly_database_connection(db_path) as conn:
        row = conn.execute(sql, (topic_id,)).fetchone()
    return row_to_dict(row)


def upsert_topic_module(
    db_path: str | None,
    *,
    name: str,
    description: str = "",
    sort_order: int = 0,
) -> dict:
    """Create or update a topic module and return it."""
    safe_name = _text(name)
    if not safe_name:
        raise ValueError("大专题模块名称不能为空")
    module_id = stable_id("TM", safe_name)
    with existing_database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO topic_module(module_id, name, description, sort_order)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description = excluded.description,
                sort_order = excluded.sort_order,
                updated_at = CURRENT_TIMESTAMP
            """,
            (module_id, safe_name, _text(description), coerce_int(sort_order)),
        )
        row = conn.execute("SELECT * FROM topic_module WHERE name = ?", (safe_name,)).fetchone()
    return row_to_dict(row)


def upsert_topic(
    db_path: str | None,
    *,
    module_name: str,
    name: str,
    file_name: str = "",
    description: str = "",
    problem_intro_tex: str = "",
    answer_intro_tex: str = "",
    export_note: str = "",
    module_description: str = "",
    module_sort_order: int = 0,
    extra_json: Any = None,
) -> dict:
    """Create or update a topic container, including export intro fields."""
    safe_name = _text(name)
    if not safe_name:
        raise ValueError("专题名称不能为空")
    with existing_database_connection(db_path) as conn:
        _ensure_topic_extra_columns(conn)
        safe_module_name = _text(module_name or "未分类专题")
        module_id = stable_id("TM", safe_module_name)
        conn.execute(
            """
            INSERT INTO topic_module(module_id, name, description, sort_order)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description = excluded.description,
                sort_order = excluded.sort_order,
                updated_at = CURRENT_TIMESTAMP
            """,
            (module_id, safe_module_name, _text(module_description), coerce_int(module_sort_order)),
        )
        module = row_to_dict(conn.execute("SELECT * FROM topic_module WHERE name = ?", (safe_module_name,)).fetchone())
        module_id = str(module["module_id"])
        topic_id = stable_id("T", module_id, safe_name)
        conn.execute(
            """
            INSERT INTO topic(
                topic_id, module_id, name, file_name, description,
                problem_intro_tex, answer_intro_tex, export_note, extra_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(module_id, name) DO UPDATE SET
                file_name = excluded.file_name,
                description = excluded.description,
                problem_intro_tex = excluded.problem_intro_tex,
                answer_intro_tex = excluded.answer_intro_tex,
                export_note = excluded.export_note,
                extra_json = excluded.extra_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                topic_id,
                module_id,
                safe_name,
                _text(file_name),
                _text(description),
                str(problem_intro_tex or ""),
                str(answer_intro_tex or ""),
                _text(export_note),
                _json_text(extra_json),
            ),
        )
        row = conn.execute(
            """
            SELECT t.*, tm.name AS module_name
            FROM topic t
            LEFT JOIN topic_module tm ON tm.module_id = t.module_id
            WHERE t.module_id = ? AND t.name = ?
            """,
            (module_id, safe_name),
        ).fetchone()
    return row_to_dict(row)


def update_topic_intro(
    db_path: str | None,
    topic_id: str,
    *,
    problem_intro_tex: str | None = None,
    answer_intro_tex: str | None = None,
    export_note: str | None = None,
) -> dict:
    """Update topic intro fields used by future exports."""
    safe_topic_id = _text(topic_id)
    if not safe_topic_id:
        raise ValueError("topic_id 不能为空")
    assignments = []
    params: list[Any] = []
    if problem_intro_tex is not None:
        assignments.append("problem_intro_tex = ?")
        params.append(str(problem_intro_tex))
    if answer_intro_tex is not None:
        assignments.append("answer_intro_tex = ?")
        params.append(str(answer_intro_tex))
    if export_note is not None:
        assignments.append("export_note = ?")
        params.append(_text(export_note))
    if not assignments:
        return get_topic(db_path, safe_topic_id)
    params.append(safe_topic_id)
    with existing_database_connection(db_path) as conn:
        _ensure_topic_extra_columns(conn)
        conn.execute(
            f"""
            UPDATE topic
            SET {", ".join(assignments)}, updated_at = CURRENT_TIMESTAMP
            WHERE topic_id = ?
            """,
            params,
        )
        row = conn.execute(
            """
            SELECT t.*, tm.name AS module_name
            FROM topic t
            LEFT JOIN topic_module tm ON tm.module_id = t.module_id
            WHERE t.topic_id = ?
            """,
            (safe_topic_id,),
        ).fetchone()
    if not row:
        raise KeyError(f"专题不存在：{safe_topic_id}")
    return row_to_dict(row)


def list_topic_questions(
    db_path: str | None,
    topic_id: str,
    group_name: str = "",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Return questions linked to one topic."""
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    clauses = ["tq.topic_id = ?"]
    params: list[Any] = [topic_id]
    if group_name:
        clauses.append("tq.group_name = ?")
        params.append(group_name)
    params.extend([safe_limit, safe_offset])
    sql = f"""
        SELECT
            tq.*,
            q.legacy_id,
            q.question_type_id,
            q.difficulty,
            q.tags_json,
            q.note,
            l.legacy_file_path,
            l.detected_chapter,
            l.detected_year,
            l.detected_source,
            l.detected_question_number,
            substr(q.stem_tex, 1, 180) AS stem_preview
        FROM topic_question tq
        JOIN question q ON q.question_id = tq.question_id
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        WHERE {" AND ".join(clauses)}
        ORDER BY tq.group_name, tq.sort_order, tq.topic_question_id
        LIMIT ? OFFSET ?
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def count_topic_questions(db_path: str | None, topic_id: str, group_name: str = "") -> int:
    """Count questions linked to one topic."""
    clauses = ["topic_id = ?"]
    params: list[Any] = [topic_id]
    if group_name:
        clauses.append("group_name = ?")
        params.append(group_name)
    with readonly_database_connection(db_path) as conn:
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM topic_question WHERE {' AND '.join(clauses)}",
                params,
            ).fetchone()[0]
        )


def list_topic_groups(db_path: str | None, topic_id: str) -> list[dict]:
    """Return distinct groups for one topic with counts and next sort-order hints."""
    sql = """
        SELECT
            group_name,
            COUNT(topic_question_id) AS question_count,
            MIN(sort_order) AS min_sort_order,
            MAX(sort_order) AS max_sort_order
        FROM topic_question
        WHERE topic_id = ?
        GROUP BY group_name
        ORDER BY group_name, min_sort_order
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, (topic_id,)).fetchall()
    groups = [dict(row) for row in rows]
    for group in groups:
        group["next_sort_order"] = int(group.get("max_sort_order") or 0) + 1
        if not group.get("group_name"):
            group["label"] = f"默认分组 · {group.get('question_count') or 0} 题"
        else:
            group["label"] = f"{group.get('group_name')} · {group.get('question_count') or 0} 题"
    return groups


def resolve_question_lookups(db_path: str | None, raw_lookups: str) -> dict:
    """Resolve Q IDs or legacy numeric IDs into formal question IDs."""
    tokens = []
    for part in str(raw_lookups or "").replace("，", ",").replace("、", ",").replace("\n", ",").split(","):
        cleaned = part.strip()
        if cleaned:
            tokens.append(cleaned)
    resolved: list[dict] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    with readonly_database_connection(db_path) as conn:
        for token in tokens:
            row = conn.execute(
                """
                SELECT
                    q.question_id,
                    q.legacy_id,
                    l.detected_year,
                    l.detected_source,
                    l.detected_question_number,
                    l.detected_chapter,
                    substr(q.stem_tex, 1, 120) AS stem_preview
                FROM question q
                LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
                WHERE q.question_id = ? OR q.legacy_id = ? OR l.legacy_id = ?
                ORDER BY q.question_id
                LIMIT 1
                """,
                (token, token, token),
            ).fetchone()
            if not row:
                unresolved.append(token)
                continue
            item = dict(row)
            question_id = str(item.get("question_id") or "")
            if question_id and question_id not in seen:
                seen.add(question_id)
                resolved.append(item)
    return {"input_count": len(tokens), "resolved": resolved, "unresolved": unresolved}


def add_questions_to_topic(
    db_path: str | None,
    topic_id: str,
    question_ids: list[str],
    *,
    group_name: str = "",
    start_order: int = 1,
    topic_note: str = "",
    operator: str = "streamlit_ui",
) -> dict:
    """Add many questions to a topic with stable ordering."""
    safe_topic_id = _text(topic_id)
    if not safe_topic_id:
        raise ValueError("topic_id 不能为空")
    unique_question_ids = []
    seen = set()
    for question_id in question_ids:
        safe_question_id = _text(question_id)
        if safe_question_id and safe_question_id not in seen:
            seen.add(safe_question_id)
            unique_question_ids.append(safe_question_id)

    added: list[dict] = []
    skipped: list[dict] = []
    safe_group_name = _text(group_name)
    with existing_database_connection(db_path) as conn:
        topic = row_to_dict(conn.execute("SELECT * FROM topic WHERE topic_id = ?", (safe_topic_id,)).fetchone())
        if not topic:
            raise KeyError(f"专题不存在：{safe_topic_id}")
        current_max = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM topic_question WHERE topic_id = ? AND group_name = ?",
            (safe_topic_id, safe_group_name),
        ).fetchone()[0]
        next_order = max(coerce_int(start_order, 1), int(current_max or 0) + 1)
        for question_id in unique_question_ids:
            if not _question_exists(conn, question_id):
                skipped.append({"question_id": question_id, "reason": "题目不存在"})
                continue
            existing = conn.execute(
                """
                SELECT topic_question_id
                FROM topic_question
                WHERE topic_id = ? AND question_id = ? AND group_name = ?
                """,
                (safe_topic_id, question_id, safe_group_name),
            ).fetchone()
            if existing:
                skipped.append({"question_id": question_id, "reason": "该分组已收录"})
                continue
            link_id = stable_id("TQ", safe_topic_id, question_id, safe_group_name)
            conn.execute(
                """
                INSERT INTO topic_question(topic_question_id, topic_id, question_id, group_name, sort_order, topic_note)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (link_id, safe_topic_id, question_id, safe_group_name, next_order, _text(topic_note)),
            )
            after = _topic_link_snapshot(conn, link_id)
            revision_id = _record_topic_link_revision(
                conn,
                question_id=question_id,
                before={},
                after=after,
                operator=operator,
                note=f"add topic collection link {link_id}",
            )
            added.append({"question_id": question_id, "topic_question_id": link_id, "sort_order": next_order, "revision_id": revision_id})
            next_order += 1
    return {"topic_id": safe_topic_id, "added": added, "skipped": skipped, "added_count": len(added), "skipped_count": len(skipped)}


def update_topic_question_link(
    db_path: str | None,
    topic_question_id: str,
    *,
    group_name: str,
    sort_order: int,
    topic_note: str = "",
    operator: str = "streamlit_ui",
) -> dict:
    """Update one collected question row."""
    safe_link_id = _text(topic_question_id)
    if not safe_link_id:
        raise ValueError("topic_question_id 不能为空")
    with existing_database_connection(db_path) as conn:
        before = _topic_link_snapshot(conn, safe_link_id)
        if not before:
            raise KeyError(f"专题题目关系不存在：{safe_link_id}")
        conn.execute(
            """
            UPDATE topic_question
            SET group_name = ?, sort_order = ?, topic_note = ?, updated_at = CURRENT_TIMESTAMP
            WHERE topic_question_id = ?
            """,
            (_text(group_name), coerce_int(sort_order), _text(topic_note), safe_link_id),
        )
        after = _topic_link_snapshot(conn, safe_link_id)
        revision_id = _record_topic_link_revision(
            conn,
            question_id=str(before.get("question_id") or ""),
            before=before,
            after=after,
            operator=operator,
            note=f"update topic collection link {safe_link_id}",
        )
    return {"topic_question_id": safe_link_id, "updated": True, "revision_id": revision_id, "link": after}


def delete_topic_question_link(
    db_path: str | None,
    topic_question_id: str,
    *,
    operator: str = "streamlit_ui",
) -> dict:
    """Delete one collected question row."""
    safe_link_id = _text(topic_question_id)
    if not safe_link_id:
        raise ValueError("topic_question_id 不能为空")
    with existing_database_connection(db_path) as conn:
        before = _topic_link_snapshot(conn, safe_link_id)
        if not before:
            raise KeyError(f"专题题目关系不存在：{safe_link_id}")
        conn.execute("DELETE FROM topic_question WHERE topic_question_id = ?", (safe_link_id,))
        revision_id = _record_topic_link_revision(
            conn,
            question_id=str(before.get("question_id") or ""),
            before=before,
            after={},
            operator=operator,
            note=f"delete topic collection link {safe_link_id}",
        )
    return {"topic_question_id": safe_link_id, "question_id": before.get("question_id") or "", "deleted": True, "revision_id": revision_id}


def list_question_topic_links(db_path: str | None, question_id: str) -> list[dict]:
    """Return topic links for one question."""
    sql = """
        SELECT
            tm.module_id,
            tm.name AS module_name,
            t.topic_id,
            t.name AS topic_name,
            t.file_name,
            tq.topic_question_id,
            tq.group_name,
            tq.sort_order,
            tq.topic_note
        FROM topic_question tq
        JOIN topic t ON t.topic_id = tq.topic_id
        LEFT JOIN topic_module tm ON tm.module_id = t.module_id
        WHERE tq.question_id = ?
        ORDER BY tm.sort_order, t.name, tq.group_name, tq.sort_order
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, (question_id,)).fetchall()
    return [dict(row) for row in rows]
