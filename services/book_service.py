"""Book/catalog helpers for the structured question-bank database."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.database_service import readonly_database_connection, row_to_dict


@dataclass(frozen=True)
class BookListFilters:
    keyword: str = ""
    publisher: str = ""
    grade: str = ""
    volume: str = ""
    limit: int = 50
    offset: int = 0


def _safe_limit(value: int) -> int:
    return max(1, min(int(value or 50), 200))


def _safe_offset(value: int) -> int:
    return max(0, int(value or 0))


def _build_book_where(filters: BookListFilters) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if filters.keyword:
        clauses.append(
            """
            (
                b.title LIKE ?
                OR b.publisher LIKE ?
                OR b.edition LIKE ?
                OR b.grade LIKE ?
                OR b.volume LIKE ?
                OR b.description LIKE ?
            )
            """
        )
        like = f"%{filters.keyword}%"
        params.extend([like, like, like, like, like, like])

    if filters.publisher:
        clauses.append("b.publisher = ?")
        params.append(filters.publisher)

    if filters.grade:
        clauses.append("b.grade = ?")
        params.append(filters.grade)

    if filters.volume:
        clauses.append("b.volume = ?")
        params.append(filters.volume)

    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(f"({clause})" for clause in clauses), params


def list_books(db_path: str | None = None, filters: BookListFilters | None = None) -> list[dict]:
    """Return paginated books with section and exercise-link counts."""
    filters = filters or BookListFilters()
    where_sql, params = _build_book_where(filters)
    params.extend([_safe_limit(filters.limit), _safe_offset(filters.offset)])
    sql = f"""
        SELECT
            b.*,
            COUNT(DISTINCT s.section_id) AS section_count,
            COUNT(DISTINCT beq.book_exercise_question_id) AS question_link_count
        FROM book b
        LEFT JOIN book_section s ON s.book_id = b.book_id
        LEFT JOIN book_exercise_question beq ON beq.book_id = b.book_id
        {where_sql}
        GROUP BY b.book_id
        ORDER BY b.title, b.grade, b.volume
        LIMIT ? OFFSET ?
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def count_books(db_path: str | None = None, filters: BookListFilters | None = None) -> int:
    """Count books matching filters."""
    filters = filters or BookListFilters()
    where_sql, params = _build_book_where(filters)
    with readonly_database_connection(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM book b {where_sql}", params).fetchone()[0])


def get_book(db_path: str | None, book_id: str) -> dict:
    """Return one book with aggregate counts."""
    sql = """
        SELECT
            b.*,
            COUNT(DISTINCT s.section_id) AS section_count,
            COUNT(DISTINCT beq.book_exercise_question_id) AS question_link_count
        FROM book b
        LEFT JOIN book_section s ON s.book_id = b.book_id
        LEFT JOIN book_exercise_question beq ON beq.book_id = b.book_id
        WHERE b.book_id = ?
        GROUP BY b.book_id
    """
    with readonly_database_connection(db_path) as conn:
        row = conn.execute(sql, (book_id,)).fetchone()
    return row_to_dict(row)


def list_book_sections(db_path: str | None, book_id: str) -> list[dict]:
    """Return the section tree rows for one book."""
    sql = """
        SELECT
            s.*,
            parent.title AS parent_title,
            COUNT(beq.book_exercise_question_id) AS question_link_count
        FROM book_section s
        LEFT JOIN book_section parent ON parent.section_id = s.parent_section_id
        LEFT JOIN book_exercise_question beq ON beq.section_id = s.section_id
        WHERE s.book_id = ?
        GROUP BY s.section_id
        ORDER BY s.sort_order, s.page_start, s.title
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, (book_id,)).fetchall()
    return [dict(row) for row in rows]


def list_book_questions(
    db_path: str | None,
    book_id: str,
    section_id: str = "",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Return question links for one book, optionally restricted to one section."""
    safe_limit = _safe_limit(limit)
    safe_offset = _safe_offset(offset)
    clauses = ["beq.book_id = ?"]
    params: list[Any] = [book_id]
    if section_id:
        clauses.append("beq.section_id = ?")
        params.append(section_id)
    params.extend([safe_limit, safe_offset])
    sql = f"""
        SELECT
            beq.*,
            s.title AS section_title,
            q.legacy_id,
            q.question_type_id,
            q.difficulty,
            q.tags_json,
            q.note,
            l.legacy_file_path,
            l.detected_chapter,
            substr(q.stem_tex, 1, 180) AS stem_preview
        FROM book_exercise_question beq
        LEFT JOIN book_section s ON s.section_id = beq.section_id
        JOIN question q ON q.question_id = beq.question_id
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        WHERE {" AND ".join(clauses)}
        ORDER BY s.sort_order, beq.display_order, beq.page_number, beq.exercise_number, beq.sub_number
        LIMIT ? OFFSET ?
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def count_book_questions(db_path: str | None, book_id: str, section_id: str = "") -> int:
    """Count question links for one book."""
    clauses = ["book_id = ?"]
    params: list[Any] = [book_id]
    if section_id:
        clauses.append("section_id = ?")
        params.append(section_id)
    with readonly_database_connection(db_path) as conn:
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM book_exercise_question WHERE {' AND '.join(clauses)}",
                params,
            ).fetchone()[0]
        )


def list_question_book_links(db_path: str | None, question_id: str) -> list[dict]:
    """Return all book appearances for one question."""
    sql = """
        SELECT
            b.book_id,
            b.title,
            b.publisher,
            b.edition,
            b.grade,
            b.volume,
            s.section_id,
            s.title AS section_title,
            beq.book_exercise_question_id,
            beq.page_number,
            beq.column_name,
            beq.exercise_number,
            beq.sub_number,
            beq.display_order,
            beq.source_note
        FROM book_exercise_question beq
        JOIN book b ON b.book_id = beq.book_id
        LEFT JOIN book_section s ON s.section_id = beq.section_id
        WHERE beq.question_id = ?
        ORDER BY b.title, s.sort_order, beq.display_order
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, (question_id,)).fetchall()
    return [dict(row) for row in rows]
