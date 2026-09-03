"""Audit SQLite -> legacy ``.tex`` bridge coverage.

The script is read-only for both SQLite and the legacy question files.  It is
intended to answer whether SQLite cards can safely enter transitional old UI
paths such as the exam basket.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.question_db_service import QuestionListFilters, count_questions, list_questions
from services.sqlite_legacy_adapter import list_sqlite_legacy_cards, resolve_legacy_card_file_path


def relative_to_root(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计 SQLite 到旧 .tex 文件桥接覆盖率。")
    parser.add_argument("--db", default="data/mathcyclus.sqlite3", help="SQLite 数据库路径。")
    parser.add_argument("--limit", type=int, default=0, help="最多扫描多少题；0 表示扫描全部。")
    parser.add_argument("--page-size", type=int, default=100, help="分页读取大小；服务层会限制在 1-100。")
    parser.add_argument("--content-sample", type=int, default=20, help="抽查旧题卡内容结构的题目数。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
    parser.add_argument("--no-report", action="store_true", help="只打印摘要，不写 reports。")
    return parser.parse_args()


def iter_summaries(db_path: str, *, limit: int, page_size: int) -> list[dict[str, Any]]:
    total = count_questions(db_path)
    target = total if limit <= 0 else min(total, limit)
    rows: list[dict[str, Any]] = []
    offset = 0
    safe_page_size = max(1, min(page_size, 100))
    while len(rows) < target:
        batch_limit = min(safe_page_size, target - len(rows))
        batch = list_questions(db_path, QuestionListFilters(limit=batch_limit, offset=offset))
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
    return rows


def audit_bridge(db_path: str, *, limit: int, page_size: int, content_sample: int) -> dict[str, Any]:
    total_questions = count_questions(db_path)
    summaries = iter_summaries(db_path, limit=limit, page_size=page_size)
    unresolved: list[dict[str, str]] = []
    resolved_paths: list[str] = []
    seen_paths: set[str] = set()

    for row in summaries:
        raw_path = str(row.get("legacy_file_path") or "")
        resolved = resolve_legacy_card_file_path({"path": raw_path}, PROJECT_ROOT)
        if resolved:
            if resolved not in seen_paths:
                resolved_paths.append(resolved)
                seen_paths.add(resolved)
            continue
        unresolved.append(
            {
                "question_id": str(row.get("question_id") or ""),
                "legacy_file_path": raw_path,
            }
        )

    content_checks: list[dict[str, Any]] = []
    if content_sample > 0:
        sample_cards = list_sqlite_legacy_cards(
            db_path,
            QuestionListFilters(limit=min(content_sample, 100), offset=0),
        )
        for card in sample_cards:
            resolved = resolve_legacy_card_file_path(card, PROJECT_ROOT)
            old_text = Path(resolved).read_text(encoding="utf-8") if resolved else ""
            card_text = str(card.get("content") or "")
            row = card.get("row") or {}
            content_checks.append(
                {
                    "question_id": card.get("question_id"),
                    "legacy_path": relative_to_root(resolved) if resolved else "",
                    "filename_matches_path": bool(resolved and row.get("文件名称") == Path(resolved).stem),
                    "card_has_problem": "\\begin{problem}" in card_text and "\\end{problem}" in card_text,
                    "old_file_has_problem": "\\begin{problem}" in old_text and "\\end{problem}" in old_text,
                    "card_length": len(card_text),
                    "old_file_length": len(old_text),
                }
            )

    blockers: list[str] = []
    if unresolved:
        blockers.append("存在 SQLite 题目无法解析到项目内旧 .tex 文件。")
    failed_content = [
        item
        for item in content_checks
        if not (item["filename_matches_path"] and item["card_has_problem"] and item["old_file_has_problem"])
    ]
    if failed_content:
        blockers.append("抽样题卡存在旧题卡结构或旧文件结构异常。")

    return {
        "database": db_path,
        "status": "ok" if not blockers else "blocked",
        "total_questions": total_questions,
        "scanned_questions": len(summaries),
        "resolved_paths": len(resolved_paths),
        "unresolved_count": len(unresolved),
        "unresolved_sample": unresolved[:30],
        "content_sample": len(content_checks),
        "content_failures": failed_content[:30],
        "blockers": blockers,
        "writes_formal_database": False,
        "writes_legacy_tex": False,
    }


def write_reports(report: dict[str, Any], stamp: str) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / f"sqlite_legacy_bridge_audit_{stamp}.json"
    md_path = REPORTS_DIR / f"sqlite_legacy_bridge_audit_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# SQLite 到旧题卡桥接审计",
        "",
        f"> 数据库：`{report['database']}`  ",
        f"> 状态：`{report['status']}`  ",
        f"> 扫描题目：`{report['scanned_questions']}` / `{report['total_questions']}`  ",
        f"> 可解析旧路径：`{report['resolved_paths']}`  ",
        f"> 未解析：`{report['unresolved_count']}`  ",
        "",
        "## 结论",
        "",
    ]
    if report["blockers"]:
        lines.extend(f"- {item}" for item in report["blockers"])
    else:
        lines.append("- 当前扫描范围内 SQLite 题卡均能解析到项目内旧 `.tex` 文件。")
        lines.append("- 抽样题卡具备 `problem` 环境，旧文件也具备 `problem` 环境。")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 本脚本只读 SQLite 和旧 `.tex` 文件；",
            "- 不比较 SQLite 规范化 TeX 与旧文件源码是否逐字一致；",
            "- 逐字差异通常来自元数据、空白和规范化导出格式，不应作为迁移阻塞依据。",
        ]
    )
    if report["unresolved_sample"]:
        lines.extend(["", "## 未解析样例", ""])
        lines.extend(
            f"- `{item['question_id']}`：`{item['legacy_file_path']}`"
            for item in report["unresolved_sample"]
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path


def main() -> int:
    args = parse_args()
    report = audit_bridge(
        args.db,
        limit=args.limit,
        page_size=args.page_size,
        content_sample=args.content_sample,
    )
    if not args.no_report:
        md_path, json_path = write_reports(report, args.stamp)
        report["report"] = relative_to_root(md_path)
        report["json"] = relative_to_root(json_path)

    print(f"status={report['status']}")
    print(f"scanned={report['scanned_questions']}")
    print(f"resolved_paths={report['resolved_paths']}")
    print(f"unresolved={report['unresolved_count']}")
    if not args.no_report:
        print(f"report={report['report']}")
        print(f"json={report['json']}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
