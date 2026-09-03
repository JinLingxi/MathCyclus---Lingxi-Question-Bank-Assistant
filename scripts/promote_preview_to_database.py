from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_combined_20260902_initial.sqlite3"
DEFAULT_TARGET_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
REPORTS_DIR = PROJECT_ROOT / "reports"
CONFIRM_TEXT = "PROMOTE_SQLITE_PREVIEW"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.diff_preview_databases import TABLES as DIFF_TABLES
from scripts.precommit_database_audit import audit_database


ID_COLUMNS = {
    "question": "question_id",
    "question_analysis": "question_id",
    "question_asset": "asset_id",
    "question_revision": "revision_id",
    "import_batch": "batch_id",
    "import_report_item": "item_id",
    "question_import_draft": "draft_id",
    "question_import_draft_asset": "draft_asset_id",
    "paper": "paper_id",
    "paper_question": "paper_question_id",
    "book": "book_id",
    "book_section": "section_id",
    "book_exercise_question": "book_exercise_question_id",
    "topic_module": "module_id",
    "topic": "topic_id",
    "topic_question": "topic_question_id",
}


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def resolve_project_path(path: str | Path) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    return target.resolve()


def ensure_inside_project(path: Path) -> None:
    try:
        path.resolve().relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"路径必须位于项目目录内：{path}") from exc


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_integrity(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        conn.close()


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def table_count(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def id_set(conn: sqlite3.Connection, table: str, column: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    rows = conn.execute(f"SELECT {column} FROM {table}").fetchall()
    return {str(row[0]) for row in rows}


def count_snapshot(db_path: Path | None) -> dict[str, int]:
    if not db_path or not db_path.exists():
        return {table: 0 for table in DIFF_TABLES}
    conn = sqlite3.connect(db_path)
    try:
        return {table: table_count(conn, table) for table in DIFF_TABLES}
    finally:
        conn.close()


def diff_against_target(source_db: Path, target_db: Path, sample_limit: int) -> dict[str, Any]:
    before_counts = count_snapshot(target_db if target_db.exists() else None)
    after_counts = count_snapshot(source_db)
    count_diff = [
        {
            "table": table,
            "before": before_counts.get(table, 0),
            "after": after_counts.get(table, 0),
            "delta": after_counts.get(table, 0) - before_counts.get(table, 0),
        }
        for table in DIFF_TABLES
    ]

    inserted_ids: dict[str, list[str]] = {}
    deleted_ids: dict[str, list[str]] = {}
    source = sqlite3.connect(source_db)
    target = sqlite3.connect(target_db) if target_db.exists() else None
    try:
        for table, id_column in ID_COLUMNS.items():
            source_ids = id_set(source, table, id_column)
            target_ids = id_set(target, table, id_column) if target else set()
            inserted_ids[table] = sorted(source_ids - target_ids)[:sample_limit]
            deleted_ids[table] = sorted(target_ids - source_ids)[:sample_limit]
    finally:
        source.close()
        if target:
            target.close()

    return {
        "target_exists": target_db.exists(),
        "count_diff": count_diff,
        "inserted_id_samples": inserted_ids,
        "deleted_id_samples": deleted_ids,
        "inserted_total_sampled": sum(len(ids) for ids in inserted_ids.values()),
        "deleted_total_sampled": sum(len(ids) for ids in deleted_ids.values()),
    }


def next_backup_path(target_db: Path, stamp: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    candidate = BACKUP_DIR / f"{target_db.stem}_{stamp}.sqlite3"
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = BACKUP_DIR / f"{target_db.stem}_{stamp}_{index}.sqlite3"
        if not candidate.exists():
            return candidate
        index += 1


def backup_database(source_db: Path, backup_db: Path) -> None:
    backup_db.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(source_db)
    target = sqlite3.connect(backup_db)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def copy_sqlite_atomically(source_db: Path, target_db: Path, stamp: str) -> Path:
    target_db.parent.mkdir(parents=True, exist_ok=True)
    temp_db = target_db.with_name(f".{target_db.stem}.{stamp}.tmp.sqlite3")
    if temp_db.exists():
        temp_db.unlink()
    source = sqlite3.connect(source_db)
    target = sqlite3.connect(temp_db)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    if sqlite_integrity(temp_db) != "ok":
        temp_db.unlink(missing_ok=True)
        raise RuntimeError(f"临时数据库完整性检查失败：{temp_db}")
    os.replace(temp_db, target_db)
    return target_db


def apply_policy(audit: dict[str, Any], allow_warnings: bool) -> dict[str, Any]:
    blockers = list(audit.get("blockers") or [])
    warnings = list(audit.get("warnings") or [])
    apply_blockers = list(blockers)
    if warnings and not allow_warnings:
        apply_blockers.append("存在 warning，正式写入需要加 --allow-warnings 并人工确认")
    return {
        "can_apply": not apply_blockers,
        "apply_blockers": apply_blockers,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "audit_status": audit.get("status", ""),
    }


def markdown_count_diff(diff: dict[str, Any]) -> str:
    return "\n".join(
        f"| `{row['table']}` | {row['before']} | {row['after']} | {row['delta']} |"
        for row in diff["count_diff"]
    )


def markdown_id_samples(title: str, samples: dict[str, list[str]]) -> str:
    lines = []
    for table, ids in samples.items():
        if ids:
            lines.append(f"- `{table}`：{', '.join(f'`{row_id}`' for row_id in ids[:20])}")
    return "\n".join(lines) or f"{title}：无"


def write_report(report: dict[str, Any], md_path: Path, json_path: Path) -> None:
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    action = report["action"]
    policy = report["policy"]
    backup = report["backup"]
    diff = report["diff"]
    source = report["source"]
    target = report["target"]
    md_path.write_text(
        f"""# 正式 SQLite 提交流程报告

> 生成时间：{report['created_at']}  
> 来源预览库：`{source['path']}`  
> 目标正式库：`{target['path']}`  
> 执行模式：`{action}`  
> 写入确认文本：`{CONFIRM_TEXT}`  

## 结论

- 可写入：`{policy['can_apply']}`
- 审计状态：`{policy['audit_status']}`
- 阻断项：`{policy['blocker_count']}`
- 警告项：`{policy['warning_count']}`
- 实际写入：`{target['written']}`

## 备份

- 目标库原本存在：`{target['existed_before']}`
- 备份库：`{backup['path'] or '无'}`
- 备份完整性：`{backup['integrity_check']}`
- 备份 SHA256：`{backup['sha256'] or '无'}`

## 差异预览

| 表 | 当前正式库 | 来源预览库 | 写入后变化 |
| --- | ---: | ---: | ---: |
{markdown_count_diff(diff)}

## 新增 ID 样例

{markdown_id_samples('新增 ID 样例', diff['inserted_id_samples'])}

## 删除 ID 样例

{markdown_id_samples('删除 ID 样例', diff['deleted_id_samples'])}

## 写入策略

- 默认 dry-run 只生成报告，不写入 `data/mathcyclus.sqlite3`。
- 正式写入必须同时提供 `--apply` 和 `--confirm {CONFIRM_TEXT}`。
- 存在 audit blocker 时禁止写入。
- 存在 warning 时默认禁止写入，除非加 `--allow-warnings`。
- 如果目标正式库已存在，写入前必须先备份到 `data/backups/`。
- 写入采用临时 SQLite 副本校验后原子替换，降低半写入风险。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把预览 SQLite 安全提升为正式 SQLite；默认只 dry-run。")
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB), help="来源预览 SQLite。")
    parser.add_argument("--target-db", default=str(DEFAULT_TARGET_DB), help="目标正式 SQLite。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告与备份时间戳。")
    parser.add_argument("--apply", action="store_true", help="实际写入目标正式库；默认不写。")
    parser.add_argument("--confirm", default="", help=f"实际写入必须填写 {CONFIRM_TEXT}。")
    parser.add_argument("--allow-warnings", action="store_true", help="允许带 warning 写入；仍不允许 blocker。")
    parser.add_argument("--sample-limit", type=int, default=50, help="差异报告中每张表最多展示多少个 ID。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_db = resolve_project_path(args.source_db)
    target_db = resolve_project_path(args.target_db)
    ensure_inside_project(source_db)
    ensure_inside_project(target_db)
    if not source_db.exists():
        raise SystemExit(f"来源预览库不存在：{source_db}")
    if source_db == target_db:
        raise SystemExit("来源库和目标库不能是同一个文件")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    source_audit = audit_database(source_db)
    policy = apply_policy(source_audit, allow_warnings=args.allow_warnings)
    diff = diff_against_target(source_db, target_db, sample_limit=max(1, min(args.sample_limit, 500)))

    target_existed_before = target_db.exists()
    backup_path = next_backup_path(target_db, args.stamp) if target_existed_before else None
    backup_info = {
        "path": relative_to_root(backup_path) if backup_path else "",
        "sha256": "",
        "integrity_check": "not_needed",
    }

    target_written = False
    if args.apply:
        if args.confirm != CONFIRM_TEXT:
            raise SystemExit(f"正式写入被拒绝：必须提供 --confirm {CONFIRM_TEXT}")
        if not policy["can_apply"]:
            raise SystemExit("正式写入被拒绝：" + "；".join(policy["apply_blockers"]))
        if target_existed_before and backup_path:
            backup_database(target_db, backup_path)
            backup_info["sha256"] = file_hash(backup_path)
            backup_info["integrity_check"] = sqlite_integrity(backup_path)
        copy_sqlite_atomically(source_db, target_db, args.stamp)
        target_written = True

    report = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": "apply" if args.apply else "dry_run",
        "source": {
            "path": relative_to_root(source_db),
            "sha256": file_hash(source_db),
            "integrity_check": sqlite_integrity(source_db),
        },
        "target": {
            "path": relative_to_root(target_db),
            "existed_before": target_existed_before,
            "written": target_written,
            "sha256_after": file_hash(target_db) if target_db.exists() else "",
            "integrity_check_after": sqlite_integrity(target_db) if target_db.exists() else "not_created",
        },
        "backup": backup_info,
        "policy": policy,
        "audit": source_audit,
        "diff": diff,
    }

    md_path = REPORTS_DIR / f"promote_preview_to_database_{args.stamp}.md"
    json_path = REPORTS_DIR / f"promote_preview_to_database_{args.stamp}.json"
    write_report(report, md_path, json_path)

    print(f"action={report['action']}")
    print(f"can_apply={policy['can_apply']}")
    print(f"written={target_written}")
    print(f"target_exists={target_db.exists()}")
    print(f"blockers={policy['blocker_count']}")
    print(f"warnings={policy['warning_count']}")
    print(f"report={relative_to_root(md_path)}")
    print(f"json={relative_to_root(json_path)}")


if __name__ == "__main__":
    main()
