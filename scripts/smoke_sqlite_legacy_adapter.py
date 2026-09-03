"""Smoke test for the read-only SQLite -> legacy UI adapter."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.question_db_service import QuestionListFilters, count_questions
from services.sqlite_legacy_adapter import (
    LEGACY_CSV_HEADERS,
    list_resolved_legacy_card_paths,
    list_sqlite_legacy_cards,
    resolve_legacy_card_file_path,
)


def check(name: str, ok: bool, detail=None) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def main() -> int:
    db_path = "data/mathcyclus.sqlite3"
    before_count = count_questions(db_path)
    cards = list_sqlite_legacy_cards(
        db_path,
        QuestionListFilters(chapter="三角函数", limit=5, offset=0),
    )
    after_count = count_questions(db_path)

    checks = []
    checks.append(check("cards_returned", bool(cards), len(cards)))

    first = cards[0] if cards else {}
    row = first.get("row") or {}
    missing_headers = [header for header in LEGACY_CSV_HEADERS if header not in row]
    checks.append(check("legacy_csv_headers_present", not missing_headers, missing_headers))
    checks.append(check("legacy_tex_present", "\\begin{problem}" in str(first.get("content") or ""), first.get("question_id")))
    checks.append(check("legacy_card_identity_present", bool(first.get("label") and first.get("path") and first.get("file")), first))
    resolved_path = resolve_legacy_card_file_path(first, PROJECT_ROOT) if first else ""
    checks.append(check("legacy_card_path_resolves", bool(resolved_path and Path(resolved_path).exists()), resolved_path))
    resolved_sample = [resolve_legacy_card_file_path(card, PROJECT_ROOT) for card in cards]
    summary_paths = list_resolved_legacy_card_paths(
        db_path,
        QuestionListFilters(chapter="三角函数", limit=5, offset=0),
        project_root=PROJECT_ROOT,
    )
    checks.append(
        check(
            "legacy_card_paths_resolve_for_page",
            all(Path(path).exists() for path in resolved_sample if path) and len([path for path in resolved_sample if path]) == len(cards),
            {"cards": len(cards), "resolved": len([path for path in resolved_sample if path])},
        )
    )
    checks.append(
        check(
            "legacy_summary_paths_resolve_for_page",
            len(summary_paths) == len(cards) and all(Path(path).exists() for path in summary_paths),
            {"cards": len(cards), "summary_paths": len(summary_paths)},
        )
    )
    checks.append(
        check(
            "legacy_search_fields_present",
            all(key in row for key in ["文件名称", "试卷名称", "知识板块", "标签", "备注", "题干", "答案", "解析", "难度星级"]),
            {key: row.get(key) for key in ["文件名称", "试卷名称", "知识板块", "题型"]},
        )
    )
    checks.append(check("source_database_unchanged", before_count == after_count, {"before": before_count, "after": after_count}))

    ok = all(item["ok"] for item in checks)
    print(
        json.dumps(
            {
                "source_database": db_path,
                "status": "ok" if ok else "failed",
                "checks": checks,
                "writes_formal_database": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
