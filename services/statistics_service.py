"""Statistics helpers for the question-bank dashboard.

The dashboard should prefer the structured SQLite database once it exists, but
older local installs may still only have the CSV index or the legacy TeX tree.
This module keeps that fallback chain outside the Streamlit page.
"""

from __future__ import annotations

import datetime as _datetime
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from services.database_service import DEFAULT_DATABASE_PATH, readonly_database_connection, resolve_database_path
from utils.core_config import CHAPTERS_DIR


def empty_statistics() -> dict[str, Any]:
    return {
        "total_questions": 0,
        "total_tikz": 0,
        "today_new_questions": 0,
        "today_mod_questions": 0,
        "today_new_tikz": 0,
        "today_mod_tikz": 0,
        "daily_activity": {},
        "hourly_activity_by_day": {},
        "subject_counts": {},
        "type_counts": {},
        "difficulty_dist": {},
        "tag_counts": {},
        "year_counts": {},
        "source_series_counts": {},
        "track_counts": {},
        "revision_source_counts": {},
        "topic_counts": {},
        "book_counts": {},
        "paper_relation_count": 0,
        "paper_linked_questions": 0,
        "topic_count": 0,
        "topic_link_count": 0,
        "topic_linked_questions": 0,
        "book_count": 0,
        "book_link_count": 0,
        "book_linked_questions": 0,
        "asset_count": 0,
        "asset_linked_questions": 0,
        "total_difficulty": 0.0,
        "difficulty_count": 0,
        "source": "empty",
        "source_label": "暂无数据源",
        "source_detail": "",
        "source_priority": "SQLite -> CSV -> legacy TeX",
        "sqlite_primary": False,
        "fallback_used": False,
        "fallback_error": "",
    }


def _parse_datetime(value: Any) -> _datetime.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    for parser in (
        lambda item: _datetime.datetime.fromisoformat(item),
        lambda item: _datetime.datetime.strptime(item, "%Y-%m-%d %H:%M:%S"),
        lambda item: _datetime.datetime.strptime(item, "%Y-%m-%d"),
    ):
        try:
            parsed = parser(normalized)
            if parsed.tzinfo:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except ValueError:
            continue
    return None


def _add_activity(stats: dict[str, Any], when: _datetime.datetime | None, count: int = 1) -> None:
    if when is None:
        return
    event_date = when.date().isoformat()
    event_hour = f"{when.hour:02d}"
    stats["daily_activity"][event_date] = stats["daily_activity"].get(event_date, 0) + count
    stats["hourly_activity_by_day"].setdefault(
        event_date,
        {str(hour).zfill(2): 0 for hour in range(24)},
    )
    stats["hourly_activity_by_day"][event_date][event_hour] += count


def _json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [item.strip() for item in re.split(r"[，,;；\n]+", text) if item.strip()]


def _numeric_difficulty(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _difficulty_label(value: float) -> str:
    if value <= 2.0:
        return "0-2星 (基础)"
    if value <= 4.0:
        return "3-4星 (中档)"
    return "5-6星 (压轴)"


def _has_tikz(row: dict[str, Any]) -> bool:
    text = "\n".join(
        str(row.get(field) or "")
        for field in ("canonical_tex", "stem_tex", "answer_tex", "solution_tex")
    )
    return "\\begin{tikzpicture}" in text


def _is_wk_csv_row(row: dict[str, Any]) -> bool:
    return (row.get("试卷类型", "") or "").strip() == "WK"


def _is_wk_tex_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/")
    return "-WK-" in normalized


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _sqlite_question_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "question"):
        raise RuntimeError("SQLite 数据库缺少 question 表")

    sql = """
        SELECT
            q.question_id,
            q.question_type_id,
            q.difficulty,
            q.tags_json,
            q.note,
            q.canonical_tex,
            q.stem_tex,
            q.answer_tex,
            q.solution_tex,
            q.created_at,
            q.updated_at,
            COALESCE(qt.name, '未知') AS question_type_name,
            COALESCE(primary_ka.name, l.detected_chapter, '未分类') AS subject_name,
            COALESCE(l.legacy_file_path, q.legacy_file_path, '') AS legacy_file_path,
            COALESCE(l.detected_source, '') AS detected_source,
            COALESCE(paper_scope.has_wk, 0) AS has_wk
        FROM question q
        LEFT JOIN question_type qt ON qt.question_type_id = q.question_type_id
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        LEFT JOIN (
            SELECT
                qka.question_id,
                MIN(ka.name) AS name
            FROM question_knowledge_area qka
            JOIN knowledge_area ka ON ka.knowledge_area_id = qka.knowledge_area_id
            WHERE qka.is_primary = 1
            GROUP BY qka.question_id
        ) primary_ka ON primary_ka.question_id = q.question_id
        LEFT JOIN (
            SELECT
                pq.question_id,
                MAX(CASE WHEN p.paper_series = 'WK' THEN 1 ELSE 0 END) AS has_wk
            FROM paper_question pq
            JOIN paper p ON p.paper_id = pq.paper_id
            GROUP BY pq.question_id
        ) paper_scope ON paper_scope.question_id = q.question_id
        WHERE COALESCE(paper_scope.has_wk, 0) = 0
          AND COALESCE(l.legacy_file_path, q.legacy_file_path, '') NOT LIKE '%-WK-%'
        ORDER BY q.question_id
    """
    return [dict(row) for row in conn.execute(sql).fetchall()]


def _sqlite_revision_rows(conn: sqlite3.Connection, question_ids: set[str]) -> list[dict[str, Any]]:
    if not question_ids or not _table_exists(conn, "question_revision"):
        return []
    placeholders = ",".join("?" for _ in question_ids)
    rows = conn.execute(
        f"""
        SELECT question_id, change_source, created_at
        FROM question_revision
        WHERE question_id IN ({placeholders})
        """,
        sorted(question_ids),
    ).fetchall()
    return [dict(row) for row in rows]


def _group_counts(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...] = (),
    *,
    empty_label: str = "未标注",
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in conn.execute(sql, params).fetchall():
        label = str(row[0] or "").strip() or empty_label
        counts[label] = int(row[1] or 0)
    return counts


def _scalar_count(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0) if row else 0


def _question_placeholders(question_ids: set[str]) -> tuple[str, tuple[str, ...]]:
    ordered = tuple(sorted(question_ids))
    return ",".join("?" for _ in ordered), ordered


def _sqlite_relation_statistics(conn: sqlite3.Connection, question_ids: set[str]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    if not question_ids:
        return stats
    placeholders, params = _question_placeholders(question_ids)

    if _table_exists(conn, "paper") and _table_exists(conn, "paper_question"):
        stats["paper_relation_count"] = _scalar_count(
            conn,
            f"SELECT COUNT(*) FROM paper_question WHERE question_id IN ({placeholders})",
            params,
        )
        stats["paper_linked_questions"] = _scalar_count(
            conn,
            f"SELECT COUNT(DISTINCT question_id) FROM paper_question WHERE question_id IN ({placeholders})",
            params,
        )
        stats["year_counts"] = _group_counts(
            conn,
            f"""
            SELECT COALESCE(CAST(p.year AS TEXT), ''), COUNT(DISTINCT pq.question_id)
            FROM paper_question pq
            JOIN paper p ON p.paper_id = pq.paper_id
            WHERE pq.question_id IN ({placeholders})
              AND COALESCE(p.paper_series, '') <> 'WK'
            GROUP BY p.year
            ORDER BY p.year DESC
            """,
            params,
        )
        stats["source_series_counts"] = _group_counts(
            conn,
            f"""
            SELECT COALESCE(NULLIF(p.paper_series, ''), '未标注'), COUNT(DISTINCT pq.question_id)
            FROM paper_question pq
            JOIN paper p ON p.paper_id = pq.paper_id
            WHERE pq.question_id IN ({placeholders})
              AND COALESCE(p.paper_series, '') <> 'WK'
            GROUP BY COALESCE(NULLIF(p.paper_series, ''), '未标注')
            ORDER BY COUNT(DISTINCT pq.question_id) DESC
            """,
            params,
        )
        stats["track_counts"] = _group_counts(
            conn,
            f"""
            SELECT COALESCE(NULLIF(p.track, ''), '未标注'), COUNT(DISTINCT pq.question_id)
            FROM paper_question pq
            JOIN paper p ON p.paper_id = pq.paper_id
            WHERE pq.question_id IN ({placeholders})
              AND COALESCE(p.paper_series, '') <> 'WK'
            GROUP BY COALESCE(NULLIF(p.track, ''), '未标注')
            ORDER BY COUNT(DISTINCT pq.question_id) DESC
            """,
            params,
        )

    if _table_exists(conn, "topic") and _table_exists(conn, "topic_question"):
        stats["topic_count"] = _scalar_count(conn, "SELECT COUNT(*) FROM topic")
        stats["topic_link_count"] = _scalar_count(
            conn,
            f"SELECT COUNT(*) FROM topic_question WHERE question_id IN ({placeholders})",
            params,
        )
        stats["topic_linked_questions"] = _scalar_count(
            conn,
            f"SELECT COUNT(DISTINCT question_id) FROM topic_question WHERE question_id IN ({placeholders})",
            params,
        )
        stats["topic_counts"] = _group_counts(
            conn,
            f"""
            SELECT t.name, COUNT(tq.question_id)
            FROM topic_question tq
            JOIN topic t ON t.topic_id = tq.topic_id
            WHERE tq.question_id IN ({placeholders})
            GROUP BY t.topic_id, t.name
            ORDER BY COUNT(tq.question_id) DESC, t.name
            """,
            params,
        )

    if _table_exists(conn, "book") and _table_exists(conn, "book_exercise_question"):
        stats["book_count"] = _scalar_count(conn, "SELECT COUNT(*) FROM book")
        stats["book_link_count"] = _scalar_count(
            conn,
            f"SELECT COUNT(*) FROM book_exercise_question WHERE question_id IN ({placeholders})",
            params,
        )
        stats["book_linked_questions"] = _scalar_count(
            conn,
            f"SELECT COUNT(DISTINCT question_id) FROM book_exercise_question WHERE question_id IN ({placeholders})",
            params,
        )
        stats["book_counts"] = _group_counts(
            conn,
            f"""
            SELECT b.title, COUNT(beq.question_id)
            FROM book_exercise_question beq
            JOIN book b ON b.book_id = beq.book_id
            WHERE beq.question_id IN ({placeholders})
            GROUP BY b.book_id, b.title
            ORDER BY COUNT(beq.question_id) DESC, b.title
            """,
            params,
        )

    if _table_exists(conn, "question_asset"):
        stats["asset_count"] = _scalar_count(
            conn,
            f"SELECT COUNT(*) FROM question_asset WHERE question_id IN ({placeholders})",
            params,
        )
        stats["asset_linked_questions"] = _scalar_count(
            conn,
            f"SELECT COUNT(DISTINCT question_id) FROM question_asset WHERE question_id IN ({placeholders})",
            params,
        )

    if _table_exists(conn, "question_revision"):
        stats["revision_source_counts"] = _group_counts(
            conn,
            f"""
            SELECT COALESCE(NULLIF(change_source, ''), '未标注'), COUNT(*)
            FROM question_revision
            WHERE question_id IN ({placeholders})
            GROUP BY COALESCE(NULLIF(change_source, ''), '未标注')
            ORDER BY COUNT(*) DESC
            """,
            params,
        )

    return stats


def get_statistics_from_sqlite(db_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    stats = empty_statistics()
    stats.update(
        {
            "source": "sqlite",
            "source_label": "SQLite 正式库",
            "source_detail": "读取 data/mathcyclus.sqlite3 的结构化字段",
            "sqlite_primary": True,
            "fallback_used": False,
        }
    )

    with readonly_database_connection(db_path) as conn:
        rows = _sqlite_question_rows(conn)
        question_ids = {str(row.get("question_id") or "") for row in rows if row.get("question_id")}
        revision_rows = _sqlite_revision_rows(conn, question_ids)
        relation_stats = _sqlite_relation_statistics(conn, question_ids)

    stats["total_questions"] = len(rows)
    stats.update(relation_stats)
    today = _datetime.date.today()
    tikz_question_ids: set[str] = set()
    created_today_tikz: set[str] = set()
    modified_today_tikz: set[str] = set()
    created_dates: dict[str, _datetime.date] = {}
    revision_today_question_ids: set[str] = set()

    for row in rows:
        question_id = str(row.get("question_id") or "")
        if _has_tikz(row):
            tikz_question_ids.add(question_id)

        subject = str(row.get("subject_name") or "未分类").strip() or "未分类"
        stats["subject_counts"][subject] = stats["subject_counts"].get(subject, 0) + 1

        question_type = str(row.get("question_type_name") or "未知").strip() or "未知"
        stats["type_counts"][question_type] = stats["type_counts"].get(question_type, 0) + 1

        diff_value = _numeric_difficulty(row.get("difficulty"))
        if diff_value is not None:
            stats["total_difficulty"] += diff_value
            stats["difficulty_count"] += 1
            label = _difficulty_label(diff_value)
            stats["difficulty_dist"][label] = stats["difficulty_dist"].get(label, 0) + 1

        for tag in _json_list(row.get("tags_json")):
            stats["tag_counts"][tag] = stats["tag_counts"].get(tag, 0) + 1

        created_at = _parse_datetime(row.get("created_at"))
        updated_at = _parse_datetime(row.get("updated_at"))
        if created_at:
            created_dates[question_id] = created_at.date()
            _add_activity(stats, created_at)
            if created_at.date() == today:
                stats["today_new_questions"] += 1
                if question_id in tikz_question_ids:
                    created_today_tikz.add(question_id)
        if updated_at and (not created_at or updated_at.replace(microsecond=0) > created_at.replace(microsecond=0)):
            if not created_at or updated_at.date() != created_at.date():
                _add_activity(stats, updated_at)

    for revision in revision_rows:
        question_id = str(revision.get("question_id") or "")
        created_at = _parse_datetime(revision.get("created_at"))
        if not created_at:
            continue
        _add_activity(stats, created_at)
        if created_at.date() == today:
            revision_today_question_ids.add(question_id)
            if question_id in tikz_question_ids and created_dates.get(question_id) != today:
                modified_today_tikz.add(question_id)

    if revision_today_question_ids:
        stats["today_mod_questions"] = sum(
            1
            for question_id in revision_today_question_ids
            if created_dates.get(question_id) != today
        )
    else:
        stats["today_mod_questions"] = sum(
            1
            for row in rows
            if (
                (updated_at := _parse_datetime(row.get("updated_at")))
                and updated_at.date() == today
                and created_dates.get(str(row.get("question_id") or "")) != today
            )
        )

    stats["total_tikz"] = len(tikz_question_ids)
    stats["today_new_tikz"] = len(created_today_tikz)
    stats["today_mod_tikz"] = len(modified_today_tikz)
    return stats


def _csv_rows_for_statistics() -> list[dict[str, Any]]:
    from utils.csv_ops import read_csv_index

    return [row for row in read_csv_index() if not _is_wk_csv_row(row)]


def get_statistics_from_csv() -> dict[str, Any]:
    from utils.local_stats import sync_question_activity

    stats = empty_statistics()
    stats.update(
        {
            "source": "csv",
            "source_label": "CSV 索引缓存",
            "source_detail": "SQLite 不可用时读取 utils/题库索引表.csv",
            "sqlite_primary": False,
            "fallback_used": True,
        }
    )
    csv_data = _csv_rows_for_statistics()
    stats["total_questions"] = len(csv_data)
    stats.update(sync_question_activity(csv_data))

    for row in csv_data:
        if row.get("包含TikZ绘图") == "是":
            stats["total_tikz"] += 1

        subject = row.get("知识板块", "").split("，")[0] if row.get("知识板块") else "未分类"
        stats["subject_counts"][subject] = stats["subject_counts"].get(subject, 0) + 1

        question_type = row.get("题型", "未知") or "未知"
        stats["type_counts"][question_type] = stats["type_counts"].get(question_type, 0) + 1

        diff_value = _numeric_difficulty(row.get("难度星级", ""))
        if diff_value is not None:
            stats["total_difficulty"] += diff_value
            stats["difficulty_count"] += 1
            label = _difficulty_label(diff_value)
            stats["difficulty_dist"][label] = stats["difficulty_dist"].get(label, 0) + 1

        for tag in _json_list(row.get("标签", "")):
            stats["tag_counts"][tag] = stats["tag_counts"].get(tag, 0) + 1

    return stats


def get_statistics_from_legacy_tex(chapters_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    stats = empty_statistics()
    stats.update(
        {
            "source": "legacy_tex",
            "source_label": "旧 TeX 扫描兜底",
            "source_detail": "SQLite 和 CSV 均不可用时扫描 chapters 目录",
            "sqlite_primary": False,
            "fallback_used": True,
        }
    )
    root_dir = os.fspath(chapters_dir or CHAPTERS_DIR)
    today_start = _datetime.datetime.combine(_datetime.date.today(), _datetime.time.min).timestamp()
    if not os.path.exists(root_dir):
        return stats

    for root, _, files in os.walk(root_dir):
        is_tikz_dir = "相关图" in root
        for file_name in files:
            if not file_name.endswith(".tex"):
                continue
            if file_name.startswith("content_"):
                continue
            file_path = os.path.join(root, file_name)
            relative_path = os.path.relpath(file_path, root_dir)
            if _is_wk_tex_path(relative_path):
                continue
            try:
                stat_info = os.stat(file_path)
            except OSError:
                continue

            created_at = _datetime.datetime.fromtimestamp(stat_info.st_ctime)
            updated_at = _datetime.datetime.fromtimestamp(stat_info.st_mtime)
            _add_activity(stats, created_at)
            if updated_at.date() != created_at.date():
                _add_activity(stats, updated_at)

            is_today_created = stat_info.st_ctime >= today_start
            is_today_modified = stat_info.st_mtime >= today_start and not is_today_created
            if is_tikz_dir or " 图" in file_name:
                stats["total_tikz"] += 1
                if is_today_created:
                    stats["today_new_tikz"] += 1
                elif is_today_modified:
                    stats["today_mod_tikz"] += 1
            else:
                stats["total_questions"] += 1
                if is_today_created:
                    stats["today_new_questions"] += 1
                elif is_today_modified:
                    stats["today_mod_questions"] += 1
    return stats


def get_statistics_sqlite_first(db_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Return dashboard statistics with SQLite -> CSV -> legacy TeX fallback."""
    target_db = Path(resolve_database_path(db_path or DEFAULT_DATABASE_PATH))
    sqlite_error = ""
    if target_db.exists() and target_db.stat().st_size > 0:
        try:
            return get_statistics_from_sqlite(str(target_db))
        except Exception as exc:
            sqlite_error = str(exc)

    try:
        stats = get_statistics_from_csv()
        if sqlite_error:
            stats["fallback_error"] = f"SQLite 统计失败，已回退 CSV：{sqlite_error}"
        return stats
    except Exception as csv_exc:
        stats = get_statistics_from_legacy_tex()
        if sqlite_error:
            stats["fallback_error"] = f"SQLite 统计失败：{sqlite_error}；CSV 统计失败：{csv_exc}"
        else:
            stats["fallback_error"] = f"CSV 统计失败，已回退旧 TeX 扫描：{csv_exc}"
        return stats
