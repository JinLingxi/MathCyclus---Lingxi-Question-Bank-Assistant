"""Per-installation activity tracking for the local question bank."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sqlite3
from contextlib import closing

from .core_config import BASE_DIR


LOCAL_STATS_PATH = os.path.join(BASE_DIR, "utils", "local_stats.sqlite3")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(LOCAL_STATS_PATH), exist_ok=True)
    conn = sqlite3.connect(LOCAL_STATS_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS question_snapshots (
            relative_path TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            is_tikz INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date TEXT NOT NULL,
            event_hour TEXT NOT NULL,
            event_type TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS local_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    return conn


def _row_fingerprint(row: dict) -> str:
    ignored_fields = {"初次录入的时间", "最后修改时间"}
    payload = {
        key: str(value or "")
        for key, value in row.items()
        if key not in ignored_fields
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _record_event(conn: sqlite3.Connection, event_type: str, relative_path: str, now: datetime.datetime) -> None:
    conn.execute(
        """
        INSERT INTO activity_events(event_date, event_hour, event_type, relative_path, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (now.date().isoformat(), f"{now.hour:02d}", event_type, relative_path, now.timestamp()),
    )


def sync_question_activity(rows: list[dict]) -> dict:
    """Update the local snapshot and return activity aggregates.

    The first run records only a baseline. This prevents a fresh installation
    from presenting the repository's historical timestamps as the new user's
    personal activity.
    """
    now = datetime.datetime.now()
    current = {
        (row.get("相对文件路径", "") or "").replace("/", "\\").strip(): row
        for row in rows
        if (row.get("相对文件路径", "") or "").strip()
    }

    with closing(_connect()) as conn:
        existing = {
            path: (fingerprint, bool(is_tikz))
            for path, fingerprint, is_tikz in conn.execute(
                "SELECT relative_path, fingerprint, is_tikz FROM question_snapshots"
            ).fetchall()
        }
        first_sync = conn.execute(
            "SELECT 1 FROM local_meta WHERE key = 'baseline_initialized'"
        ).fetchone() is None
        for path, row in current.items():
            fingerprint = _row_fingerprint(row)
            is_tikz = (row.get("包含TikZ绘图", "") or "").strip() == "是"
            previous = existing.get(path)
            if not first_sync and previous is None:
                _record_event(conn, "new_question", path, now)
                if is_tikz:
                    _record_event(conn, "new_tikz", path, now)
            elif not first_sync and previous[0] != fingerprint:
                _record_event(conn, "modified_question", path, now)
                if is_tikz:
                    _record_event(conn, "modified_tikz", path, now)
            conn.execute(
                """
                INSERT INTO question_snapshots(relative_path, fingerprint, is_tikz, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(relative_path) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    is_tikz = excluded.is_tikz,
                    updated_at = excluded.updated_at
                """,
                (path, fingerprint, int(is_tikz), now.timestamp()),
            )

        removed_paths = set(existing) - set(current)
        for path in removed_paths:
            conn.execute("DELETE FROM question_snapshots WHERE relative_path = ?", (path,))
        conn.execute(
            "INSERT OR REPLACE INTO local_meta(key, value) VALUES('baseline_initialized', '1')"
        )
        conn.commit()

        today = now.date().isoformat()
        today_counts = {
            event_type: count
            for event_type, count in conn.execute(
                "SELECT event_type, COUNT(*) FROM activity_events WHERE event_date = ? GROUP BY event_type",
                (today,),
            ).fetchall()
        }
        daily_activity = {
            event_date: count
            for event_date, count in conn.execute(
                "SELECT event_date, COUNT(*) FROM activity_events GROUP BY event_date"
            ).fetchall()
        }
        hourly_activity_by_day = {}
        for event_date, event_hour, count in conn.execute(
            """
            SELECT event_date, event_hour, COUNT(*)
            FROM activity_events
            GROUP BY event_date, event_hour
            """
        ).fetchall():
            hourly_activity_by_day.setdefault(
                event_date, {str(hour).zfill(2): 0 for hour in range(24)}
            )[event_hour] = count

    return {
        "today_new_questions": today_counts.get("new_question", 0),
        "today_mod_questions": today_counts.get("modified_question", 0),
        "today_new_tikz": today_counts.get("new_tikz", 0),
        "today_mod_tikz": today_counts.get("modified_tikz", 0),
        "daily_activity": daily_activity,
        "hourly_activity_by_day": hourly_activity_by_day,
    }
