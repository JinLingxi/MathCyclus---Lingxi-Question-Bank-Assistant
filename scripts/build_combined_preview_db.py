from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_paper_mapped_20260902_with_knowledge.sqlite3"
DEFAULT_DECISIONS = PROJECT_ROOT / "db" / "seed" / "equivalence_review_decisions_20260902_initial.csv"
DEFAULT_DRAFT_INPUT = PROJECT_ROOT / "templates" / "ai_ocr_draft_import_example.json"
DEFAULT_DRAFT_REVIEW = PROJECT_ROOT / "db" / "seed" / "import_draft_review_20260902_warning_review.csv"
DEFAULT_TEX_CORRECTIONS = PROJECT_ROOT / "db" / "seed" / "question_tex_corrections_20260902_final_review.csv"
DEFAULT_BOOK_INPUT = PROJECT_ROOT / "templates" / "book_import_example.json"
DEFAULT_TOPIC_INPUT = PROJECT_ROOT / "templates" / "topic_import_example.json"
SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.apply_equivalence_review_dry_run import apply_decision, load_decisions
from scripts.import_book_json_dry_run import import_book, load_payload as load_book_payload
from scripts.import_topic_json_dry_run import import_topics, load_payload as load_topic_payload
from scripts.migrate_assets_dry_run import insert_asset_records, scan_assets
from scripts.commit_import_drafts_dry_run import (
    commit_draft,
    get_draft_question_from_conn,
    insert_report_item_from_conn,
)
from services.import_service import (
    compact_json,
    create_import_batch,
    finish_import_batch,
    insert_draft_question,
    insert_report_item,
    list_ready_draft_ids,
    normalize_draft_question,
    summarize_batch,
)


COUNT_TABLES = [
    "question",
    "paper",
    "paper_question",
    "knowledge_area",
    "question_knowledge_area",
    "question_equivalence",
    "question_asset",
    "question_revision",
    "import_batch",
    "question_import_draft",
    "question_import_draft_asset",
    "import_report_item",
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


def resolve_project_path(path: str | Path) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    return target.resolve()


def ensure_inside_project(path: Path) -> None:
    try:
        path.resolve().relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"输出路径必须位于项目目录内：{path}") from exc


def ensure_schema(db_path: Path) -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript(schema)
    finally:
        conn.close()


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def database_counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            if table_exists(conn, table)
            else 0
            for table in COUNT_TABLES
        }
    finally:
        conn.close()


def load_draft_items(input_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {}, [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("items") or data.get("questions") or []
        if not isinstance(items, list):
            raise ValueError("AI/OCR 草稿 JSON 中的 items/questions 必须是数组")
        return data, [item for item in items if isinstance(item, dict)]
    raise ValueError("AI/OCR 草稿 JSON 顶层必须是对象或数组")


def count_delta(before: dict[str, int], after: dict[str, int], table: str) -> int:
    return after.get(table, 0) - before.get(table, 0)


def apply_equivalence_layer(output_db: Path, decisions_path: Path) -> dict[str, Any]:
    before_counts = database_counts(output_db)
    decisions = load_decisions(decisions_path)

    conn = sqlite3.connect(output_db)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            results = [apply_decision(conn, row) for row in decisions]
    finally:
        conn.close()

    after_counts = database_counts(output_db)
    status_counts = Counter(str(row["status"]) for row in results)
    decision_counts = Counter(str(row["decision"]) for row in results)
    return {
        "enabled": True,
        "decisions_path": relative_to_root(decisions_path),
        "rows": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "equivalence_delta": count_delta(before_counts, after_counts, "question_equivalence"),
        "knowledge_delta": count_delta(before_counts, after_counts, "question_knowledge_area"),
    }


def apply_asset_layer(output_db: Path, copy_files: bool) -> dict[str, Any]:
    before_counts = database_counts(output_db)
    conn = sqlite3.connect(output_db)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            rows = scan_assets(conn)
            insert_asset_records(conn, rows, copy_files=copy_files)
    finally:
        conn.close()

    after_counts = database_counts(output_db)
    matched = [row for row in rows if row["status"] == "matched"]
    unmatched = [row for row in rows if row["status"] != "matched"]
    by_question = Counter(row["question_id"] for row in matched)
    return {
        "enabled": True,
        "copy_files": copy_files,
        "scanned": len(rows),
        "matched": len(matched),
        "unmatched": len(unmatched),
        "question_asset_delta": count_delta(before_counts, after_counts, "question_asset"),
        "covered_questions": len(by_question),
        "sample": [
            {
                "question_id": row["question_id"],
                "source_path": row["source_path"],
                "planned_path": row["planned_path"],
            }
            for row in matched[:10]
        ],
    }


def load_question_tex_corrections(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(file)
        ]


def split_pipe_list(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def remove_includegraphics_reference(text: str, graphics_ref: str) -> tuple[str, int]:
    if not graphics_ref or graphics_ref not in text:
        return text, 0

    lines = text.splitlines(keepends=True)
    output: list[str] = []
    removed = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if "\\begin{wrapfigure}" in line:
            block_start = index
            block = [line]
            index += 1
            while index < len(lines):
                block.append(lines[index])
                if "\\end{wrapfigure}" in lines[index]:
                    index += 1
                    break
                index += 1
            block_text = "".join(block)
            if graphics_ref in block_text:
                removed += block_text.count(graphics_ref)
                continue
            output.extend(block)
            continue

        if graphics_ref in line and "\\includegraphics" in line:
            removed += 1
            index += 1
            continue

        output.append(line)
        index += 1

    updated = "".join(output)
    updated = re.sub(r"\n{3,}", "\n\n", updated).strip() + ("\n" if text.endswith("\n") else "")
    return updated, removed


def apply_question_tex_corrections_layer(output_db: Path, corrections_path: Path) -> dict[str, Any]:
    rows = load_question_tex_corrections(corrections_path)
    if not rows:
        return {"enabled": False, "corrections_path": relative_to_root(corrections_path), "reason": "missing or empty"}

    before_counts = database_counts(output_db)
    results: list[dict[str, object]] = []
    conn = sqlite3.connect(output_db)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            for row in rows:
                correction_id = row.get("correction_id", "")
                action = row.get("action", "")
                question_id = row.get("question_id", "")
                if row.get("review_status") != "approved":
                    results.append(
                        {
                            "correction_id": correction_id,
                            "action": action,
                            "question_id": question_id,
                            "status": "skipped",
                            "changed_fields": 0,
                            "removed_refs": 0,
                            "message": "review_status 不是 approved",
                        }
                    )
                    continue
                question = conn.execute(
                    "SELECT question_id FROM question WHERE question_id = ?",
                    (question_id,),
                ).fetchone()
                if not question:
                    results.append(
                        {
                            "correction_id": correction_id,
                            "action": action,
                            "question_id": question_id,
                            "status": "invalid",
                            "changed_fields": 0,
                            "removed_refs": 0,
                            "message": "question_id 不存在",
                        }
                    )
                    continue
                fields = split_pipe_list(row.get("fields", "")) or ["stem_tex", "answer_tex", "solution_tex", "canonical_tex"]
                unsupported_fields = [
                    field
                    for field in fields
                    if field not in {"stem_tex", "answer_tex", "solution_tex", "canonical_tex", "raw_source_tex"}
                ]
                if unsupported_fields:
                    results.append(
                        {
                            "correction_id": correction_id,
                            "action": action,
                            "question_id": question_id,
                            "status": "invalid",
                            "changed_fields": 0,
                            "removed_refs": 0,
                            "message": "不支持的字段：" + " | ".join(unsupported_fields),
                        }
                    )
                    continue

                changed_fields = 0
                removed_refs = 0
                for field in fields:
                    value_row = conn.execute(f"SELECT {field} FROM question WHERE question_id = ?", (question_id,)).fetchone()
                    original = str(value_row[0] or "")
                    if action == "remove_includegraphics_ref":
                        updated, removed = remove_includegraphics_reference(original, row.get("match_text", ""))
                    elif action == "replace_text":
                        match_text = row.get("match_text", "")
                        replacement_text = row.get("replacement_text", "")
                        if not match_text:
                            updated, removed = original, 0
                        else:
                            removed = original.count(match_text)
                            updated = original.replace(match_text, replacement_text)
                    else:
                        results.append(
                            {
                                "correction_id": correction_id,
                                "action": action,
                                "question_id": question_id,
                                "status": "invalid",
                                "changed_fields": 0,
                                "removed_refs": 0,
                                "message": "action 不支持",
                            }
                        )
                        break
                    if updated != original:
                        conn.execute(
                            f"""
                            UPDATE question
                            SET {field} = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE question_id = ?
                            """,
                            (updated, question_id),
                        )
                        changed_fields += 1
                        removed_refs += removed
                else:
                    results.append(
                        {
                            "correction_id": correction_id,
                            "action": action,
                            "question_id": question_id,
                            "status": "applied" if changed_fields else "noop",
                            "changed_fields": changed_fields,
                            "removed_refs": removed_refs,
                            "message": f"changed_fields={changed_fields}; removed_refs={removed_refs}",
                        }
                    )
    finally:
        conn.close()

    after_counts = database_counts(output_db)
    status_counts = Counter(str(row["status"]) for row in results)
    return {
        "enabled": True,
        "corrections_path": relative_to_root(corrections_path),
        "rows": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "changed_fields": sum(int(row["changed_fields"]) for row in results),
        "removed_refs": sum(int(row["removed_refs"]) for row in results),
        "question_delta": count_delta(before_counts, after_counts, "question"),
    }


def import_draft_layer(output_db: Path, input_path: Path, stamp: str) -> dict[str, Any]:
    metadata, items = load_draft_items(input_path)
    source_path = str(metadata.get("source_path") or relative_to_root(input_path))
    batch_summary_text = str(metadata.get("summary") or f"draft items={len(items)}")
    before_counts = database_counts(output_db)
    batch_id = create_import_batch(
        str(output_db),
        import_type="ai_ocr_json_combined_preview",
        source_path=source_path,
        mode="combined_preview_dry_run",
        stamp=stamp,
        summary=batch_summary_text,
    )

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        draft = normalize_draft_question(item)
        draft_id, validation = insert_draft_question(str(output_db), batch_id, draft, index)
        review_status = "blocked" if validation["errors"] else "needs_review" if validation["warnings"] else draft.review_status
        if draft.review_status == "ready" and not validation["errors"] and not validation["warnings"]:
            review_status = "ready"
        review_reason = "；".join(validation["errors"] or validation["warnings"])
        source_label = draft.source_label or draft.source_item_id or f"item-{index}"
        report_status = "needs_review" if review_status in {"needs_review", "ready"} else "error"
        insert_report_item(
            str(output_db),
            batch_id,
            index,
            source_label,
            draft.target_question_id or None,
            report_status,
            review_reason,
            json.dumps(validation, ensure_ascii=False),
        )
        rows.append(
            {
                "draft_id": draft_id,
                "source_label": source_label,
                "review_status": review_status,
                "review_reason": review_reason,
            }
        )

    finish_import_batch(str(output_db), batch_id, f"combined preview draft import completed; items={len(rows)}")
    batch_summary = summarize_batch(str(output_db), batch_id)
    after_counts = database_counts(output_db)
    return {
        "enabled": True,
        "input_path": relative_to_root(input_path),
        "batch_id": batch_id,
        "items": len(rows),
        "draft_status_counts": batch_summary["draft_status_counts"],
        "draft_asset_count": batch_summary.get("draft_asset_count", 0),
        "question_import_draft_delta": count_delta(before_counts, after_counts, "question_import_draft"),
        "question_import_draft_asset_delta": count_delta(before_counts, after_counts, "question_import_draft_asset"),
        "import_report_item_delta": count_delta(before_counts, after_counts, "import_report_item"),
    }


def load_draft_review_decisions(review_path: Path) -> dict[str, dict[str, str]]:
    if not review_path.exists():
        return {}
    import csv

    decisions: dict[str, dict[str, str]] = {}
    with review_path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            cleaned = {key: (value or "").strip() for key, value in row.items()}
            source_item_id = cleaned.get("source_item_id", "")
            draft_id = cleaned.get("draft_id", "")
            if source_item_id:
                decisions[f"source_item_id:{source_item_id}"] = cleaned
            if draft_id:
                decisions[f"draft_id:{draft_id}"] = cleaned
    return decisions


def reviewed_draft_status(decision: str, current_status: str, has_missing_required_content: bool) -> tuple[str, str]:
    if decision == "keep_as_sample":
        return "sample", "人工审查：样例草稿，不进入正式题表"
    if decision == "reject":
        return "rejected", "人工审查：拒绝导入"
    if decision == "mark_ready":
        if has_missing_required_content:
            return "needs_review", "人工审查请求 ready，但题干/答案/解析仍不完整"
        return "ready", "人工审查：字段完整，可进入提交预演"
    if decision in {"manual_complete_fields", "needs_manual_fix"}:
        return "needs_review", "人工审查：仍需补齐字段"
    return current_status, ""


def apply_draft_review_layer(output_db: Path, review_path: Path) -> dict[str, Any]:
    before_counts = database_counts(output_db)
    decisions = load_draft_review_decisions(review_path)
    if not decisions:
        return {"enabled": False, "review_path": relative_to_root(review_path), "reason": "review csv missing or empty"}

    conn = sqlite3.connect(output_db)
    conn.row_factory = sqlite3.Row
    results: list[dict[str, str]] = []
    try:
        rows = conn.execute(
            """
            SELECT draft_id, source_item_id, review_status, stem_tex, answer_tex, solution_tex
            FROM question_import_draft
            ORDER BY created_at, draft_id
            """
        ).fetchall()
        with conn:
            for row in rows:
                review = decisions.get(f"source_item_id:{row['source_item_id']}") or decisions.get(f"draft_id:{row['draft_id']}")
                if not review:
                    results.append(
                        {
                            "draft_id": row["draft_id"],
                            "source_item_id": row["source_item_id"],
                            "decision": "",
                            "status": "skipped",
                            "message": "未找到审查决策",
                        }
                    )
                    continue
                decision = review.get("review_decision", "")
                missing_required_content = not str(row["stem_tex"] or "").strip() or not str(row["answer_tex"] or "").strip() or not str(row["solution_tex"] or "").strip()
                next_status, reason = reviewed_draft_status(decision, str(row["review_status"]), missing_required_content)
                if not decision:
                    results.append(
                        {
                            "draft_id": row["draft_id"],
                            "source_item_id": row["source_item_id"],
                            "decision": "",
                            "status": "skipped",
                            "message": "review_decision 为空",
                        }
                    )
                    continue
                conn.execute(
                    """
                    UPDATE question_import_draft
                    SET review_status = ?, review_reason = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE draft_id = ?
                    """,
                    (next_status, review.get("reviewer_note") or reason, row["draft_id"]),
                )
                results.append(
                    {
                        "draft_id": row["draft_id"],
                        "source_item_id": row["source_item_id"],
                        "decision": decision,
                        "status": "applied",
                        "message": f"{row['review_status']} -> {next_status}",
                    }
                )
    finally:
        conn.close()

    after_counts = database_counts(output_db)
    status_counts = Counter(row["status"] for row in results)
    decision_counts = Counter(row["decision"] or "空" for row in results)
    return {
        "enabled": True,
        "review_path": relative_to_root(review_path),
        "rows": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "question_import_draft_delta": count_delta(before_counts, after_counts, "question_import_draft"),
    }


def commit_ready_drafts_layer(output_db: Path, batch_id: str) -> dict[str, Any]:
    before_counts = database_counts(output_db)
    draft_ids = list_ready_draft_ids(str(output_db), batch_id)
    conn = sqlite3.connect(output_db)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
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
            for item_batch_id in batch_ids:
                conn.execute(
                    """
                    UPDATE import_batch
                    SET finished_at = ?, summary = ?
                    WHERE batch_id = ?
                    """,
                    (
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "combined preview commit-ready-drafts completed",
                        item_batch_id,
                    ),
                )
    finally:
        conn.close()

    after_counts = database_counts(output_db)
    status_counts = Counter(str(row["status"]) for row in results)
    return {
        "enabled": True,
        "batch_id": batch_id,
        "drafts": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "question_delta": count_delta(before_counts, after_counts, "question"),
        "question_asset_delta": count_delta(before_counts, after_counts, "question_asset"),
        "question_revision_delta": count_delta(before_counts, after_counts, "question_revision"),
        "import_report_item_delta": count_delta(before_counts, after_counts, "import_report_item"),
        "written_question_ids": [row["question_id"] for row in results if row.get("question_id")],
    }


def import_book_layer(output_db: Path, input_path: Path) -> dict[str, Any]:
    before_counts = database_counts(output_db)
    payload = load_book_payload(input_path)
    conn = sqlite3.connect(output_db)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            results = import_book(conn, payload)
    finally:
        conn.close()

    after_counts = database_counts(output_db)
    kind_counts = Counter(row["kind"] for row in results)
    status_counts = Counter(row["status"] for row in results)
    return {
        "enabled": True,
        "input_path": relative_to_root(input_path),
        "items": len(results),
        "kind_counts": dict(sorted(kind_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "book_delta": count_delta(before_counts, after_counts, "book"),
        "book_section_delta": count_delta(before_counts, after_counts, "book_section"),
        "book_exercise_question_delta": count_delta(before_counts, after_counts, "book_exercise_question"),
    }


def import_topic_layer(output_db: Path, input_path: Path) -> dict[str, Any]:
    before_counts = database_counts(output_db)
    payload = load_topic_payload(input_path)
    conn = sqlite3.connect(output_db)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            results = import_topics(conn, payload)
    finally:
        conn.close()

    after_counts = database_counts(output_db)
    kind_counts = Counter(row["kind"] for row in results)
    status_counts = Counter(row["status"] for row in results)
    return {
        "enabled": True,
        "input_path": relative_to_root(input_path),
        "items": len(results),
        "kind_counts": dict(sorted(kind_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "topic_module_delta": count_delta(before_counts, after_counts, "topic_module"),
        "topic_delta": count_delta(before_counts, after_counts, "topic"),
        "topic_question_delta": count_delta(before_counts, after_counts, "topic_question"),
    }


def markdown_table_from_counts(before: dict[str, int], after: dict[str, int]) -> str:
    return "\n".join(
        f"| `{table}` | {before.get(table, 0)} | {after.get(table, 0)} | {after.get(table, 0) - before.get(table, 0)} |"
        for table in COUNT_TABLES
    )


def compact_dict_lines(data: dict[str, Any]) -> str:
    if not data:
        return "无"
    return "，".join(f"`{key}`={value}" for key, value in data.items())


def write_report(
    source_db: Path,
    output_db: Path,
    report_path: Path,
    before_counts: dict[str, int],
    after_counts: dict[str, int],
    summaries: dict[str, Any],
    commit_ready_drafts: bool,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    equivalence = summaries.get("equivalence", {})
    assets = summaries.get("assets", {})
    tex_corrections = summaries.get("tex_corrections", {})
    drafts = summaries.get("drafts", {})
    draft_review = summaries.get("draft_review", {})
    draft_commit = summaries.get("draft_commit", {})
    book = summaries.get("book", {})
    topic = summaries.get("topic", {})

    asset_sample = "\n".join(
        f"- `{row['question_id']}`：`{row['source_path']}`"
        for row in assets.get("sample", [])
    ) or "无"

    report_path.write_text(
        f"""# 综合预览库生成报告

> 生成时间：{now}  
> 来源数据库：`{relative_to_root(source_db)}`  
> 输出数据库：`{relative_to_root(output_db)}`  
> 执行方式：复制预览库后叠加各 dry-run 层；不修改正式数据库，不修改 `.tex` 原题库。  
> ready 草稿提交预演：`{commit_ready_drafts}`

## 总览

| 表 | 生成前 | 生成后 | 变化 |
| --- | ---: | ---: | ---: |
{markdown_table_from_counts(before_counts, after_counts)}

## 叠加层结果

| 层 | 状态 | 关键结果 |
| --- | --- | --- |
| 同题审核决策 | {'已执行' if equivalence.get('enabled') else '跳过'} | 决策 {equivalence.get('rows', 0)} 行；写入同题关系变化 {equivalence.get('equivalence_delta', 0)}；补充知识关系 {equivalence.get('knowledge_delta', 0)} |
| 图片资源登记 | {'已执行' if assets.get('enabled') else '跳过'} | 扫描 {assets.get('scanned', 0)} 个；匹配 {assets.get('matched', 0)} 个；新增资源记录 {assets.get('question_asset_delta', 0)} |
| 题目 TeX 修正 | {'已执行' if tex_corrections.get('enabled') else '跳过'} | 修正 {tex_corrections.get('rows', 0)} 条；变更字段 {tex_corrections.get('changed_fields', 0)}；移除引用 {tex_corrections.get('removed_refs', 0)} |
| AI/OCR 草稿导入 | {'已执行' if drafts.get('enabled') else '跳过'} | 草稿 {drafts.get('items', 0)} 条；状态 {compact_dict_lines(drafts.get('draft_status_counts', {}))} |
| AI/OCR 草稿审查 | {'已执行' if draft_review.get('enabled') else '跳过'} | 审查 {draft_review.get('rows', 0)} 条；决策 {compact_dict_lines(draft_review.get('decision_counts', {}))} |
| ready 草稿提交预演 | {'已执行' if draft_commit.get('enabled') else '跳过'} | 处理 {draft_commit.get('drafts', 0)} 条；新增题目 {draft_commit.get('question_delta', 0)}；新增修订 {draft_commit.get('question_revision_delta', 0)} |
| 教材关系样例导入 | {'已执行' if book.get('enabled') else '跳过'} | book +{book.get('book_delta', 0)}；section +{book.get('book_section_delta', 0)}；question links +{book.get('book_exercise_question_delta', 0)} |
| 专题关系样例导入 | {'已执行' if topic.get('enabled') else '跳过'} | module +{topic.get('topic_module_delta', 0)}；topic +{topic.get('topic_delta', 0)}；question links +{topic.get('topic_question_delta', 0)} |

## 状态分布

- 同题审核决策：{compact_dict_lines(equivalence.get('decision_counts', {}))}
- 同题审核执行：{compact_dict_lines(equivalence.get('status_counts', {}))}
- 题目 TeX 修正：{compact_dict_lines(tex_corrections.get('status_counts', {}))}
- AI/OCR 草稿：{compact_dict_lines(drafts.get('draft_status_counts', {}))}
- AI/OCR 草稿审查：{compact_dict_lines(draft_review.get('status_counts', {}))}
- ready 草稿提交：{compact_dict_lines(draft_commit.get('status_counts', {}))}
- 教材导入：{compact_dict_lines(book.get('status_counts', {}))}
- 专题导入：{compact_dict_lines(topic.get('status_counts', {}))}

## 图片样例

{asset_sample}

## 边界说明

- 这是“综合预览库”，用于把当前重构成果放到同一个 SQLite 副本中验证。
- 默认只导入 AI/OCR 草稿，不把 ready 草稿写入正式题表；如需预演写入，使用 `--commit-ready-drafts`。
- 图片资源默认只登记旧路径，不复制真实图片；如需复制到 `assets/questions/<question_id>/`，使用 `--copy-assets`。
- 教材和专题当前使用 `templates/` 下的样例 JSON，只验证结构链路，不代表最终真实教材/专题数据。
- 正式接入前仍需要人工审查 `db/seed/paper_name_mapping.csv` 和 `db/seed/equivalence_review_decisions_20260902_initial.csv`。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成综合预览 SQLite 库，叠加当前所有 dry-run 结构层。")
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB), help="基础预览库。")
    parser.add_argument("--output-db", default="", help="输出 SQLite；默认写入 data/mathcyclus_preview_combined_<stamp>.sqlite3。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="输出时间戳。")
    parser.add_argument("--decisions", default=str(DEFAULT_DECISIONS), help="同题审核决策 CSV。")
    parser.add_argument("--draft-input", default=str(DEFAULT_DRAFT_INPUT), help="AI/OCR 草稿 JSON。")
    parser.add_argument("--draft-review", default=str(DEFAULT_DRAFT_REVIEW), help="AI/OCR 草稿人工审查 CSV。")
    parser.add_argument("--tex-corrections", default=str(DEFAULT_TEX_CORRECTIONS), help="题目 TeX 内容修正 CSV。")
    parser.add_argument("--book-input", default=str(DEFAULT_BOOK_INPUT), help="教材关系 JSON。")
    parser.add_argument("--topic-input", default=str(DEFAULT_TOPIC_INPUT), help="专题关系 JSON。")
    parser.add_argument("--report-stem", default="", help="报告文件名前缀；默认使用 combined_preview_build_<stamp>。")
    parser.add_argument("--skip-equivalence", action="store_true", help="跳过同题审核决策层。")
    parser.add_argument("--skip-assets", action="store_true", help="跳过图片资源登记层。")
    parser.add_argument("--skip-drafts", action="store_true", help="跳过 AI/OCR 草稿层。")
    parser.add_argument("--skip-book", action="store_true", help="跳过教材关系样例层。")
    parser.add_argument("--skip-topic", action="store_true", help="跳过专题关系样例层。")
    parser.add_argument("--copy-assets", action="store_true", help="复制图片到 assets/questions/<question_id>/；默认只登记。")
    parser.add_argument("--commit-ready-drafts", action="store_true", help="在综合库副本中预演提交 ready/approved 草稿。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_db = resolve_project_path(args.source_db)
    if not source_db.exists():
        raise SystemExit(f"来源数据库不存在：{source_db}")

    output_db = resolve_project_path(args.output_db) if args.output_db else DATA_DIR / f"mathcyclus_preview_combined_{args.stamp}.sqlite3"
    ensure_inside_project(output_db)
    report_stem = args.report_stem or f"combined_preview_build_{args.stamp}"
    report_path = REPORTS_DIR / f"{report_stem}.md"
    json_path = REPORTS_DIR / f"{report_stem}.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if output_db.exists():
        output_db.unlink()
    shutil.copy2(source_db, output_db)
    ensure_schema(output_db)

    before_counts = database_counts(output_db)
    summaries: dict[str, Any] = {}

    if args.skip_equivalence:
        summaries["equivalence"] = {"enabled": False}
    else:
        decisions_path = resolve_project_path(args.decisions)
        if not decisions_path.exists():
            raise SystemExit(f"同题审核决策 CSV 不存在：{decisions_path}")
        summaries["equivalence"] = apply_equivalence_layer(output_db, decisions_path)

    if args.skip_assets:
        summaries["assets"] = {"enabled": False}
    else:
        summaries["assets"] = apply_asset_layer(output_db, copy_files=args.copy_assets)

    tex_corrections_path = resolve_project_path(args.tex_corrections)
    summaries["tex_corrections"] = apply_question_tex_corrections_layer(output_db, tex_corrections_path)

    batch_id = ""
    if args.skip_drafts:
        summaries["drafts"] = {"enabled": False}
        summaries["draft_commit"] = {"enabled": False}
    else:
        draft_input = resolve_project_path(args.draft_input)
        if not draft_input.exists():
            raise SystemExit(f"AI/OCR 草稿 JSON 不存在：{draft_input}")
        summaries["drafts"] = import_draft_layer(output_db, draft_input, args.stamp)
        draft_review_path = resolve_project_path(args.draft_review)
        summaries["draft_review"] = apply_draft_review_layer(output_db, draft_review_path)
        batch_id = str(summaries["drafts"].get("batch_id") or "")
        summaries["draft_commit"] = (
            commit_ready_drafts_layer(output_db, batch_id)
            if args.commit_ready_drafts and batch_id
            else {"enabled": False}
        )

    if args.skip_book:
        summaries["book"] = {"enabled": False}
    else:
        book_input = resolve_project_path(args.book_input)
        if not book_input.exists():
            raise SystemExit(f"教材关系 JSON 不存在：{book_input}")
        summaries["book"] = import_book_layer(output_db, book_input)

    if args.skip_topic:
        summaries["topic"] = {"enabled": False}
    else:
        topic_input = resolve_project_path(args.topic_input)
        if not topic_input.exists():
            raise SystemExit(f"专题关系 JSON 不存在：{topic_input}")
        summaries["topic"] = import_topic_layer(output_db, topic_input)

    after_counts = database_counts(output_db)
    write_report(source_db, output_db, report_path, before_counts, after_counts, summaries, args.commit_ready_drafts)
    json_path.write_text(
        json.dumps(
            {
                "source_db": relative_to_root(source_db),
                "output_db": relative_to_root(output_db),
                "before_counts": before_counts,
                "after_counts": after_counts,
            "summaries": summaries,
                "commit_ready_drafts": args.commit_ready_drafts,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"database={relative_to_root(output_db)}")
    print(f"report={relative_to_root(report_path)}")
    print(f"json={relative_to_root(json_path)}")
    print(f"questions={after_counts['question']}")
    print(f"assets={after_counts['question_asset']}")
    print(f"drafts={after_counts['question_import_draft']}")
    print(f"books={after_counts['book']}")
    print(f"topics={after_counts['topic']}")


if __name__ == "__main__":
    main()
