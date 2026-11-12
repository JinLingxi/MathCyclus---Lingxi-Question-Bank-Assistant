"""Smoke test for SQLite-backed exam selection helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.question_db_service import count_questions
from services.smart_exam_service import build_candidate_pool, plan_selection, CandidateOptions, ensure_plan_current


def check(name: str, ok: bool, detail=None) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def main() -> int:
    db_path = "data/mathcyclus.sqlite3"
    before_count = count_questions(db_path)
    pool = build_candidate_pool(db_path, options=CandidateOptions(seed=42), limit=500)
    regular = plan_selection(pool, target_count=10, unknown_limit=10)
    quotas = {"single_choice":8,"multiple_choice":3,"fill_blank":3,"solution":5}
    paper_pool = build_candidate_pool(db_path, options=CandidateOptions(seed=42), limit=500, quotas=quotas)
    paper = plan_selection(paper_pool, target_count=19, quotas=quotas, unknown_limit=19)
    ensure_plan_current(db_path, regular["rows"])
    ensure_plan_current(db_path, paper["rows"])
    after_count = count_questions(db_path)
    checks = [
        check("whole_bank_candidates_before_cap", pool["matched_count"] >= len(pool["rows"]), pool["matched_count"]),
        check("formal_type_fields", all(r["type_code"] for r in pool["rows"])),
        check("regular_target_met", regular["ready"] and len(regular["rows"]) == 10),
        check("paper_type_quotas_met", paper["ready"] and len(paper["rows"]) == 19),
        check("question_ids_unique", len({r["question_id"] for r in paper["rows"]}) == len(paper["rows"])),
        check("source_database_count_unchanged", before_count == after_count, {"before":before_count,"after":after_count}),
    ]
    ok = all(c["ok"] for c in checks)
    print(json.dumps({"status":"ok" if ok else "failed", "checks":checks,
        "writes_formal_database":False,"writes_legacy_tex":False}, ensure_ascii=False, indent=2))
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
