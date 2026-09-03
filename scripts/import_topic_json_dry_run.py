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
DEFAULT_INPUT = PROJECT_ROOT / "templates" / "topic_import_example.json"
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


def coerce_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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
        raise ValueError("专题 JSON 顶层必须是对象")
    if not isinstance(data.get("module"), dict):
        raise ValueError("专题 JSON 必须包含 module 对象")
    if not isinstance(data.get("topics", []), list):
        raise ValueError("topics 必须是数组")
    return data


def question_exists(conn: sqlite3.Connection, question_id: str) -> bool:
    return conn.execute("SELECT 1 FROM question WHERE question_id = ?", (question_id,)).fetchone() is not None


def import_topics(conn: sqlite3.Connection, payload: dict[str, Any]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    module = payload["module"]
    module_name = str(module.get("name") or "").strip()
    if not module_name:
        raise ValueError("module.name 不能为空")
    module_id = stable_id("TM", module_name)
    conn.execute(
        """
        INSERT OR REPLACE INTO topic_module(
            module_id, name, description, sort_order, updated_at
        )
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            module_id,
            module_name,
            str(module.get("description") or "").strip(),
            coerce_int(module.get("sort_order")),
        ),
    )
    results.append({"kind": "module", "status": "upserted", "id": module_id, "message": module_name})

    for topic_index, topic in enumerate(payload.get("topics", []), start=1):
        if not isinstance(topic, dict):
            results.append({"kind": "topic", "status": "invalid", "id": "", "message": f"第 {topic_index} 个 topic 不是对象"})
            continue
        topic_key = str(topic.get("topic_key") or f"topic-{topic_index}").strip()
        topic_name = str(topic.get("name") or "").strip()
        if not topic_name:
            results.append({"kind": "topic", "status": "invalid", "id": topic_key, "message": "name 不能为空"})
            continue
        topic_id = stable_id("T", module_id, topic_key, topic_name)
        conn.execute(
            """
            INSERT OR REPLACE INTO topic(
                topic_id, module_id, name, file_name, description, updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                topic_id,
                module_id,
                topic_name,
                str(topic.get("file_name") or "").strip(),
                str(topic.get("description") or "").strip(),
            ),
        )
        results.append({"kind": "topic", "status": "upserted", "id": topic_id, "message": topic_name})

        questions = topic.get("questions", [])
        if not isinstance(questions, list):
            results.append({"kind": "topic_question", "status": "invalid", "id": topic_id, "message": "questions 必须是数组"})
            continue
        for question_index, link in enumerate(questions, start=1):
            if not isinstance(link, dict):
                results.append(
                    {
                        "kind": "topic_question",
                        "status": "invalid",
                        "id": topic_id,
                        "message": f"第 {question_index} 个 question 不是对象",
                    }
                )
                continue
            question_id = str(link.get("question_id") or "").strip()
            if not question_id or not question_exists(conn, question_id):
                results.append({"kind": "topic_question", "status": "invalid", "id": question_id, "message": "question_id 不存在"})
                continue
            group_name = str(link.get("group_name") or "").strip()
            sort_order = coerce_int(link.get("sort_order")) or question_index
            topic_note = str(link.get("topic_note") or "").strip()
            relation_id = stable_id("TQ", topic_id, question_id, group_name)
            conn.execute(
                """
                INSERT OR REPLACE INTO topic_question(
                    topic_question_id, topic_id, question_id, group_name,
                    sort_order, topic_note, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (relation_id, topic_id, question_id, group_name, sort_order, topic_note),
            )
            results.append({"kind": "topic_question", "status": "linked", "id": relation_id, "message": question_id})

    return results


def write_report(source_db: Path, output_db: Path, input_path: Path, report_path: Path, results: list[dict[str, str]]) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    kind_counts = Counter(row["kind"] for row in results)
    status_counts = Counter(row["status"] for row in results)
    kind_lines = "\n".join(f"| `{key}` | {value} |" for key, value in sorted(kind_counts.items())) or "| 无 | 0 |"
    status_lines = "\n".join(f"| `{key}` | {value} |" for key, value in sorted(status_counts.items())) or "| 无 | 0 |"
    invalid_text = "\n".join(
        f"- `{row['kind']}` / `{row['id']}`：{row['message']}"
        for row in results
        if row["status"] == "invalid"
    ) or "无"

    report_path.write_text(
        f"""# 专题 JSON 导入 Dry-run 报告

> 生成时间：{now}  
> 来源数据库：`{relative_to_root(source_db)}`  
> 输出数据库：`{relative_to_root(output_db)}`  
> 输入 JSON：`{relative_to_root(input_path)}`  
> 执行方式：复制预览库后写入专题模块、专题和专题题目关系；不修改 `.tex`。

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
- `question_id` 不存在的专题关系不会写入。
- 专题排序、分组、专题备注都保存在 `topic_question`，不写入 `question` 本体。
- 专题文件名只作为导出建议，不作为题目身份。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入专题 JSON 到数据库副本。")
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB), help="来源 SQLite 预览库。")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="专题 JSON。")
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
    output_db = DATA_DIR / f"mathcyclus_preview_topic_import_{args.stamp}.sqlite3"
    report_path = REPORTS_DIR / f"topic_import_dry_run_{args.stamp}.md"

    if output_db.exists():
        output_db.unlink()
    shutil.copy2(source_db, output_db)
    ensure_schema(output_db)

    payload = load_payload(input_path)
    conn = sqlite3.connect(output_db)
    try:
        with conn:
            results = import_topics(conn, payload)
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
