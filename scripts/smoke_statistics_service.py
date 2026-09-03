from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.statistics_service import get_statistics_from_sqlite


def assert_equal(name: str, actual, expected) -> None:
    if actual != expected:
        raise AssertionError(f"{name}: expected {expected!r}, got {actual!r}")


def insert_question(
    conn: sqlite3.Connection,
    *,
    question_id: str,
    question_type_id: int,
    difficulty: int | None,
    tags: list[str],
    subject: str,
    legacy_path: str,
    canonical_tex: str,
    created_at: datetime,
    updated_at: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO question(
            question_id, question_type_id, difficulty, tags_json, canonical_tex,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            question_id,
            question_type_id,
            difficulty,
            json.dumps(tags, ensure_ascii=False),
            canonical_tex,
            created_at.strftime("%Y-%m-%d %H:%M:%S"),
            updated_at.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.execute(
        """
        INSERT INTO legacy_question_map(
            question_id, legacy_file_path, detected_chapter, content_hash
        )
        VALUES (?, ?, ?, ?)
        """,
        (question_id, legacy_path, subject, question_id.lower()),
    )


def main() -> None:
    now = datetime.now().replace(microsecond=0)
    yesterday = now - timedelta(days=1)
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "stats.sqlite3"
        schema_sql = (PROJECT_ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
        with closing(sqlite3.connect(db_path)) as conn:
            conn.executescript(schema_sql)
            insert_question(
                conn,
                question_id="QSTATS001",
                question_type_id=1,
                difficulty=2,
                tags=["函数", "周期"],
                subject="函数",
                legacy_path="函数/2026/2026-G-测试卷-1-函数.tex",
                canonical_tex="普通题干",
                created_at=now,
                updated_at=now,
            )
            insert_question(
                conn,
                question_id="QSTATS002",
                question_type_id=4,
                difficulty=5,
                tags=["导数"],
                subject="导数",
                legacy_path="导数/2026/2026-G-测试卷-17-导数.tex",
                canonical_tex=r"\begin{tikzpicture}\draw (0,0)--(1,1);\end{tikzpicture}",
                created_at=yesterday,
                updated_at=now,
            )
            insert_question(
                conn,
                question_id="QSTATSWK",
                question_type_id=1,
                difficulty=4,
                tags=["挖空"],
                subject="挖空题",
                legacy_path="挖空题/2026/2026-WK-测试卷-1-挖空题.tex",
                canonical_tex=r"\begin{tikzpicture}\draw (0,0)--(1,1);\end{tikzpicture}",
                created_at=now,
                updated_at=now,
            )
            conn.execute(
                "INSERT INTO paper(paper_id, year, paper_series, paper_name) VALUES (?, ?, ?, ?)",
                ("PWK", 2026, "WK", "挖空测试"),
            )
            conn.execute(
                """
                INSERT INTO paper_question(paper_question_id, paper_id, question_id)
                VALUES (?, ?, ?)
                """,
                ("PQWK", "PWK", "QSTATSWK"),
            )
            conn.execute(
                "INSERT INTO paper(paper_id, year, paper_series, track, paper_name) VALUES (?, ?, ?, ?, ?)",
                ("P2026G", 2026, "G", "新高考", "统计测试卷"),
            )
            conn.execute(
                """
                INSERT INTO paper_question(paper_question_id, paper_id, question_id)
                VALUES (?, ?, ?)
                """,
                ("PQSTATS001", "P2026G", "QSTATS001"),
            )
            conn.execute(
                """
                INSERT INTO paper_question(paper_question_id, paper_id, question_id)
                VALUES (?, ?, ?)
                """,
                ("PQSTATS002", "P2026G", "QSTATS002"),
            )
            conn.execute(
                "INSERT INTO topic_module(module_id, name) VALUES (?, ?)",
                ("TMSTATS", "统计模块"),
            )
            conn.execute(
                "INSERT INTO topic(topic_id, module_id, name) VALUES (?, ?, ?)",
                ("TSTATS", "TMSTATS", "统计专题"),
            )
            conn.execute(
                """
                INSERT INTO topic_question(topic_question_id, topic_id, question_id, sort_order)
                VALUES (?, ?, ?, ?)
                """,
                ("TQSTATS", "TSTATS", "QSTATS001", 1),
            )
            conn.execute(
                "INSERT INTO book(book_id, title) VALUES (?, ?)",
                ("BSTATS", "统计教材"),
            )
            conn.execute(
                """
                INSERT INTO book_exercise_question(book_exercise_question_id, book_id, question_id, display_order)
                VALUES (?, ?, ?, ?)
                """,
                ("BEQSTATS", "BSTATS", "QSTATS002", 1),
            )
            conn.execute(
                """
                INSERT INTO question_asset(asset_id, question_id, role, file_path, original_file_name, mime_type, file_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "ASTATS",
                    "QSTATS002",
                    "problem_image",
                    "assets/questions/QSTATS002/figure_01.png",
                    "figure_01.png",
                    "image/png",
                    "stats-asset-hash",
                ),
            )
            conn.execute(
                """
                INSERT INTO question_revision(
                    revision_id, question_id, change_source, changed_fields_json, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "RSTATS002",
                    "QSTATS002",
                    "manual",
                    json.dumps(["solution_tex"], ensure_ascii=False),
                    now.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            conn.commit()

        stats = get_statistics_from_sqlite(str(db_path))
        assert_equal("source", stats["source"], "sqlite")
        assert_equal("sqlite_primary", stats["sqlite_primary"], True)
        assert_equal("fallback_used", stats["fallback_used"], False)
        assert_equal("total_questions", stats["total_questions"], 2)
        assert_equal("total_tikz", stats["total_tikz"], 1)
        assert_equal("today_new_questions", stats["today_new_questions"], 1)
        assert_equal("today_mod_questions", stats["today_mod_questions"], 1)
        assert_equal("today_new_tikz", stats["today_new_tikz"], 0)
        assert_equal("today_mod_tikz", stats["today_mod_tikz"], 1)
        assert_equal("difficulty_count", stats["difficulty_count"], 2)
        assert_equal("difficulty_dist", stats["difficulty_dist"], {"0-2星 (基础)": 1, "5-6星 (压轴)": 1})
        assert_equal("tag_counts", stats["tag_counts"], {"函数": 1, "周期": 1, "导数": 1})
        assert_equal("subject_counts", stats["subject_counts"], {"函数": 1, "导数": 1})
        assert_equal("type_counts", stats["type_counts"], {"单选题": 1, "解答题": 1})
        assert_equal("paper_relation_count", stats["paper_relation_count"], 2)
        assert_equal("paper_linked_questions", stats["paper_linked_questions"], 2)
        assert_equal("year_counts", stats["year_counts"], {"2026": 2})
        assert_equal("source_series_counts", stats["source_series_counts"], {"G": 2})
        assert_equal("track_counts", stats["track_counts"], {"新高考": 2})
        assert_equal("topic_count", stats["topic_count"], 1)
        assert_equal("topic_link_count", stats["topic_link_count"], 1)
        assert_equal("topic_linked_questions", stats["topic_linked_questions"], 1)
        assert_equal("topic_counts", stats["topic_counts"], {"统计专题": 1})
        assert_equal("book_count", stats["book_count"], 1)
        assert_equal("book_link_count", stats["book_link_count"], 1)
        assert_equal("book_linked_questions", stats["book_linked_questions"], 1)
        assert_equal("book_counts", stats["book_counts"], {"统计教材": 1})
        assert_equal("asset_count", stats["asset_count"], 1)
        assert_equal("asset_linked_questions", stats["asset_linked_questions"], 1)
        assert_equal("revision_source_counts", stats["revision_source_counts"], {"manual": 1})

    print("smoke_statistics_service: status=ok")


if __name__ == "__main__":
    main()
