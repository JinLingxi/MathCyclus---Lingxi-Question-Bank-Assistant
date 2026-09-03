"""Topic/module helpers for the structured question-bank database."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.database_service import readonly_database_connection, row_to_dict


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
