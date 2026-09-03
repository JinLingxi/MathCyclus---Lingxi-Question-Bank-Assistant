from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAPPING = PROJECT_ROOT / "db" / "seed" / "paper_name_mapping.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


FIELDNAMES = [
    "source_year",
    "source_series",
    "source_track",
    "source_name",
    "normalized_paper_name",
    "normalized_track",
    "question_count",
    "review_status",
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


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def int_value(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def pending_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("review_status") != "approved"]


def eligible_for_auto_approval(row: dict[str, str], max_question_count: int) -> bool:
    if row.get("review_status") == "approved":
        return False
    if row.get("source_track") and row.get("source_track") != row.get("normalized_track"):
        return False
    if not row.get("source_year") or not row.get("source_series"):
        return False
    if not row.get("source_name") or not row.get("normalized_paper_name") or not row.get("normalized_track"):
        return False
    return int_value(row.get("question_count", "")) <= max_question_count


def auto_approved_copy(rows: list[dict[str, str]], max_question_count: int, note: str) -> tuple[list[dict[str, str]], int]:
    changed = 0
    copied = []
    for row in rows:
        next_row = dict(row)
        if eligible_for_auto_approval(next_row, max_question_count=max_question_count):
            next_row["review_status"] = "approved"
            next_row["note"] = note or f"auto-approved draft: question_count <= {max_question_count}"
            changed += 1
        copied.append(next_row)
    return copied, changed


def row_brief(row: dict[str, str]) -> str:
    return (
        f"{row.get('source_year')} / {row.get('source_series')} / "
        f"{row.get('source_name')} -> {row.get('normalized_track')} / "
        f"{row.get('normalized_paper_name')} / count={row.get('question_count')} / "
        f"status={row.get('review_status')}"
    )


def command_list(args: argparse.Namespace) -> None:
    mapping = resolve_project_path(args.mapping)
    if not mapping.exists():
        raise SystemExit(f"映射表不存在：{mapping}")
    rows = pending_rows(read_rows(mapping))
    rows.sort(key=lambda row: (-int_value(row.get("question_count", "")), row.get("source_year", ""), row.get("source_name", "")))
    for row in rows[: max(1, args.limit)]:
        print(row_brief(row))
    print(f"pending={len(rows)}")


def command_draft_auto_approve(args: argparse.Namespace) -> None:
    mapping = resolve_project_path(args.mapping)
    output = resolve_project_path(args.output)
    if not mapping.exists():
        raise SystemExit(f"映射表不存在：{mapping}")
    if output == mapping:
        raise SystemExit("输出路径不能覆盖原映射表；请先生成人工审查副本")

    rows = read_rows(mapping)
    before_counts = Counter(row["review_status"] for row in rows)
    copied, changed = auto_approved_copy(rows, args.max_question_count, args.note)
    after_counts = Counter(row["review_status"] for row in copied)
    write_rows(output, copied)

    print(f"source={relative_to_root(mapping)}")
    print(f"output={relative_to_root(output)}")
    print(f"changed={changed}")
    print(f"before={dict(sorted(before_counts.items()))}")
    print(f"after={dict(sorted(after_counts.items()))}")


def markdown_rows(rows: list[dict[str, str]], limit: int) -> str:
    if not rows:
        return "无"
    return "\n".join(f"- `{row_brief(row)}`" for row in rows[:limit])


def command_report(args: argparse.Namespace) -> None:
    mapping = resolve_project_path(args.mapping)
    if not mapping.exists():
        raise SystemExit(f"映射表不存在：{mapping}")
    rows = read_rows(mapping)
    pending = pending_rows(rows)
    pending.sort(key=lambda row: (-int_value(row.get("question_count", "")), row.get("source_year", ""), row.get("source_name", "")))
    eligible = [row for row in rows if eligible_for_auto_approval(row, args.max_question_count)]
    eligible.sort(key=lambda row: (-int_value(row.get("question_count", "")), row.get("source_year", ""), row.get("source_name", "")))
    review_counts = Counter(row["review_status"] for row in rows)
    track_counts = Counter(row["normalized_track"] for row in rows)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"paper_mapping_review_helper_{args.stamp}.md"
    report_path.write_text(
        f"""# 试卷映射人工审查辅助报告

> 生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
> 映射表：`{relative_to_root(mapping)}`  
> 执行方式：只读分析，不修改 CSV。

## 总览

| 指标 | 数量 |
| --- | ---: |
| 总行数 | {len(rows)} |
| 未 approved | {len(pending)} |
| 可批量候选 | {len(eligible)} |

- review_status：{dict(sorted(review_counts.items()))}
- normalized_track：{dict(sorted(track_counts.items()))}

## 优先人工审查

{markdown_rows(pending, args.limit)}

## 可批量 approved 候选

当前规则：

- `question_count <= {args.max_question_count}`；
- `source_track` 为空，或者等于 `normalized_track`；
- 必要字段不为空；
- 当前不是 `approved`。

{markdown_rows(eligible, args.limit)}

## 建议命令

```text
python scripts/review_paper_mapping.py draft-auto-approve --max-question-count {args.max_question_count} --output db/seed/paper_name_mapping.reviewed.csv
```

该命令只生成副本，不覆盖原表。人工确认后再决定是否替换 `db/seed/paper_name_mapping.csv`。
""",
        encoding="utf-8",
    )
    print(f"rows={len(rows)}")
    print(f"pending={len(pending)}")
    print(f"eligible={len(eligible)}")
    print(f"report={relative_to_root(report_path)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="辅助人工审查试卷名称映射 CSV。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list-pending", help="按题量列出待审试卷映射。")
    list_parser.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    list_parser.add_argument("--limit", type=int, default=30)

    report_parser = subparsers.add_parser("report", help="生成试卷映射审查辅助报告。")
    report_parser.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    report_parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    report_parser.add_argument("--limit", type=int, default=30)
    report_parser.add_argument("--max-question-count", type=int, default=3)

    approve_parser = subparsers.add_parser("draft-auto-approve", help="生成批量 approved 副本，不覆盖原表。")
    approve_parser.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    approve_parser.add_argument("--output", required=True)
    approve_parser.add_argument("--max-question-count", type=int, default=3)
    approve_parser.add_argument("--note", default="")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "list-pending":
        command_list(args)
    elif args.command == "report":
        command_report(args)
    elif args.command == "draft-auto-approve":
        command_draft_auto_approve(args)
    else:
        raise SystemExit(f"未知命令：{args.command}")


if __name__ == "__main__":
    main()
