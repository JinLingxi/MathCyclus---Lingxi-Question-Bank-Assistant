from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_combined_20260902_initial.sqlite3"
DEFAULT_DECISIONS = PROJECT_ROOT / "db" / "seed" / "equivalence_review_decisions_20260902_initial.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


FIELDNAMES = [
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


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        return [
            {field: (row.get(field) or "").strip() for field in FIELDNAMES}
            for row in csv.DictReader(file)
        ]


def split_pipe_list(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def question_rows(db_path: Path, question_ids: list[str]) -> list[dict[str, object]]:
    if not question_ids:
        return []
    placeholders = ",".join("?" for _ in question_ids)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT
                q.question_id,
                q.legacy_id,
                q.question_type_id,
                q.difficulty,
                q.tags_json,
                q.note,
                q.stem_tex,
                q.answer_tex,
                q.solution_tex,
                l.legacy_file_path,
                l.detected_chapter,
                l.detected_year,
                l.detected_source,
                l.detected_question_number
            FROM question q
            LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
            WHERE q.question_id IN ({placeholders})
            ORDER BY q.question_id
            """,
            question_ids,
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def trim_text(text: str, length: int) -> str:
    value = " ".join((text or "").split())
    if len(value) <= length:
        return value
    return value[: length - 1] + "…"


def command_show(args: argparse.Namespace) -> None:
    db_path = resolve_project_path(args.db)
    decisions_path = resolve_project_path(args.decisions)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")
    if not decisions_path.exists():
        raise SystemExit(f"同题决策表不存在：{decisions_path}")
    rows = read_rows(decisions_path)
    matches = [row for row in rows if row["review_id"] == args.review_id] if args.review_id else rows
    if not matches:
        raise SystemExit("没有找到匹配的 review_id")
    for row in matches[: max(1, args.limit)]:
        print("=" * 80)
        print(f"review_id: {row['review_id']}")
        print(f"issue_type: {row['issue_type']}")
        print(f"paper_label: {row['paper_label']}")
        print(f"decision: {row['decision']}")
        print(f"question_ids: {row['question_ids']}")
        for question in question_rows(db_path, split_pipe_list(row["question_ids"])):
            print("-" * 80)
            print(f"{question['question_id']} / legacy={question['legacy_id']} / chapter={question['detected_chapter']}")
            print(f"source: {question['detected_year']} {question['detected_source']} #{question['detected_question_number']}")
            print(f"path: {question['legacy_file_path']}")
            print(f"difficulty={question['difficulty']} tags={question['tags_json']}")
            print(f"stem: {trim_text(str(question['stem_tex'] or ''), args.text_limit)}")
            print(f"answer: {trim_text(str(question['answer_tex'] or ''), args.text_limit)}")


def question_markdown(question: dict[str, object], text_limit: int) -> str:
    return f"""- `{question['question_id']}` / 旧 ID `{question['legacy_id']}` / `{question['detected_chapter']}`
  - 来源：{question['detected_year']} {question['detected_source']} 第 {question['detected_question_number']} 题
  - 路径：`{question['legacy_file_path']}`
  - 难度/标签：`{question['difficulty']}` / `{question['tags_json']}`
  - 题干：{trim_text(str(question['stem_tex'] or ''), text_limit)}
  - 答案：{trim_text(str(question['answer_tex'] or ''), text_limit)}"""


def row_markdown(db_path: Path, row: dict[str, str], text_limit: int) -> str:
    questions = question_rows(db_path, split_pipe_list(row["question_ids"]))
    question_text = "\n".join(question_markdown(question, text_limit) for question in questions) or "- 数据库中未找到题目"
    return f"""### `{row['review_id']}`

- 类型：`{row['issue_type']}`
- 试卷位置：{row['paper_label'] or '无'}
- 建议动作：`{row['recommended_action']}`
- 当前决策：`{row['decision']}`
- 题目组：`{row['question_ids']}`
- 备注：{row['note'] or '无'}

{question_text}
"""


def command_report(args: argparse.Namespace) -> None:
    db_path = resolve_project_path(args.db)
    decisions_path = resolve_project_path(args.decisions)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")
    if not decisions_path.exists():
        raise SystemExit(f"同题决策表不存在：{decisions_path}")
    rows = read_rows(decisions_path)
    selected = [row for row in rows if row["decision"] == args.decision] if args.decision else rows
    selected = selected[: max(1, args.limit)]
    decision_counts = Counter(row["decision"] for row in rows)
    issue_counts = Counter(row["issue_type"] for row in rows)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"equivalence_decision_review_helper_{args.stamp}.md"
    blocks = "\n".join(row_markdown(db_path, row, args.text_limit) for row in selected)
    report_path.write_text(
        f"""# 同题决策人工审查辅助报告

> 生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
> 数据库：`{relative_to_root(db_path)}`  
> 决策表：`{relative_to_root(decisions_path)}`  
> 执行方式：只读分析，不修改 CSV、不修改数据库。

## 总览

- 总行数：{len(rows)}
- 本报告展示：{len(selected)}
- decision 分布：{dict(sorted(decision_counts.items()))}
- issue_type 分布：{dict(sorted(issue_counts.items()))}

## 填写建议

- 如果确认只是同题或同源重复，但暂不删除：填 `mark_equivalent`。
- 如果确认都要保留：填 `keep_all`。
- 如果确认要合并到一道 canonical 题：填 `merge_to_canonical`，并填写 `canonical_question_id`。
- 如果确认不是问题：填 `ignore`。
- 不确定时继续保留 `pending`。

## 待审详情

{blocks}
""",
        encoding="utf-8",
    )
    print(f"rows={len(rows)}")
    print(f"selected={len(selected)}")
    print(f"report={relative_to_root(report_path)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="辅助人工审查同题/重复题决策 CSV。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show", help="在终端展示一组或多组待审题。")
    show.add_argument("--db", default=str(DEFAULT_DB))
    show.add_argument("--decisions", default=str(DEFAULT_DECISIONS))
    show.add_argument("--review-id", default="")
    show.add_argument("--limit", type=int, default=10)
    show.add_argument("--text-limit", type=int, default=240)

    report = subparsers.add_parser("report", help="生成同题审查辅助 Markdown。")
    report.add_argument("--db", default=str(DEFAULT_DB))
    report.add_argument("--decisions", default=str(DEFAULT_DECISIONS))
    report.add_argument("--decision", default="pending")
    report.add_argument("--limit", type=int, default=20)
    report.add_argument("--text-limit", type=int, default=360)
    report.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"))

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "show":
        command_show(args)
    elif args.command == "report":
        command_report(args)
    else:
        raise SystemExit(f"未知命令：{args.command}")


if __name__ == "__main__":
    main()
