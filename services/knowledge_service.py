"""Read-only knowledge-area and equivalence helpers for the structured database."""

from __future__ import annotations

from services.database_service import readonly_database_connection


def list_knowledge_areas(db_path: str | None = None) -> list[dict]:
    """Return knowledge areas with question counts."""
    sql = """
        SELECT
            ka.knowledge_area_id,
            ka.name,
            ka.parent_id,
            ka.description,
            ka.sort_order,
            COUNT(qka.question_id) AS question_count
        FROM knowledge_area ka
        LEFT JOIN question_knowledge_area qka ON qka.knowledge_area_id = ka.knowledge_area_id
        GROUP BY ka.knowledge_area_id
        ORDER BY ka.sort_order, ka.name
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(row) for row in rows]


def list_questions_by_knowledge_area(
    db_path: str | None,
    knowledge_area_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Return questions linked to one knowledge area."""
    safe_limit = max(1, min(int(limit or 50), 200))
    safe_offset = max(0, int(offset or 0))
    sql = """
        SELECT
            q.question_id,
            q.legacy_id,
            q.question_type_id,
            q.difficulty,
            q.tags_json,
            q.note,
            qka.source,
            qka.confidence,
            qka.is_primary,
            l.legacy_file_path,
            l.detected_year,
            l.detected_source,
            l.detected_question_number,
            substr(q.stem_tex, 1, 180) AS stem_preview
        FROM question_knowledge_area qka
        JOIN question q ON q.question_id = qka.question_id
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        WHERE qka.knowledge_area_id = ?
        ORDER BY l.detected_year DESC, l.detected_source, CAST(l.detected_question_number AS INTEGER), q.question_id
        LIMIT ? OFFSET ?
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, (knowledge_area_id, safe_limit, safe_offset)).fetchall()
    return [dict(row) for row in rows]


def list_equivalence_candidates(db_path: str | None = None) -> list[dict]:
    """Return pending same-question candidates."""
    sql = """
        SELECT
            qe.equivalence_id,
            qe.question_id_a,
            qe.question_id_b,
            qe.relation_type,
            qe.confidence,
            qe.review_status,
            qe.note,
            la.legacy_id AS legacy_id_a,
            la.legacy_file_path AS legacy_file_path_a,
            la.detected_year AS year_a,
            la.detected_source AS source_a,
            la.detected_question_number AS number_a,
            la.detected_chapter AS chapter_a,
            lb.legacy_id AS legacy_id_b,
            lb.legacy_file_path AS legacy_file_path_b,
            lb.detected_year AS year_b,
            lb.detected_source AS source_b,
            lb.detected_question_number AS number_b,
            lb.detected_chapter AS chapter_b
        FROM question_equivalence qe
        LEFT JOIN legacy_question_map la ON la.question_id = qe.question_id_a
        LEFT JOIN legacy_question_map lb ON lb.question_id = qe.question_id_b
        ORDER BY qe.review_status, qe.confidence DESC, qe.question_id_a
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(row) for row in rows]
