from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_import_drafts_20260902_initial.sqlite3"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.import_service import (
    compact_json,
    list_ready_draft_ids,
)
from services.revision_service import changed_fields


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def full_question_from_draft(question_id: str, draft: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question_type_id": draft.get("question_type_id"),
        "stem_tex": draft.get("stem_tex") or "",
        "choices_json": draft.get("choices_json") or "[]",
        "answer_tex": draft.get("answer_tex") or "",
        "solution_tex": draft.get("solution_tex") or "",
        "difficulty": draft.get("difficulty"),
        "tags_json": draft.get("tags_json") or "[]",
        "note": draft.get("note") or "",
        "official_flag": draft.get("official_flag") or 0,
        "canonical_tex": draft.get("normalized_tex") or "",
        "raw_source_tex": draft.get("raw_source_text") or "",
        "normalized_status": status,
        "legacy_id": "",
        "legacy_file_path": "",
        "usage_count": 0,
    }


def get_draft_question_from_conn(conn: sqlite3.Connection, draft_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT *
        FROM question_import_draft
        WHERE draft_id = ?
        """,
        (draft_id,),
    ).fetchone()
    if not row:
        return {}
    assets = conn.execute(
        """
        SELECT *
        FROM question_import_draft_asset
        WHERE draft_id = ?
        ORDER BY role, sort_order, draft_asset_id
        """,
        (draft_id,),
    ).fetchall()
    result = dict(row)
    result["assets"] = [dict(asset) for asset in assets]
    return result


def stable_id(prefix: str, *values: object, length: int = 14) -> str:
    import hashlib

    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def next_question_id_from_conn(conn: sqlite3.Connection) -> str:
    max_number = 0
    rows = conn.execute("SELECT question_id FROM question WHERE question_id LIKE 'Q%'").fetchall()
    for row in rows:
        value = str(row[0])
        if value.startswith("Q") and value[1:].isdigit():
            max_number = max(max_number, int(value[1:]))
    return f"Q{max_number + 1:06d}"


def question_snapshot_from_conn(conn: sqlite3.Connection, question_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM question WHERE question_id = ?", (question_id,)).fetchone()
    return dict(row) if row else {}


def insert_question_revision_from_conn(
    conn: sqlite3.Connection,
    question_id: str,
    change_source: str,
    before: dict[str, Any],
    after: dict[str, Any],
    note: str,
) -> str:
    revision_id = stable_id("REV", question_id, change_source, compact_json(before), compact_json(after), note)
    conn.execute(
        """
        INSERT OR REPLACE INTO question_revision(
            revision_id, question_id, change_source, changed_fields_json,
            before_json, after_json, operator, note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            revision_id,
            question_id,
            change_source,
            compact_json(changed_fields(before, after)),
            compact_json(before),
            compact_json(after),
            "",
            note,
        ),
    )
    return revision_id


def update_draft_review_status_from_conn(
    conn: sqlite3.Connection,
    draft_id: str,
    review_status: str,
    review_reason: str,
) -> None:
    conn.execute(
        """
        UPDATE question_import_draft
        SET review_status = ?, review_reason = ?, updated_at = CURRENT_TIMESTAMP
        WHERE draft_id = ?
        """,
        (review_status, review_reason, draft_id),
    )


def insert_report_item_from_conn(
    conn: sqlite3.Connection,
    batch_id: str,
    index: int,
    source_file: str,
    question_id: str | None,
    status: str,
    reason: str,
    detail: str,
) -> str:
    item_id = stable_id("IRI", batch_id, index, source_file, status, reason)
    safe_question_id = question_id
    if safe_question_id:
        exists = conn.execute(
            "SELECT 1 FROM question WHERE question_id = ?",
            (safe_question_id,),
        ).fetchone()
        if not exists:
            safe_question_id = None
    conn.execute(
        """
        INSERT OR REPLACE INTO import_report_item(
            item_id, batch_id, source_file, question_id, status, reason, detail
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (item_id, batch_id, source_file, safe_question_id, status, reason, detail),
    )
    return item_id


def finish_import_batch_from_conn(conn: sqlite3.Connection, batch_id: str, summary: str) -> None:
    conn.execute(
        """
        UPDATE import_batch
        SET finished_at = ?, summary = CASE WHEN ? != '' THEN ? ELSE summary END
        WHERE batch_id = ?
        """,
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            summary,
            summary,
            batch_id,
        ),
    )


def insert_question_from_draft(conn: sqlite3.Connection, question: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO question(
            question_id, question_type_id, stem_tex, choices_json, answer_tex,
            solution_tex, difficulty, tags_json, note, official_flag,
            canonical_tex, raw_source_tex, normalized_status, legacy_id,
            legacy_file_path, usage_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            question["question_id"],
            question["question_type_id"],
            question["stem_tex"],
            question["choices_json"],
            question["answer_tex"],
            question["solution_tex"],
            question["difficulty"],
            question["tags_json"],
            question["note"],
            question["official_flag"],
            question["canonical_tex"],
            question["raw_source_tex"],
            question["normalized_status"],
            question["legacy_id"],
            question["legacy_file_path"],
            question["usage_count"],
        ),
    )
    conn.execute(
        "INSERT INTO question_analysis(question_id) VALUES (?)",
        (question["question_id"],),
    )


def update_question_from_draft(conn: sqlite3.Connection, question_id: str, draft: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM question WHERE question_id = ?", (question_id,)).fetchone()
    if not row:
        raise KeyError(f"target question not found: {question_id}")
    before = dict(row)
    after = dict(before)
    after.update(
        {
            "question_type_id": draft.get("question_type_id"),
            "stem_tex": draft.get("stem_tex") or "",
            "choices_json": draft.get("choices_json") or "[]",
            "answer_tex": draft.get("answer_tex") or "",
            "solution_tex": draft.get("solution_tex") or "",
            "difficulty": draft.get("difficulty"),
            "tags_json": draft.get("tags_json") or "[]",
            "note": draft.get("note") or "",
            "official_flag": draft.get("official_flag") or 0,
            "canonical_tex": draft.get("normalized_tex") or before.get("canonical_tex") or "",
            "raw_source_tex": draft.get("raw_source_text") or before.get("raw_source_tex") or "",
            "normalized_status": "normalized",
        }
    )
    conn.execute(
        """
        UPDATE question
        SET
            question_type_id = ?,
            stem_tex = ?,
            choices_json = ?,
            answer_tex = ?,
            solution_tex = ?,
            difficulty = ?,
            tags_json = ?,
            note = ?,
            official_flag = ?,
            canonical_tex = ?,
            raw_source_tex = ?,
            normalized_status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE question_id = ?
        """,
        (
            after["question_type_id"],
            after["stem_tex"],
            after["choices_json"],
            after["answer_tex"],
            after["solution_tex"],
            after["difficulty"],
            after["tags_json"],
            after["note"],
            after["official_flag"],
            after["canonical_tex"],
            after["raw_source_tex"],
            after["normalized_status"],
            question_id,
        ),
    )
    return {"before": before, "after": after}


def copy_draft_assets_to_question_assets(
    conn: sqlite3.Connection,
    draft: dict[str, Any],
    question_id: str,
) -> int:
    inserted = 0
    for index, asset in enumerate(draft.get("assets") or [], start=1):
        file_path = asset.get("planned_file_path") or asset.get("source_path") or ""
        if not file_path:
            continue
        asset_id = f"AID{question_id}_{index:03d}"
        conn.execute(
            """
            INSERT OR REPLACE INTO question_asset(
                asset_id, question_id, role, file_path, original_file_name,
                mime_type, file_hash, caption, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                question_id,
                asset.get("role") or "problem",
                file_path,
                asset.get("original_file_name") or Path(file_path).name,
                asset.get("mime_type") or "",
                asset.get("file_hash") or "",
                asset.get("caption") or "",
                asset.get("sort_order") or index,
            ),
        )
        inserted += 1
    return inserted


def commit_draft(conn: sqlite3.Connection, draft_id: str, index: int) -> dict[str, Any]:
    draft = get_draft_question_from_conn(conn, draft_id)
    if not draft:
        return {
            "draft_id": draft_id,
            "status": "error",
            "question_id": "",
            "revision_id": "",
            "asset_count": 0,
            "message": "草稿不存在",
        }

    if draft.get("review_status") not in {"ready", "approved"}:
        return {
            "draft_id": draft_id,
            "status": "skipped",
            "question_id": "",
            "revision_id": "",
            "asset_count": 0,
            "message": f"草稿状态不是 ready/approved：{draft.get('review_status')}",
        }

    proposed_action = draft.get("proposed_action") or "insert"
    if proposed_action == "skip":
        update_draft_review_status_from_conn(conn, draft_id, "rejected", "commit dry-run skip")
        return {
            "draft_id": draft_id,
            "status": "skipped",
            "question_id": "",
            "revision_id": "",
            "asset_count": 0,
            "message": "草稿建议跳过",
        }

    if proposed_action == "update":
        question_id = draft.get("target_question_id") or ""
        if not question_id:
            return {
                "draft_id": draft_id,
                "status": "error",
                "question_id": "",
                "revision_id": "",
                "asset_count": 0,
                "message": "update 草稿缺少 target_question_id",
            }
        snapshots = update_question_from_draft(conn, question_id, draft)
        asset_count = copy_draft_assets_to_question_assets(conn, draft, question_id)
        revision_id = insert_question_revision_from_conn(
            conn,
            question_id,
            "ai_ocr_draft_dry_run",
            snapshots["before"],
            snapshots["after"],
            note=f"draft_id={draft_id}",
        )
        update_draft_review_status_from_conn(conn, draft_id, "approved", "commit dry-run applied as update")
        return {
            "draft_id": draft_id,
            "status": "updated",
            "question_id": question_id,
            "revision_id": revision_id,
            "asset_count": asset_count,
            "message": "已在副本中模拟更新题目",
        }

    if proposed_action != "insert":
        return {
            "draft_id": draft_id,
            "status": "error",
            "question_id": "",
            "revision_id": "",
            "asset_count": 0,
            "message": f"不支持 proposed_action：{proposed_action}",
        }

    question_id = next_question_id_from_conn(conn)
    question = full_question_from_draft(question_id, draft, status="draft_committed")
    insert_question_from_draft(conn, question)
    asset_count = copy_draft_assets_to_question_assets(conn, draft, question_id)
    after = question_snapshot_from_conn(conn, question_id)
    revision_id = insert_question_revision_from_conn(
        conn,
        question_id,
        "ai_ocr_draft_dry_run",
        {},
        after,
        note=f"draft_id={draft_id}",
    )
    update_draft_review_status_from_conn(conn, draft_id, "approved", "commit dry-run applied as insert")
    return {
        "draft_id": draft_id,
        "status": "inserted",
        "question_id": question_id,
        "revision_id": revision_id,
        "asset_count": asset_count,
        "message": "已在副本中模拟新增题目",
    }


def database_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        "question",
        "question_asset",
        "question_revision",
        "question_import_draft",
        "import_report_item",
    ]
    return {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in tables
    }


def write_report(
    source_db: Path,
    output_db: Path,
    report_path: Path,
    results: list[dict[str, Any]],
    before_counts: dict[str, int],
    after_counts: dict[str, int],
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_counts = Counter(row["status"] for row in results)
    status_lines = "\n".join(
        f"| `{status}` | {count} |"
        for status, count in sorted(status_counts.items())
    ) or "| 无 | 0 |"
    count_lines = "\n".join(
        f"| `{table}` | {before_counts.get(table, 0)} | {after_counts.get(table, 0)} | {after_counts.get(table, 0) - before_counts.get(table, 0)} |"
        for table in before_counts
    )
    item_lines = "\n".join(
        f"- `{row['draft_id']}` -> `{row['question_id'] or '-'}` / `{row['status']}`：{row['message']}"
        for row in results[:50]
    ) or "无"

    report_path.write_text(
        f"""# 草稿确认入库 Dry-run 报告

> 生成时间：{now}  
> 来源数据库：`{relative_to_root(source_db)}`  
> 输出数据库：`{relative_to_root(output_db)}`  
> 执行方式：复制草稿预览库后，仅模拟提交 `ready/approved` 草稿。

## 总览

| 指标 | 数量 |
| --- | ---: |
| 处理草稿数 | {len(results)} |
| 写入/更新题目数 | {sum(1 for row in results if row['status'] in {'inserted', 'updated'})} |
| 写入图片资产数 | {sum(int(row['asset_count']) for row in results)} |

## 状态分布

| status | 数量 |
| --- | ---: |
{status_lines}

## 表计数变化

| 表 | 执行前 | 执行后 | 变化 |
| --- | ---: | ---: | ---: |
{count_lines}

## 处理明细

{item_lines}

## 安全边界

- 本脚本只写数据库副本。
- 只有 `ready` 或 `approved` 草稿会被模拟提交。
- 每个插入或更新都会写入 `question_revision`。
- 图片只从草稿资产转成 `question_asset` 记录，不复制真实文件。
- 正式提交前仍需要数据库备份、重复题检查、图片存在性检查和前端 LaTeX 预览。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把 ready/approved 草稿模拟提交到数据库副本。")
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB), help="来源草稿预览库。")
    parser.add_argument("--batch-id", default="", help="只提交某个导入批次。")
    parser.add_argument("--draft-id", action="append", default=[], help="只提交指定草稿，可重复传入。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="输出时间戳。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_db = Path(args.source_db)
    if not source_db.is_absolute():
        source_db = PROJECT_ROOT / source_db
    source_db = source_db.resolve()
    if not source_db.exists():
        raise SystemExit(f"来源数据库不存在：{source_db}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_db = DATA_DIR / f"mathcyclus_preview_draft_commit_{args.stamp}.sqlite3"
    report_path = REPORTS_DIR / f"commit_import_drafts_dry_run_{args.stamp}.md"

    if output_db.exists():
        output_db.unlink()
    shutil.copy2(source_db, output_db)

    draft_ids = args.draft_id or list_ready_draft_ids(str(output_db), args.batch_id or "")

    conn = sqlite3.connect(output_db)
    conn.row_factory = sqlite3.Row
    try:
        before_counts = database_counts(conn)
        results: list[dict[str, Any]] = []
        batch_ids: set[str] = set()
        with conn:
            for index, draft_id in enumerate(draft_ids, start=1):
                result = commit_draft(conn, draft_id, index)
                results.append(result)
                draft = get_draft_question_from_conn(conn, draft_id)
                if draft.get("batch_id"):
                    batch_ids.add(str(draft["batch_id"]))
                if not draft:
                    continue
                insert_report_item_from_conn(
                    conn,
                    draft.get("batch_id", ""),
                    index,
                    draft_id,
                    result["question_id"] or None,
                    result["status"],
                    result["message"],
                    compact_json(result),
                )
        with conn:
            for batch_id in batch_ids:
                finish_import_batch_from_conn(conn, batch_id, "commit dry-run completed")
        after_counts = database_counts(conn)
    finally:
        conn.close()

    write_report(source_db, output_db, report_path, results, before_counts, after_counts)

    print(f"drafts={len(results)}")
    print(f"inserted={sum(1 for row in results if row['status'] == 'inserted')}")
    print(f"updated={sum(1 for row in results if row['status'] == 'updated')}")
    print(f"database={relative_to_root(output_db)}")
    print(f"report={relative_to_root(report_path)}")


if __name__ == "__main__":
    main()
