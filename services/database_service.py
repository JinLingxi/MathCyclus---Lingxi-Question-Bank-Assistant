"""SQLite helpers for the planned structured question-bank database."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


BASE_DIR = str(Path(__file__).resolve().parents[1])
DEFAULT_DATABASE_PATH = os.path.join(BASE_DIR, "data", "mathcyclus.sqlite3")
SCHEMA_PATH = os.path.join(BASE_DIR, "db", "schema.sql")


def resolve_database_path(path: str | os.PathLike[str] | None = None) -> str:
    """Return an absolute SQLite path for the structured question-bank database."""
    target = os.fspath(path) if path else DEFAULT_DATABASE_PATH
    if not os.path.isabs(target):
        target = os.path.join(BASE_DIR, target)
    return os.path.abspath(target)


def connect_database(path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with project defaults."""
    db_path = resolve_database_path(path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=20)
    return configure_connection(conn)


def configure_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Apply project defaults to a SQLite connection."""
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def connect_existing_database(
    path: str | os.PathLike[str] | None = None,
    *,
    readonly: bool = False,
) -> sqlite3.Connection:
    """Open an existing database without creating an empty file."""
    db_path = resolve_database_path(path)
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"SQLite 数据库不存在：{db_path}")

    if readonly:
        uri = Path(db_path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=20)
        conn.execute("PRAGMA query_only = ON")
    else:
        conn = sqlite3.connect(db_path, timeout=20)
    return configure_connection(conn)


@contextmanager
def database_connection(path: str | os.PathLike[str] | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager that commits on success and rolls back on failure."""
    conn = connect_database(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def existing_database_connection(path: str | os.PathLike[str] | None = None) -> Iterator[sqlite3.Connection]:
    """Writable context manager for an existing database only."""
    conn = connect_existing_database(path, readonly=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def readonly_database_connection(path: str | os.PathLike[str] | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager for read-only queries against an existing SQLite database."""
    conn = connect_existing_database(path, readonly=True)
    try:
        yield conn
    finally:
        conn.close()


def initialize_database(path: str | os.PathLike[str] | None = None, schema_path: str | os.PathLike[str] | None = None) -> str:
    """Create database tables from `db/schema.sql` and return the database path."""
    db_path = resolve_database_path(path)
    schema_file = Path(schema_path or SCHEMA_PATH)
    if not schema_file.is_absolute():
        schema_file = Path(BASE_DIR) / schema_file
    schema_sql = schema_file.read_text(encoding="utf-8")
    with database_connection(db_path) as conn:
        conn.executescript(schema_sql)
    return db_path


def row_to_dict(row: sqlite3.Row | None) -> dict:
    return dict(row) if row is not None else {}
