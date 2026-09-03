from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_paper_mapped_20260902_with_knowledge.sqlite3"
REPORTS_DIR = PROJECT_ROOT / "reports"


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


def count(conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def relation_counts(conn: sqlite3.Connection) -> dict[str, int]:
    relation_tables = {
        "paper_question": "question_id",
        "question_knowledge_area": "question_id",
        "question_asset": "question_id",
        "book_exercise_question": "question_id",
        "topic_question": "question_id",
        "question_revision": "question_id",
    }
    result = {"question": count(conn, "SELECT COUNT(*) FROM question")}
    for table, question_column in relation_tables.items():
        if table_exists(conn, table):
            result[table] = count(conn, f"SELECT COUNT(*) FROM {table}")
            result[f"{table}_covered_questions"] = count(
                conn,
                f"SELECT COUNT(DISTINCT {question_column}) FROM {table}",
            )
        else:
            result[table] = 0
            result[f"{table}_covered_questions"] = 0
    return result


def question_relation_rows(conn: sqlite3.Connection, limit: int = 1000) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
            q.question_id,
            q.legacy_id,
            l.legacy_file_path,
            l.detected_chapter,
            l.detected_year,
            l.detected_source,
            l.detected_question_number,
            COUNT(DISTINCT pq.paper_question_id) AS paper_links,
            COUNT(DISTINCT qka.knowledge_area_id) AS knowledge_links,
            COUNT(DISTINCT qa.asset_id) AS asset_links,
            COUNT(DISTINCT beq.book_exercise_question_id) AS book_links,
            COUNT(DISTINCT tq.topic_question_id) AS topic_links,
            COUNT(DISTINCT qr.revision_id) AS revision_links
        FROM question q
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        LEFT JOIN paper_question pq ON pq.question_id = q.question_id
        LEFT JOIN question_knowledge_area qka ON qka.question_id = q.question_id
        LEFT JOIN question_asset qa ON qa.question_id = q.question_id
        LEFT JOIN book_exercise_question beq ON beq.question_id = q.question_id
        LEFT JOIN topic_question tq ON tq.question_id = q.question_id
        LEFT JOIN question_revision qr ON qr.question_id = q.question_id
        GROUP BY q.question_id
        ORDER BY q.question_id
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def summary(db_path: Path, limit: int) -> dict[str, object]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        counts = relation_counts(conn)
        rows = question_relation_rows(conn, limit=limit)
    finally:
        conn.close()
    return {
        "database": relative_to_root(db_path),
        "counts": counts,
        "rows": rows,
    }


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    fieldnames = [
        "question_id",
        "legacy_id",
        "legacy_file_path",
        "detected_chapter",
        "detected_year",
        "detected_source",
        "detected_question_number",
        "paper_links",
        "knowledge_links",
        "asset_links",
        "book_links",
        "topic_links",
        "revision_links",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(data: dict[str, object], csv_path: Path, path: Path) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    counts = data["counts"]
    total = max(1, int(counts["question"]))

    def coverage(table: str) -> str:
        value = int(counts.get(f"{table}_covered_questions", 0))
        return f"{value} / {counts['question']} ({value / total:.1%})"

    path.write_text(
        f"""# 题库关系覆盖总览

> 生成时间：{now}  
> 数据库：`{data['database']}`  
> 明细 CSV：`{relative_to_root(csv_path)}`  
> 审计方式：只读统计，不修改数据库和 `.tex` 文件。

## 覆盖率

| 关系 | 关系记录数 | 覆盖题目 |
| --- | ---: | ---: |
| 试卷关系 `paper_question` | {counts.get('paper_question', 0)} | {coverage('paper_question')} |
| 知识板块 `question_knowledge_area` | {counts.get('question_knowledge_area', 0)} | {coverage('question_knowledge_area')} |
| 图片资源 `question_asset` | {counts.get('question_asset', 0)} | {coverage('question_asset')} |
| 教材关系 `book_exercise_question` | {counts.get('book_exercise_question', 0)} | {coverage('book_exercise_question')} |
| 专题关系 `topic_question` | {counts.get('topic_question', 0)} | {coverage('topic_question')} |
| 修订记录 `question_revision` | {counts.get('question_revision', 0)} | {coverage('question_revision')} |

## 判断

- 当前基础库应几乎全部覆盖试卷关系和知识板块关系。
- 图片、教材、专题、修订记录会随后续导入逐步增长。
- 如果某个阶段覆盖率异常下降，应优先检查关系表外键和导入脚本。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出题库关系覆盖总览。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
    parser.add_argument("--limit", type=int, default=1000, help="明细最多导出多少道题。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    db_path = db_path.resolve()
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    data = summary(db_path, limit=max(1, args.limit))
    csv_path = REPORTS_DIR / f"relation_summary_{args.stamp}.csv"
    json_path = REPORTS_DIR / f"relation_summary_{args.stamp}.json"
    md_path = REPORTS_DIR / f"relation_summary_{args.stamp}.md"
    write_csv(data["rows"], csv_path)
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(data, csv_path, md_path)

    print(f"questions={data['counts']['question']}")
    print(f"report={relative_to_root(md_path)}")
    print(f"csv={relative_to_root(csv_path)}")
    print(f"json={relative_to_root(json_path)}")


if __name__ == "__main__":
    main()
