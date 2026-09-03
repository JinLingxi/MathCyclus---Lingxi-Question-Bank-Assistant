"""SQLite schema migration helpers.

Migrations are intentionally explicit and conservative:

- inspection is read-only;
- apply requires the caller to opt in;
- a SQLite backup is created before the first write by default;
- migration SQL files must be named ``0001_name.sql``.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from services.database_service import BASE_DIR, DEFAULT_DATABASE_PATH, configure_connection, resolve_database_path


PROJECT_ROOT = Path(BASE_DIR)
DEFAULT_MIGRATIONS_DIR = PROJECT_ROOT / "db" / "migrations"
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{4})_(?P<name>.+)\.sql$")


@dataclass(frozen=True)
class MigrationFile:
    version: int
    name: str
    path: Path
    checksum: str

    @property
    def filename(self) -> str:
        return self.path.name


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def ensure_inside_project(path: Path) -> None:
    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"路径不在项目目录内：{path}") from exc


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def list_migration_files(migrations_dir: str | os.PathLike[str] | None = None) -> list[MigrationFile]:
    directory = Path(migrations_dir or DEFAULT_MIGRATIONS_DIR)
    if not directory.is_absolute():
        directory = PROJECT_ROOT / directory
    directory = directory.resolve()
    ensure_inside_project(directory)
    if not directory.exists():
        return []

    migrations: list[MigrationFile] = []
    seen_versions: dict[int, str] = {}
    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_PATTERN.match(path.name)
        if not match:
            continue
        version = int(match.group("version"))
        name = match.group("name")
        if version in seen_versions:
            raise ValueError(f"迁移版本重复：{version:04d} ({seen_versions[version]} / {path.name})")
        seen_versions[version] = path.name
        migrations.append(MigrationFile(version=version, name=name, path=path, checksum=file_sha256(path)))
    return sorted(migrations, key=lambda item: item.version)


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        is not None
    )


def read_app_meta(conn: sqlite3.Connection) -> dict[str, str]:
    if not table_exists(conn, "app_meta"):
        return {}
    rows = conn.execute("SELECT key, value FROM app_meta ORDER BY key").fetchall()
    return {str(row["key"]): str(row["value"]) for row in rows}


def read_applied_migrations(conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    if not table_exists(conn, "schema_migration"):
        return {}
    rows = conn.execute(
        """
        SELECT version, name, checksum, applied_at
        FROM schema_migration
        ORDER BY version
        """
    ).fetchall()
    return {
        int(row["version"]): {
            "version": int(row["version"]),
            "name": str(row["name"]),
            "checksum": str(row["checksum"] or ""),
            "applied_at": str(row["applied_at"] or ""),
        }
        for row in rows
    }


def migration_status(
    db_path: str | os.PathLike[str] | None = None,
    migrations_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    database = Path(resolve_database_path(db_path or DEFAULT_DATABASE_PATH))
    migrations = list_migration_files(migrations_dir)
    if not database.exists():
        return {
            "status": "missing_database",
            "database": relative_to_root(database),
            "current_version": 0,
            "target_version": migrations[-1].version if migrations else 0,
            "pending_count": len(migrations),
            "applied_count": 0,
            "checksum_mismatches": [],
            "pending": [migration_to_dict(item) for item in migrations],
            "applied": [],
        }

    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    try:
        app_meta = read_app_meta(conn)
        applied = read_applied_migrations(conn)
    finally:
        conn.close()

    checksum_mismatches = []
    pending = []
    for migration in migrations:
        applied_item = applied.get(migration.version)
        if not applied_item:
            pending.append(migration)
            continue
        if applied_item.get("checksum") and applied_item["checksum"] != migration.checksum:
            checksum_mismatches.append(
                {
                    "version": migration.version,
                    "name": migration.name,
                    "expected": migration.checksum,
                    "actual": applied_item["checksum"],
                }
            )

    current_version = 0
    raw_version = app_meta.get("schema_version") or ""
    if raw_version.isdigit():
        current_version = int(raw_version)
    elif applied:
        current_version = max(applied)

    status = "blocked" if checksum_mismatches else "pending" if pending else "ok"
    return {
        "status": status,
        "database": relative_to_root(database),
        "current_version": current_version,
        "target_version": migrations[-1].version if migrations else current_version,
        "pending_count": len(pending),
        "applied_count": len(applied),
        "checksum_mismatches": checksum_mismatches,
        "pending": [migration_to_dict(item) for item in pending],
        "applied": list(applied.values()),
        "app_meta": app_meta,
    }


def migration_to_dict(migration: MigrationFile) -> dict[str, Any]:
    return {
        "version": migration.version,
        "name": migration.name,
        "filename": migration.filename,
        "path": relative_to_root(migration.path),
        "checksum": migration.checksum,
    }


def ensure_meta_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migration (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL DEFAULT '',
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def next_backup_path(database: Path, stamp: str, backup_dir: str | os.PathLike[str] | None = None) -> Path:
    target_backup_dir = Path(backup_dir or DEFAULT_BACKUP_DIR)
    if not target_backup_dir.is_absolute():
        target_backup_dir = PROJECT_ROOT / target_backup_dir
    target_backup_dir = target_backup_dir.resolve()
    ensure_inside_project(target_backup_dir)
    target_backup_dir.mkdir(parents=True, exist_ok=True)
    candidate = target_backup_dir / f"{database.stem}_schema_migration_{stamp}.sqlite3"
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = target_backup_dir / f"{database.stem}_schema_migration_{stamp}_{index}.sqlite3"
        if not candidate.exists():
            return candidate
        index += 1


def backup_database(database: Path, stamp: str, backup_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    backup_path = next_backup_path(database, stamp, backup_dir)
    ensure_inside_project(backup_path)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(database)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return {
        "path": relative_to_root(backup_path),
        "sha256": file_sha256(backup_path),
        "size": backup_path.stat().st_size,
    }


def apply_one_migration(conn: sqlite3.Connection, migration: MigrationFile) -> None:
    sql = migration.path.read_text(encoding="utf-8")
    conn.executescript(sql)
    ensure_meta_tables(conn)
    conn.execute(
        """
        INSERT INTO schema_migration(version, name, checksum, applied_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(version) DO UPDATE SET
            name = excluded.name,
            checksum = excluded.checksum,
            applied_at = excluded.applied_at
        """,
        (migration.version, migration.name, migration.checksum),
    )
    conn.execute(
        """
        INSERT INTO app_meta(key, value, updated_at)
        VALUES ('schema_version', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (str(migration.version),),
    )


def apply_pending_migrations(
    db_path: str | os.PathLike[str] | None = None,
    migrations_dir: str | os.PathLike[str] | None = None,
    *,
    apply: bool = False,
    backup: bool = True,
    backup_dir: str | os.PathLike[str] | None = None,
    stamp: str | None = None,
) -> dict[str, Any]:
    database = Path(resolve_database_path(db_path or DEFAULT_DATABASE_PATH))
    ensure_inside_project(database)
    migrations = list_migration_files(migrations_dir)
    before = migration_status(database, migrations_dir)
    if before["status"] == "missing_database":
        return {
            "status": "missing_database",
            "dry_run": not apply,
            "database": relative_to_root(database),
            "before": before,
            "after": before,
            "backup": {},
            "applied": [],
            "writes_database": False,
            "deletes_files": False,
        }
    if before["checksum_mismatches"]:
        return {
            "status": "blocked",
            "dry_run": not apply,
            "database": relative_to_root(database),
            "before": before,
            "after": before,
            "backup": {},
            "applied": [],
            "writes_database": False,
            "deletes_files": False,
            "blockers": ["已应用迁移的 checksum 与当前文件不一致，拒绝继续。"],
        }

    pending_versions = {int(item["version"]) for item in before["pending"]}
    pending = [migration for migration in migrations if migration.version in pending_versions]
    if not apply:
        return {
            "status": "pending" if pending else "ok",
            "dry_run": True,
            "database": relative_to_root(database),
            "before": before,
            "after": before,
            "backup": {},
            "applied": [],
            "writes_database": False,
            "deletes_files": False,
        }

    backup_info = (
        backup_database(database, stamp or datetime.now().strftime("%Y%m%d_%H%M%S"), backup_dir)
        if backup and pending
        else {}
    )
    applied: list[dict[str, Any]] = []
    conn = configure_connection(sqlite3.connect(database, timeout=20))
    try:
        with conn:
            ensure_meta_tables(conn)
            for migration in pending:
                apply_one_migration(conn, migration)
                applied.append(migration_to_dict(migration))
    finally:
        conn.close()

    after = migration_status(database, migrations_dir)
    return {
        "status": "ok" if after["status"] == "ok" else after["status"],
        "dry_run": False,
        "database": relative_to_root(database),
        "before": before,
        "after": after,
        "backup": backup_info,
        "applied": applied,
        "writes_database": bool(applied),
        "deletes_files": False,
    }


def copy_database_for_dry_run(source_db: Path, target_db: Path) -> None:
    ensure_inside_project(source_db)
    ensure_inside_project(target_db)
    target_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_db, target_db)
