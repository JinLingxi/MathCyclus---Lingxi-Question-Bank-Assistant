from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAPER_MAPPING = PROJECT_ROOT / "db" / "seed" / "paper_name_mapping.csv"
DEFAULT_EQUIVALENCE_DECISIONS = PROJECT_ROOT / "db" / "seed" / "equivalence_review_decisions_20260902_initial.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"

PAPER_REVIEW_STATUSES = {"pending", "approved", "rejected", "needs_review", "missing_mapping"}
PAPER_TRACKS = {"文科", "理科", "新高考", "综合"}
EQUIVALENCE_DECISIONS = {"pending", "keep_all", "mark_equivalent", "merge_to_canonical", "ignore"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


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


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(file)
        ]


def int_value(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def split_pipe_list(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def paper_mapping_summary(path: Path) -> dict[str, Any]:
    rows = read_csv(path)
    review_counts = Counter(row.get("review_status", "") for row in rows)
    track_counts = Counter(row.get("normalized_track", "") for row in rows)
    year_counts = Counter(row.get("source_year", "") for row in rows)
    unsupported_review_status = [
        row for row in rows if row.get("review_status", "") not in PAPER_REVIEW_STATUSES
    ]
    unsupported_tracks = [
        row for row in rows if row.get("normalized_track", "") not in PAPER_TRACKS
    ]
    missing_required = [
        row
        for row in rows
        if not row.get("source_year")
        or not row.get("source_series")
        or not row.get("source_name")
        or not row.get("normalized_paper_name")
        or not row.get("normalized_track")
    ]

    source_groups: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    normalized_groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        source_key = (
            row.get("source_year", ""),
            row.get("source_series", ""),
            row.get("source_name", ""),
        )
        normalized_key = (
            row.get("source_year", ""),
            row.get("source_series", ""),
            row.get("normalized_track", ""),
            row.get("normalized_paper_name", ""),
        )
        source_groups[source_key].append(row)
        normalized_groups[normalized_key].append(row)

    duplicate_source_keys = {
        " / ".join(key): len(group)
        for key, group in source_groups.items()
        if len(group) > 1
    }
    normalized_merge_groups = [
        {
            "key": " / ".join(key),
            "count": len(group),
            "source_names": sorted({item.get("source_name", "") for item in group}),
            "question_count": sum(int_value(item.get("question_count", "")) for item in group),
        }
        for key, group in normalized_groups.items()
        if len(group) > 1
    ]
    normalized_merge_groups.sort(key=lambda item: (-int(item["question_count"]), item["key"]))

    pending_rows = [row for row in rows if row.get("review_status") != "approved"]
    high_priority_pending = sorted(
        pending_rows,
        key=lambda row: (-int_value(row.get("question_count", "")), row.get("source_year", ""), row.get("source_name", "")),
    )[:30]

    return {
        "path": relative_to_root(path),
        "exists": path.exists(),
        "total": len(rows),
        "review_status_counts": dict(sorted(review_counts.items())),
        "normalized_track_counts": dict(sorted(track_counts.items())),
        "year_counts": dict(sorted(year_counts.items())),
        "pending_or_unapproved": len(pending_rows),
        "approved": review_counts.get("approved", 0),
        "unsupported_review_status_count": len(unsupported_review_status),
        "unsupported_track_count": len(unsupported_tracks),
        "missing_required_count": len(missing_required),
        "duplicate_source_key_count": len(duplicate_source_keys),
        "normalized_merge_group_count": len(normalized_merge_groups),
        "normalized_merge_group_samples": normalized_merge_groups[:20],
        "high_priority_pending": high_priority_pending,
    }


def validate_equivalence_row(row: dict[str, str]) -> list[str]:
    errors: list[str] = []
    decision = row.get("decision", "")
    question_ids = split_pipe_list(row.get("question_ids", ""))
    canonical_question_id = row.get("canonical_question_id", "")

    if decision not in EQUIVALENCE_DECISIONS:
        errors.append(f"unsupported decision: {decision}")
    if len(question_ids) < 2:
        errors.append("question_ids 少于 2 个")
    if decision == "merge_to_canonical":
        if not canonical_question_id:
            errors.append("merge_to_canonical 缺少 canonical_question_id")
        elif canonical_question_id not in question_ids:
            errors.append("canonical_question_id 不在 question_ids 内")
    if decision == "mark_equivalent" and canonical_question_id and canonical_question_id not in question_ids:
        errors.append("mark_equivalent 的 canonical_question_id 不在 question_ids 内")
    return errors


def equivalence_decision_summary(path: Path) -> dict[str, Any]:
    rows = read_csv(path)
    decision_counts = Counter(row.get("decision", "") for row in rows)
    issue_counts = Counter(row.get("issue_type", "") for row in rows)
    invalid_rows = []
    ready_to_apply = []
    for row in rows:
        errors = validate_equivalence_row(row)
        if errors:
            invalid_rows.append({**row, "errors": errors})
        elif row.get("decision") not in {"pending"}:
            ready_to_apply.append(row)

    high_priority_pending = [
        row
        for row in rows
        if row.get("decision") == "pending"
    ][:30]

    return {
        "path": relative_to_root(path),
        "exists": path.exists(),
        "total": len(rows),
        "decision_counts": dict(sorted(decision_counts.items())),
        "issue_type_counts": dict(sorted(issue_counts.items())),
        "pending": decision_counts.get("pending", 0),
        "ready_to_apply": len(ready_to_apply),
        "invalid_count": len(invalid_rows),
        "invalid_samples": invalid_rows[:20],
        "high_priority_pending": high_priority_pending,
    }


def compact_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "无"
    return "，".join(f"`{key or '空'}`={value}" for key, value in counts.items())


def row_label(row: dict[str, str]) -> str:
    if row.get("source_name"):
        return (
            f"`{row.get('source_year')}` / `{row.get('source_series')}` / "
            f"`{row.get('source_name')}` → `{row.get('normalized_track')}` / "
            f"`{row.get('normalized_paper_name')}`，题量 {row.get('question_count') or 0}"
        )
    return (
        f"`{row.get('review_id')}` / `{row.get('issue_type')}` / "
        f"`{row.get('paper_label')}` / `{row.get('question_ids')}`"
    )


def markdown_rows(rows: list[dict[str, str]], limit: int = 20) -> str:
    if not rows:
        return "无"
    return "\n".join(f"- {row_label(row)}" for row in rows[:limit])


def write_report(report: dict[str, Any], md_path: Path, json_path: Path) -> None:
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    paper = report["paper_mapping"]
    equivalence = report["equivalence_decisions"]
    merge_samples = "\n".join(
        f"- `{item['key']}`：{item['count']} 行，题量 {item['question_count']}，来源 {' / '.join(item['source_names'][:8])}"
        for item in paper["normalized_merge_group_samples"]
    ) or "无"
    invalid_equivalence = "\n".join(
        f"- `{row.get('review_id')}`：{'；'.join(row.get('errors', []))}"
        for row in equivalence["invalid_samples"]
    ) or "无"
    blockers = "\n".join(f"- {item}" for item in report["blockers"]) or "无"
    warnings = "\n".join(f"- {item}" for item in report["warnings"]) or "无"

    md_path.write_text(
        f"""# 种子表人工审查状态报告

> 生成时间：{report['created_at']}  
> 试卷映射表：`{paper['path']}`  
> 同题决策表：`{equivalence['path']}`  
> 执行方式：只读 CSV 审查，不修改数据库、不修改 `.tex`。

## 结论

- 状态：`{report['status']}`
- 阻断项：{len(report['blockers'])}
- 警告项：{len(report['warnings'])}

## 阻断项

{blockers}

## 警告项

{warnings}

## 试卷映射表

| 指标 | 数量 |
| --- | ---: |
| 总行数 | {paper['total']} |
| 已 approved | {paper['approved']} |
| 未 approved | {paper['pending_or_unapproved']} |
| 不支持的 review_status | {paper['unsupported_review_status_count']} |
| 不支持的 normalized_track | {paper['unsupported_track_count']} |
| 缺少必要字段 | {paper['missing_required_count']} |
| 重复来源 key | {paper['duplicate_source_key_count']} |
| 规范化后会合并的组 | {paper['normalized_merge_group_count']} |

- review_status 分布：{compact_counts(paper['review_status_counts'])}
- normalized_track 分布：{compact_counts(paper['normalized_track_counts'])}

### 优先审查的试卷映射

{markdown_rows(paper['high_priority_pending'])}

### 规范化合并样例

{merge_samples}

## 同题决策表

| 指标 | 数量 |
| --- | ---: |
| 总行数 | {equivalence['total']} |
| pending | {equivalence['pending']} |
| 可应用决策 | {equivalence['ready_to_apply']} |
| 无效行 | {equivalence['invalid_count']} |

- decision 分布：{compact_counts(equivalence['decision_counts'])}
- issue_type 分布：{compact_counts(equivalence['issue_type_counts'])}

### 优先审查的同题决策

{markdown_rows(equivalence['high_priority_pending'])}

### 无效同题决策样例

{invalid_equivalence}

## 下一步

1. 先审查题量较大的 `paper_name_mapping.csv` 行；
2. 再审查 `equivalence_review_decisions_20260902_initial.csv` 的 10 个 pending；
3. 审查完成后重新运行对应 dry-run；
4. 重新生成综合预览库；
5. 再运行正式库提升 dry-run。
""",
        encoding="utf-8",
    )


def build_report(paper_mapping: Path, equivalence_decisions: Path) -> dict[str, Any]:
    paper = paper_mapping_summary(paper_mapping)
    equivalence = equivalence_decision_summary(equivalence_decisions)
    blockers = []
    warnings = []

    if not paper["exists"]:
        blockers.append("试卷映射表不存在")
    if not equivalence["exists"]:
        blockers.append("同题决策表不存在")
    if paper["unsupported_review_status_count"]:
        blockers.append("试卷映射表存在不支持的 review_status")
    if paper["unsupported_track_count"]:
        blockers.append("试卷映射表存在不支持的 normalized_track")
    if paper["missing_required_count"]:
        blockers.append("试卷映射表存在必要字段缺失")
    if paper["duplicate_source_key_count"]:
        blockers.append("试卷映射表存在重复来源 key")
    if equivalence["invalid_count"]:
        blockers.append("同题决策表存在无效行")

    if paper["pending_or_unapproved"]:
        warnings.append(f"试卷映射表还有 {paper['pending_or_unapproved']} 行未 approved")
    if paper["normalized_merge_group_count"]:
        warnings.append(f"试卷映射表有 {paper['normalized_merge_group_count']} 个规范化合并组，需要人工确认")
    if equivalence["pending"]:
        warnings.append(f"同题决策表还有 {equivalence['pending']} 行 pending")

    return {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "paper_mapping": paper,
        "equivalence_decisions": equivalence,
        "blockers": blockers,
        "warnings": warnings,
        "status": "blocked" if blockers else "warning" if warnings else "ok",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读审查 seed CSV 的人工审核状态。")
    parser.add_argument("--paper-mapping", default=str(DEFAULT_PAPER_MAPPING), help="试卷名称映射 CSV。")
    parser.add_argument("--equivalence-decisions", default=str(DEFAULT_EQUIVALENCE_DECISIONS), help="同题人工决策 CSV。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paper_mapping = resolve_project_path(args.paper_mapping)
    equivalence_decisions = resolve_project_path(args.equivalence_decisions)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = build_report(paper_mapping, equivalence_decisions)
    md_path = REPORTS_DIR / f"seed_review_status_{args.stamp}.md"
    json_path = REPORTS_DIR / f"seed_review_status_{args.stamp}.json"
    write_report(report, md_path, json_path)

    print(f"status={report['status']}")
    print(f"blockers={len(report['blockers'])}")
    print(f"warnings={len(report['warnings'])}")
    print(f"paper_pending={report['paper_mapping']['pending_or_unapproved']}")
    print(f"equivalence_pending={report['equivalence_decisions']['pending']}")
    print(f"report={relative_to_root(md_path)}")
    print(f"json={relative_to_root(json_path)}")


if __name__ == "__main__":
    main()
