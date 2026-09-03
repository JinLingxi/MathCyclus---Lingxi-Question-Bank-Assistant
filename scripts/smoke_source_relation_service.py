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

from services.question_db_service import QuestionListFilters, count_questions, list_questions_page
from services.revision_service import list_question_revisions
from services.source_relation_service import (
    delete_question_book_link,
    delete_question_paper_link,
    delete_question_topic_link,
    upsert_question_book_link,
    upsert_question_paper_link,
    upsert_question_topic_link,
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
    parser = argparse.ArgumentParser(description="烟测正式题来源关系服务；只写入临时数据库副本。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    return parser.parse_args()


def row_exists(db_path: Path, table: str, key_field: str, key_value: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(f"SELECT 1 FROM {table} WHERE {key_field} = ? LIMIT 1", (key_value,)).fetchone()
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

    source_question_count_before = count_questions(str(source_db))
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mathcyclus_source_relation_smoke_") as tmp_dir:
        temp_db = Path(tmp_dir) / source_db.name
        shutil.copy2(source_db, temp_db)

        page = list_questions_page(str(temp_db), QuestionListFilters(limit=1, offset=0))
        question_id = page["items"][0]["question_id"] if page["items"] else ""
        checks.append(check("find_sample_question", bool(question_id), question_id))

        paper_result = upsert_question_paper_link(
            str(temp_db),
            question_id,
            year=2099,
            paper_series="SMOKE",
            track="测试",
            paper_name="来源关系 smoke 卷",
            source_name="来源关系 smoke 卷",
            question_number="1",
            sub_number="",
            display_order=1,
            operator="smoke_source_relation",
        )
        paper_result_updated = upsert_question_paper_link(
            str(temp_db),
            question_id,
            year=2099,
            paper_series="SMOKE",
            track="测试",
            paper_name="来源关系 smoke 卷",
            source_name="来源关系 smoke 卷",
            question_number="1",
            sub_number="",
            display_order=8,
            origin_tex="smoke origin",
            operator="smoke_source_relation",
        )
        checks.extend(
            [
                check(
                    "paper_link_created",
                    row_exists(temp_db, "paper_question", "paper_question_id", paper_result["paper_question_id"]),
                    paper_result,
                ),
                check(
                    "paper_link_updated_without_duplicate",
                    paper_result["paper_question_id"] == paper_result_updated["paper_question_id"]
                    and paper_result_updated["link"].get("display_order") == 8,
                    paper_result_updated,
                ),
            ]
        )
        paper_delete = delete_question_paper_link(
            str(temp_db),
            paper_result["paper_question_id"],
            operator="smoke_source_relation",
        )
        checks.append(
            check(
                "paper_link_deleted",
                paper_delete.get("deleted")
                and not row_exists(temp_db, "paper_question", "paper_question_id", paper_result["paper_question_id"]),
                paper_delete,
            )
        )

        book_result = upsert_question_book_link(
            str(temp_db),
            question_id,
            title="来源关系 smoke 教材",
            publisher="smoke 出版社",
            edition="A版",
            grade="高一",
            volume="必修一",
            curriculum_version="smoke 课标",
            section_title="第一章 smoke 章节",
            page_number=12,
            column_name="练习",
            exercise_number="3",
            display_order=3,
            source_note="smoke 教材来源",
            operator="smoke_source_relation",
        )
        checks.append(
            check(
                "book_link_created",
                row_exists(temp_db, "book_exercise_question", "book_exercise_question_id", book_result["book_exercise_question_id"]),
                book_result,
            )
        )
        book_delete = delete_question_book_link(
            str(temp_db),
            book_result["book_exercise_question_id"],
            operator="smoke_source_relation",
        )
        checks.append(
            check(
                "book_link_deleted",
                book_delete.get("deleted")
                and not row_exists(temp_db, "book_exercise_question", "book_exercise_question_id", book_result["book_exercise_question_id"]),
                book_delete,
            )
        )

        topic_result = upsert_question_topic_link(
            str(temp_db),
            question_id,
            module_name="来源关系 smoke 模块",
            topic_name="来源关系 smoke 专题",
            topic_file_name="source_relation_smoke.tex",
            group_name="基础",
            sort_order=1,
            topic_note="smoke 专题来源",
            operator="smoke_source_relation",
        )
        checks.append(
            check(
                "topic_link_created",
                row_exists(temp_db, "topic_question", "topic_question_id", topic_result["topic_question_id"]),
                topic_result,
            )
        )
        topic_delete = delete_question_topic_link(
            str(temp_db),
            topic_result["topic_question_id"],
            operator="smoke_source_relation",
        )
        checks.append(
            check(
                "topic_link_deleted",
                topic_delete.get("deleted")
                and not row_exists(temp_db, "topic_question", "topic_question_id", topic_result["topic_question_id"]),
                topic_delete,
            )
        )

        revisions = list_question_revisions(str(temp_db), question_id=question_id, limit=20)
        checks.append(
            check(
                "source_relation_revisions_written",
                sum(1 for row in revisions if row.get("change_source") == "source_relation_edit") >= 6,
                {"question_id": question_id, "revision_count": len(revisions)},
            )
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
