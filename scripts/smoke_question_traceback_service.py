from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from services.question_db_service import (
    QuestionListFilters,
    count_questions,
    get_question_bank_availability,
    list_questions_page,
)
from services.traceback_service import ASSET_ISSUE_LABELS, get_question_traceback


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def check(name: str, ok: bool, detail: Any = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test the read-only question traceback service.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    db_path = db_path.resolve()
    if not db_path.exists():
        raise SystemExit(f"SQLite database does not exist: {db_path}")

    checks: list[dict[str, Any]] = []
    question_count_before = count_questions(str(db_path))
    checks.append(check("question_count", question_count_before > 0, question_count_before))
    availability = get_question_bank_availability(str(db_path))
    checks.append(
        check(
            "question_bank_availability_ready",
            availability.get("ready_for_browse") is True
            and availability.get("question_count") == question_count_before,
            availability,
        )
    )

    with tempfile.TemporaryDirectory(prefix="mathcyclus_traceback_availability_smoke_") as temp_dir:
        empty_db = Path(temp_dir) / "empty.sqlite3"
        schema_sql = (PROJECT_ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
        with closing(sqlite3.connect(empty_db)) as conn:
            conn.executescript(schema_sql)
            conn.commit()
        empty_availability = get_question_bank_availability(str(empty_db))
        checks.append(
            check(
                "question_bank_availability_empty",
                empty_availability.get("status") == "empty"
                and empty_availability.get("ready_for_browse") is False,
                empty_availability,
            )
        )
        missing_availability = get_question_bank_availability(str(Path(temp_dir) / "missing.sqlite3"))
        checks.append(
            check(
                "question_bank_availability_missing",
                missing_availability.get("status") == "missing"
                and missing_availability.get("ready_for_browse") is False,
                missing_availability,
            )
        )

    page = list_questions_page(str(db_path), QuestionListFilters(limit=1, offset=0))
    question_id = page["items"][0]["question_id"] if page["items"] else ""
    checks.append(check("sample_question_found", bool(question_id), question_id))

    traceback = get_question_traceback(str(db_path), question_id, project_root=PROJECT_ROOT) if question_id else {}
    counts = traceback.get("counts") or {}
    issue_keys = [key for _, key in ASSET_ISSUE_LABELS]
    checks.extend(
        [
            check("traceback_exists", bool(traceback.get("exists")), traceback.get("question_id")),
            check("traceback_summary", bool(traceback.get("summary")), traceback.get("summary")),
            check("source_rows_are_list", isinstance(traceback.get("source_rows"), list), traceback.get("source_rows")),
            check(
                "asset_issue_rows_are_list",
                isinstance(traceback.get("asset_issue_rows"), list),
                traceback.get("asset_issue_rows"),
            ),
            check(
                "source_count_matches_links",
                counts.get("source")
                == len(traceback.get("paper_links") or [])
                + len(traceback.get("book_links") or [])
                + len(traceback.get("topic_links") or []),
                counts,
            ),
            check(
                "asset_count_matches_links",
                counts.get("asset") == len(traceback.get("assets") or []),
                counts,
            ),
            check(
                "asset_issue_count_matches_detail",
                counts.get("asset_issue")
                == sum(len((traceback.get("asset_issues") or {}).get(key) or []) for key in issue_keys),
                counts,
            ),
        ]
    )

    missing = get_question_traceback(str(db_path), "__missing_question__", project_root=PROJECT_ROOT)
    checks.append(check("missing_question_safe", not missing.get("exists") and missing.get("summary") == "暂无资料", missing))

    question_count_after = count_questions(str(db_path))
    checks.append(
        check(
            "source_database_unchanged",
            question_count_after == question_count_before,
            {"before": question_count_before, "after": question_count_after},
        )
    )

    failed = [item for item in checks if not item["ok"]]
    report = {
        "database": relative_to_root(db_path),
        "status": "failed" if failed else "ok",
        "checks": checks,
        "writes_formal_database": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
