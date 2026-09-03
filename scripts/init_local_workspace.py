"""Initialize local runtime folders and an empty SQLite database.

This is the bootstrap script for a fresh checkout.  It prepares the files that
should exist on a user's own machine, while keeping personal data out of Git.

The script is safe by default:

- creates missing runtime directories;
- creates an empty database only when it does not already exist;
- never deletes, resets, or overwrites existing user data.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

LOCAL_DIRECTORIES = [
    "data",
    "data/backups",
    "data/indexes",
    "assets",
    "assets/questions",
    "exports",
    "reports",
]

GITKEEP_DIRECTORIES = [
    "data",
    "data/backups",
    "data/indexes",
    "assets",
    "assets/questions",
    "exports",
    "reports",
]

GITIGNORE_PROBES = [
    ("formal_database", "data/mathcyclus.sqlite3"),
    ("local_preferences", "data/local_preferences.json"),
    ("database_backup", "data/backups/example.sqlite3"),
    ("runtime_index", "data/indexes/example.sqlite3"),
    ("question_asset", "assets/questions/Q000001/example.png"),
    ("report", "reports/example.md"),
    ("export", "exports/example.tex"),
    ("csv_cache", "utils/题库索引表.csv"),
]


def relative_to_root(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_project_path(project_root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def ensure_inside_project(project_root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError(f"路径不在项目目录内：{path}") from exc


def create_directories(project_root: Path, *, dry_run: bool) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for relative in LOCAL_DIRECTORIES:
        target = resolve_project_path(project_root, relative)
        ensure_inside_project(project_root, target)
        existed = target.exists()
        if not dry_run:
            target.mkdir(parents=True, exist_ok=True)
        actions.append(
            {
                "path": relative,
                "existed": existed,
                "created": not existed and not dry_run,
                "would_create": not existed and dry_run,
            }
        )
    return actions


def create_gitkeeps(project_root: Path, *, dry_run: bool) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for relative_dir in GITKEEP_DIRECTORIES:
        target = resolve_project_path(project_root, relative_dir) / ".gitkeep"
        ensure_inside_project(project_root, target)
        existed = target.exists()
        if not dry_run and not existed:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
        actions.append(
            {
                "path": relative_to_root(target, project_root),
                "existed": existed,
                "created": not existed and not dry_run,
                "would_create": not existed and dry_run,
            }
        )
    return actions


def database_table_names(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [str(row[0]) for row in rows]


def initialize_database(
    project_root: Path,
    *,
    db_path: Path,
    schema_path: Path,
    dry_run: bool,
    skip_db: bool,
) -> dict[str, Any]:
    ensure_inside_project(project_root, db_path)
    ensure_inside_project(project_root, schema_path)

    if skip_db:
        return {
            "path": relative_to_root(db_path, project_root),
            "status": "skipped",
            "created": False,
            "would_create": False,
            "table_count": 0,
        }

    if not schema_path.exists():
        raise FileNotFoundError(f"缺少 SQLite schema：{schema_path}")

    if db_path.exists() and db_path.stat().st_size > 0:
        tables = database_table_names(db_path)
        return {
            "path": relative_to_root(db_path, project_root),
            "status": "exists",
            "created": False,
            "would_create": False,
            "table_count": len(tables),
            "tables": tables,
        }

    if dry_run:
        return {
            "path": relative_to_root(db_path, project_root),
            "status": "missing",
            "created": False,
            "would_create": True,
            "table_count": 0,
        }

    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = schema_path.read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(schema_sql)
        conn.commit()

    tables = database_table_names(db_path)
    return {
        "path": relative_to_root(db_path, project_root),
        "status": "created",
        "created": True,
        "would_create": False,
        "table_count": len(tables),
        "tables": tables,
    }


def git_check_ignore(project_root: Path, relative_path: str) -> bool | None:
    try:
        completed = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", relative_path],
            cwd=project_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    return None


def check_gitignore(project_root: Path) -> dict[str, Any]:
    probes = []
    unavailable = False
    for label, relative_path in GITIGNORE_PROBES:
        ignored = git_check_ignore(project_root, relative_path)
        if ignored is None:
            unavailable = True
        probes.append({"label": label, "path": relative_path, "ignored": ignored})
    uncovered = [item for item in probes if item["ignored"] is False]
    return {
        "available": not unavailable,
        "ok": not uncovered,
        "uncovered": uncovered,
        "probes": probes,
    }


def ensure_local_workspace(
    *,
    project_root: str | Path = PROJECT_ROOT,
    db_path: str | Path = "data/mathcyclus.sqlite3",
    schema_path: str | Path = "db/schema.sql",
    dry_run: bool = False,
    skip_db: bool = False,
    check_ignore: bool = True,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    database = resolve_project_path(root, db_path)
    schema = resolve_project_path(root, schema_path)
    directory_actions = create_directories(root, dry_run=dry_run)
    gitkeep_actions = create_gitkeeps(root, dry_run=dry_run)
    database_action = initialize_database(
        root,
        db_path=database,
        schema_path=schema,
        dry_run=dry_run,
        skip_db=skip_db,
    )
    ignore_result = check_gitignore(root) if check_ignore else {"available": False, "ok": True, "uncovered": [], "probes": []}
    status = "warning" if not ignore_result["ok"] else "ok"
    return {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_root": str(root),
        "status": status,
        "dry_run": dry_run,
        "directories": directory_actions,
        "gitkeeps": gitkeep_actions,
        "database": database_action,
        "gitignore": ignore_result,
        "writes_legacy_tex": False,
        "overwrites_existing_database": False,
        "deletes_files": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="初始化本地运行目录和空 SQLite 数据库。")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT), help="项目根目录，默认当前仓库根目录。")
    parser.add_argument("--db", default="data/mathcyclus.sqlite3", help="SQLite 数据库路径。")
    parser.add_argument("--schema", default="db/schema.sql", help="SQLite schema 路径。")
    parser.add_argument("--dry-run", action="store_true", help="只显示将执行的动作，不写文件。")
    parser.add_argument("--skip-db", action="store_true", help="只创建目录，不初始化数据库。")
    parser.add_argument("--skip-gitignore-check", action="store_true", help="跳过 Git 忽略规则探针。")
    parser.add_argument("--strict-gitignore", action="store_true", help="若敏感路径未被忽略则返回失败。")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = ensure_local_workspace(
        project_root=args.project_root,
        db_path=args.db,
        schema_path=args.schema,
        dry_run=args.dry_run,
        skip_db=args.skip_db,
        check_ignore=not args.skip_gitignore_check,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        created_dirs = sum(1 for item in report["directories"] if item["created"] or item["would_create"])
        created_gitkeeps = sum(1 for item in report["gitkeeps"] if item["created"] or item["would_create"])
        print(f"status={report['status']}")
        print(f"dry_run={report['dry_run']}")
        print(f"directory_actions={created_dirs}")
        print(f"gitkeep_actions={created_gitkeeps}")
        print(f"database_status={report['database']['status']}")
        print(f"database={report['database']['path']}")
        print(f"database_tables={report['database'].get('table_count', 0)}")
        print(f"gitignore_ok={report['gitignore']['ok']}")
        if report["gitignore"]["uncovered"]:
            print("uncovered=" + ",".join(item["path"] for item in report["gitignore"]["uncovered"]))

    if args.strict_gitignore and not report["gitignore"]["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
