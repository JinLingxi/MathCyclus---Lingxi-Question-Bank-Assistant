"""Smoke test atomic batch draft commit on a temporary database copy."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.database_service import readonly_database_connection
from services.import_service import commit_draft_to_question, commit_drafts_to_questions, create_manual_entry_drafts
import services.import_service as import_service_module


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mathcyclus_batch_commit_smoke_") as temp_dir:
        db_path = Path(temp_dir) / SOURCE_DB.name
        shutil.copy2(SOURCE_DB, db_path)

        created = create_manual_entry_drafts(
            str(db_path),
            [
                {"source_item_id": "smoke-batch-ok-1", "stem_tex": r"$x+1=2$", "review_status": "ready"},
                {"source_item_id": "smoke-batch-ok-2", "stem_tex": r"$x+2=3$", "review_status": "ready"},
            ],
            stamp="smoke_batch_commit_ok",
        )
        result = commit_drafts_to_questions(str(db_path), [item["draft_id"] for item in created["results"]])
        assert result["status"] == "committed", result
        assert len(result["committed"]) == 2, result

        book_created = create_manual_entry_drafts(
            str(db_path),
            [{
                "source_item_id": "smoke-book-1",
                "source_label": "教材烟测",
                "stem_tex": r"$a_1+a_2=3$",
                "review_status": "ready",
                "extra": {
                    "source_kind": "教材",
                    "book_title": "教材烟测",
                    "book_page_number": "12",
                    "book_column_name": "课后练习",
                    "book_exercise_number": "3",
                },
            }],
            stamp="smoke_book_commit",
        )
        book_result = commit_drafts_to_questions(str(db_path), [book_created["results"][0]["draft_id"]])
        assert book_result["status"] == "committed", book_result
        with readonly_database_connection(str(db_path)) as conn:
            book_link_count = conn.execute(
                "SELECT COUNT(*) FROM book_exercise_question WHERE question_id = ?",
                (book_result["question_ids"][0],),
            ).fetchone()[0]
            section_count = conn.execute(
                "SELECT COUNT(*) FROM book_section s JOIN book_exercise_question beq ON beq.book_id = s.book_id WHERE beq.question_id = ?",
                (book_result["question_ids"][0],),
            ).fetchone()[0]
        assert book_link_count == 1 and section_count == 1, (book_link_count, section_count)

        paper_extra = {
            "source_kind": "试卷",
            "detected_year": 2025,
            "paper_series": "G",
            "track": "",
            "detected_source": "自动关联冒烟卷",
            "detected_question_number": "1",
            "sub_number": "",
        }
        with readonly_database_connection(str(db_path)) as conn:
            question_count_before_link = conn.execute("SELECT COUNT(*) FROM question").fetchone()[0]
        paper_first = create_manual_entry_drafts(
            str(db_path),
            [{"source_item_id": "smoke-paper-link-1", "stem_tex": r"$x=1$", "answer_tex": "1", "solution_tex": r"x=1", "review_status": "ready", "extra": paper_extra}],
            stamp="smoke_paper_link_first",
        )
        first_commit = commit_draft_to_question(str(db_path), paper_first["results"][0]["draft_id"], require_ready=False)
        paper_second = create_manual_entry_drafts(
            str(db_path),
            [{"source_item_id": "smoke-paper-link-2", "stem_tex": r"$x=1$", "answer_tex": "1", "solution_tex": r"x=1", "review_status": "ready", "extra": paper_extra}],
            stamp="smoke_paper_link_second",
        )
        linked_commit = commit_drafts_to_questions(str(db_path), [paper_second["results"][0]["draft_id"]])
        assert linked_commit["results"][0]["status"] == "linked", linked_commit
        with readonly_database_connection(str(db_path)) as conn:
            question_count = conn.execute("SELECT COUNT(*) FROM question").fetchone()[0]
            source_count = conn.execute("SELECT COUNT(*) FROM paper_question WHERE question_id = ?", (first_commit["question_id"],)).fetchone()[0]
            revision_count = conn.execute("SELECT COUNT(*) FROM question_revision WHERE question_id = ? AND change_source = 'source_relation_edit'", (first_commit["question_id"],)).fetchone()[0]
            report_count = conn.execute("SELECT COUNT(*) FROM import_report_item WHERE batch_id = ? AND status = 'linked'", (paper_second["batch_id"],)).fetchone()[0]
        assert question_count == question_count_before_link + 1, (question_count_before_link, question_count)
        assert source_count == 1 and revision_count == 1 and report_count == 1, (source_count, revision_count, report_count)

        topic_created = create_manual_entry_drafts(
            str(db_path),
            [{
                "source_item_id": "smoke-topic-link-1",
                "stem_tex": r"$y=x$",
                "answer_tex": "x",
                "solution_tex": r"y=x",
                "review_status": "ready",
                "extra": {
                    "source_kind": "专题",
                    "detected_source": "函数专题",
                    "topic_name": "函数专题",
                    "topic_module": "代数",
                    "topic_group": "基础",
                    "topic_note": "smoke",
                },
            }],
            stamp="smoke_topic_link",
        )
        topic_commit = commit_draft_to_question(str(db_path), topic_created["results"][0]["draft_id"], require_ready=False)
        with readonly_database_connection(str(db_path)) as conn:
            topic_link_count = conn.execute("SELECT COUNT(*) FROM topic_question WHERE question_id = ?", (topic_commit["question_id"],)).fetchone()[0]
        assert topic_link_count == 1, topic_link_count

        asset_source = Path(temp_dir) / "rollback-source.txt"
        asset_source.write_text("rollback", encoding="utf-8")
        rollback_created = create_manual_entry_drafts(
            str(db_path),
            [{
                "source_item_id": "smoke-rollback-asset",
                "stem_tex": r"$b_1+b_2=4$",
                "review_status": "ready",
                "assets": [{"role": "source", "source_path": str(asset_source)}],
            }],
            stamp="smoke_asset_rollback",
        )
        original_revision = import_service_module.insert_question_revision_from_conn
        import_service_module.insert_question_revision_from_conn = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("forced smoke failure"))
        try:
            rollback_result = commit_drafts_to_questions(str(db_path), [rollback_created["results"][0]["draft_id"]])
        finally:
            import_service_module.insert_question_revision_from_conn = original_revision
        assert rollback_result["status"] == "failed", rollback_result
        with readonly_database_connection(str(db_path)) as conn:
            rollback_question_count = conn.execute(
                "SELECT COUNT(*) FROM question_import_draft WHERE batch_id = ? AND review_status = 'committed'",
                (rollback_created["batch_id"],),
            ).fetchone()[0]
        assert rollback_question_count == 0
        leaked_assets = list((PROJECT_ROOT / "assets" / "questions").glob("*/rollback-source.txt"))
        assert not leaked_assets, leaked_assets

        failed_batch = create_manual_entry_drafts(
            str(db_path),
            [
                {"source_item_id": "smoke-batch-failed-1", "stem_tex": r"$x=1$", "review_status": "ready"},
                {"source_item_id": "smoke-batch-failed-2", "stem_tex": "", "review_status": "ready"},
            ],
            stamp="smoke_batch_commit_failed",
        )
        failed = commit_drafts_to_questions(str(db_path), [item["draft_id"] for item in failed_batch["results"]])
        assert failed["status"] == "blocked", failed
        with readonly_database_connection(str(db_path)) as conn:
            committed_count = conn.execute(
                "SELECT COUNT(*) FROM question_import_draft WHERE batch_id = ? AND review_status = 'committed'",
                (failed_batch["batch_id"],),
            ).fetchone()[0]
        assert committed_count == 0, committed_count

    print("batch_commit_service_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
