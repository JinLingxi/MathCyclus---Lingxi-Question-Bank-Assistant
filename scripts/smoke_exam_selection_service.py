"""Smoke test for SQLite-backed exam selection helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.exam_selection_service import DEFAULT_HIGH_EXAM_SUBJECTS, legacy_rows_to_existing_paths, select_exam_rows
from services.question_db_service import QuestionListFilters, count_questions
from services.sqlite_legacy_adapter import list_sqlite_legacy_rows


CHAPTERS_DIR = PROJECT_ROOT / "chapters"
SUBJECTS = sorted({path.name for path in CHAPTERS_DIR.iterdir() if path.is_dir()} | set(DEFAULT_HIGH_EXAM_SUBJECTS))


def check(name: str, ok: bool, detail=None) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def main() -> int:
    db_path = "data/mathcyclus.sqlite3"
    before_count = count_questions(db_path)
    rows = list_sqlite_legacy_rows(db_path, QuestionListFilters(limit=20, offset=0))
    all_rows = list_sqlite_legacy_rows(db_path, QuestionListFilters(limit=100, offset=0), max_rows=0)
    regular_result = select_exam_rows(
        all_rows,
        ["高考范围"],
        all_subjects=SUBJECTS,
        target_count=10,
        is_paper_template=False,
        target_difficulty=3.0,
        intent_text="侧重函数与导数，不要太难",
        random_seed=42,
    )
    paper_result = select_exam_rows(
        all_rows,
        ["高考范围"],
        all_subjects=SUBJECTS,
        target_count=19,
        is_paper_template=True,
        target_difficulty=3.0,
        intent_text="最后一道导数压轴",
        random_seed=42,
    )
    regular_paths = legacy_rows_to_existing_paths(
        regular_result["selected_rows"],
        project_root=PROJECT_ROOT,
        chapters_dir=CHAPTERS_DIR,
    )
    paper_paths = legacy_rows_to_existing_paths(
        paper_result["selected_rows"],
        project_root=PROJECT_ROOT,
        chapters_dir=CHAPTERS_DIR,
    )
    after_count = count_questions(db_path)

    checks = [
        check("sqlite_legacy_rows_returned", bool(rows), len(rows)),
        check(
            "sqlite_legacy_rows_have_selection_fields",
            all(key in (rows[0] if rows else {}) for key in ["相对文件路径", "知识板块", "题型", "难度星级", "题干", "答案", "解析"]),
            rows[0] if rows else {},
        ),
        check("regular_selection_target_met", len(regular_paths) == 10, {"selected": len(regular_paths), "candidates": regular_result["candidate_count"]}),
        check("regular_selection_paths_exist", all(Path(path).exists() for path in regular_paths), regular_paths[:3]),
        check("paper_selection_nonempty", bool(paper_paths), {"selected": len(paper_paths), "candidates": paper_result["candidate_count"]}),
        check("selection_paths_unique", len(regular_paths) == len(set(regular_paths)) and len(paper_paths) == len(set(paper_paths))),
        check("source_database_unchanged", before_count == after_count, {"before": before_count, "after": after_count}),
    ]
    ok = all(item["ok"] for item in checks)
    print(
        json.dumps(
            {
                "source_database": db_path,
                "status": "ok" if ok else "failed",
                "checks": checks,
                "writes_formal_database": False,
                "writes_legacy_tex": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
