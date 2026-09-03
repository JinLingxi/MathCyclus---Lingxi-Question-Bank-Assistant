"""Smoke tests for local workspace bootstrap and migration bundle tools."""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.init_local_workspace import ensure_local_workspace
from scripts.local_data_bundle import export_bundle, inspect_bundle, restore_bundle


def table_count(db_path: Path, table: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mathcyclus_local_tools_") as temp_dir:
        source_root = Path(temp_dir) / "source"
        target_root = Path(temp_dir) / "target"
        (source_root / "db").mkdir(parents=True)
        (target_root / "db").mkdir(parents=True)
        shutil.copy2(PROJECT_ROOT / "db" / "schema.sql", source_root / "db" / "schema.sql")
        shutil.copy2(PROJECT_ROOT / "db" / "schema.sql", target_root / "db" / "schema.sql")

        init_report = ensure_local_workspace(
            project_root=source_root,
            dry_run=False,
            check_ignore=False,
        )
        source_db = source_root / "data" / "mathcyclus.sqlite3"
        assert init_report["database"]["status"] == "created", init_report
        assert source_db.exists()
        assert table_count(source_db, "question_type") == 5

        asset_dir = source_root / "assets" / "questions" / "Q000001"
        asset_dir.mkdir(parents=True, exist_ok=True)
        (asset_dir / "problem_01.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (source_root / "utils").mkdir(parents=True, exist_ok=True)
        (source_root / "utils" / "题库索引表.csv").write_text("题目ID,文件名称\n", encoding="utf-8-sig")

        bundle_path = source_root / "data" / "backups" / "smoke_bundle.zip"
        export_report = export_bundle(project_root=source_root, output=bundle_path, stamp="smoke")
        assert bundle_path.exists()
        assert export_report["item_count"] >= 3, export_report
        assert export_report["contains_personal_data"] is True
        assert export_report["intended_for_git"] is False

        inspect_report = inspect_bundle(bundle_path)
        assert inspect_report["status"] == "ok", inspect_report
        assert inspect_report["item_count"] == export_report["item_count"]

        restore_dry_run = restore_bundle(project_root=target_root, bundle=bundle_path, apply=False)
        assert restore_dry_run["status"] == "ok", restore_dry_run
        assert restore_dry_run["dry_run"] is True
        assert restore_dry_run["restored_count"] == export_report["item_count"]
        assert not (target_root / "data" / "mathcyclus.sqlite3").exists()

        restore_apply = restore_bundle(project_root=target_root, bundle=bundle_path, apply=True)
        assert restore_apply["status"] == "ok", restore_apply
        assert (target_root / "data" / "mathcyclus.sqlite3").exists()
        assert (target_root / "assets" / "questions" / "Q000001" / "problem_01.png").exists()
        assert (target_root / "utils" / "题库索引表.csv").exists()

        restore_conflict = restore_bundle(project_root=target_root, bundle=bundle_path, apply=False)
        assert restore_conflict["status"] == "blocked", restore_conflict
        assert restore_conflict["conflict_count"] >= 1

    print("status=ok")
    print("init_local_workspace=ok")
    print("local_data_bundle_export=ok")
    print("local_data_bundle_inspect=ok")
    print("local_data_bundle_restore=ok")
    print("writes_project_data=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
