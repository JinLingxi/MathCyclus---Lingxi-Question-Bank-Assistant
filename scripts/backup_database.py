from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
REPORTS_DIR = PROJECT_ROOT / "reports"


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def next_backup_path(source_db: Path, stamp: str) -> Path:
    stem = source_db.stem
    candidate = BACKUP_DIR / f"{stem}_{stamp}.sqlite3"
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = BACKUP_DIR / f"{stem}_{stamp}_{index}.sqlite3"
        if not candidate.exists():
            return candidate
        index += 1


def integrity_check(db_path: Path) -> str:
    conn = sqlite3.connect(db_path)
    try:
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        conn.close()


def backup_database(source_db: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(source_db)
    target = sqlite3.connect(output_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def write_report(source_db: Path, output_path: Path, report_path: Path, dry_run: bool) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_hash = file_hash(source_db)
    output_hash = file_hash(output_path) if output_path.exists() else ""
    data = {
        "created_at": now,
        "source_db": relative_to_root(source_db),
        "backup_db": relative_to_root(output_path),
        "dry_run": dry_run,
        "source_size_bytes": source_db.stat().st_size,
        "backup_size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        "source_sha256": source_hash,
        "backup_sha256": output_hash,
        "source_integrity_check": integrity_check(source_db),
        "backup_integrity_check": integrity_check(output_path) if output_path.exists() else "not_created",
        "hash_match": source_hash == output_hash if output_path.exists() else False,
    }
    report_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="备份 SQLite 数据库并生成校验报告。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="要备份的 SQLite 数据库。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="备份时间戳。")
    parser.add_argument("--dry-run", action="store_true", help="只计算目标路径和源库校验，不创建备份。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_db = Path(args.db)
    if not source_db.is_absolute():
        source_db = PROJECT_ROOT / source_db
    source_db = source_db.resolve()
    if not source_db.exists():
        raise SystemExit(f"数据库不存在：{source_db}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = next_backup_path(source_db, args.stamp)
    report_path = REPORTS_DIR / f"database_backup_{args.stamp}.json"

    if not args.dry_run:
        backup_database(source_db, output_path)
    write_report(source_db, output_path, report_path, args.dry_run)

    print(f"source={relative_to_root(source_db)}")
    print(f"backup={relative_to_root(output_path)}")
    print(f"report={relative_to_root(report_path)}")
    print(f"dry_run={args.dry_run}")
    if output_path.exists():
        print(f"integrity={integrity_check(output_path)}")


if __name__ == "__main__":
    main()
