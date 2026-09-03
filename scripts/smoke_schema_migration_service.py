from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.schema_migration_service import apply_pending_migrations, migration_status


def table_exists(db_path: Path, table_name: str) -> bool:
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None


def meta_value(db_path: Path, key: str) -> str:
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else ""


def migration_checksum(db_path: Path, version: int) -> str:
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute("SELECT checksum FROM schema_migration WHERE version = ?", (version,)).fetchone()
        return str(row[0]) if row else ""


def main() -> int:
    smoke_parent = PROJECT_ROOT / "data" / "backups"
    smoke_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mathcyclus_schema_migration_", dir=smoke_parent) as temp_dir:
        root = Path(temp_dir)
        db_path = root / "data" / "legacy.sqlite3"
        migrations_dir = root / "db" / "migrations"
        backup_dir = root / "backups"
        migrations_dir.mkdir(parents=True)
        db_path.parent.mkdir(parents=True)
        shutil.copy2(
            PROJECT_ROOT / "db" / "migrations" / "0001_schema_version_baseline.sql",
            migrations_dir / "0001_schema_version_baseline.sql",
        )

        with closing(sqlite3.connect(db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE question (
                    question_id TEXT PRIMARY KEY,
                    stem_tex TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute("INSERT INTO question(question_id, stem_tex) VALUES ('QLEGACY', '保留旧数据')")
            conn.commit()

        before = migration_status(db_path, migrations_dir)
        assert before["status"] == "pending", before
        assert before["pending_count"] == 1, before
        assert not table_exists(db_path, "app_meta")

        dry_run = apply_pending_migrations(db_path, migrations_dir, apply=False)
        assert dry_run["status"] == "pending", dry_run
        assert dry_run["writes_database"] is False, dry_run
        assert not table_exists(db_path, "app_meta")

        applied = apply_pending_migrations(db_path, migrations_dir, apply=True, backup_dir=backup_dir, stamp="smoke")
        assert applied["status"] == "ok", applied
        assert applied["writes_database"] is True, applied
        assert applied["applied"][0]["version"] == 1, applied
        assert applied["backup"]["path"].endswith("_smoke.sqlite3"), applied
        assert table_exists(db_path, "app_meta")
        assert table_exists(db_path, "schema_migration")
        assert meta_value(db_path, "schema_version") == "1"
        assert migration_checksum(db_path, 1)

        with closing(sqlite3.connect(db_path)) as conn:
            row = conn.execute("SELECT stem_tex FROM question WHERE question_id = 'QLEGACY'").fetchone()
            assert row and row[0] == "保留旧数据"

        second = apply_pending_migrations(db_path, migrations_dir, apply=True, backup_dir=backup_dir, stamp="smoke2")
        assert second["status"] == "ok", second
        assert second["writes_database"] is False, second
        assert second["applied"] == [], second

    print("smoke_schema_migration_service: status=ok")
    print("writes_project_database=false")
    print("deletes_files=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
