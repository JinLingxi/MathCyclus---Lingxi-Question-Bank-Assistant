from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BEFORE_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_import_drafts_20260902_initial.sqlite3"
DEFAULT_AFTER_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_draft_commit_20260902_initial.sqlite3"
REPORTS_DIR = PROJECT_ROOT / "reports"


TABLES = [
    "question",
    "question_analysis",
    "question_asset",
    "question_revision",
    "import_batch",
    "import_report_item",
    "question_import_draft",
    "question_import_draft_asset",
    "paper",
    "paper_question",
    "book",
    "book_section",
    "book_exercise_question",
    "topic_module",
    "topic",
    "topic_question",
]


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone() is not None


def table_count(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def id_set(conn: sqlite3.Connection, table: str, id_column: str) -> set[str]:
    if not table_exists(conn, table):
        return set()
    rows = conn.execute(f"SELECT {id_column} FROM {table}").fetchall()
    return {str(row[0]) for row in rows}


def fetch_rows_by_ids(conn: sqlite3.Connection, table: str, id_column: str, ids: list[str], limit: int = 30) -> list[dict]:
    if not ids or not table_exists(conn, table):
        return []
    rows = []
    for row_id in ids[:limit]:
        row = conn.execute(f"SELECT * FROM {table} WHERE {id_column} = ?", (row_id,)).fetchone()
        if row:
            rows.append(dict(row))
    return rows


def diff_database(before_db: Path, after_db: Path) -> dict[str, object]:
    before = sqlite3.connect(before_db)
    after = sqlite3.connect(after_db)
    before.row_factory = sqlite3.Row
    after.row_factory = sqlite3.Row
    try:
        count_diff = []
        for table in TABLES:
            before_count = table_count(before, table)
            after_count = table_count(after, table)
            count_diff.append(
                {
                    "table": table,
                    "before": before_count,
                    "after": after_count,
                    "delta": after_count - before_count,
                }
            )

        id_columns = {
            "question": "question_id",
            "question_asset": "asset_id",
            "question_revision": "revision_id",
            "import_report_item": "item_id",
            "book": "book_id",
            "book_section": "section_id",
            "book_exercise_question": "book_exercise_question_id",
            "topic_module": "module_id",
            "topic": "topic_id",
            "topic_question": "topic_question_id",
        }
        inserted = {}
        deleted = {}
        samples = {}
        for table, id_column in id_columns.items():
            before_ids = id_set(before, table, id_column)
            after_ids = id_set(after, table, id_column)
            inserted_ids = sorted(after_ids - before_ids)
            deleted_ids = sorted(before_ids - after_ids)
            inserted[table] = inserted_ids
            deleted[table] = deleted_ids
            samples[table] = fetch_rows_by_ids(after, table, id_column, inserted_ids)
    finally:
        before.close()
        after.close()

    return {
        "before_db": relative_to_root(before_db),
        "after_db": relative_to_root(after_db),
        "count_diff": count_diff,
        "inserted_ids": inserted,
        "deleted_ids": deleted,
        "inserted_samples": samples,
    }


def write_markdown(diff: dict[str, object], output_path: Path) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    count_lines = "\n".join(
        f"| `{row['table']}` | {row['before']} | {row['after']} | {row['delta']} |"
        for row in diff["count_diff"]
    )
    inserted_lines = []
    for table, ids in diff["inserted_ids"].items():
        if ids:
            inserted_lines.append(f"- `{table}`：{', '.join(f'`{row_id}`' for row_id in ids[:20])}")
    deleted_lines = []
    for table, ids in diff["deleted_ids"].items():
        if ids:
            deleted_lines.append(f"- `{table}`：{', '.join(f'`{row_id}`' for row_id in ids[:20])}")

    output_path.write_text(
        f"""# 预览数据库差异报告

> 生成时间：{now}  
> 变更前：`{diff['before_db']}`  
> 变更后：`{diff['after_db']}`  
> 用途：确认 dry-run 提交前后到底新增、删除了哪些记录。

## 表计数变化

| 表 | 变更前 | 变更后 | 差值 |
| --- | ---: | ---: | ---: |
{count_lines}

## 新增 ID

{chr(10).join(inserted_lines) or '无'}

## 删除 ID

{chr(10).join(deleted_lines) or '无'}

## 判断

- dry-run 提交正常情况下不应删除任何正式题目。
- 新增题、资产、修订、报告项都应能在这里看到。
- 如果正式提交前出现异常删除，应停止并回滚。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="比较两个 SQLite 预览库的关键表差异。")
    parser.add_argument("--before-db", default=str(DEFAULT_BEFORE_DB), help="变更前数据库。")
    parser.add_argument("--after-db", default=str(DEFAULT_AFTER_DB), help="变更后数据库。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    before_db = Path(args.before_db)
    after_db = Path(args.after_db)
    if not before_db.is_absolute():
        before_db = PROJECT_ROOT / before_db
    if not after_db.is_absolute():
        after_db = PROJECT_ROOT / after_db
    before_db = before_db.resolve()
    after_db = after_db.resolve()
    if not before_db.exists():
        raise SystemExit(f"变更前数据库不存在：{before_db}")
    if not after_db.exists():
        raise SystemExit(f"变更后数据库不存在：{after_db}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    diff = diff_database(before_db, after_db)
    json_path = REPORTS_DIR / f"database_diff_{args.stamp}.json"
    md_path = REPORTS_DIR / f"database_diff_{args.stamp}.md"
    json_path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(diff, md_path)

    changed_tables = [row for row in diff["count_diff"] if row["delta"]]
    deleted_total = sum(len(ids) for ids in diff["deleted_ids"].values())
    print(f"changed_tables={len(changed_tables)}")
    print(f"deleted_ids={deleted_total}")
    print(f"report={relative_to_root(md_path)}")
    print(f"json={relative_to_root(json_path)}")


if __name__ == "__main__":
    main()
