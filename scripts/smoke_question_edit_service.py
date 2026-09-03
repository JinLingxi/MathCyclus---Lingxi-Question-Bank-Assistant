from __future__ import annotations

import argparse
import json
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

from services.question_db_service import QuestionListFilters, list_questions_page
from services.question_db_service import get_question
from services.question_edit_service import (
    edit_form_to_question_updates_with_canonical,
    get_question_edit_state,
    question_to_edit_form,
    update_question_fields,
    visible_question_edit_fields,
)
from services.revision_service import list_question_revisions


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def check(name: str, ok: bool, detail: Any = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="烟测题目编辑服务层；只写入临时数据库副本。")
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
    with tempfile.TemporaryDirectory(prefix="mathcyclus_edit_smoke_") as tmp_dir:
        temp_db = Path(tmp_dir) / source_db.name
        shutil.copy2(source_db, temp_db)

        page = list_questions_page(str(temp_db), QuestionListFilters(limit=1, offset=0))
        question_id = page["items"][0]["question_id"] if page["items"] else ""
        checks.append(check("find_sample_question", bool(question_id), question_id))
        question = get_question(str(temp_db), question_id)
        form_payload = question_to_edit_form(question)
        checks.append(
            check(
                "build_edit_form",
                set(visible_question_edit_fields()).issubset(form_payload.keys()),
                sorted(form_payload.keys()),
            )
        )
        edit_state = get_question_edit_state(str(temp_db), question_id, revision_limit=5)
        checks.append(
            check(
                "build_edit_state",
                edit_state["question_id"] == question_id
                and set(visible_question_edit_fields()).issubset(edit_state["form"].keys())
                and isinstance(edit_state["question_types"], list)
                and isinstance(edit_state["revisions"], list),
                {
                    "question_id": edit_state["question_id"],
                    "field_count": len(edit_state["visible_fields"]),
                    "type_count": len(edit_state["question_types"]),
                    "revision_count": len(edit_state["revisions"]),
                },
            )
        )
        form_payload["note"] = "smoke_question_edit_service 临时写入验证"
        updates = edit_form_to_question_updates_with_canonical(question, form_payload)
        checks.append(
            check(
                "build_canonical_update",
                "canonical_tex" in updates,
                sorted(updates.keys()),
            )
        )

        update_result = update_question_fields(
            str(temp_db),
            question_id,
            updates,
            operator="smoke",
            note="临时副本写入测试；不修改正式库",
            change_source="smoke_question_edit_service",
        )
        checks.append(
            check(
                "update_question_note",
                "note" in update_result["changed_fields"] and bool(update_result["revision_id"]),
                {
                    "changed_fields": update_result["changed_fields"],
                    "revision_id": update_result["revision_id"],
                },
            )
        )
        updated_question = get_question(str(temp_db), question_id)
        checks.append(
            check(
                "metadata_update_persisted",
                updated_question.get("note") == form_payload["note"]
                and form_payload["note"] in str(updated_question.get("canonical_tex") or ""),
                {
                    "note": updated_question.get("note"),
                    "canonical_has_note": form_payload["note"] in str(updated_question.get("canonical_tex") or ""),
                },
            )
        )

        revisions = list_question_revisions(str(temp_db), question_id=question_id, limit=5)
        checks.append(
            check(
                "revision_written",
                any(row.get("revision_id") == update_result["revision_id"] for row in revisions),
                {"question_id": question_id, "revision_count": len(revisions)},
            )
        )

    failed = [item for item in checks if not item["ok"]]
    report = {
        "source_database": relative_to_root(source_db),
        "status": "failed" if failed else "ok",
        "checks": checks,
        "writes_formal_database": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
