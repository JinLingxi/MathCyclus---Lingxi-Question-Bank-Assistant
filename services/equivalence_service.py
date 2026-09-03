"""Helpers for same-question relations and manual review decision files."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from services.database_service import BASE_DIR, readonly_database_connection


PROJECT_ROOT = Path(BASE_DIR)
DEFAULT_DECISIONS_PATH = PROJECT_ROOT / "db" / "seed" / "equivalence_review_decisions_20260902_initial.csv"
SUPPORTED_DECISIONS = {"pending", "keep_all", "mark_equivalent", "merge_to_canonical", "ignore"}


def resolve_path(path: str | Path | None = None) -> Path:
    target = Path(path) if path else DEFAULT_DECISIONS_PATH
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    return target.resolve()


def split_pipe_list(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def list_review_decisions(path: str | Path | None = None) -> list[dict]:
    """Load the manual equivalence-review CSV as dictionaries."""
    decisions_path = resolve_path(path)
    if not decisions_path.exists():
        return []

    with decisions_path.open(encoding="utf-8-sig", newline="") as file:
        rows = []
        for row in csv.DictReader(file):
            normalized = {key: (value or "").strip() for key, value in row.items()}
            normalized["question_id_list"] = split_pipe_list(normalized.get("question_ids", ""))
            normalized["chapter_list"] = split_pipe_list(normalized.get("chapters", ""))
            rows.append(normalized)
    return rows


def summarize_review_decisions(path: str | Path | None = None) -> dict:
    """Return counts for the current equivalence-review decision CSV."""
    rows = list_review_decisions(path)
    decision_counts = Counter(row.get("decision", "") for row in rows)
    issue_counts = Counter(row.get("issue_type", "") for row in rows)
    unsupported = [
        row
        for row in rows
        if row.get("decision", "") not in SUPPORTED_DECISIONS
    ]
    return {
        "total": len(rows),
        "decision_counts": dict(sorted(decision_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "unsupported_decision_rows": len(unsupported),
    }


def list_equivalence_relations(
    db_path: str | None = None,
    review_status: str = "",
    relation_type: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List same-question relation rows with lightweight source context."""
    safe_limit = max(1, min(int(limit or 50), 200))
    safe_offset = max(0, int(offset or 0))
    clauses: list[str] = []
    params: list[object] = []

    if review_status:
        clauses.append("qe.review_status = ?")
        params.append(review_status)
    if relation_type:
        clauses.append("qe.relation_type = ?")
        params.append(relation_type)

    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend([safe_limit, safe_offset])

    sql = f"""
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
        {where_sql}
        ORDER BY qe.review_status, qe.relation_type, qe.confidence DESC, qe.question_id_a
        LIMIT ? OFFSET ?
    """
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def count_equivalence_relations(
    db_path: str | None = None,
    review_status: str = "",
    relation_type: str = "",
) -> int:
    """Count same-question relation rows."""
    clauses: list[str] = []
    params: list[object] = []
    if review_status:
        clauses.append("review_status = ?")
        params.append(review_status)
    if relation_type:
        clauses.append("relation_type = ?")
        params.append(relation_type)

    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    with readonly_database_connection(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM question_equivalence {where_sql}", params).fetchone()[0])
