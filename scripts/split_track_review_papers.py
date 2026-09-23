from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
DEFAULT_REVIEW_CSV = PROJECT_ROOT / "reports" / "paper_track_review_20260904.csv"
BACKUP_ROOT = PROJECT_ROOT / ".backups" / "split_track_review_papers"
REPORTS_DIR = PROJECT_ROOT / "reports"
TARGET_TRACKS = [
    ("文科", "文"),
    ("理科", "理"),
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


@dataclass(frozen=True)
class ReviewPaper:
    paper_id: str
    year: int | None
    paper_series: str
    current_paper_name: str
    current_source_name: str
    question_count: int


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def resolve_project_path(path: str | Path) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    return target.resolve()


def ensure_inside_project(path: Path) -> None:
    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"Path is outside project root, refusing to process: {path}") from exc


def connect_database(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def stable_id(prefix: str, *values: object, length: int = 14) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def text_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def normalize_line_endings(tex: str) -> str:
    return (tex or "").replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")


def strip_track_suffix(name: str) -> str:
    value = (name or "").strip()
    value = re.sub(r"[（(]\s*(文|文科|理|理科)\s*[）)]$", "", value).strip()
    return value


def source_name_for_track(base_name: str, short_track: str) -> str:
    base = strip_track_suffix(base_name)
    return f"{base}（{short_track}）"


def rewrite_problem_header(
    tex: str,
    *,
    year: Any,
    paper_series: str,
    source_name: str,
    question_number: str,
    topic: str,
    legacy_id: str,
) -> str:
    header = (
        f"\\begin{{problem}}{{{year or ''}}}{{{paper_series or 'G'}}}"
        f"{{{source_name}}}{{{question_number or ''}}}{{{topic or ''}}}"
    )
    content = normalize_line_endings(tex)
    content = re.sub(r"(?m)^% ID:.*$", f"% ID: {legacy_id}", content, count=1)
    pattern = re.compile(
        r"\\begin\{problem\}"
        r"\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}",
        re.MULTILINE,
    )
    if pattern.search(content):
        return pattern.sub(lambda _match: header, content, count=1)
    return header + "\n" + content


def next_question_numbers(conn: sqlite3.Connection) -> tuple[int, int]:
    max_question_number = conn.execute(
        "SELECT MAX(CAST(SUBSTR(question_id, 2) AS INTEGER)) FROM question WHERE question_id GLOB 'Q[0-9]*'"
    ).fetchone()[0] or 0
    max_legacy_number = conn.execute(
        "SELECT MAX(CAST(legacy_id AS INTEGER)) FROM question WHERE legacy_id GLOB '[0-9]*'"
    ).fetchone()[0] or 0
    return int(max_question_number), int(max_legacy_number)


def read_review_papers(path: Path) -> list[ReviewPaper]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    papers: list[ReviewPaper] = []
    for row in rows:
        paper_id = (row.get("paper_id") or "").strip()
        if not paper_id:
            continue
        year_text = (row.get("year") or "").strip()
        papers.append(
            ReviewPaper(
                paper_id=paper_id,
                year=int(year_text) if year_text.isdigit() else None,
                paper_series=(row.get("paper_series") or "G").strip(),
                current_paper_name=(row.get("current_paper_name") or "").strip(),
                current_source_name=(row.get("current_source_name") or "").strip(),
                question_count=int((row.get("question_count") or "0").strip() or 0),
            )
        )
    return papers


def fetch_paper_bundle(conn: sqlite3.Connection, paper_id: str) -> dict[str, Any]:
    paper = conn.execute("SELECT * FROM paper WHERE paper_id = ?", (paper_id,)).fetchone()
    if paper is None:
        raise ValueError(f"Paper does not exist: {paper_id}")
    links = conn.execute(
        """
        SELECT pq.*, q.*, lqm.legacy_file_path, lqm.detected_chapter, lqm.detected_topic
        FROM paper_question pq
        JOIN question q ON q.question_id = pq.question_id
        LEFT JOIN legacy_question_map lqm ON lqm.question_id = q.question_id
        WHERE pq.paper_id = ?
        ORDER BY pq.display_order, CAST(pq.question_number AS INTEGER), pq.question_number, pq.sub_number
        """,
        (paper_id,),
    ).fetchall()
    return {"paper": dict(paper), "links": [dict(row) for row in links]}


def validate_source_questions(conn: sqlite3.Connection, paper_ids: list[str]) -> list[str]:
    errors: list[str] = []
    if not paper_ids:
        return ["No review papers provided."]
    placeholders = ",".join("?" for _ in paper_ids)
    duplicate_sources = conn.execute(
        f"""
        SELECT pq.question_id, COUNT(*) AS relation_count
        FROM paper_question pq
        WHERE pq.question_id IN (
            SELECT question_id FROM paper_question WHERE paper_id IN ({placeholders})
        )
        GROUP BY pq.question_id
        HAVING relation_count > 1
        """,
        tuple(paper_ids),
    ).fetchall()
    for row in duplicate_sources:
        errors.append(
            f"Question {row['question_id']} has {row['relation_count']} paper relations; "
            "manual split is required."
        )

    missing_legacy = conn.execute(
        f"""
        SELECT q.question_id
        FROM paper_question pq
        JOIN question q ON q.question_id = pq.question_id
        LEFT JOIN legacy_question_map lqm ON lqm.question_id = q.question_id
        WHERE pq.paper_id IN ({placeholders}) AND (lqm.legacy_file_path IS NULL OR lqm.legacy_file_path = '')
        """,
        tuple(paper_ids),
    ).fetchall()
    for row in missing_legacy:
        errors.append(f"Question {row['question_id']} is missing legacy_question_map path.")

    equivalence_rows = conn.execute(
        f"""
        SELECT qe.equivalence_id
        FROM question_equivalence qe
        WHERE qe.question_id_a IN (SELECT question_id FROM paper_question WHERE paper_id IN ({placeholders}))
           OR qe.question_id_b IN (SELECT question_id FROM paper_question WHERE paper_id IN ({placeholders}))
        """,
        tuple(paper_ids) * 2,
    ).fetchall()
    if equivalence_rows:
        errors.append(f"{len(equivalence_rows)} existing equivalence rows reference source questions; manual handling required.")
    return errors


def target_legacy_path(source_path: str, source_name: str, question_number: str, topic: str, year: Any, paper_series: str) -> Path:
    old_path = PROJECT_ROOT / source_path
    ensure_inside_project(old_path)
    filename = f"{year or ''}-{paper_series or 'G'}-{source_name}-{question_number or ''}-{topic or old_path.stem.split('-')[-1]}.tex"
    target = old_path.with_name(filename).resolve()
    ensure_inside_project(target)
    return target


def copy_database(source_db: Path, backup_db: Path) -> None:
    backup_db.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(source_db)
    backup_conn = sqlite3.connect(backup_db)
    try:
        source_conn.backup(backup_conn)
    finally:
        backup_conn.close()
        source_conn.close()


def backup_source_file(source_path: Path, backup_root: Path) -> str:
    if not source_path.exists():
        return ""
    target = backup_root / "legacy_before_split" / source_path.relative_to(PROJECT_ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target)
    return relative_to_root(target)


def ensure_target_paper(
    conn: sqlite3.Connection,
    *,
    year: int | None,
    paper_series: str,
    track: str,
    paper_name: str,
    source_name: str,
    now: str,
) -> str:
    existing = conn.execute(
        """
        SELECT paper_id FROM paper
        WHERE year IS ? AND paper_series = ? AND track = ? AND paper_name = ?
        """,
        (year, paper_series, track, paper_name),
    ).fetchone()
    if existing:
        return str(existing["paper_id"])
    paper_id = stable_id("P", year, paper_series, track, paper_name)
    conn.execute(
        """
        INSERT INTO paper(paper_id, year, paper_series, track, paper_name, source_name, description, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            year,
            paper_series,
            track,
            paper_name,
            source_name,
            "由综合卷按默认文理规则拆分创建",
            now,
            now,
        ),
    )
    return paper_id


def insert_question_copy(
    conn: sqlite3.Connection,
    *,
    source: dict[str, Any],
    new_question_id: str,
    new_legacy_id: str,
    new_legacy_path: str,
    raw_tex: str,
    canonical_tex: str,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO question(
            question_id, question_type_id, stem_tex, choices_json, answer_tex, solution_tex,
            difficulty, tags_json, note, official_flag, canonical_tex, raw_source_tex,
            normalized_status, legacy_id, legacy_file_path, usage_count, created_at, updated_at, last_manual_edit_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_question_id,
            source.get("question_type_id"),
            source.get("stem_tex") or "",
            source.get("choices_json") or "[]",
            source.get("answer_tex") or "",
            source.get("solution_tex") or "",
            source.get("difficulty"),
            source.get("tags_json") or "[]",
            source.get("note") or "",
            int(source.get("official_flag") or 0),
            canonical_tex,
            raw_tex,
            source.get("normalized_status") or "raw",
            new_legacy_id,
            new_legacy_path,
            int(source.get("usage_count") or 0),
            now,
            now,
            now,
        ),
    )


def copy_child_rows(conn: sqlite3.Connection, old_question_id: str, new_question_id: str, now: str) -> None:
    analysis = conn.execute("SELECT * FROM question_analysis WHERE question_id = ?", (old_question_id,)).fetchone()
    if analysis:
        conn.execute(
            """
            INSERT INTO question_analysis(
                question_id, target_tex, production_tex, evaluation_tex, marking_data_tex,
                warning_tex, reference_text, extra_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_question_id,
                analysis["target_tex"] or "",
                analysis["production_tex"] or "",
                analysis["evaluation_tex"] or "",
                analysis["marking_data_tex"] or "",
                analysis["warning_tex"] or "",
                analysis["reference_text"] or "",
                analysis["extra_json"] or "{}",
            ),
        )

    for row in conn.execute("SELECT * FROM question_knowledge_area WHERE question_id = ?", (old_question_id,)):
        conn.execute(
            """
            INSERT INTO question_knowledge_area(
                question_id, knowledge_area_id, source, confidence, is_primary, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                new_question_id,
                row["knowledge_area_id"],
                row["source"] or "split_track_review",
                row["confidence"],
                int(row["is_primary"] or 0),
                now,
            ),
        )

    for row in conn.execute("SELECT * FROM question_asset WHERE question_id = ?", (old_question_id,)):
        conn.execute(
            """
            INSERT INTO question_asset(
                asset_id, question_id, role, file_path, original_file_name, mime_type,
                width, height, file_hash, caption, sort_order, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stable_id("QA", new_question_id, row["asset_id"], row["role"], row["file_path"]),
                new_question_id,
                row["role"],
                row["file_path"],
                row["original_file_name"] or "",
                row["mime_type"] or "",
                row["width"],
                row["height"],
                row["file_hash"] or "",
                row["caption"] or "",
                int(row["sort_order"] or 0),
                now,
            ),
        )


def delete_question_cascade(conn: sqlite3.Connection, question_id: str) -> None:
    conn.execute("DELETE FROM question_revision WHERE question_id = ?", (question_id,))
    conn.execute("DELETE FROM question_analysis WHERE question_id = ?", (question_id,))
    conn.execute("DELETE FROM question_asset WHERE question_id = ?", (question_id,))
    conn.execute("DELETE FROM question_equivalence WHERE question_id_a = ? OR question_id_b = ?", (question_id, question_id))
    conn.execute("DELETE FROM question_knowledge_area WHERE question_id = ?", (question_id,))
    conn.execute("DELETE FROM topic_question WHERE question_id = ?", (question_id,))
    conn.execute("DELETE FROM book_exercise_question WHERE question_id = ?", (question_id,))
    conn.execute("DELETE FROM paper_question WHERE question_id = ?", (question_id,))
    conn.execute("DELETE FROM legacy_question_map WHERE question_id = ?", (question_id,))
    conn.execute("DELETE FROM question WHERE question_id = ?", (question_id,))


def insert_legacy_map(
    conn: sqlite3.Connection,
    *,
    source: dict[str, Any],
    new_question_id: str,
    new_legacy_id: str,
    new_legacy_path: str,
    source_name: str,
    question_number: str,
    file_tex: str,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO legacy_question_map(
            question_id, legacy_id, legacy_file_path, content_hash, detected_chapter,
            detected_year, detected_source, detected_question_number, detected_topic,
            scan_status, scan_note, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_question_id,
            new_legacy_id,
            new_legacy_path,
            text_hash(file_tex),
            source.get("detected_chapter") or "",
            source.get("year"),
            source_name,
            question_number,
            source.get("detected_topic") or source.get("detected_chapter") or "",
            "split_track_review",
            f"Copied from {source.get('question_id')} during default Wen/Li split.",
            now,
            now,
        ),
    )


def insert_revision(conn: sqlite3.Connection, question_id: str, before: dict[str, Any], after: dict[str, Any], note: str, now: str) -> None:
    conn.execute(
        """
        INSERT INTO question_revision(
            revision_id, question_id, change_source, changed_fields_json,
            before_json, after_json, operator, note, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            stable_id("QR", question_id, now, note),
            question_id,
            "split_track_review",
            json.dumps(["question_id", "legacy_id", "legacy_file_path", "paper.track", "paper.source_name"], ensure_ascii=False),
            json.dumps(before, ensure_ascii=False, separators=(",", ":")),
            json.dumps(after, ensure_ascii=False, separators=(",", ":")),
            "maintenance",
            note,
            now,
        ),
    )


def build_plan(conn: sqlite3.Connection, review_papers: list[ReviewPaper]) -> tuple[list[dict[str, Any]], list[str]]:
    errors = validate_source_questions(conn, [paper.paper_id for paper in review_papers])
    max_question_number, max_legacy_number = next_question_numbers(conn)
    next_question_number = max_question_number + 1
    next_legacy_number = max_legacy_number + 1
    planned: list[dict[str, Any]] = []
    target_paths_seen: set[str] = set()

    for review in review_papers:
        bundle = fetch_paper_bundle(conn, review.paper_id)
        paper = bundle["paper"]
        base_paper_name = strip_track_suffix(review.current_paper_name or paper.get("paper_name") or review.current_source_name)
        base_source_name = strip_track_suffix(review.current_source_name or paper.get("source_name") or base_paper_name)
        year = paper.get("year")
        paper_series = paper.get("paper_series") or review.paper_series or "G"
        for source in bundle["links"]:
            old_legacy_path = str(source.get("legacy_file_path") or source.get("legacy_file_path:1") or "")
            old_path = PROJECT_ROOT / old_legacy_path
            ensure_inside_project(old_path)
            if not old_path.exists():
                errors.append(f"Legacy TeX file does not exist for {source.get('question_id')}: {old_legacy_path}")
            topic = str(source.get("detected_topic") or source.get("detected_chapter") or old_path.stem.split("-")[-1] or "").strip()
            for track, short_track in TARGET_TRACKS:
                new_question_id = f"Q{next_question_number:06d}"
                new_legacy_id = str(next_legacy_number)
                next_question_number += 1
                next_legacy_number += 1
                target_source_name = source_name_for_track(base_source_name, short_track)
                target_paper_name = base_paper_name
                question_number = str(source.get("question_number") or "")
                target_path = target_legacy_path(old_legacy_path, target_source_name, question_number, topic, year, paper_series)
                rel_target = relative_to_root(target_path)
                if rel_target in target_paths_seen:
                    errors.append(f"Duplicate target legacy path in plan: {rel_target}")
                target_paths_seen.add(rel_target)
                if target_path.exists() and target_path.resolve() != old_path.resolve():
                    existing_text = target_path.read_text(encoding="utf-8")
                    expected_header = (
                        f"\\begin{{problem}}{{{year or ''}}}{{{paper_series or 'G'}}}"
                        f"{{{target_source_name}}}{{{question_number or ''}}}{{{topic or ''}}}"
                    )
                    if expected_header not in existing_text:
                        errors.append(f"Target legacy TeX file already exists: {rel_target}")
                planned.append(
                    {
                        "source_paper": paper,
                        "source_question": source,
                        "track": track,
                        "short_track": short_track,
                        "target_paper_name": target_paper_name,
                        "target_source_name": target_source_name,
                        "target_question_id": new_question_id,
                        "target_legacy_id": new_legacy_id,
                        "target_legacy_file_path": rel_target,
                    }
                )
    return planned, errors


def apply_plan(db_path: Path, planned: list[dict[str, Any]], *, stamp: str) -> dict[str, Any]:
    backup_root = BACKUP_ROOT / stamp
    backup_db = backup_root / "mathcyclus_before_track_split.sqlite3"
    copy_database(db_path, backup_db)

    source_file_backups: dict[str, str] = {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_paper_ids = sorted({item["source_paper"]["paper_id"] for item in planned})
    source_question_ids = sorted({item["source_question"]["question_id"] for item in planned})
    created_question_ids: list[str] = []
    created_paper_ids: set[str] = set()
    created_files: list[str] = []
    reused_existing_targets: list[str] = []
    resolved_targets: dict[tuple[Any, ...], str] = {}

    with connect_database(db_path) as conn:
        existing_track_targets = {
            (
                row["year"],
                row["paper_series"],
                row["track"],
                row["paper_name"],
                row["question_number"],
                row["sub_number"],
            ): row["question_id"]
            for row in conn.execute(
                """
                SELECT p.year, p.paper_series, p.track, p.paper_name, pq.question_number, pq.sub_number, pq.question_id
                FROM paper_question pq
                JOIN paper p ON p.paper_id = pq.paper_id
                """
            )
        }
        existing_legacy_paths = {
            row["legacy_file_path"]: row["question_id"]
            for row in conn.execute("SELECT question_id, legacy_file_path FROM legacy_question_map")
        }

        for item in planned:
            paper = item["source_paper"]
            source = item["source_question"]
            old_legacy_path = str(source["legacy_file_path"])
            old_path = PROJECT_ROOT / old_legacy_path
            if old_legacy_path not in source_file_backups:
                source_file_backups[old_legacy_path] = backup_source_file(old_path, backup_root)
            source_file_text = old_path.read_text(encoding="utf-8")
            raw_before = source.get("raw_source_tex") or source_file_text
            canonical_before = source.get("canonical_tex") or source_file_text
            topic = str(source.get("detected_topic") or source.get("detected_chapter") or old_path.stem.split("-")[-1] or "").strip()
            question_number = str(source.get("question_number") or "")

            raw_after = rewrite_problem_header(
                raw_before,
                year=paper.get("year"),
                paper_series=paper.get("paper_series") or "G",
                source_name=item["target_source_name"],
                question_number=question_number,
                topic=topic,
                legacy_id=item["target_legacy_id"],
            )
            canonical_after = rewrite_problem_header(
                canonical_before,
                year=paper.get("year"),
                paper_series=paper.get("paper_series") or "G",
                source_name=item["target_source_name"],
                question_number=question_number,
                topic=topic,
                legacy_id=item["target_legacy_id"],
            )
            file_after = rewrite_problem_header(
                source_file_text,
                year=paper.get("year"),
                paper_series=paper.get("paper_series") or "G",
                source_name=item["target_source_name"],
                question_number=question_number,
                topic=topic,
                legacy_id=item["target_legacy_id"],
            )

            target_paper_id = ensure_target_paper(
                conn,
                year=paper.get("year"),
                paper_series=paper.get("paper_series") or "G",
                track=item["track"],
                paper_name=item["target_paper_name"],
                source_name=item["target_source_name"],
                now=now,
            )
            created_paper_ids.add(target_paper_id)

            target_question_key = (
                paper.get("year"),
                paper.get("paper_series") or "G",
                item["track"],
                item["target_paper_name"],
                question_number,
                source.get("sub_number") or "",
            )
            if target_question_key in existing_track_targets:
                reused_existing_targets.append(item["target_legacy_file_path"])
                resolved_targets[target_question_key] = existing_track_targets[target_question_key]
                continue

            if item["target_legacy_file_path"] in existing_legacy_paths:
                reused_existing_targets.append(item["target_legacy_file_path"])
                resolved_targets[target_question_key] = existing_legacy_paths[item["target_legacy_file_path"]]
                continue

            target_path = PROJECT_ROOT / item["target_legacy_file_path"]
            ensure_inside_project(target_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(file_after, encoding="utf-8")
            created_files.append(relative_to_root(target_path))

            insert_question_copy(
                conn,
                source=source,
                new_question_id=item["target_question_id"],
                new_legacy_id=item["target_legacy_id"],
                new_legacy_path=item["target_legacy_file_path"],
                raw_tex=raw_after,
                canonical_tex=canonical_after,
                now=now,
            )
            insert_legacy_map(
                conn,
                source=source,
                new_question_id=item["target_question_id"],
                new_legacy_id=item["target_legacy_id"],
                new_legacy_path=item["target_legacy_file_path"],
                source_name=item["target_source_name"],
                question_number=question_number,
                file_tex=file_after,
                now=now,
            )
            copy_child_rows(conn, source["question_id"], item["target_question_id"], now)
            conn.execute(
                """
                INSERT INTO paper_question(
                    paper_question_id, paper_id, question_id, question_number, sub_number,
                    display_order, origin_tex, location_tex, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stable_id("PQ", target_paper_id, item["target_question_id"], question_number, source.get("sub_number") or ""),
                    target_paper_id,
                    item["target_question_id"],
                    question_number,
                    source.get("sub_number") or "",
                    int(source.get("display_order") or 0),
                    source.get("origin_tex") or "",
                    source.get("location_tex") or "",
                    now,
                    now,
                ),
            )
            insert_revision(
                conn,
                item["target_question_id"],
                before={"source_question_id": source["question_id"], "source_paper_id": paper["paper_id"]},
                after={
                    "question_id": item["target_question_id"],
                    "paper_id": target_paper_id,
                    "track": item["track"],
                    "source_name": item["target_source_name"],
                    "legacy_file_path": item["target_legacy_file_path"],
                },
                note=f"Created by default Wen/Li split from {source['question_id']}.",
                now=now,
            )
            created_question_ids.append(item["target_question_id"])
            resolved_targets[target_question_key] = item["target_question_id"]

        by_source: dict[str, dict[str, str]] = {}
        for item in planned:
            source_id = item["source_question"]["question_id"]
            target_question_key = (
                item["source_paper"].get("year"),
                item["source_paper"].get("paper_series") or "G",
                item["track"],
                item["target_paper_name"],
                str(item["source_question"].get("question_number") or ""),
                item["source_question"].get("sub_number") or "",
            )
            resolved_target_id = resolved_targets.get(target_question_key)
            if resolved_target_id:
                by_source.setdefault(source_id, {})[item["track"]] = resolved_target_id
        for source_id, pair in by_source.items():
            left = pair.get("文科")
            right = pair.get("理科")
            if left and right:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO question_equivalence(
                        equivalence_id, question_id_a, question_id_b, relation_type,
                        confidence, review_status, note, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stable_id("QE", left, right, "same_ambiguous_track_source"),
                        left,
                        right,
                        "same_ambiguous_track_source",
                        1.0,
                        "approved",
                        f"Split from one ambiguous-track source question {source_id}.",
                        now,
                    ),
                )

        for question_id in source_question_ids:
            delete_question_cascade(conn, question_id)
        for paper_id in source_paper_ids:
            conn.execute("DELETE FROM paper WHERE paper_id = ?", (paper_id,))
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        fk_errors = [dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
        if integrity != "ok" or fk_errors:
            raise RuntimeError(f"Integrity check failed: {integrity}; fk_errors={fk_errors}")
        conn.commit()

    created_file_set = set(created_files)
    for source_path in source_file_backups:
        if source_path in created_file_set:
            continue
        old_path = PROJECT_ROOT / source_path
        if old_path.exists():
            old_path.unlink()

    manifest = {
        "stamp": stamp,
        "database_backup": relative_to_root(backup_db),
        "source_papers_deleted": source_paper_ids,
        "source_questions_deleted": source_question_ids,
        "created_question_count": len(created_question_ids),
        "created_paper_count": len(created_paper_ids),
        "created_files_count": len(created_files),
        "reused_existing_targets": reused_existing_targets,
        "source_file_backups": source_file_backups,
        "created_question_ids": created_question_ids,
        "created_paper_ids": sorted(created_paper_ids),
        "created_files": created_files,
    }
    manifest_path = backup_root / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest"] = relative_to_root(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def write_report(report: dict[str, Any], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    errors = report.get("errors") or []
    sample_items = report.get("items", [])[:80]
    lines = [
        "# Ambiguous Track Paper Split Report",
        "",
        f"> Mode: `{report['mode']}`  ",
        f"> Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"> Database: `{report['database']}`  ",
        f"> Review CSV: `{report['review_csv']}`",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| Source papers | {report['source_paper_count']} |",
        f"| Source questions | {report['source_question_count']} |",
        f"| Planned new questions | {report['planned_new_question_count']} |",
        f"| Planned new papers | {report['planned_new_paper_count']} |",
        f"| Errors | {len(errors)} |",
        "",
    ]
    if report.get("apply_result"):
        apply_result = report["apply_result"]
        lines.extend(
            [
                "## Apply Result",
                "",
                f"- Database backup: `{apply_result['database_backup']}`",
                f"- Deleted source papers: {len(apply_result['source_papers_deleted'])}",
                f"- Deleted source questions: {len(apply_result['source_questions_deleted'])}",
                f"- Created questions: {apply_result['created_question_count']}",
                f"- Created papers: {apply_result['created_paper_count']}",
                f"- Created legacy TeX files: {apply_result['created_files_count']}",
                f"- Reused existing targets: {len(apply_result.get('reused_existing_targets', []))}",
                f"- Manifest: `{apply_result['manifest']}`",
                "",
            ]
        )
    if errors:
        lines.extend(["## Errors", ""])
        lines.extend(f"- {error}" for error in errors)
        lines.append("")
    lines.extend(
        [
            "## Planned Items Sample",
            "",
            "| source_question | target_question | track | target_source | target_path |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in sample_items:
        lines.append(
            f"| `{item['source_question_id']}` | `{item['target_question_id']}` | "
            f"{item['track']} | {item['target_source_name']} | `{item['target_legacy_file_path']}` |"
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_report(db_path: Path, review_csv: Path, planned: list[dict[str, Any]], errors: list[str], mode: str) -> dict[str, Any]:
    source_papers = sorted({item["source_paper"]["paper_id"] for item in planned})
    source_questions = sorted({item["source_question"]["question_id"] for item in planned})
    target_papers = sorted(
        {
            (
                item["source_paper"].get("year"),
                item["source_paper"].get("paper_series") or "G",
                item["track"],
                item["target_paper_name"],
            )
            for item in planned
        }
    )
    return {
        "mode": mode,
        "database": relative_to_root(db_path),
        "review_csv": relative_to_root(review_csv),
        "source_paper_count": len(source_papers),
        "source_question_count": len(source_questions),
        "planned_new_question_count": len(planned),
        "planned_new_paper_count": len(target_papers),
        "errors": errors,
        "items": [
            {
                "source_paper_id": item["source_paper"]["paper_id"],
                "source_question_id": item["source_question"]["question_id"],
                "target_question_id": item["target_question_id"],
                "target_legacy_id": item["target_legacy_id"],
                "track": item["track"],
                "target_paper_name": item["target_paper_name"],
                "target_source_name": item["target_source_name"],
                "target_legacy_file_path": item["target_legacy_file_path"],
            }
            for item in planned
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把待确认综合卷按默认规则拆成文科、理科两套题。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    parser.add_argument("--review-csv", default=str(DEFAULT_REVIEW_CSV), help="待拆分试卷 CSV。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告/备份时间戳。")
    parser.add_argument("--apply", action="store_true", help="正式写库和写 TeX。默认只预演。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = resolve_project_path(args.db)
    review_csv = resolve_project_path(args.review_csv)
    if not db_path.exists():
        raise SystemExit(f"Database does not exist: {db_path}")
    if not review_csv.exists():
        raise SystemExit(f"Review CSV does not exist: {review_csv}")

    review_papers = read_review_papers(review_csv)
    with connect_database(db_path) as conn:
        planned, errors = build_plan(conn, review_papers)
    report = build_report(db_path, review_csv, planned, errors, "apply" if args.apply else "dry_run")
    if args.apply:
        if errors:
            report_path = REPORTS_DIR / f"split_track_review_papers_{args.stamp}.md"
            write_report(report, report_path)
            raise SystemExit(f"Refusing to apply because validation found {len(errors)} errors. Report: {relative_to_root(report_path)}")
        report["apply_result"] = apply_plan(db_path, planned, stamp=args.stamp)

    report_path = REPORTS_DIR / f"split_track_review_papers_{args.stamp}.md"
    json_path = REPORTS_DIR / f"split_track_review_papers_{args.stamp}.json"
    write_report(report, report_path)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"mode={report['mode']}")
    print(f"source_papers={report['source_paper_count']}")
    print(f"source_questions={report['source_question_count']}")
    print(f"planned_new_questions={report['planned_new_question_count']}")
    print(f"planned_new_papers={report['planned_new_paper_count']}")
    print(f"errors={len(report['errors'])}")
    print(f"report={relative_to_root(report_path)}")
    print(f"json={relative_to_root(json_path)}")
    if report.get("apply_result"):
        print(f"database_backup={report['apply_result']['database_backup']}")


if __name__ == "__main__":
    main()
