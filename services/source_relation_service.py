"""Write helpers for formal paper/book/topic source relations."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from services.database_service import existing_database_connection, row_to_dict
from services.revision_service import insert_question_revision_from_conn


def stable_id(prefix: str, *values: object, length: int = 12) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def display_order_from_number(value: Any, fallback: int = 0) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else int(fallback or 0)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _ensure_question_exists(conn, question_id: str) -> None:
    exists = conn.execute("SELECT 1 FROM question WHERE question_id = ?", (question_id,)).fetchone()
    if not exists:
        raise ValueError(f"题目不存在：{question_id}")


def _insert_relation_revision(
    conn,
    *,
    question_id: str,
    relation_name: str,
    before: dict[str, Any],
    after: dict[str, Any],
    operator: str,
    note: str,
) -> str:
    return insert_question_revision_from_conn(
        conn,
        question_id=question_id,
        change_source="source_relation_edit",
        before={relation_name: before},
        after={relation_name: after},
        operator=operator,
        note=note,
        changed_field_names=[relation_name],
    )


def _paper_by_identity(conn, year: int | None, paper_series: str, track: str, paper_name: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT *
        FROM paper
        WHERE
            ((year = ?) OR (year IS NULL AND ? IS NULL))
            AND paper_series = ?
            AND track = ?
            AND paper_name = ?
        """,
        (year, year, paper_series, track, paper_name),
    ).fetchone()
    return row_to_dict(row)


def _paper_link_snapshot(conn, paper_question_id: str) -> dict[str, Any]:
    return row_to_dict(
        conn.execute(
            """
            SELECT
                pq.*,
                p.year,
                p.paper_series,
                p.track,
                p.paper_name,
                p.source_name
            FROM paper_question pq
            JOIN paper p ON p.paper_id = pq.paper_id
            WHERE pq.paper_question_id = ?
            """,
            (paper_question_id,),
        ).fetchone()
    )


def upsert_question_paper_link(
    db_path: str | None,
    question_id: str,
    *,
    year: int | str | None,
    paper_series: str,
    paper_name: str,
    track: str = "",
    source_name: str = "",
    description: str = "",
    question_number: str = "",
    sub_number: str = "",
    display_order: int | None = None,
    origin_tex: str = "",
    location_tex: str = "",
    operator: str = "streamlit_ui",
) -> dict[str, Any]:
    """Create or update one paper-question relation and record a revision."""
    safe_question_id = _text(question_id)
    safe_paper_series = _text(paper_series) or "G"
    safe_paper_name = _text(paper_name)
    safe_track = _text(track)
    if not safe_question_id:
        raise ValueError("question_id 不能为空")
    if not safe_paper_name:
        raise ValueError("paper_name 不能为空")
    safe_year = coerce_int(year)
    safe_question_number = _text(question_number)
    safe_sub_number = _text(sub_number)
    final_display_order = display_order if display_order is not None else display_order_from_number(safe_question_number)

    with existing_database_connection(db_path) as conn:
        _ensure_question_exists(conn, safe_question_id)
        paper = _paper_by_identity(conn, safe_year, safe_paper_series, safe_track, safe_paper_name)
        if paper:
            paper_id = str(paper["paper_id"])
            conn.execute(
                """
                UPDATE paper
                SET
                    source_name = CASE WHEN ? != '' THEN ? ELSE source_name END,
                    description = CASE WHEN ? != '' THEN ? ELSE description END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE paper_id = ?
                """,
                (_text(source_name), _text(source_name), _text(description), _text(description), paper_id),
            )
        else:
            paper_id = stable_id("P", safe_year or "", safe_paper_series, safe_track, safe_paper_name, length=10)
            conn.execute(
                """
                INSERT INTO paper(paper_id, year, paper_series, track, paper_name, source_name, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    safe_year,
                    safe_paper_series,
                    safe_track,
                    safe_paper_name,
                    _text(source_name) or safe_paper_name,
                    _text(description),
                ),
            )

        existing = conn.execute(
            """
            SELECT *
            FROM paper_question
            WHERE paper_id = ? AND question_id = ? AND question_number = ? AND sub_number = ?
            """,
            (paper_id, safe_question_id, safe_question_number, safe_sub_number),
        ).fetchone()
        paper_question_id = (
            str(existing["paper_question_id"])
            if existing
            else stable_id("PQ", paper_id, safe_question_id, safe_question_number, safe_sub_number, length=12)
        )
        before = _paper_link_snapshot(conn, paper_question_id) if existing else {}
        conn.execute(
            """
            INSERT INTO paper_question(
                paper_question_id, paper_id, question_id, question_number,
                sub_number, display_order, origin_tex, location_tex
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_id, question_id, question_number, sub_number) DO UPDATE SET
                display_order = excluded.display_order,
                origin_tex = excluded.origin_tex,
                location_tex = excluded.location_tex,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                paper_question_id,
                paper_id,
                safe_question_id,
                safe_question_number,
                safe_sub_number,
                int(final_display_order or 0),
                _text(origin_tex),
                _text(location_tex),
            ),
        )
        after = _paper_link_snapshot(conn, paper_question_id)
        revision_id = _insert_relation_revision(
            conn,
            question_id=safe_question_id,
            relation_name="paper_question",
            before=before,
            after=after,
            operator=operator,
            note=f"upsert paper link {paper_question_id}",
        )
        return {"paper_id": paper_id, "paper_question_id": paper_question_id, "revision_id": revision_id, "link": after}


def delete_question_paper_link(
    db_path: str | None,
    paper_question_id: str,
    *,
    operator: str = "streamlit_ui",
) -> dict[str, Any]:
    safe_link_id = _text(paper_question_id)
    if not safe_link_id:
        raise ValueError("paper_question_id 不能为空")
    with existing_database_connection(db_path) as conn:
        before = _paper_link_snapshot(conn, safe_link_id)
        if not before:
            raise KeyError(f"试卷来源关系不存在：{safe_link_id}")
        question_id = str(before.get("question_id") or "")
        conn.execute("DELETE FROM paper_question WHERE paper_question_id = ?", (safe_link_id,))
        revision_id = _insert_relation_revision(
            conn,
            question_id=question_id,
            relation_name="paper_question",
            before=before,
            after={},
            operator=operator,
            note=f"delete paper link {safe_link_id}",
        )
        return {"paper_question_id": safe_link_id, "question_id": question_id, "deleted": True, "revision_id": revision_id}


def _book_by_identity(
    conn,
    title: str,
    publisher: str,
    edition: str,
    grade: str,
    volume: str,
    curriculum_version: str,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT *
        FROM book
        WHERE title = ? AND publisher = ? AND edition = ? AND grade = ? AND volume = ? AND curriculum_version = ?
        """,
        (title, publisher, edition, grade, volume, curriculum_version),
    ).fetchone()
    return row_to_dict(row)


def _book_section_by_identity(conn, book_id: str, parent_section_id: str | None, title: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT *
        FROM book_section
        WHERE
            book_id = ?
            AND ((parent_section_id = ?) OR (parent_section_id IS NULL AND ? IS NULL))
            AND title = ?
        """,
        (book_id, parent_section_id, parent_section_id, title),
    ).fetchone()
    return row_to_dict(row)


def _book_link_snapshot(conn, book_exercise_question_id: str) -> dict[str, Any]:
    return row_to_dict(
        conn.execute(
            """
            SELECT
                beq.*,
                b.title,
                b.publisher,
                b.edition,
                b.grade,
                b.volume,
                s.title AS section_title
            FROM book_exercise_question beq
            JOIN book b ON b.book_id = beq.book_id
            LEFT JOIN book_section s ON s.section_id = beq.section_id
            WHERE beq.book_exercise_question_id = ?
            """,
            (book_exercise_question_id,),
        ).fetchone()
    )


def upsert_question_book_link(
    db_path: str | None,
    question_id: str,
    *,
    title: str,
    publisher: str = "",
    edition: str = "",
    grade: str = "",
    volume: str = "",
    curriculum_version: str = "",
    book_description: str = "",
    section_title: str = "",
    parent_section_id: str | None = None,
    section_level: int | None = None,
    page_start: int | None = None,
    page_end: int | None = None,
    section_sort_order: int | None = None,
    page_number: int | None = None,
    column_name: str = "",
    exercise_number: str = "",
    sub_number: str = "",
    display_order: int | None = None,
    source_note: str = "",
    operator: str = "streamlit_ui",
) -> dict[str, Any]:
    """Create or update one book-exercise relation and record a revision."""
    safe_question_id = _text(question_id)
    safe_title = _text(title)
    if not safe_question_id:
        raise ValueError("question_id 不能为空")
    if not safe_title:
        raise ValueError("教材 title 不能为空")
    publisher = _text(publisher)
    edition = _text(edition)
    grade = _text(grade)
    volume = _text(volume)
    curriculum_version = _text(curriculum_version)
    safe_section_title = _text(section_title)
    safe_exercise_number = _text(exercise_number)
    safe_sub_number = _text(sub_number)
    final_display_order = display_order if display_order is not None else display_order_from_number(safe_exercise_number)

    with existing_database_connection(db_path) as conn:
        _ensure_question_exists(conn, safe_question_id)
        book = _book_by_identity(conn, safe_title, publisher, edition, grade, volume, curriculum_version)
        if book:
            book_id = str(book["book_id"])
            conn.execute(
                """
                UPDATE book
                SET description = CASE WHEN ? != '' THEN ? ELSE description END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE book_id = ?
                """,
                (_text(book_description), _text(book_description), book_id),
            )
        else:
            book_id = stable_id("B", safe_title, publisher, edition, grade, volume, curriculum_version)
            conn.execute(
                """
                INSERT INTO book(book_id, title, publisher, edition, grade, volume, curriculum_version, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (book_id, safe_title, publisher, edition, grade, volume, curriculum_version, _text(book_description)),
            )

        section_id = None
        if safe_section_title:
            section = _book_section_by_identity(conn, book_id, parent_section_id, safe_section_title)
            if section:
                section_id = str(section["section_id"])
                conn.execute(
                    """
                    UPDATE book_section
                    SET section_level = ?, page_start = ?, page_end = ?, sort_order = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE section_id = ?
                    """,
                    (
                        coerce_int(section_level) or section.get("section_level") or 1,
                        coerce_int(page_start),
                        coerce_int(page_end),
                        coerce_int(section_sort_order) or section.get("sort_order") or 0,
                        section_id,
                    ),
                )
            else:
                section_id = stable_id("BS", book_id, parent_section_id or "", safe_section_title)
                conn.execute(
                    """
                    INSERT INTO book_section(
                        section_id, book_id, parent_section_id, title, section_level,
                        page_start, page_end, sort_order
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        section_id,
                        book_id,
                        parent_section_id,
                        safe_section_title,
                        coerce_int(section_level) or 1,
                        coerce_int(page_start),
                        coerce_int(page_end),
                        coerce_int(section_sort_order) or 0,
                    ),
                )

        existing = conn.execute(
            """
            SELECT *
            FROM book_exercise_question
            WHERE
                book_id = ?
                AND ((section_id = ?) OR (section_id IS NULL AND ? IS NULL))
                AND question_id = ?
                AND ((page_number = ?) OR (page_number IS NULL AND ? IS NULL))
                AND column_name = ?
                AND exercise_number = ?
                AND sub_number = ?
            """,
            (
                book_id,
                section_id,
                section_id,
                safe_question_id,
                coerce_int(page_number),
                coerce_int(page_number),
                _text(column_name),
                safe_exercise_number,
                safe_sub_number,
            ),
        ).fetchone()
        book_link_id = (
            str(existing["book_exercise_question_id"])
            if existing
            else stable_id("BEQ", book_id, section_id or "", safe_question_id, page_number or "", column_name, safe_exercise_number, safe_sub_number)
        )
        before = _book_link_snapshot(conn, book_link_id) if existing else {}
        conn.execute(
            """
            INSERT INTO book_exercise_question(
                book_exercise_question_id, book_id, section_id, question_id, page_number,
                column_name, exercise_number, sub_number, display_order, source_note
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(book_exercise_question_id) DO UPDATE SET
                section_id = excluded.section_id,
                page_number = excluded.page_number,
                column_name = excluded.column_name,
                exercise_number = excluded.exercise_number,
                sub_number = excluded.sub_number,
                display_order = excluded.display_order,
                source_note = excluded.source_note,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                book_link_id,
                book_id,
                section_id,
                safe_question_id,
                coerce_int(page_number),
                _text(column_name),
                safe_exercise_number,
                safe_sub_number,
                int(final_display_order or 0),
                _text(source_note),
            ),
        )
        after = _book_link_snapshot(conn, book_link_id)
        revision_id = _insert_relation_revision(
            conn,
            question_id=safe_question_id,
            relation_name="book_exercise_question",
            before=before,
            after=after,
            operator=operator,
            note=f"upsert book link {book_link_id}",
        )
        return {"book_id": book_id, "section_id": section_id or "", "book_exercise_question_id": book_link_id, "revision_id": revision_id, "link": after}


def delete_question_book_link(
    db_path: str | None,
    book_exercise_question_id: str,
    *,
    operator: str = "streamlit_ui",
) -> dict[str, Any]:
    safe_link_id = _text(book_exercise_question_id)
    if not safe_link_id:
        raise ValueError("book_exercise_question_id 不能为空")
    with existing_database_connection(db_path) as conn:
        before = _book_link_snapshot(conn, safe_link_id)
        if not before:
            raise KeyError(f"教材来源关系不存在：{safe_link_id}")
        question_id = str(before.get("question_id") or "")
        conn.execute("DELETE FROM book_exercise_question WHERE book_exercise_question_id = ?", (safe_link_id,))
        revision_id = _insert_relation_revision(
            conn,
            question_id=question_id,
            relation_name="book_exercise_question",
            before=before,
            after={},
            operator=operator,
            note=f"delete book link {safe_link_id}",
        )
        return {"book_exercise_question_id": safe_link_id, "question_id": question_id, "deleted": True, "revision_id": revision_id}


def _topic_module_by_name(conn, name: str) -> dict[str, Any]:
    return row_to_dict(conn.execute("SELECT * FROM topic_module WHERE name = ?", (name,)).fetchone())


def _topic_by_identity(conn, module_id: str, name: str) -> dict[str, Any]:
    return row_to_dict(
        conn.execute(
            """
            SELECT *
            FROM topic
            WHERE ((module_id = ?) OR (module_id IS NULL AND ? IS NULL)) AND name = ?
            """,
            (module_id, module_id, name),
        ).fetchone()
    )


def _topic_link_snapshot(conn, topic_question_id: str) -> dict[str, Any]:
    return row_to_dict(
        conn.execute(
            """
            SELECT
                tq.*,
                t.name AS topic_name,
                t.file_name,
                tm.name AS module_name
            FROM topic_question tq
            JOIN topic t ON t.topic_id = tq.topic_id
            LEFT JOIN topic_module tm ON tm.module_id = t.module_id
            WHERE tq.topic_question_id = ?
            """,
            (topic_question_id,),
        ).fetchone()
    )


def upsert_question_topic_link(
    db_path: str | None,
    question_id: str,
    *,
    module_name: str,
    topic_name: str,
    topic_file_name: str = "",
    module_description: str = "",
    topic_description: str = "",
    module_sort_order: int | None = None,
    group_name: str = "",
    sort_order: int | None = None,
    topic_note: str = "",
    operator: str = "streamlit_ui",
) -> dict[str, Any]:
    """Create or update one topic-question relation and record a revision."""
    safe_question_id = _text(question_id)
    safe_module_name = _text(module_name)
    safe_topic_name = _text(topic_name)
    if not safe_question_id:
        raise ValueError("question_id 不能为空")
    if not safe_module_name:
        raise ValueError("专题模块名不能为空")
    if not safe_topic_name:
        raise ValueError("专题名不能为空")
    safe_group_name = _text(group_name)

    with existing_database_connection(db_path) as conn:
        _ensure_question_exists(conn, safe_question_id)
        module = _topic_module_by_name(conn, safe_module_name)
        if module:
            module_id = str(module["module_id"])
            conn.execute(
                """
                UPDATE topic_module
                SET description = CASE WHEN ? != '' THEN ? ELSE description END,
                    sort_order = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE module_id = ?
                """,
                (
                    _text(module_description),
                    _text(module_description),
                    coerce_int(module_sort_order) or module.get("sort_order") or 0,
                    module_id,
                ),
            )
        else:
            module_id = stable_id("TM", safe_module_name)
            conn.execute(
                """
                INSERT INTO topic_module(module_id, name, description, sort_order)
                VALUES (?, ?, ?, ?)
                """,
                (module_id, safe_module_name, _text(module_description), coerce_int(module_sort_order) or 0),
            )

        topic = _topic_by_identity(conn, module_id, safe_topic_name)
        if topic:
            topic_id = str(topic["topic_id"])
            conn.execute(
                """
                UPDATE topic
                SET
                    file_name = CASE WHEN ? != '' THEN ? ELSE file_name END,
                    description = CASE WHEN ? != '' THEN ? ELSE description END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE topic_id = ?
                """,
                (_text(topic_file_name), _text(topic_file_name), _text(topic_description), _text(topic_description), topic_id),
            )
        else:
            topic_id = stable_id("T", module_id, safe_topic_name)
            conn.execute(
                """
                INSERT INTO topic(topic_id, module_id, name, file_name, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                (topic_id, module_id, safe_topic_name, _text(topic_file_name), _text(topic_description)),
            )

        existing = conn.execute(
            """
            SELECT *
            FROM topic_question
            WHERE topic_id = ? AND question_id = ? AND group_name = ?
            """,
            (topic_id, safe_question_id, safe_group_name),
        ).fetchone()
        topic_link_id = (
            str(existing["topic_question_id"])
            if existing
            else stable_id("TQ", topic_id, safe_question_id, safe_group_name)
        )
        before = _topic_link_snapshot(conn, topic_link_id) if existing else {}
        conn.execute(
            """
            INSERT INTO topic_question(topic_question_id, topic_id, question_id, group_name, sort_order, topic_note)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic_id, question_id, group_name) DO UPDATE SET
                sort_order = excluded.sort_order,
                topic_note = excluded.topic_note,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                topic_link_id,
                topic_id,
                safe_question_id,
                safe_group_name,
                coerce_int(sort_order) or 0,
                _text(topic_note),
            ),
        )
        after = _topic_link_snapshot(conn, topic_link_id)
        revision_id = _insert_relation_revision(
            conn,
            question_id=safe_question_id,
            relation_name="topic_question",
            before=before,
            after=after,
            operator=operator,
            note=f"upsert topic link {topic_link_id}",
        )
        return {"module_id": module_id, "topic_id": topic_id, "topic_question_id": topic_link_id, "revision_id": revision_id, "link": after}


def delete_question_topic_link(
    db_path: str | None,
    topic_question_id: str,
    *,
    operator: str = "streamlit_ui",
) -> dict[str, Any]:
    safe_link_id = _text(topic_question_id)
    if not safe_link_id:
        raise ValueError("topic_question_id 不能为空")
    with existing_database_connection(db_path) as conn:
        before = _topic_link_snapshot(conn, safe_link_id)
        if not before:
            raise KeyError(f"专题来源关系不存在：{safe_link_id}")
        question_id = str(before.get("question_id") or "")
        conn.execute("DELETE FROM topic_question WHERE topic_question_id = ?", (safe_link_id,))
        revision_id = _insert_relation_revision(
            conn,
            question_id=question_id,
            relation_name="topic_question",
            before=before,
            after={},
            operator=operator,
            note=f"delete topic link {safe_link_id}",
        )
        return {"topic_question_id": safe_link_id, "question_id": question_id, "deleted": True, "revision_id": revision_id}
