from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_combined_20260902_initial.sqlite3"
REPORTS_DIR = PROJECT_ROOT / "reports"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def fetch_duplicate_positions(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            p.paper_id,
            p.year,
            p.paper_series,
            p.track,
            p.paper_name,
            pq.question_number,
            pq.sub_number,
            COUNT(*) AS duplicate_count
        FROM paper_question pq
        JOIN paper p ON p.paper_id = pq.paper_id
        GROUP BY p.paper_id, pq.question_number, pq.sub_number
        HAVING COUNT(*) > 1
        ORDER BY p.year, p.paper_name, CAST(pq.question_number AS INTEGER), pq.question_number
        """
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_duplicate_position_items(
    conn: sqlite3.Connection,
    paper_id: str,
    number: str,
    sub_number: str,
) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            pq.paper_question_id,
            pq.question_id,
            pq.question_number,
            pq.sub_number,
            q.legacy_id,
            l.legacy_file_path,
            l.detected_chapter,
            substr(q.stem_tex, 1, 180) AS stem_preview
        FROM paper_question pq
        JOIN question q ON q.question_id = pq.question_id
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        WHERE pq.paper_id = ?
          AND pq.question_number = ?
          AND pq.sub_number = ?
        ORDER BY pq.question_id
        """,
        (paper_id, number, sub_number),
    ).fetchall()
    return [dict(row) for row in rows]


def normalize_text(text: str) -> str:
    replacements = [
        (" ", ""),
        ("\r", ""),
        ("\n", ""),
        ("\t", ""),
        ("，", ","),
        ("。", "."),
    ]
    result = text or ""
    for old, new in replacements:
        result = result.replace(old, new)
    return result


def fetch_potential_same_stems(conn: sqlite3.Connection) -> list[list[dict]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            q.question_id,
            q.legacy_id,
            l.legacy_file_path,
            l.detected_year,
            l.detected_source,
            l.detected_question_number,
            l.detected_chapter,
            q.stem_tex
        FROM question q
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        """
    ).fetchall()
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        key = normalize_text(row["stem_tex"])
        if key:
            groups[key].append(dict(row))
    same_stems = [items for items in groups.values() if len(items) > 1]
    same_stems.sort(key=lambda items: (-len(items), str(items[0].get("question_id", ""))))
    return same_stems


def orphan_paper_question_count(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM paper_question pq
            LEFT JOIN paper p ON p.paper_id = pq.paper_id
            LEFT JOIN question q ON q.question_id = pq.question_id
            WHERE p.paper_id IS NULL OR q.question_id IS NULL
            """
        ).fetchone()[0]
    )


def duplicate_position_markdown(duplicate_details: list[tuple[dict, list[dict]]]) -> str:
    lines: list[str] = []
    for row, items in duplicate_details[:30]:
        lines.append(
            f"- `{row['year']} {row['paper_name']} {row['track']} 第 {row['question_number']} 题`："
            f"{row['duplicate_count']} 条"
        )
        for item in items:
            lines.append(
                f"  - `{item['question_id']}` / 旧 ID `{item['legacy_id']}` / "
                f"`{item['detected_chapter']}` / `{item['legacy_file_path']}`"
            )
    return "\n".join(lines) or "无"


def same_stem_markdown(same_stems: list[list[dict]]) -> str:
    lines: list[str] = []
    for group in same_stems[:20]:
        lines.append(f"- 疑似同题组：{len(group)} 条")
        for item in group:
            lines.append(
                f"  - `{item['question_id']}` / 旧 ID `{item['legacy_id']}` / "
                f"{item['detected_year']} {item['detected_source']} 第 {item['detected_question_number']} 题 / "
                f"`{item['detected_chapter']}`"
            )
    return "\n".join(lines) or "无"


def write_report(db_path: Path, report_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        duplicate_positions = fetch_duplicate_positions(conn)
        duplicate_details = [
            (
                row,
                fetch_duplicate_position_items(
                    conn,
                    row["paper_id"],
                    row["question_number"],
                    row["sub_number"],
                ),
            )
            for row in duplicate_positions
        ]
        same_stems = fetch_potential_same_stems(conn)
        orphan_count = orphan_paper_question_count(conn)
    finally:
        conn.close()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_path.write_text(
        f"""# 数据库关系审计报告

> 生成时间：{now}  
> 数据库：`{relative_to_root(db_path)}`  
> 审计方式：只读检查，不修改数据库和 `.tex` 文件。

## 总览

| 指标 | 数量 |
| --- | ---: |
| 失联 paper-question 关系 | {orphan_count} |
| 同一试卷同一题号重复位置 | {len(duplicate_positions)} |
| 题干完全一致的疑似同题组 | {len(same_stems)} |

## 同一试卷同一题号重复样例

{duplicate_position_markdown(duplicate_details)}

## 题干完全一致疑似同题样例

{same_stem_markdown(same_stems)}

## 判断

- 同一试卷同一题号重复不一定都是错误，可能是同题被多个知识板块收录。
- 如果未来试卷库要做到“一张卷一套题号”，这些重复必须人工确认。
- 第一版迁移不自动合并题目，避免误删跨板块收录信息。
- 后续应通过知识板块关系或同题关系表达“一题多板块”，而不是复制多个题目文件。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计预览数据库中的题目关系。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
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
    report_path = REPORTS_DIR / f"db_relation_audit_{args.stamp}.md"
    write_report(db_path, report_path)
    print(f"report={relative_to_root(report_path)}")


if __name__ == "__main__":
    main()
