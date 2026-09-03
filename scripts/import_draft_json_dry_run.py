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
DEFAULT_SOURCE_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_paper_mapped_20260902_with_knowledge.sqlite3"
DEFAULT_INPUT = PROJECT_ROOT / "templates" / "ai_ocr_draft_import_example.json"
SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.import_service import (
    create_import_batch,
    finish_import_batch,
    insert_draft_question,
    insert_report_item,
    normalize_draft_question,
    summarize_batch,
)


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def ensure_schema(db_path: Path) -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.executescript(schema)
    finally:
        conn.close()


def load_items(input_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {}, [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        items = data.get("items") or data.get("questions") or []
        if not isinstance(items, list):
            raise ValueError("JSON 中的 items/questions 必须是数组")
        return data, [item for item in items if isinstance(item, dict)]
    raise ValueError("JSON 顶层必须是对象或数组")


def write_report(
    source_db: Path,
    output_db: Path,
    input_path: Path,
    report_path: Path,
    batch_id: str,
    rows: list[dict[str, Any]],
    batch_summary: dict[str, Any],
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_counts = Counter(row["review_status"] for row in rows)
    status_lines = "\n".join(
        f"| `{status}` | {count} |"
        for status, count in sorted(status_counts.items())
    ) or "| 无 | 0 |"
    item_lines = "\n".join(
        f"- `{row['draft_id']}` / `{row['source_label']}` / `{row['review_status']}`：{row['review_reason'] or '无'}"
        for row in rows[:50]
    ) or "无"

    report_path.write_text(
        f"""# AI/OCR 草稿导入 Dry-run 报告

> 生成时间：{now}  
> 来源数据库：`{relative_to_root(source_db)}`  
> 输出数据库：`{relative_to_root(output_db)}`  
> 输入 JSON：`{relative_to_root(input_path)}`  
> 导入批次：`{batch_id}`  
> 执行方式：复制预览库后写入 `question_import_draft`；不写正式 `question`，不修改 `.tex`。

## 总览

| 指标 | 数量 |
| --- | ---: |
| 输入题目数 | {len(rows)} |
| 草稿资产数 | {batch_summary.get('draft_asset_count', 0)} |

## 草稿状态

| review_status | 数量 |
| --- | ---: |
{status_lines}

## 草稿样例

{item_lines}

## 安全边界

- AI/OCR 输出只进入草稿表。
- `ready` 只表示字段初检通过，不代表自动进入正式题库。
- `needs_review` 和 `blocked` 必须人工处理。
- 正式入库前仍需要 LaTeX 渲染、图片路径、重复题、试卷/教材/专题关系校验。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把 AI/OCR JSON 输出导入预览库草稿表，不写正式题库。")
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB), help="来源 SQLite 预览库。")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="AI/OCR 草稿 JSON。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="输出时间戳。")
    parser.add_argument("--import-type", default="ai_ocr_json", help="导入类型。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_db = Path(args.source_db)
    input_path = Path(args.input)
    if not source_db.is_absolute():
        source_db = PROJECT_ROOT / source_db
    if not input_path.is_absolute():
        input_path = PROJECT_ROOT / input_path
    source_db = source_db.resolve()
    input_path = input_path.resolve()

    if not source_db.exists():
        raise SystemExit(f"来源数据库不存在：{source_db}")
    if not input_path.exists():
        raise SystemExit(f"输入 JSON 不存在：{input_path}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_db = DATA_DIR / f"mathcyclus_preview_import_drafts_{args.stamp}.sqlite3"
    report_path = REPORTS_DIR / f"import_draft_json_dry_run_{args.stamp}.md"

    if output_db.exists():
        output_db.unlink()
    shutil.copy2(source_db, output_db)
    ensure_schema(output_db)

    metadata, items = load_items(input_path)
    source_path = str(metadata.get("source_path") or relative_to_root(input_path))
    batch_summary_text = str(metadata.get("summary") or f"draft items={len(items)}")
    batch_id = create_import_batch(
        str(output_db),
        import_type=args.import_type,
        source_path=source_path,
        mode="dry_run",
        stamp=args.stamp,
        summary=batch_summary_text,
    )

    result_rows: list[dict[str, Any]] = []
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
        result_rows.append(
            {
                "draft_id": draft_id,
                "source_label": source_label,
                "review_status": review_status,
                "review_reason": review_reason,
            }
        )

    finish_import_batch(str(output_db), batch_id, f"draft dry-run completed; items={len(result_rows)}")
    batch_summary = summarize_batch(str(output_db), batch_id)
    write_report(source_db, output_db, input_path, report_path, batch_id, result_rows, batch_summary)

    print(f"items={len(result_rows)}")
    print(f"batch_id={batch_id}")
    print(f"draft_status_counts={batch_summary['draft_status_counts']}")
    print(f"database={relative_to_root(output_db)}")
    print(f"report={relative_to_root(report_path)}")


if __name__ == "__main__":
    main()
