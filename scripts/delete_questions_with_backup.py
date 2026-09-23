from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
BACKUP_ROOT = PROJECT_ROOT / ".backups" / "deleted_questions"
REPORTS_DIR = PROJECT_ROOT / "reports"

RELATION_TABLES = [
    ("paper_question", "question_id"),
    ("question_knowledge_area", "question_id"),
    ("question_equivalence", "question_id_a"),
    ("question_equivalence", "question_id_b"),
    ("book_exercise_question", "question_id"),
    ("topic_question", "question_id"),
    ("question_asset", "question_id"),
    ("question_revision", "question_id"),
    ("legacy_question_map", "question_id"),
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def resolve_db_path(path: str | Path) -> Path:
    db_path = Path(path)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return db_path.resolve()


def connect_database(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def fetch_question(conn: sqlite3.Connection, question_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            q.question_id,
            q.legacy_id,
            q.legacy_file_path,
            q.stem_tex,
            q.answer_tex,
            q.solution_tex,
            l.legacy_file_path AS mapped_legacy_file_path,
            l.detected_chapter,
            l.detected_year,
            l.detected_source,
            l.detected_question_number
        FROM question q
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        WHERE q.question_id = ?
        """,
        (question_id,),
    ).fetchone()
    return dict(row) if row else None


def relation_counts(conn: sqlite3.Connection, question_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table, column in RELATION_TABLES:
        if not table_exists(conn, table):
            continue
        counts[f"{table}.{column}"] = int(
            conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} = ?",
                (question_id,),
            ).fetchone()[0]
        )
    return counts


def copy_sqlite_database(source_db: Path, backup_db: Path) -> None:
    backup_db.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(source_db)
    backup_conn = sqlite3.connect(backup_db)
    try:
        source_conn.backup(backup_conn)
    finally:
        backup_conn.close()
        source_conn.close()


def resolve_legacy_file(question: dict[str, Any]) -> Path | None:
    legacy_path = str(question.get("mapped_legacy_file_path") or question.get("legacy_file_path") or "").strip()
    if not legacy_path:
        return None
    source = Path(legacy_path)
    if not source.is_absolute():
        source = PROJECT_ROOT / source
    source = source.resolve()
    try:
        source.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        raise ValueError(f"旧 TeX 路径不在项目目录内，已拒绝处理：{source}")
    return source


def quarantine_legacy_file(source: Path, quarantine_root: Path) -> dict[str, Any]:
    if not source.exists():
        return {
            "source": relative_to_root(source),
            "status": "missing",
            "quarantine_path": "",
        }
    relative_source = source.relative_to(PROJECT_ROOT.resolve())
    target = (quarantine_root / relative_source).resolve()
    try:
        target.relative_to(quarantine_root.resolve())
    except ValueError:
        raise ValueError(f"隔离目标路径越界，已拒绝处理：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        suffix = datetime.now().strftime("%H%M%S")
        target = target.with_name(f"{target.stem}_{suffix}{target.suffix}")
    shutil.move(str(source), str(target))
    return {
        "source": relative_to_root(source),
        "status": "moved",
        "quarantine_path": relative_to_root(target),
    }


def delete_questions(
    db_path: Path,
    question_ids: list[str],
    *,
    apply: bool,
    stamp: str,
    reason: str,
) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在：{db_path}")

    quarantine_root = (BACKUP_ROOT / stamp).resolve()
    backup_db = quarantine_root / "mathcyclus_before_delete.sqlite3"
    manifest_path = quarantine_root / "manifest.json"
    report_path = REPORTS_DIR / f"delete_questions_{stamp}.md"

    with connect_database(db_path) as conn:
        before_total = int(conn.execute("SELECT COUNT(*) FROM question").fetchone()[0])
        questions = []
        missing_ids = []
        for question_id in question_ids:
            question = fetch_question(conn, question_id)
            if question is None:
                missing_ids.append(question_id)
                continue
            question["relation_counts"] = relation_counts(conn, question_id)
            questions.append(question)

    legacy_actions: list[dict[str, Any]] = []
    if apply:
        copy_sqlite_database(db_path, backup_db)
        for question in questions:
            source = resolve_legacy_file(question)
            if source is None:
                legacy_actions.append(
                    {
                        "question_id": question["question_id"],
                        "source": "",
                        "status": "no_legacy_path",
                        "quarantine_path": "",
                    }
                )
            else:
                action = quarantine_legacy_file(source, quarantine_root)
                action["question_id"] = question["question_id"]
                legacy_actions.append(action)

        with connect_database(db_path) as conn:
            deleted = 0
            for question in questions:
                cursor = conn.execute(
                    "DELETE FROM question WHERE question_id = ?",
                    (question["question_id"],),
                )
                deleted += cursor.rowcount
            after_total = int(conn.execute("SELECT COUNT(*) FROM question").fetchone()[0])
            integrity_check = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_key_errors = [dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
            conn.commit()
    else:
        deleted = 0
        after_total = before_total
        integrity_check = "not_run_in_dry_run"
        foreign_key_errors = []
        for question in questions:
            source = resolve_legacy_file(question)
            legacy_actions.append(
                {
                    "question_id": question["question_id"],
                    "source": relative_to_root(source) if source else "",
                    "status": "would_move" if source and source.exists() else "missing_or_no_legacy_path",
                    "quarantine_path": "",
                }
            )

    manifest = {
        "stamp": stamp,
        "mode": "apply" if apply else "dry_run",
        "database": relative_to_root(db_path),
        "database_backup": relative_to_root(backup_db) if apply else "",
        "reason": reason,
        "requested_question_ids": question_ids,
        "missing_ids": missing_ids,
        "before_total": before_total,
        "after_total": after_total,
        "deleted_count": deleted,
        "integrity_check": integrity_check,
        "foreign_key_errors": foreign_key_errors,
        "questions": questions,
        "legacy_file_actions": legacy_actions,
    }

    if apply:
        quarantine_root.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    write_report(report_path, manifest)
    manifest["report"] = relative_to_root(report_path)
    if apply:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def write_report(path: Path, manifest: dict[str, Any]) -> None:
    question_lines = []
    for question in manifest["questions"]:
        question_lines.append(
            f"| `{question['question_id']}` | `{question.get('legacy_id') or ''}` | "
            f"`{question.get('legacy_file_path') or question.get('mapped_legacy_file_path') or ''}` | "
            f"{sum(int(value) for value in question.get('relation_counts', {}).values())} |"
        )
    legacy_lines = []
    for action in manifest["legacy_file_actions"]:
        legacy_lines.append(
            f"| `{action.get('question_id') or ''}` | {action.get('status') or ''} | "
            f"`{action.get('source') or ''}` | `{action.get('quarantine_path') or ''}` |"
        )
    path.write_text(
        f"""# 题目删除报告

> 模式：{manifest['mode']}  
> 数据库：`{manifest['database']}`  
> 数据库备份：`{manifest['database_backup'] or 'dry-run 未生成'}`  
> 原因：{manifest['reason']}

## 摘要

| 项目 | 数量 |
| --- | ---: |
| 删除前题目数 | {manifest['before_total']} |
| 删除后题目数 | {manifest['after_total']} |
| 实际删除题目数 | {manifest['deleted_count']} |
| 请求但不存在 ID | {len(manifest['missing_ids'])} |

## 待删题目

| question_id | legacy_id | legacy_file_path | 关联行计数合计 |
| --- | --- | --- | ---: |
{chr(10).join(question_lines) or '| 无 |  |  | 0 |'}

## 旧 TeX 文件处理

| question_id | 状态 | 原路径 | 隔离路径 |
| --- | --- | --- | --- |
{chr(10).join(legacy_lines) or '| 无 |  |  |  |'}

## 完整性

- `PRAGMA integrity_check`：`{manifest['integrity_check']}`
- 外键错误数：{len(manifest['foreign_key_errors'])}
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="备份 SQLite 并删除指定 question_id，同时隔离对应旧 TeX 文件。")
    parser.add_argument("question_ids", nargs="+", help="要删除的 question_id。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    parser.add_argument("--apply", action="store_true", help="真正删除；默认只生成 dry-run 报告。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
    parser.add_argument("--reason", default="manual_duplicate_cleanup", help="删除原因，写入报告。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = resolve_db_path(args.db)
    manifest = delete_questions(
        db_path,
        [str(question_id).strip() for question_id in args.question_ids if str(question_id).strip()],
        apply=bool(args.apply),
        stamp=args.stamp,
        reason=args.reason,
    )
    print(f"mode={manifest['mode']}")
    print(f"deleted_count={manifest['deleted_count']}")
    print(f"before_total={manifest['before_total']}")
    print(f"after_total={manifest['after_total']}")
    print(f"report={manifest['report']}")
    if manifest.get("database_backup"):
        print(f"database_backup={manifest['database_backup']}")


if __name__ == "__main__":
    main()
