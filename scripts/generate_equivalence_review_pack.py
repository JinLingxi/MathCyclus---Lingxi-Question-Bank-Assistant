from __future__ import annotations

import argparse
import csv
import hashlib
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_paper_mapped_20260902_with_knowledge.sqlite3"
REPORTS_DIR = PROJECT_ROOT / "reports"
SEED_DIR = PROJECT_ROOT / "db" / "seed"


def relative_to_root(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def stable_review_id(*values: object) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return "R" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def normalize_text(text: str) -> str:
    result = text or ""
    for old, new in [
        (" ", ""),
        ("\r", ""),
        ("\n", ""),
        ("\t", ""),
        ("．", "."),
        ("，", ","),
        ("。", "."),
    ]:
        result = result.replace(old, new)
    return result


def fetch_duplicate_positions(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    duplicate_groups = conn.execute(
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

    result = []
    for group in duplicate_groups:
        items = conn.execute(
            """
            SELECT
                pq.paper_question_id,
                pq.question_id,
                pq.question_number,
                pq.sub_number,
                q.legacy_id,
                q.answer_tex,
                l.legacy_file_path,
                l.detected_chapter,
                substr(q.stem_tex, 1, 220) AS stem_preview
            FROM paper_question pq
            JOIN question q ON q.question_id = pq.question_id
            LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
            WHERE pq.paper_id = ?
              AND pq.question_number = ?
              AND pq.sub_number = ?
            ORDER BY pq.question_id
            """,
            (group["paper_id"], group["question_number"], group["sub_number"]),
        ).fetchall()
        result.append({"group": dict(group), "items": [dict(item) for item in items]})
    return result


def fetch_same_stem_groups(conn: sqlite3.Connection) -> list[list[dict]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            q.question_id,
            q.legacy_id,
            q.answer_tex,
            q.stem_tex,
            l.legacy_file_path,
            l.detected_year,
            l.detected_source,
            l.detected_question_number,
            l.detected_chapter,
            substr(q.stem_tex, 1, 220) AS stem_preview
        FROM question q
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        ORDER BY q.question_id
        """
    ).fetchall()

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        key = normalize_text(row["stem_tex"])
        if key:
            grouped[key].append(dict(row))
    return [items for items in grouped.values() if len(items) > 1]


def decision_rows(duplicate_positions: list[dict], same_stem_groups: list[list[dict]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    for entry in duplicate_positions:
        group = entry["group"]
        items = entry["items"]
        question_ids = [item["question_id"] for item in items]
        chapters = [item["detected_chapter"] for item in items]
        rows.append(
            {
                "review_id": stable_review_id("duplicate_position", group["paper_id"], group["question_number"], group["sub_number"]),
                "issue_type": "duplicate_position",
                "paper_id": group["paper_id"],
                "paper_label": f"{group['year']} {group['paper_name']} {group['track']} 第{group['question_number']}题",
                "question_ids": " | ".join(question_ids),
                "legacy_ids": " | ".join(item["legacy_id"] or "" for item in items),
                "chapters": " | ".join(chapters),
                "recommended_action": "review_keep_all_or_merge_equivalent",
                "decision": "pending",
                "canonical_question_id": "",
                "merge_into_knowledge_areas": "",
                "note": "同一试卷同一题号存在多条记录，可能是一题多知识板块，也可能是误重复。",
            }
        )

    for items in same_stem_groups:
        question_ids = [item["question_id"] for item in items]
        rows.append(
            {
                "review_id": stable_review_id("same_stem", *question_ids),
                "issue_type": "same_stem",
                "paper_id": "",
                "paper_label": " | ".join(
                    f"{item['detected_year']} {item['detected_source']} 第{item['detected_question_number']}题"
                    for item in items
                ),
                "question_ids": " | ".join(question_ids),
                "legacy_ids": " | ".join(item["legacy_id"] or "" for item in items),
                "chapters": " | ".join(item["detected_chapter"] or "" for item in items),
                "recommended_action": "review_mark_equivalent",
                "decision": "pending",
                "canonical_question_id": "",
                "merge_into_knowledge_areas": "",
                "note": "题干规范化后完全一致，建议人工判断是否同题。",
            }
        )

    return rows


def write_decision_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "review_id",
        "issue_type",
        "paper_id",
        "paper_label",
        "question_ids",
        "legacy_ids",
        "chapters",
        "recommended_action",
        "decision",
        "canonical_question_id",
        "merge_into_knowledge_areas",
        "note",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(
    duplicate_positions: list[dict],
    same_stem_groups: list[list[dict]],
    decision_path: Path,
    report_path: Path,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    duplicate_text = []
    for entry in duplicate_positions:
        group = entry["group"]
        duplicate_text.append(
            f"- `{group['year']} {group['paper_name']} {group['track']} 第{group['question_number']}题`"
        )
        for item in entry["items"]:
            duplicate_text.append(
                f"  - `{item['question_id']}` / 旧 ID `{item['legacy_id']}` / "
                f"`{item['detected_chapter']}` / `{item['legacy_file_path']}`"
            )

    same_stem_text = []
    for items in same_stem_groups:
        same_stem_text.append("- 疑似同题组")
        for item in items:
            same_stem_text.append(
                f"  - `{item['question_id']}` / 旧 ID `{item['legacy_id']}` / "
                f"{item['detected_year']} {item['detected_source']} 第{item['detected_question_number']}题 / "
                f"`{item['detected_chapter']}`"
            )

    report_path.write_text(
        f"""# 重复题与同题审查包

> 生成时间：{now}  
> 决策表：`{relative_to_root(decision_path)}`  
> 用途：人工审查迁移中发现的重复题号、疑似同题、一题多知识板块问题。

## 总览

| 指标 | 数量 |
| --- | ---: |
| 同一试卷同一题号重复位置 | {len(duplicate_positions)} |
| 题干完全一致疑似同题组 | {len(same_stem_groups)} |

## 决策表填写说明

`decision` 字段可填写：

- `pending`：暂不处理。
- `keep_all`：确认都保留，可能是不同题或不同版本。
- `mark_equivalent`：确认是同题，但暂不合并，只建立同题关系。
- `merge_to_canonical`：确认可以合并到 `canonical_question_id`。
- `ignore`：确认不是问题。

`canonical_question_id`：

- 当 `decision = merge_to_canonical` 时填写。
- 例如：`Q000028`。

`merge_into_knowledge_areas`：

- 当多条题目其实是一题多知识板块时填写。
- 例如：`三角函数 | 解三角形`。

## 同一试卷同一题号重复

{chr(10).join(duplicate_text) or '无'}

## 题干完全一致疑似同题

{chr(10).join(same_stem_text) or '无'}

## 原则

- 本阶段不自动删除、不自动合并。
- 人工确认之前，所有题目都保留。
- 真正合并前，必须确认答案、解析、图片、试卷关系、知识板块关系如何保留。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成重复题和疑似同题人工审查包。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="输出时间戳。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    decision_path = SEED_DIR / f"equivalence_review_decisions_{args.stamp}.csv"
    report_path = REPORTS_DIR / f"equivalence_review_pack_{args.stamp}.md"

    conn = sqlite3.connect(db_path)
    try:
        duplicate_positions = fetch_duplicate_positions(conn)
        same_stem_groups = fetch_same_stem_groups(conn)
    finally:
        conn.close()

    rows = decision_rows(duplicate_positions, same_stem_groups)
    write_decision_csv(rows, decision_path)
    write_markdown(duplicate_positions, same_stem_groups, decision_path, report_path)

    print(f"duplicate_positions={len(duplicate_positions)}")
    print(f"same_stem_groups={len(same_stem_groups)}")
    print(f"decision_csv={relative_to_root(decision_path)}")
    print(f"report={relative_to_root(report_path)}")


if __name__ == "__main__":
    main()
