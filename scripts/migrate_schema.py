from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.schema_migration_service import apply_pending_migrations, migration_status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查或应用本地 SQLite schema 迁移。默认只 dry-run。")
    parser.add_argument("--db", default="data/mathcyclus.sqlite3", help="目标 SQLite 数据库。")
    parser.add_argument("--migrations-dir", default="db/migrations", help="迁移 SQL 目录。")
    parser.add_argument("--apply", action="store_true", help="实际应用待执行迁移；不加则只检查。")
    parser.add_argument("--no-backup", action="store_true", help="应用迁移前不备份数据库。不推荐。")
    parser.add_argument("--backup-dir", default="data/backups", help="迁移前备份目录。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="备份时间戳。")
    parser.add_argument("--status-only", action="store_true", help="只读取状态，不返回 apply 计划。")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON。")
    return parser.parse_args()


def print_status(report: dict) -> None:
    print(f"status={report.get('status')}")
    print(f"database={report.get('database')}")
    print(f"current_version={report.get('current_version')}")
    print(f"target_version={report.get('target_version')}")
    print(f"pending_count={report.get('pending_count')}")
    print(f"applied_count={report.get('applied_count')}")
    if report.get("checksum_mismatches"):
        print(f"checksum_mismatches={len(report['checksum_mismatches'])}")


def print_apply(report: dict) -> None:
    before = report.get("before") or {}
    after = report.get("after") or {}
    print(f"status={report.get('status')}")
    print(f"dry_run={report.get('dry_run')}")
    print(f"database={report.get('database')}")
    print(f"before_version={before.get('current_version')}")
    print(f"after_version={after.get('current_version')}")
    print(f"target_version={after.get('target_version', before.get('target_version'))}")
    print(f"pending_before={before.get('pending_count')}")
    print(f"pending_after={after.get('pending_count')}")
    print(f"applied_count={len(report.get('applied') or [])}")
    print(f"writes_database={report.get('writes_database')}")
    if report.get("backup"):
        print(f"backup={report['backup'].get('path')}")
    if report.get("blockers"):
        print("blockers=" + "；".join(report["blockers"]))


def main() -> int:
    args = parse_args()
    if args.status_only:
        report = migration_status(args.db, args.migrations_dir)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print_status(report)
        return 1 if report.get("status") == "blocked" else 0

    report = apply_pending_migrations(
        args.db,
        args.migrations_dir,
        apply=args.apply,
        backup=not args.no_backup,
        backup_dir=args.backup_dir,
        stamp=args.stamp,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_apply(report)
    return 1 if report.get("status") in {"blocked", "missing_database"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
