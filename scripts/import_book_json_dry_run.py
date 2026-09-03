from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_paper_mapped_20260902_with_knowledge.sqlite3"
DEFAULT_INPUT = PROJECT_ROOT / "templates" / "book_import_example.json"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def stable_id(prefix: str, *values: object, length: int = 12) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def ensure_schema(db_path: Path) -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.executescript(schema)
    finally:
        conn.close()


def load_payload(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("教材 JSON 顶层必须是对象")
    if not isinstance(data.get("book"), dict):
        raise ValueError("教材 JSON 必须包含 book 对象")
    if not isinstance(data.get("sections", []), list):
        raise ValueError("sections 必须是数组")
    if not isinstance(data.get("questions", []), list):
        raise ValueError("questions 必须是数组")
    return data


def question_exists(conn: sqlite3.Connection, question_id: str) -> bool:
    return conn.execute("SELECT 1 FROM question WHERE question_id = ?", (question_id,)).fetchone() is not None


def import_book(conn: sqlite3.Connection, payload: dict[str, Any]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    book = payload["book"]
    title = str(book.get("title") or "").strip()
    if not title:
        raise ValueError("book.title 不能为空")
    publisher = str(book.get("publisher") or "").strip()
    edition = str(book.get("edition") or "").strip()
    grade = str(book.get("grade") or "").strip()
    volume = str(book.get("volume") or "").strip()
    curriculum_version = str(book.get("curriculum_version") or "").strip()
    description = str(book.get("description") or "").strip()
    book_id = stable_id("B", title, publisher, edition, grade, volume, curriculum_version)

    conn.execute(
        """
        INSERT OR REPLACE INTO book(
            book_id, title, publisher, edition, grade, volume,
            curriculum_version, description, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (book_id, title, publisher, edition, grade, volume, curriculum_version, description),
    )
    results.append({"kind": "book", "status": "upserted", "id": book_id, "message": title})

    section_id_by_key: dict[str, str] = {}
    for index, section in enumerate(payload.get("sections", []), start=1):
        if not isinstance(section, dict):
            results.append({"kind": "section", "status": "invalid", "id": "", "message": f"第 {index} 个 section 不是对象"})
            continue
        key = str(section.get("section_key") or f"section-{index}").strip()
        title_text = str(section.get("title") or "").strip()
        if not title_text:
            results.append({"kind": "section", "status": "invalid", "id": key, "message": "title 不能为空"})
            continue
        parent_key = str(section.get("parent_key") or "").strip()
        parent_section_id = section_id_by_key.get(parent_key) if parent_key else None
        if parent_key and not parent_section_id:
            results.append({"kind": "section", "status": "invalid", "id": key, "message": f"parent_key 未找到：{parent_key}"})
            continue
        section_id = stable_id("BS", book_id, key, title_text)
        section_id_by_key[key] = section_id
        conn.execute(
            """
            INSERT OR REPLACE INTO book_section(
                section_id, book_id, parent_section_id, title, section_level,
                page_start, page_end, sort_order, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                section_id,
                book_id,
                parent_section_id,
                title_text,
                coerce_int(section.get("section_level")) or 1,
                coerce_int(section.get("page_start")),
                coerce_int(section.get("page_end")),
                coerce_int(section.get("sort_order")) or index,
            ),
        )
        results.append({"kind": "section", "status": "upserted", "id": section_id, "message": title_text})

    for index, link in enumerate(payload.get("questions", []), start=1):
        if not isinstance(link, dict):
            results.append({"kind": "question_link", "status": "invalid", "id": "", "message": f"第 {index} 个 question 不是对象"})
            continue
        question_id = str(link.get("question_id") or "").strip()
        section_key = str(link.get("section_key") or "").strip()
        section_id = section_id_by_key.get(section_key)
        if not question_id or not question_exists(conn, question_id):
            results.append({"kind": "question_link", "status": "invalid", "id": question_id, "message": "question_id 不存在"})
            continue
        if section_key and not section_id:
            results.append({"kind": "question_link", "status": "invalid", "id": question_id, "message": f"section_key 未找到：{section_key}"})
            continue
        page_number = coerce_int(link.get("page_number"))
        column_name = str(link.get("column_name") or "").strip()
        exercise_number = str(link.get("exercise_number") or "").strip()
        sub_number = str(link.get("sub_number") or "").strip()
        display_order = coerce_int(link.get("display_order")) or index
        source_note = str(link.get("source_note") or "").strip()
        relation_id = stable_id(
            "BEQ",
            book_id,
            section_id or "",
            question_id,
            page_number,
            column_name,
            exercise_number,
            sub_number,
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO book_exercise_question(
                book_exercise_question_id, book_id, section_id, question_id,
                page_number, column_name, exercise_number, sub_number,
                display_order, source_note, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                relation_id,
                book_id,
                section_id,
                question_id,
                page_number,
                column_name,
                exercise_number,
                sub_number,
                display_order,
                source_note,
            ),
        )
        results.append({"kind": "question_link", "status": "linked", "id": relation_id, "message": question_id})

    return results


def write_report(source_db: Path, output_db: Path, input_path: Path, report_path: Path, results: list[dict[str, str]]) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    kind_counts = Counter(row["kind"] for row in results)
    status_counts = Counter(row["status"] for row in results)
    status_lines = "\n".join(f"| `{key}` | {value} |" for key, value in sorted(status_counts.items())) or "| 无 | 0 |"
    kind_lines = "\n".join(f"| `{key}` | {value} |" for key, value in sorted(kind_counts.items())) or "| 无 | 0 |"
    invalid_text = "\n".join(
        f"- `{row['kind']}` / `{row['id']}`：{row['message']}"
        for row in results
        if row["status"] == "invalid"
    ) or "无"

    report_path.write_text(
        f"""# 教材 JSON 导入 Dry-run 报告

> 生成时间：{now}  
> 来源数据库：`{relative_to_root(source_db)}`  
> 输出数据库：`{relative_to_root(output_db)}`  
> 输入 JSON：`{relative_to_root(input_path)}`  
> 执行方式：复制预览库后写入教材、章节和教材题目关系；不修改 `.tex`。

## 类型统计

| 类型 | 数量 |
| --- | ---: |
{kind_lines}

## 状态统计

| 状态 | 数量 |
| --- | ---: |
{status_lines}

## 无效项

{invalid_text}

## 安全边界

- 本脚本只写数据库副本。
- `question_id` 不存在的教材关系不会写入。
- `section_key` 找不到时不会写入对应关系。
- 教材页码、栏目、题号都保存在 `book_exercise_question`，不写入 `question` 本体。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入教材 JSON 到数据库副本。")
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB), help="来源 SQLite 预览库。")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="教材 JSON。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="输出时间戳。")
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
    output_db = DATA_DIR / f"mathcyclus_preview_book_import_{args.stamp}.sqlite3"
    report_path = REPORTS_DIR / f"book_import_dry_run_{args.stamp}.md"

    if output_db.exists():
        output_db.unlink()
    shutil.copy2(source_db, output_db)
    ensure_schema(output_db)

    payload = load_payload(input_path)
    conn = sqlite3.connect(output_db)
    try:
        with conn:
            results = import_book(conn, payload)
    finally:
        conn.close()

    write_report(source_db, output_db, input_path, report_path, results)
    status_counts = Counter(row["status"] for row in results)
    print(f"items={len(results)}")
    print(f"status_counts={dict(sorted(status_counts.items()))}")
    print(f"database={relative_to_root(output_db)}")
    print(f"report={relative_to_root(report_path)}")


if __name__ == "__main__":
    main()
