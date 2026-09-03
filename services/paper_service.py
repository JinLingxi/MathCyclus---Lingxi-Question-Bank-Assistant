"""Read-only paper/query helpers for the structured SQLite question bank."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.database_service import readonly_database_connection, row_to_dict


@dataclass(frozen=True)
class PaperListFilters:
    year: int | None = None
    paper_series: str = ""
    track: str = ""
    keyword: str = ""
    limit: int = 50
    offset: int = 0


def _safe_limit(value: int) -> int:
    return max(1, min(int(value or 50), 200))


def _safe_offset(value: int) -> int:
    return max(0, int(value or 0))


def _build_paper_where(filters: PaperListFilters) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if filters.year is not None:
        clauses.append("p.year = ?")
        params.append(filters.year)

    if filters.paper_series:
        clauses.append("p.paper_series = ?")
        params.append(filters.paper_series)

    if filters.track:
        clauses.append("p.track = ?")
        params.append(filters.track)

    if filters.keyword:
        clauses.append("(p.paper_name LIKE ? OR p.source_name LIKE ? OR p.description LIKE ?)")
        like = f"%{filters.keyword}%"
        params.extend([like, like, like])

    if not clauses:
        return "", params
    return "WHERE " + " AND ".join(f"({clause})" for clause in clauses), params


def list_papers(db_path: str | None = None, filters: PaperListFilters | None = None) -> list[dict]:
    """Return paginated papers with question counts."""
    filters = filters or PaperListFilters()
    where_sql, params = _build_paper_where(filters)
    params.extend([_safe_limit(filters.limit), _safe_offset(filters.offset)])

    sql = f"""
        SELECT
            p.paper_id,
            p.year,
            p.paper_series,
            p.track,
            p.paper_name,
            p.source_name,
            p.description,
            COUNT(pq.paper_question_id) AS question_count
        FROM paper p
        LEFT JOIN paper_question pq ON pq.paper_id = p.paper_id
        {where_sql}
        GROUP BY p.paper_id
        ORDER BY p.year DESC, p.paper_name, p.track
        LIMIT ? OFFSET ?
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def count_papers(db_path: str | None = None, filters: PaperListFilters | None = None) -> int:
    """Count papers matching filters."""
    filters = filters or PaperListFilters()
    where_sql, params = _build_paper_where(filters)
    sql = f"SELECT COUNT(*) FROM paper p {where_sql}"
    with readonly_database_connection(db_path) as conn:
        return int(conn.execute(sql, params).fetchone()[0])


def get_paper(db_path: str | None, paper_id: str) -> dict:
    """Return one paper by ID."""
    sql = """
        SELECT
            p.*,
            COUNT(pq.paper_question_id) AS question_count
        FROM paper p
        LEFT JOIN paper_question pq ON pq.paper_id = p.paper_id
        WHERE p.paper_id = ?
        GROUP BY p.paper_id
    """
    with readonly_database_connection(db_path) as conn:
        row = conn.execute(sql, (paper_id,)).fetchone()
    return row_to_dict(row)


def list_paper_questions(db_path: str | None, paper_id: str) -> list[dict]:
    """Return questions linked to one paper."""
    sql = """
        SELECT
            pq.paper_question_id,
            pq.question_id,
            pq.question_number,
            pq.sub_number,
            pq.display_order,
            q.legacy_id,
            q.question_type_id,
            q.difficulty,
            q.tags_json,
            q.note,
            l.legacy_file_path,
            l.detected_chapter,
            l.detected_topic,
            substr(q.stem_tex, 1, 160) AS stem_preview
        FROM paper_question pq
        JOIN question q ON q.question_id = pq.question_id
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        WHERE pq.paper_id = ?
        ORDER BY pq.display_order, pq.question_number, pq.sub_number, pq.question_id
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, (paper_id,)).fetchall()
    return [dict(row) for row in rows]


def list_question_paper_links(db_path: str | None, question_id: str) -> list[dict]:
    """Return all paper appearances for one question."""
    sql = """
        SELECT
            p.paper_id,
            p.year,
            p.paper_series,
            p.track,
            p.paper_name,
            p.source_name,
            pq.paper_question_id,
            pq.question_number,
            pq.sub_number,
            pq.display_order
        FROM paper_question pq
        JOIN paper p ON p.paper_id = pq.paper_id
        WHERE pq.question_id = ?
        ORDER BY p.year DESC, p.paper_name, pq.display_order
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, (question_id,)).fetchall()
    return [dict(row) for row in rows]


def list_paper_years(db_path: str | None = None) -> list[int]:
    """Return available paper years descending."""
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT year FROM paper WHERE year IS NOT NULL ORDER BY year DESC"
        ).fetchall()
    return [int(row[0]) for row in rows]


def list_paper_tracks(db_path: str | None = None) -> list[str]:
    """Return available paper tracks."""
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT track FROM paper WHERE track != '' ORDER BY track"
        ).fetchall()
    return [str(row[0]) for row in rows]
