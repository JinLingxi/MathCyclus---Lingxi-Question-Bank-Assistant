from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
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

from services.import_service import (
    commit_draft_to_question,
    create_manual_entry_draft,
    get_draft_question,
    update_draft_question_fields,
)
from services.question_db_service import count_questions, get_question
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
    parser = argparse.ArgumentParser(description="烟测草稿审核确认入库服务；只写入临时数据库副本。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    return parser.parse_args()


def paper_link_exists(db_path: Path, question_id: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM paper_question WHERE question_id = ? LIMIT 1",
            (question_id,),
        ).fetchone()
        return bool(row)
    finally:
        conn.close()


def main() -> None:
    args = parse_args()
    source_db = Path(args.db)
    if not source_db.is_absolute():
        source_db = PROJECT_ROOT / source_db
    source_db = source_db.resolve()
    if not source_db.exists():
        raise SystemExit(f"数据库不存在：{source_db}")

    checks: list[dict[str, Any]] = []
    source_question_count_before = count_questions(str(source_db))
    with tempfile.TemporaryDirectory(prefix="mathcyclus_draft_commit_smoke_") as tmp_dir:
        temp_db = Path(tmp_dir) / source_db.name
        shutil.copy2(source_db, temp_db)

        question_count_before = count_questions(str(temp_db))
        insert_draft_result = create_manual_entry_draft(
            str(temp_db),
            {
                "source_item_id": "smoke-draft-commit-insert",
                "source_label": "2026 smoke 卷第1题",
                "proposed_action": "insert",
                "review_status": "ready",
                "question_type_id": 4,
                "stem_tex": r"设 $f(x)=x^2$，求 $f'(x)$。",
                "answer_tex": r"$2x$",
                "solution_tex": r"由幂函数求导公式可得 $f'(x)=2x$。",
                "difficulty": 1,
                "tags": ["smoke", "导数"],
                "note": "临时副本新增入库测试",
                "extra": {
                    "source_kind": "试卷",
                    "detected_year": "2026",
                    "paper_series": "G",
                    "detected_source": "2026 smoke 卷",
                    "detected_question_number": "1",
                    "detected_topic": "导数",
                },
            },
            stamp="smoke_draft_commit_insert",
        )
        insert_draft_id = str(insert_draft_result.get("draft_id") or "")
        field_update_result = update_draft_question_fields(
            str(temp_db),
            insert_draft_id,
            {
                "stem_tex": r"设 $f(x)=x^2+1$，求 $f'(x)$。",
                "tags": ["smoke", "导数", "校订"],
                "note": "临时副本新增入库前字段校订测试",
            },
            operator="smoke_draft_commit",
        )
        insert_result = commit_draft_to_question(str(temp_db), insert_draft_id, operator="smoke_draft_commit")
        inserted_question_id = str(insert_result.get("question_id") or "")
        inserted_question = get_question(str(temp_db), inserted_question_id)
        inserted_draft = get_draft_question(str(temp_db), insert_draft_id)
        inserted_revisions = list_question_revisions(str(temp_db), question_id=inserted_question_id, limit=10)
        checks.extend(
            [
                check("insert_draft_created", bool(insert_draft_id), insert_draft_id),
                check(
                    "draft_field_edit_before_commit",
                    {"stem_tex", "tags_json", "note"}.issubset(set(field_update_result.get("changed_fields") or [])),
                    field_update_result.get("changed_fields"),
                ),
                check(
                    "insert_question_count_incremented",
                    count_questions(str(temp_db)) == question_count_before + 1,
                    {"before": question_count_before, "after": count_questions(str(temp_db))},
                ),
                check(
                    "insert_question_persisted",
                    bool(inserted_question) and inserted_question.get("stem_tex") == r"设 $f(x)=x^2+1$，求 $f'(x)$。",
                    inserted_question_id,
                ),
                check(
                    "insert_draft_marked_committed",
                    inserted_draft.get("review_status") == "committed",
                    inserted_draft.get("review_status"),
                ),
                check(
                    "insert_revision_written",
                    any(row.get("revision_id") == insert_result.get("revision_id") for row in inserted_revisions),
                    {"revision_id": insert_result.get("revision_id"), "revision_count": len(inserted_revisions)},
                ),
                check("insert_paper_link_written", paper_link_exists(temp_db, inserted_question_id), inserted_question_id),
            ]
        )

        try:
            commit_draft_to_question(str(temp_db), insert_draft_id, operator="smoke_draft_commit")
            duplicate_blocked = False
            duplicate_error = ""
        except ValueError as exc:
            duplicate_blocked = "ready/approved" in str(exc)
            duplicate_error = str(exc)
        checks.append(check("committed_draft_cannot_commit_again", duplicate_blocked, duplicate_error))

        update_count_before = count_questions(str(temp_db))
        update_draft_result = create_manual_entry_draft(
            str(temp_db),
            {
                "source_item_id": "smoke-draft-commit-update",
                "source_label": "2026 smoke 卷第1题修订",
                "proposed_action": "update",
                "target_question_id": inserted_question_id,
                "review_status": "ready",
                "question_type_id": 4,
                "stem_tex": r"设 $f(x)=x^2+2$，求 $f'(x)$。",
                "answer_tex": r"$2x$",
                "solution_tex": r"常数项求导为 $0$，所以 $f'(x)=2x$。",
                "difficulty": 2,
                "tags": ["smoke", "导数", "修订"],
                "note": "临时副本更新入库测试",
                "extra": {
                    "source_kind": "试卷",
                    "detected_year": "2026",
                    "paper_series": "G",
                    "detected_source": "2026 smoke 卷",
                    "detected_question_number": "1",
                    "detected_topic": "导数",
                },
            },
            stamp="smoke_draft_commit_update",
        )
        update_draft_id = str(update_draft_result.get("draft_id") or "")
        update_result = commit_draft_to_question(str(temp_db), update_draft_id, operator="smoke_draft_commit")
        updated_question = get_question(str(temp_db), inserted_question_id)
        checks.extend(
            [
                check(
                    "update_question_count_unchanged",
                    count_questions(str(temp_db)) == update_count_before,
                    {"before": update_count_before, "after": count_questions(str(temp_db))},
                ),
                check(
                    "update_question_persisted",
                    updated_question.get("stem_tex") == r"设 $f(x)=x^2+2$，求 $f'(x)$。"
                    and updated_question.get("difficulty") == 2,
                    {"question_id": inserted_question_id, "revision_id": update_result.get("revision_id")},
                ),
                check(
                    "update_draft_marked_committed",
                    get_draft_question(str(temp_db), update_draft_id).get("review_status") == "committed",
                    update_draft_id,
                ),
            ]
        )

        skip_count_before = count_questions(str(temp_db))
        skip_draft_result = create_manual_entry_draft(
            str(temp_db),
            {
                "source_item_id": "smoke-draft-commit-skip",
                "source_label": "smoke 跳过草稿",
                "proposed_action": "skip",
                "review_status": "ready",
                "question_type_id": 5,
                "stem_tex": r"此题仅用于跳过路径测试。",
                "answer_tex": r"略",
                "solution_tex": r"略",
                "difficulty": 1,
                "tags": ["smoke"],
                "extra": {"source_kind": "其他"},
            },
            stamp="smoke_draft_commit_skip",
        )
        skip_draft_id = str(skip_draft_result.get("draft_id") or "")
        skip_result = commit_draft_to_question(str(temp_db), skip_draft_id, operator="smoke_draft_commit")
        checks.extend(
            [
                check(
                    "skip_question_count_unchanged",
                    count_questions(str(temp_db)) == skip_count_before,
                    {"before": skip_count_before, "after": count_questions(str(temp_db))},
                ),
                check("skip_status_returned", skip_result.get("status") == "skipped", skip_result),
                check(
                    "skip_draft_marked_rejected",
                    get_draft_question(str(temp_db), skip_draft_id).get("review_status") == "rejected",
                    skip_draft_id,
                ),
            ]
        )

    source_question_count_after = count_questions(str(source_db))
    checks.append(
        check(
            "source_database_unchanged",
            source_question_count_after == source_question_count_before,
            {"before": source_question_count_before, "after": source_question_count_after},
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
