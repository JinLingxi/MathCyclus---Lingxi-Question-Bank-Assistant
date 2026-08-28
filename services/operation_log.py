"""Durable local operation history for question-bank mutations."""

from __future__ import annotations

import datetime
import os
import sqlite3
from contextlib import closing

from utils.core_config import BASE_DIR


OPERATION_LOG_PATH = os.path.join(BASE_DIR, "utils", "operation_log.sqlite3")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(OPERATION_LOG_PATH), exist_ok=True)
    conn = sqlite3.connect(OPERATION_LOG_PATH, timeout=15)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS operation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            path TEXT NOT NULL DEFAULT '',
            related_path TEXT NOT NULL DEFAULT '',
            question_id TEXT NOT NULL DEFAULT '',
            details TEXT NOT NULL DEFAULT ''
        )
        """
    )
    return conn


def record_operation(
    action: str,
    status: str = "success",
    path: str = "",
    related_path: str = "",
    question_id: str = "",
    details: str = "",
) -> bool:
    """Append an operation without allowing logging failures to break a save."""
    try:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with closing(_connect()) as conn:
            conn.execute(
                """
                INSERT INTO operation_events
                    (created_at, action, status, path, related_path, question_id, details)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (now, action, status, path or "", related_path or "", question_id or "", details or ""),
            )
            conn.commit()
        return True
    except (OSError, sqlite3.Error):
        return False


def read_recent_operations(limit: int = 100) -> list[dict]:
    try:
        safe_limit = max(1, min(int(limit), 500))
        with closing(_connect()) as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, action, status, path, related_path, question_id, details
                FROM operation_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        fields = ["id", "created_at", "action", "status", "path", "related_path", "question_id", "details"]
        return [dict(zip(fields, row)) for row in rows]
    except (OSError, sqlite3.Error, ValueError):
        return []

