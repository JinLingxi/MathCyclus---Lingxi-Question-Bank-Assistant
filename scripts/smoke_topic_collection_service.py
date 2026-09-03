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

from services.export_service import export_topic_to_tex, source_export_default_filename
from services.question_db_service import QuestionListFilters, count_questions, list_questions_page
from services.revision_service import list_question_revisions
from services.schema_migration_service import apply_pending_migrations
from services.topic_service import (
    add_questions_to_topic,
    count_topic_questions,
    delete_topic_question_link,
    get_topic,
    list_topic_groups,
    list_topic_questions,
    resolve_question_lookups,
    update_topic_intro,
    update_topic_question_link,
    upsert_topic,
)


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def check(name: str, ok: bool, detail: Any = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="烟测专题收录服务；只写入临时数据库副本。")
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
    question_count_before = count_questions(str(source_db))

    smoke_parent = PROJECT_ROOT / "data" / "smoke"
    smoke_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mathcyclus_topic_collection_smoke_", dir=smoke_parent) as tmp_dir:
        tmp_root = Path(tmp_dir)
        temp_db = tmp_root / source_db.name
        shutil.copy2(source_db, temp_db)

        migration_report = apply_pending_migrations(str(temp_db), apply=True, backup=False)
        checks.append(
            check(
                "temp_schema_migrated",
                migration_report.get("status") == "ok"
                and int(migration_report.get("after", {}).get("current_version") or 0) >= 2,
                migration_report,
            )
        )

        page = list_questions_page(str(temp_db), QuestionListFilters(limit=2, offset=0))
        question_ids = [str(item["question_id"]) for item in page["items"]]
        checks.append(check("sample_questions_found", len(question_ids) >= 1, question_ids))

        topic = upsert_topic(
            str(temp_db),
            module_name="专题收录 smoke 模块",
            name="专题收录 smoke 专题",
            file_name="topic_collection_smoke.tex",
            description="smoke description",
            problem_intro_tex=r"\section*{专题收录 smoke 题目引言}",
            answer_intro_tex=r"\section*{专题收录 smoke 答案引言}",
            export_note="smoke note",
        )
        topic_id = str(topic.get("topic_id") or "")
        checks.append(check("topic_upserted", bool(topic_id), topic))
        checks.append(
            check(
                "topic_filename_preferred",
                source_export_default_filename("topic", topic) == "topic_collection_smoke.tex",
                source_export_default_filename("topic", topic),
            )
        )

        updated_topic = update_topic_intro(
            str(temp_db),
            topic_id,
            problem_intro_tex=r"\section*{updated problem intro}",
            answer_intro_tex=r"\section*{updated answer intro}",
        )
        checks.append(
            check(
                "topic_intro_updated",
                "updated problem intro" in str(updated_topic.get("problem_intro_tex") or "")
                and "updated answer intro" in str(updated_topic.get("answer_intro_tex") or ""),
                updated_topic,
            )
        )

        lookup_report = resolve_question_lookups(str(temp_db), ",".join(question_ids))
        resolved_ids = [item["question_id"] for item in lookup_report.get("resolved") or []]
        checks.append(check("question_lookup_resolved", resolved_ids == question_ids, lookup_report))

        add_report = add_questions_to_topic(
            str(temp_db),
            topic_id,
            resolved_ids,
            group_name="A组",
            start_order=1,
            topic_note="初次收录",
            operator="smoke_topic_collection",
        )
        checks.append(
            check(
                "questions_added_to_topic",
                int(add_report.get("added_count") or 0) == len(resolved_ids),
                add_report,
            )
        )
        checks.append(check("topic_question_count", count_topic_questions(str(temp_db), topic_id, "A组") == len(resolved_ids)))

        links = list_topic_questions(str(temp_db), topic_id, "A组", limit=10)
        checks.append(check("topic_questions_listed", len(links) == len(resolved_ids), links))
        if links:
            link_id = str(links[0]["topic_question_id"])
            update_report = update_topic_question_link(
                str(temp_db),
                link_id,
                group_name="B组",
                sort_order=9,
                topic_note="移动到 B 组",
                operator="smoke_topic_collection",
            )
            checks.append(
                check(
                    "topic_link_updated",
                    update_report.get("link", {}).get("group_name") == "B组"
                    and int(update_report.get("link", {}).get("sort_order") or 0) == 9,
                    update_report,
                )
            )
            delete_report = delete_topic_question_link(
                str(temp_db),
                link_id,
                operator="smoke_topic_collection",
            )
            checks.append(check("topic_link_deleted", bool(delete_report.get("deleted")), delete_report))

        groups = list_topic_groups(str(temp_db), topic_id)
        checks.append(check("topic_groups_readable", bool(groups), groups))

        export_path = tmp_root / "topic_export.tex"
        export_report = export_topic_to_tex(str(temp_db), topic_id, export_path, project_root=PROJECT_ROOT)
        exported_tex = export_path.read_text(encoding="utf-8") if export_path.exists() else ""
        checks.append(
            check(
                "topic_export_contains_intro_and_problem",
                export_path.exists()
                and "updated problem intro" in exported_tex
                and r"\begin{problem}" in exported_tex,
                export_report,
            )
        )

        revisions = list_question_revisions(str(temp_db), question_id=question_ids[0], limit=20) if question_ids else []
        checks.append(
            check(
                "topic_collection_revisions_written",
                any(row.get("change_source") == "topic_collection" for row in revisions),
                {"question_id": question_ids[0] if question_ids else "", "revision_count": len(revisions)},
            )
        )

    question_count_after = count_questions(str(source_db))
    checks.append(
        check(
            "source_database_unchanged",
            question_count_after == question_count_before,
            {"before": question_count_before, "after": question_count_after},
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
