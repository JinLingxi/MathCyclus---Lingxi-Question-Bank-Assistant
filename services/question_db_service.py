"""Read-only query helpers for the structured SQLite question bank."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from services.database_service import readonly_database_connection, resolve_database_path, row_to_dict


_SEARCH_FIELDS = (
    "q.question_id",
    "q.legacy_id",
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

_SEARCH_EXISTS_CLAUSES = (
    (
        """
        EXISTS (
            SELECT 1
            FROM question_type qt
            WHERE qt.question_type_id = q.question_type_id
              AND (qt.code LIKE ? OR qt.name LIKE ?)
        )
        """,
        2,
    ),
    (
        """
        EXISTS (
            SELECT 1
            FROM question_knowledge_area qka
            JOIN knowledge_area ka ON ka.knowledge_area_id = qka.knowledge_area_id
            WHERE qka.question_id = q.question_id
              AND ka.name LIKE ?
        )
        """,
        1,
    ),
    (
        """
        EXISTS (
            SELECT 1
            FROM paper_question pq
            JOIN paper p ON p.paper_id = pq.paper_id
            WHERE pq.question_id = q.question_id
              AND (
                p.paper_name LIKE ?
                OR p.source_name LIKE ?
                OR p.track LIKE ?
                OR p.paper_series LIKE ?
                OR CAST(p.year AS TEXT) LIKE ?
                OR pq.question_number LIKE ?
                OR pq.sub_number LIKE ?
              )
        )
        """,
        7,
    ),
)

_KEYWORD_PREFIX_PATTERN = re.compile(
    r"^(?:id|ID|题目ID|旧ID|标签|tag|tags|知识点|来源|试卷|题号)\s*[:：]\s*(?P<term>.+)$"
)


@dataclass(frozen=True)
class QuestionListFilters:
    keyword: str = ""
    year: int | None = None
    chapter: str = ""
    source_kind: str = ""
    paper_series: str = ""
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


def _fts_query(value: str) -> str:
    """Quote a term for FTS5 while keeping punctuation literal."""
    return '"' + str(value).replace('"', '""') + '"'


def get_question_bank_availability(db_path: str | None = None) -> dict[str, Any]:
    """Return whether a SQLite database can serve question browse pages."""
    target = Path(resolve_database_path(db_path))
    if not target.exists():
        return {
            "status": "missing",
            "path": str(target),
            "exists": False,
            "has_schema": False,
            "question_count": 0,
            "ready_for_browse": False,
        }
    if target.stat().st_size <= 0:
        return {
            "status": "empty_file",
            "path": str(target),
            "exists": True,
            "has_schema": False,
            "question_count": 0,
            "ready_for_browse": False,
        }

    try:
        with readonly_database_connection(str(target)) as conn:
            has_question_table = bool(
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'question'"
                ).fetchone()
            )
            if not has_question_table:
                return {
                    "status": "missing_question_table",
                    "path": str(target),
                    "exists": True,
                    "has_schema": False,
                    "question_count": 0,
                    "ready_for_browse": False,
                }
            question_count = int(conn.execute("SELECT COUNT(*) FROM question").fetchone()[0])
    except Exception as exc:
        return {
            "status": "error",
            "path": str(target),
            "exists": True,
            "has_schema": False,
            "question_count": 0,
            "ready_for_browse": False,
            "error": str(exc),
        }

    return {
        "status": "ready" if question_count > 0 else "empty",
        "path": str(target),
        "exists": True,
        "has_schema": True,
        "question_count": question_count,
        "ready_for_browse": question_count > 0,
    }


def _split_keyword_terms(keyword: str) -> list[str]:
    """Split exact-search text into non-empty terms; slash means AND."""
    normalized = str(keyword or "").replace("／", "/")
    terms: list[str] = []
    for raw_term in normalized.split("/"):
        term = raw_term.strip()
        if not term:
            continue
        prefix_match = _KEYWORD_PREFIX_PATTERN.match(term)
        if prefix_match:
            term = prefix_match.group("term").strip()
        if term:
            terms.append(term)
    return terms


def _where_with_extra_condition(where_sql: str, condition: str) -> str:
    if where_sql:
        return f"{where_sql} AND ({condition})"
    return f"WHERE ({condition})"


@contextmanager
def _query_connection(db_path: str | None, connection: sqlite3.Connection | None):
    """Reuse a caller-owned read connection when a page needs two queries."""
    if connection is not None:
        yield connection
        return
    with readonly_database_connection(db_path) as conn:
        yield conn


def _build_where(filters: QuestionListFilters) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    for term in _split_keyword_terms(filters.keyword):
        like = f"%{term}%"
        # Trigram FTS handles longer substring searches efficiently. Keep
        # paper and knowledge-area relations as SQL predicates because they
        # are maintained in separate normalized tables.
        if len(term) >= 3:
            term_clauses = [
                "q.question_id IN (SELECT qs.question_id FROM question_search qs "
                "WHERE qs.search_text MATCH ?)",
            ]
            params.append(_fts_query(term))
            extra_exists = _SEARCH_EXISTS_CLAUSES
        else:
            term_clauses = [f"{field} LIKE ?" for field in _SEARCH_FIELDS]
            params.extend([like] * len(_SEARCH_FIELDS))
            extra_exists = _SEARCH_EXISTS_CLAUSES
        for exists_sql, placeholder_count in extra_exists:
            term_clauses.append(exists_sql)
            params.extend([like] * placeholder_count)
        clauses.append(
            "("
            + " OR ".join(term_clauses)
            + ")"
        )

    if filters.year is not None:
        clauses.append("l.detected_year = ?")
        params.append(filters.year)

    if filters.source_kind:
        source_kind_exists = {
            "试卷": "EXISTS (SELECT 1 FROM paper_question pq WHERE pq.question_id = q.question_id)",
            "教材": "EXISTS (SELECT 1 FROM book_exercise_question beq WHERE beq.question_id = q.question_id)",
            "专题": "EXISTS (SELECT 1 FROM topic_question tq WHERE tq.question_id = q.question_id)",
            "未标记来源": (
                "NOT EXISTS (SELECT 1 FROM paper_question pq WHERE pq.question_id = q.question_id) "
                "AND NOT EXISTS (SELECT 1 FROM book_exercise_question beq WHERE beq.question_id = q.question_id) "
                "AND NOT EXISTS (SELECT 1 FROM topic_question tq WHERE tq.question_id = q.question_id)"
            ),
            "其他": (
                "NOT EXISTS (SELECT 1 FROM paper_question pq WHERE pq.question_id = q.question_id) "
                "AND NOT EXISTS (SELECT 1 FROM book_exercise_question beq WHERE beq.question_id = q.question_id) "
                "AND NOT EXISTS (SELECT 1 FROM topic_question tq WHERE tq.question_id = q.question_id)"
            ),
        }.get(filters.source_kind)
        if source_kind_exists:
            clauses.append(source_kind_exists)

    if filters.paper_series:
        if filters.paper_series == "__UNMARKED_SOURCE__":
            clauses.append("NOT EXISTS (SELECT 1 FROM paper_question pq WHERE pq.question_id = q.question_id)")
        else:
            clauses.append(
                "EXISTS (SELECT 1 FROM paper_question pq JOIN paper p ON p.paper_id = pq.paper_id "
                "WHERE pq.question_id = q.question_id AND p.paper_series = ?)"
            )
            params.append(filters.paper_series)

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
    *,
    _connection: sqlite3.Connection | None = None,
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
            q.choices_json,
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
    with _query_connection(db_path, _connection) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def count_questions(
    db_path: str | None = None,
    filters: QuestionListFilters | None = None,
    *,
    _connection: sqlite3.Connection | None = None,
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
    with _query_connection(db_path, _connection) as conn:
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
    with readonly_database_connection(db_path) as conn:
        total = count_questions(db_path, normalized_filters, _connection=conn)
        items = list_questions(db_path, normalized_filters, _connection=conn)
    page_count = (total + safe_limit - 1) // safe_limit if total else 0
    return {
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
        "page": safe_offset // safe_limit + 1 if total else 0,
        "page_count": page_count,
        "items": items,
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
        paper_series_sql = _where_with_extra_condition(
            where_sql,
            "p.paper_series != ''",
        )
        paper_series = [
            str(row[0])
            for row in conn.execute(
                f"""
                SELECT DISTINCT p.paper_series
                FROM paper_question pq
                JOIN paper p ON p.paper_id = pq.paper_id
                JOIN question q ON q.question_id = pq.question_id
                LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
                {paper_series_sql}
                ORDER BY p.paper_series
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
        "source_kinds": ["试卷", "教材", "专题", "未标记来源", "其他"],
        "paper_series": paper_series,
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
