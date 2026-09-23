"""Standard-paper catalog matching and manual review helpers."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from services.database_service import existing_database_connection, readonly_database_connection, row_to_dict


CATALOG_TABLES = ("paper_standard_catalog", "paper_alias", "paper_match_review")
CONFIRMED_STATUSES = {"confirmed", "active"}
TRACK_ALIASES = {
    "文": "文科",
    "文科": "文科",
    "理": "理科",
    "理科": "理科",
    "新高考": "新高考",
    "综合": "不区分",
    "不分文理": "不区分",
    "不区分": "不区分",
    "": "",
}


def stable_id(prefix: str, *values: object, length: int = 14) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _year(value: Any) -> int | None:
    text = _text(value)
    if not text:
        return None
    match = re.search(r"(?:19|20)\d{2}", text)
    if match:
        return int(match.group(0))
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def normalize_paper_series(value: Any) -> str:
    return unicodedata.normalize("NFKC", _text(value)).upper()


def normalize_track(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", _text(value)).replace(" ", "")
    return TRACK_ALIASES.get(normalized, normalized)


def normalize_paper_name(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", _text(value))
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = normalized.replace("【", "[").replace("】", "]")
    normalized = re.sub(r"[\s·•_—–-]+", "", normalized)
    normalized = normalized.replace("卷一", "卷I").replace("卷二", "卷II").replace("卷三", "卷III")
    normalized = normalized.replace("1卷", "I卷").replace("2卷", "II卷").replace("3卷", "III卷")
    return normalized.upper()


def catalog_schema_available(db_path: str | None = None) -> bool:
    try:
        with readonly_database_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?, ?)",
                CATALOG_TABLES,
            ).fetchall()
        return {str(row["name"]) for row in rows} == set(CATALOG_TABLES)
    except (FileNotFoundError, OSError):
        return False


def _catalog_row(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["year"] = _year(item.get("year"))
    item["paper_series"] = normalize_paper_series(item.get("paper_series"))
    item["track"] = normalize_track(item.get("track"))
    item["paper_name"] = _text(item.get("paper_name"))
    item["source_name"] = _text(item.get("source_name")) or item["paper_name"]
    return item


def list_standard_papers(
    db_path: str | None = None,
    *,
    year: Any = None,
    paper_series: str = "",
    status: str = "confirmed",
    limit: int = 500,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    safe_year = _year(year)
    if safe_year is not None:
        clauses.append("year = ?")
        params.append(safe_year)
    if _text(paper_series):
        clauses.append("paper_series = ?")
        params.append(normalize_paper_series(paper_series))
    if _text(status):
        clauses.append("status = ?")
        params.append(_text(status))
    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(max(1, min(int(limit or 500), 2000)))
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM paper_standard_catalog
            {where_sql}
            ORDER BY year DESC, paper_series, sort_order, paper_name, track
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [_catalog_row(row) for row in rows]


def get_standard_paper(db_path: str | None, paper_standard_id: str) -> dict[str, Any]:
    with readonly_database_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM paper_standard_catalog WHERE paper_standard_id = ?",
            (_text(paper_standard_id),),
        ).fetchone()
    return _catalog_row(row) if row else {}


def add_standard_paper(
    db_path: str | None,
    *,
    year: Any,
    paper_series: str,
    track: str,
    paper_name: str,
    source_name: str = "",
    status: str = "confirmed",
) -> dict[str, Any]:
    safe_name = _text(paper_name)
    safe_series = normalize_paper_series(paper_series)
    if not safe_name:
        raise ValueError("paper_name cannot be empty")
    if not safe_series:
        raise ValueError("paper_series cannot be empty")
    safe_year = _year(year)
    safe_track = normalize_track(track)
    paper_standard_id = stable_id("PS", safe_year or "", safe_series, safe_track, safe_name)
    with existing_database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO paper_standard_catalog(
                paper_standard_id, year, paper_series, track, paper_name, source_name, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(year, paper_series, track, paper_name) DO UPDATE SET
                source_name = CASE WHEN excluded.source_name != '' THEN excluded.source_name ELSE paper_standard_catalog.source_name END,
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
            """,
            (paper_standard_id, safe_year, safe_series, safe_track, safe_name, _text(source_name) or safe_name, _text(status) or "confirmed"),
        )
        row = conn.execute(
            """
            SELECT * FROM paper_standard_catalog
            WHERE ((year = ?) OR (year IS NULL AND ? IS NULL))
              AND paper_series = ? AND track = ? AND paper_name = ?
            """,
            (safe_year, safe_year, safe_series, safe_track, safe_name),
        ).fetchone()
    return _catalog_row(row)


def add_paper_alias(
    db_path: str | None,
    paper_standard_id: str,
    alias_name: str,
    *,
    alias_type: str = "historical",
    source: str = "",
    note: str = "",
) -> dict[str, Any]:
    safe_standard_id = _text(paper_standard_id)
    safe_alias = _text(alias_name)
    if not safe_standard_id or not safe_alias:
        raise ValueError("paper_standard_id and alias_name are required")
    paper_alias_id = stable_id("PA", safe_standard_id, safe_alias)
    with existing_database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO paper_alias(paper_alias_id, paper_standard_id, alias_name, alias_type, source, note)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_standard_id, alias_name) DO UPDATE SET
                alias_type = excluded.alias_type,
                source = excluded.source,
                note = excluded.note
            """,
            (paper_alias_id, safe_standard_id, safe_alias, _text(alias_type) or "historical", _text(source), _text(note)),
        )
        row = conn.execute("SELECT * FROM paper_alias WHERE paper_alias_id = ?", (paper_alias_id,)).fetchone()
    return row_to_dict(row)


def _candidate_score(recognized: dict[str, Any], candidate: dict[str, Any], alias_name: str = "") -> tuple[float, str]:
    source_name = alias_name or candidate["paper_name"]
    name_score = SequenceMatcher(None, normalize_paper_name(recognized["paper_name"]), normalize_paper_name(source_name)).ratio()
    score = name_score * 0.78
    reasons = ["similar_name"]
    if recognized["year"] == candidate["year"]:
        score += 0.1
        reasons.append("same_year")
    if recognized["paper_series"] == normalize_paper_series(candidate["paper_series"]):
        score += 0.08
        reasons.append("same_series")
    if recognized["track"] == normalize_track(candidate["track"]):
        score += 0.04
        reasons.append("same_track")
    elif recognized["track"] and candidate["track"]:
        reasons.append("track_conflict")
    if alias_name:
        reasons.append("alias")
    return min(score, 1.0), "+".join(reasons)


def match_paper(
    db_path: str | None,
    *,
    year: Any,
    paper_series: str,
    track: str,
    paper_name: str,
    limit: int = 5,
    similarity_threshold: float = 0.55,
) -> dict[str, Any]:
    recognized = {
        "year": _year(year),
        "paper_series": normalize_paper_series(paper_series),
        "track": normalize_track(track),
        "paper_name": _text(paper_name),
    }
    result = {"status": "invalid", "recognized": recognized, "selected": None, "candidates": []}
    if not recognized["paper_name"] or not recognized["paper_series"]:
        return result
    if not catalog_schema_available(db_path):
        result["status"] = "schema_unavailable"
        return result

    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT c.*, a.alias_name
            FROM paper_standard_catalog c
            LEFT JOIN paper_alias a ON a.paper_standard_id = c.paper_standard_id
            WHERE c.status IN ('confirmed', 'active')
              AND c.paper_series = ?
              AND ((c.year = ?) OR (? IS NULL))
            ORDER BY c.year DESC, c.sort_order, c.paper_name, c.track
            """,
            (recognized["paper_series"], recognized["year"], recognized["year"]),
        ).fetchall()

    normalized_name = normalize_paper_name(recognized["paper_name"])
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        candidate = _catalog_row(row)
        alias_name = _text(row["alias_name"])
        identity_matches = (
            candidate["year"] == recognized["year"]
            and normalize_paper_series(candidate["paper_series"]) == recognized["paper_series"]
            and normalize_track(candidate["track"]) == recognized["track"]
        )
        canonical_exact = normalize_paper_name(candidate["paper_name"]) == normalized_name
        alias_exact = bool(alias_name) and normalize_paper_name(alias_name) == normalized_name
        if identity_matches and (canonical_exact or alias_exact):
            selected = dict(candidate)
            selected["score"] = 1.0
            selected["match_reason"] = "exact_alias" if alias_exact and not canonical_exact else "exact_catalog"
            result.update(status="exact", selected=selected, candidates=[selected])
            return result

        score, reason = _candidate_score(recognized, candidate, alias_name)
        existing = grouped.get(candidate["paper_standard_id"])
        if existing is None or score > existing["score"]:
            item = dict(candidate)
            item["score"] = round(score, 4)
            item["match_reason"] = reason
            item["matched_alias"] = alias_name
            grouped[candidate["paper_standard_id"]] = item

    candidates = sorted(grouped.values(), key=lambda item: (-item["score"], item["paper_name"], item["track"]))
    candidates = [item for item in candidates if item["score"] >= similarity_threshold][: max(1, int(limit or 5))]
    result["candidates"] = candidates
    result["status"] = "needs_confirmation" if candidates else "new_paper"
    return result


def record_match_review(
    db_path: str | None,
    match_result: dict[str, Any],
    *,
    decision: str,
    confirmed_standard_id: str = "",
    operator: str = "streamlit_ui",
    note: str = "",
    batch_id: str = "",
    draft_id: str = "",
) -> dict[str, Any]:
    recognized = dict(match_result.get("recognized") or {})
    candidates = list(match_result.get("candidates") or [])
    selected = dict(match_result.get("selected") or {})
    confirmed = get_standard_paper(db_path, confirmed_standard_id) if confirmed_standard_id else selected
    suggested = candidates[0] if candidates else selected
    review_id = stable_id(
        "PMR",
        batch_id,
        draft_id,
        recognized.get("year") or "",
        recognized.get("paper_series") or "",
        recognized.get("track") or "",
        recognized.get("paper_name") or "",
        decision,
        confirmed.get("paper_standard_id") or "",
    )
    with existing_database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO paper_match_review(
                paper_match_review_id, batch_id, draft_id,
                recognized_year, recognized_series, recognized_track, recognized_name,
                suggested_standard_id, suggested_score, decision,
                confirmed_standard_id, confirmed_year, confirmed_series, confirmed_track,
                confirmed_name, operator, note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_match_review_id) DO UPDATE SET
                batch_id = excluded.batch_id,
                draft_id = excluded.draft_id,
                decision = excluded.decision,
                confirmed_standard_id = excluded.confirmed_standard_id,
                confirmed_year = excluded.confirmed_year,
                confirmed_series = excluded.confirmed_series,
                confirmed_track = excluded.confirmed_track,
                confirmed_name = excluded.confirmed_name,
                operator = excluded.operator,
                note = excluded.note,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                review_id,
                _text(batch_id),
                _text(draft_id),
                recognized.get("year"),
                _text(recognized.get("paper_series")),
                _text(recognized.get("track")),
                _text(recognized.get("paper_name")),
                _text(suggested.get("paper_standard_id")) or None,
                suggested.get("score"),
                _text(decision) or "pending",
                _text(confirmed.get("paper_standard_id")) or None,
                confirmed.get("year"),
                _text(confirmed.get("paper_series")),
                _text(confirmed.get("track")),
                _text(confirmed.get("paper_name")),
                _text(operator),
                _text(note),
            ),
        )
        row = conn.execute("SELECT * FROM paper_match_review WHERE paper_match_review_id = ?", (review_id,)).fetchone()
    return row_to_dict(row)


def attach_review_context(db_path: str | None, review_id: str, *, batch_id: str = "", draft_id: str = "") -> dict[str, Any]:
    safe_review_id = _text(review_id)
    if not safe_review_id:
        return {}
    with existing_database_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE paper_match_review
            SET batch_id = CASE WHEN ? != '' THEN ? ELSE batch_id END,
                draft_id = CASE WHEN ? != '' THEN ? ELSE draft_id END,
                updated_at = CURRENT_TIMESTAMP
            WHERE paper_match_review_id = ?
            """,
            (_text(batch_id), _text(batch_id), _text(draft_id), _text(draft_id), safe_review_id),
        )
        row = conn.execute("SELECT * FROM paper_match_review WHERE paper_match_review_id = ?", (safe_review_id,)).fetchone()
    return row_to_dict(row)


def list_match_reviews(
    db_path: str | None = None,
    *,
    decision: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return recent catalog decisions for the maintenance UI."""
    clauses: list[str] = []
    params: list[Any] = []
    if _text(decision):
        clauses.append("decision = ?")
        params.append(_text(decision))
    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(max(1, min(int(limit or 100), 500)))
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM paper_match_review
            {where_sql}
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def update_standard_paper_status(
    db_path: str | None,
    paper_standard_id: str,
    status: str,
) -> dict[str, Any]:
    """Change only the catalog status; never deletes the underlying paper."""
    safe_id = _text(paper_standard_id)
    safe_status = _text(status)
    if not safe_id or safe_status not in {"confirmed", "active", "deprecated"}:
        raise ValueError("invalid standard paper status update")
    with existing_database_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE paper_standard_catalog
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE paper_standard_id = ?
            """,
            (safe_status, safe_id),
        )
        row = conn.execute(
            "SELECT * FROM paper_standard_catalog WHERE paper_standard_id = ?",
            (safe_id,),
        ).fetchone()
    if not row:
        raise KeyError(f"standard paper not found: {safe_id}")
    return _catalog_row(row)
