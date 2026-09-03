from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
DATA_DIR = PROJECT_ROOT / "data"
BACKUP_DIR = DATA_DIR / "backups"
REPORTS_DIR = PROJECT_ROOT / "reports"
CHANGE_SOURCE = "choices_json_cleanup"
OPERATOR = "maintenance"
NOTE = "将历史 choices_json 归一为内部 TeX"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from services.choice_format_service import is_wrapped_choice_value, normalize_choice_items
from services.database_service import readonly_database_connection
from services.export_service import question_to_legacy_tex
from services.question_db_service import get_question
from services.question_edit_service import update_question_fields
from services.revision_service import compact_json


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def short_text(value: Any, limit: int = 140) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="将 question 表里的历史 choices_json 归一为内部 TeX。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    parser.add_argument("--apply", action="store_true", help="直接写回目标数据库；默认仅生成预览副本。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="输出时间戳。")
    parser.add_argument("--sample-limit", type=int, default=12, help="报告里展示多少条样例。")
    return parser.parse_args()


def resolve_db_path(db_path: str | Path) -> Path:
    path = Path(db_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def copy_sqlite_database(source_db: Path, target_db: Path) -> None:
    target_db.parent.mkdir(parents=True, exist_ok=True)
    if target_db.exists():
        target_db.unlink()
    source_conn = sqlite3.connect(source_db)
    target_conn = sqlite3.connect(target_db)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def integrity_check(db_path: Path) -> str:
    conn = sqlite3.connect(db_path)
    try:
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        conn.close()


def list_question_choice_rows(db_path: Path) -> list[dict[str, Any]]:
    with readonly_database_connection(str(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT question_id, choices_json
            FROM question
            ORDER BY question_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def build_cleanup_plan(db_path: Path) -> dict[str, Any]:
    rows = list_question_choice_rows(db_path)
    plan: list[dict[str, Any]] = []
    wrapped_items = 0
    inner_items = 0

    for row in rows:
        question_id = str(row.get("question_id") or "").strip()
        if not question_id:
            continue
        try:
            parsed_choices = json.loads(row.get("choices_json") or "[]")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{question_id} 的 choices_json 不是合法 JSON: {exc}") from exc
        if not isinstance(parsed_choices, list):
            raise ValueError(f"{question_id} 的 choices_json 不是数组")

        normalized_choices = normalize_choice_items(parsed_choices)
        current_choices = [str(item) for item in parsed_choices if str(item or "").strip()]
        for item in parsed_choices:
            if is_wrapped_choice_value(item):
                wrapped_items += 1
            elif str(item or "").strip():
                inner_items += 1

        if normalized_choices != current_choices:
            plan.append(
                {
                    "question_id": question_id,
                    "before_choices": current_choices,
                    "after_choices": normalized_choices,
                    "before_count": len(current_choices),
                    "after_count": len(normalized_choices),
                    "wrapped_item_count": sum(1 for item in parsed_choices if is_wrapped_choice_value(item)),
                }
            )

    return {
        "rows_scanned": len(rows),
        "rows_changed": len(plan),
        "wrapped_items": wrapped_items,
        "inner_items": inner_items,
        "plan": plan,
    }


def cleanup_question_choices(db_path: Path, plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in plan:
        question_id = str(item["question_id"])
        question = get_question(str(db_path), question_id)
        if not question:
            raise ValueError(f"题目不存在：{question_id}")

        updated_question = dict(question)
        updated_question["choices_json"] = compact_json(item["after_choices"])
        canonical_tex = question_to_legacy_tex(updated_question)
        updates = {
            "choices_json": item["after_choices"],
            "canonical_tex": canonical_tex,
        }
        result = update_question_fields(
            str(db_path),
            question_id,
            updates,
            operator=OPERATOR,
            note=NOTE,
            change_source=CHANGE_SOURCE,
        )
        results.append(
            {
                "question_id": question_id,
                "changed_fields": result.get("changed_fields") or [],
                "revision_id": result.get("revision_id") or "",
                "before_choices": item["before_choices"],
                "after_choices": item["after_choices"],
                "canonical_tex_changed": "canonical_tex" in (result.get("changed_fields") or []),
            }
        )
    return results


def write_report(
    report_path: Path,
    *,
    stamp: str,
    mode_label: str,
    source_db: Path,
    work_db: Path,
    backup_db: Path | None,
    plan: dict[str, Any],
    results: list[dict[str, Any]],
    before_revision_count: int,
    after_revision_count: int,
) -> None:
    samples = results[:12]
    sample_lines = "\n".join(
        f"- `{row['question_id']}`：`{short_text(json.dumps(row['before_choices'], ensure_ascii=False))}` → `{short_text(json.dumps(row['after_choices'], ensure_ascii=False))}`"
        for row in samples
    ) or "- 无"

    backup_line = f"`{relative_to_root(backup_db)}`" if backup_db else "无"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        f"""# choices_json 归一化报告

> 时间：{stamp}  
> 模式：{mode_label}  
> 源数据库：`{relative_to_root(source_db)}`  
> 工作数据库：`{relative_to_root(work_db)}`  
> 备份：{backup_line}

## 汇总

| 指标 | 数值 |
| --- | ---: |
| 扫描题目数 | {plan['rows_scanned']} |
| 需要修改题目数 | {plan['rows_changed']} |
| 已是内部 TeX 的非空选项数 | {plan['inner_items']} |
| 需要拆包的选项数 | {plan['wrapped_items']} |
| 修订记录变化 | {after_revision_count - before_revision_count} |

## 样例

{sample_lines}

## 说明

- 本次归一化只会把 `choices_json` 统一到“内部 TeX”表示。
- 导出层仍会继续输出 `\\choice{{...}}`，因此对外兼容不变。
- 每条真实修改都会写入 `question_revision`。
""",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    source_db = resolve_db_path(args.db)
    if not source_db.exists():
        raise SystemExit(f"数据库不存在：{source_db}")

    stamp = str(args.stamp)
    report_path = REPORTS_DIR / f"choices_json_cleanup_{stamp}.md"
    preview_db = DATA_DIR / f"mathcyclus_preview_choices_cleanup_{stamp}.sqlite3"
    backup_db: Path | None = None

    if args.apply:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup_db = BACKUP_DIR / f"{source_db.stem}_choices_cleanup_{stamp}.sqlite3"
        copy_sqlite_database(source_db, backup_db)
        work_db = DATA_DIR / f".{source_db.stem}.choices_cleanup.{stamp}.sqlite3"
        copy_sqlite_database(source_db, work_db)
        mode_label = "apply"
    else:
        copy_sqlite_database(source_db, preview_db)
        work_db = preview_db
        mode_label = "dry-run"

    plan = build_cleanup_plan(work_db)
    before_revision_count = 0
    with readonly_database_connection(str(work_db)) as conn:
        before_revision_count = int(conn.execute("SELECT COUNT(*) FROM question_revision").fetchone()[0])

    results = cleanup_question_choices(work_db, plan["plan"])

    with readonly_database_connection(str(work_db)) as conn:
        after_revision_count = int(conn.execute("SELECT COUNT(*) FROM question_revision").fetchone()[0])
    if integrity_check(work_db) != "ok":
        raise SystemExit(f"工作数据库完整性检查失败：{work_db}")

    if args.apply:
        os.replace(work_db, source_db)

    write_report(
        report_path,
        stamp=stamp,
        mode_label=mode_label,
        source_db=source_db,
        work_db=source_db if args.apply else work_db,
        backup_db=backup_db,
        plan=plan,
        results=results,
        before_revision_count=before_revision_count,
        after_revision_count=after_revision_count,
    )

    summary = {
        "mode": mode_label,
        "source_database": relative_to_root(source_db),
        "work_database": relative_to_root(source_db if args.apply else work_db),
        "backup_database": relative_to_root(backup_db) if backup_db else "",
        "rows_scanned": plan["rows_scanned"],
        "rows_changed": plan["rows_changed"],
        "wrapped_items": plan["wrapped_items"],
        "inner_items": plan["inner_items"],
        "revisions_written": after_revision_count - before_revision_count,
        "report": relative_to_root(report_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
