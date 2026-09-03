"""Read-only query helpers for the structured SQLite question bank."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.database_service import readonly_database_connection, row_to_dict


_SEARCH_FIELDS = (
    "q.stem_tex",
    "q.answer_tex",
    "q.solution_tex",
    "q.tags_json",
    "q.note",
    "q.canonical_tex",
    "q.raw_source_tex",
    "l.legacy_file_path",
    "l.detected_chapter",
    "l.detected_source",
    "l.detected_topic",
)


@dataclass(frozen=True)
class QuestionListFilters:
    keyword: str = ""
    year: int | None = None
    chapter: str = ""
    source: str = ""
    question_number: str = ""
    question_type_id: int | None = None
    difficulty: int | None = None
    limit: int = 20
    offset: int = 0


def _safe_limit(value: int) -> int:
    return max(1, min(int(value or 20), 100))


def _safe_offset(value: int) -> int:
    return max(0, int(value or 0))


def _split_keyword_terms(keyword: str) -> list[str]:
    """Split exact-search text into non-empty terms; slash means AND."""
    normalized = str(keyword or "").replace("／", "/")
    return [term.strip() for term in normalized.split("/") if term.strip()]


def _where_with_extra_condition(where_sql: str, condition: str) -> str:
    if where_sql:
        return f"{where_sql} AND ({condition})"
    return f"WHERE ({condition})"


def _build_where(filters: QuestionListFilters) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    for term in _split_keyword_terms(filters.keyword):
        clauses.append(
            "("
            + " OR ".join(f"{field} LIKE ?" for field in _SEARCH_FIELDS)
            + ")"
        )
        like = f"%{term}%"
        params.extend([like] * len(_SEARCH_FIELDS))

    if filters.year is not None:
        clauses.append("l.detected_year = ?")
        params.append(filters.year)

    if filters.chapter:
        clauses.append("l.detected_chapter = ?")
        params.append(filters.chapter)

    if filters.source:
        clauses.append("l.detected_source = ?")
        params.append(filters.source)

    if filters.question_number:
        clauses.append("l.detected_question_number = ?")
        params.append(filters.question_number)

    if filters.question_type_id is not None:
        clauses.append("q.question_type_id = ?")
        params.append(filters.question_type_id)

    if filters.difficulty is not None:
        clauses.append("q.difficulty = ?")
        params.append(filters.difficulty)

    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(f"({clause})" for clause in clauses), params


def list_questions(
    db_path: str | None = None,
    filters: QuestionListFilters | None = None,
) -> list[dict]:
    """Return paginated question summaries from SQLite."""
    filters = filters or QuestionListFilters()
    where_sql, params = _build_where(filters)
    params.extend([_safe_limit(filters.limit), _safe_offset(filters.offset)])

    sql = f"""
        SELECT
            q.question_id,
            q.legacy_id,
            q.question_type_id,
            q.difficulty,
            q.tags_json,
            q.note,
            q.usage_count,
            q.stem_tex,
            q.answer_tex,
            q.solution_tex,
            q.created_at,
            q.updated_at,
            l.legacy_file_path,
            l.detected_chapter,
            l.detected_year,
            l.detected_source,
            l.detected_question_number,
            l.detected_topic
        FROM question q
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        {where_sql}
        ORDER BY q.question_id
        LIMIT ? OFFSET ?
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def count_questions(
    db_path: str | None = None,
    filters: QuestionListFilters | None = None,
) -> int:
    """Count questions matching filters."""
    filters = filters or QuestionListFilters()
    where_sql, params = _build_where(filters)
    sql = f"""
        SELECT COUNT(*)
        FROM question q
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        {where_sql}
    """
    with readonly_database_connection(db_path) as conn:
        return int(conn.execute(sql, params).fetchone()[0])


def list_questions_page(
    db_path: str | None = None,
    filters: QuestionListFilters | None = None,
) -> dict:
    """Return a page object for UI pagination."""
    filters = filters or QuestionListFilters()
    safe_limit = _safe_limit(filters.limit)
    safe_offset = _safe_offset(filters.offset)
    normalized_filters = QuestionListFilters(
        keyword=filters.keyword,
        year=filters.year,
        chapter=filters.chapter,
        source=filters.source,
        question_number=filters.question_number,
        question_type_id=filters.question_type_id,
        difficulty=filters.difficulty,
        limit=safe_limit,
        offset=safe_offset,
    )
    total = count_questions(db_path, normalized_filters)
    page_count = (total + safe_limit - 1) // safe_limit if total else 0
    return {
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "page": safe_offset // safe_limit + 1 if total else 0,
        "page_count": page_count,
        "items": list_questions(db_path, normalized_filters),
    }


def list_question_filter_options(
    db_path: str | None = None,
    filters: QuestionListFilters | None = None,
) -> dict:
    """Return distinct filter values needed by browse/search UIs.

    When ``filters`` is supplied, option lists are constrained to the matching
    question set. Callers can pass staged filters to avoid circular narrowing.
    """
    filters = filters or QuestionListFilters()
    where_sql, params = _build_where(filters)
    with readonly_database_connection(db_path) as conn:
        year_sql = _where_with_extra_condition(where_sql, "l.detected_year IS NOT NULL")
        years = [
            int(row[0])
            for row in conn.execute(
                f"""
                SELECT DISTINCT l.detected_year
                FROM question q
                LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
                {year_sql}
                ORDER BY l.detected_year DESC
                """,
                list(params),
            ).fetchall()
        ]
        chapter_sql = _where_with_extra_condition(where_sql, "l.detected_chapter != ''")
        chapters = [
            str(row[0])
            for row in conn.execute(
                f"""
                SELECT DISTINCT l.detected_chapter
                FROM question q
                LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
                {chapter_sql}
                ORDER BY l.detected_chapter
                """,
                list(params),
            ).fetchall()
        ]
        source_sql = _where_with_extra_condition(where_sql, "l.detected_source != ''")
        sources = [
            str(row[0])
            for row in conn.execute(
                f"""
                SELECT DISTINCT l.detected_source
                FROM question q
                LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
                {source_sql}
                ORDER BY l.detected_source
                """,
                list(params),
            ).fetchall()
        ]
        difficulty_sql = _where_with_extra_condition(where_sql, "q.difficulty IS NOT NULL")
        difficulties = [
            int(row[0])
            for row in conn.execute(
                f"""
                SELECT DISTINCT q.difficulty
                FROM question q
                LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
                {difficulty_sql}
                ORDER BY q.difficulty
                """,
                list(params),
            ).fetchall()
        ]
        question_type_sql = _where_with_extra_condition(where_sql, "q.question_type_id IS NOT NULL")
        question_types = [
            dict(row)
            for row in conn.execute(
                f"""
                SELECT DISTINCT
                    q.question_type_id,
                    COALESCE(qt.code, '') AS code,
                    COALESCE(qt.name, CAST(q.question_type_id AS TEXT)) AS name
                FROM question q
                LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
                LEFT JOIN question_type qt ON qt.question_type_id = q.question_type_id
                {question_type_sql}
                ORDER BY q.question_type_id
                """,
                list(params),
            ).fetchall()
        ]
        all_question_types = [
            dict(row)
            for row in conn.execute(
                """
                SELECT question_type_id, code, name
                FROM question_type
                ORDER BY question_type_id
                """
            ).fetchall()
        ]
    return {
        "years": years,
        "chapters": chapters,
        "sources": sources,
        "difficulties": difficulties,
        "question_types": question_types,
        "all_question_types": all_question_types,
        "page_size_options": [5, 10, 15, 20],
    }


def get_question(db_path: str | None, question_id: str) -> dict:
    """Return one full question with analysis fields."""
    sql = """
        SELECT
            q.*,
            qa.target_tex,
            qa.production_tex,
            qa.evaluation_tex,
            qa.marking_data_tex,
            qa.warning_tex,
            qa.reference_text,
            l.legacy_file_path,
            l.detected_chapter,
            l.detected_year,
            l.detected_source,
            l.detected_question_number,
            l.detected_topic,
            pq.question_number,
            pq.sub_number,
            p.paper_series,
            p.track,
            p.paper_name
        FROM question q
        LEFT JOIN question_analysis qa ON qa.question_id = q.question_id
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        LEFT JOIN paper_question pq ON pq.question_id = q.question_id
        LEFT JOIN paper p ON p.paper_id = pq.paper_id
        WHERE q.question_id = ?
        ORDER BY p.year, p.paper_name, pq.display_order
        LIMIT 1
    """
    with readonly_database_connection(db_path) as conn:
        row = conn.execute(sql, (question_id,)).fetchone()
    return row_to_dict(row)


def list_question_assets(db_path: str | None, question_id: str) -> list[dict]:
    """Return assets attached to a question."""
    sql = """
        SELECT *
        FROM question_asset
        WHERE question_id = ?
        ORDER BY role, sort_order, asset_id
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, (question_id,)).fetchall()
    return [dict(row) for row in rows]


def list_question_papers(db_path: str | None, question_id: str) -> list[dict]:
    """Return papers linked to a question."""
    sql = """
        SELECT
            p.paper_id,
            p.year,
            p.paper_series,
            p.track,
            p.paper_name,
            pq.question_number,
            pq.sub_number,
            pq.display_order
        FROM paper_question pq
        JOIN paper p ON p.paper_id = pq.paper_id
        WHERE pq.question_id = ?
        ORDER BY p.year, p.paper_name, pq.display_order
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, (question_id,)).fetchall()
    return [dict(row) for row in rows]


def get_question_bundle(db_path: str | None, question_id: str) -> dict:
    """Return one question with all source links and assets for future UI cards."""
    from services.book_service import list_question_book_links
    from services.topic_service import list_question_topic_links

    return {
        "question": get_question(db_path, question_id),
        "assets": list_question_assets(db_path, question_id),
        "paper_links": list_question_papers(db_path, question_id),
        "book_links": list_question_book_links(db_path, question_id),
        "topic_links": list_question_topic_links(db_path, question_id),
    }
