from __future__ import annotations

import argparse
import json
import sqlite3
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.normalize_question_choices_json import (
    build_cleanup_plan,
    cleanup_question_choices,
    integrity_check,
)
from services.choice_format_service import is_wrapped_choice_value
from services.question_db_service import get_question
from services.export_service import question_to_legacy_tex


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def check(name: str, ok: bool, detail: Any = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="choices_json 归一化烟测。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_db = Path(args.db)
    if not source_db.is_absolute():
        source_db = PROJECT_ROOT / source_db
    source_db = source_db.resolve()
    if not source_db.exists():
        raise SystemExit(f"数据库不存在：{source_db}")

    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mathcyclus_choices_cleanup_smoke_") as tmp_dir:
        temp_db = Path(tmp_dir) / source_db.name
        shutil.copy2(source_db, temp_db)

        plan = build_cleanup_plan(temp_db)
        checks.append(
            check(
                "plan_scanned",
                plan["rows_scanned"] > 0,
                {"rows_scanned": plan["rows_scanned"], "rows_changed": plan["rows_changed"]},
            )
        )

        results: list[dict[str, Any]] = []
        if plan["rows_changed"] > 0:
            before_revision_count = 0
            conn = sqlite3.connect(temp_db)
            try:
                before_revision_count = int(conn.execute("SELECT COUNT(*) FROM question_revision").fetchone()[0])
            finally:
                conn.close()

            results = cleanup_question_choices(temp_db, plan["plan"])
            after_revision_count = 0
            conn = sqlite3.connect(temp_db)
            try:
                after_revision_count = int(conn.execute("SELECT COUNT(*) FROM question_revision").fetchone()[0])
            finally:
                conn.close()

            checks.append(
                check(
                    "cleanup_applied",
                    len(results) == plan["rows_changed"],
                    {"expected": plan["rows_changed"], "actual": len(results)},
                )
            )
            checks.append(
                check(
                    "revision_delta",
                    after_revision_count - before_revision_count == len(results),
                    {"before": before_revision_count, "after": after_revision_count, "expected_delta": len(results)},
                )
            )
        else:
            checks.append(check("already_normalized", True, "no rows required cleanup"))

        question_id = str(results[0].get("question_id") or "") if results else ""
        if not question_id:
            conn = sqlite3.connect(temp_db)
            try:
                row = conn.execute(
                    """
                    SELECT question_id
                    FROM question
                    WHERE choices_json IS NOT NULL AND choices_json != '[]'
                    ORDER BY question_id
                    LIMIT 1
                    """
                ).fetchone()
                question_id = str(row[0]) if row else ""
            finally:
                conn.close()

        question = get_question(str(temp_db), question_id) if question_id else {}
        parsed_choices = json.loads(question.get("choices_json") or "[]") if question else []
        checks.append(
            check(
                "choices_unwrapped",
                bool(question)
                and all(not is_wrapped_choice_value(item) for item in parsed_choices if str(item or "").strip()),
                {"question_id": question_id, "choices_json": question.get("choices_json") if question else ""},
            )
        )
        checks.append(
            check(
                "export_still_wraps",
                bool(question) and "\\choice{{" in question_to_legacy_tex(question),
                question_id,
            )
        )
        checks.append(check("integrity_ok", integrity_check(temp_db) == "ok", integrity_check(temp_db)))

    failed = [item for item in checks if not item["ok"]]
    report = {
        "database": relative_to_root(source_db),
        "status": "failed" if failed else "ok",
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
