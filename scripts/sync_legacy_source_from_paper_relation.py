from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
BACKUP_ROOT = PROJECT_ROOT / ".backups" / "sync_legacy_source"
REPORTS_DIR = PROJECT_ROOT / "reports"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def resolve_db_path(path: str | Path) -> Path:
    db_path = Path(path)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return db_path.resolve()


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


def copy_sqlite_database(source_db: Path, backup_db: Path) -> None:
    backup_db.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(source_db)
    backup_conn = sqlite3.connect(backup_db)
    try:
        source_conn.backup(backup_conn)
    finally:
        backup_conn.close()
        source_conn.close()


def stable_id(prefix: str, *values: object, length: int = 14) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def text_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def normalize_line_endings(tex: str) -> str:
    return (tex or "").replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")


def rewrite_problem_header(
    tex: str,
    *,
    year: Any,
    paper_series: str,
    source_name: str,
    question_number: str,
    topic: str,
) -> str:
    header = (
        f"\\begin{{problem}}{{{year or ''}}}{{{paper_series or 'G'}}}"
        f"{{{source_name}}}{{{question_number or ''}}}{{{topic or ''}}}"
    )
    pattern = re.compile(
        r"\\begin\{problem\}"
        r"\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}",
        re.MULTILINE,
    )
    content = normalize_line_endings(tex)
    if pattern.search(content):
        return pattern.sub(lambda _match: header, content, count=1)
    return header + "\n" + content


def fetch_context(conn: sqlite3.Connection, question_id: str) -> dict[str, Any]:
    question = conn.execute("SELECT * FROM question WHERE question_id = ?", (question_id,)).fetchone()
    if question is None:
        raise ValueError(f"Question does not exist: {question_id}")

    legacy = conn.execute("SELECT * FROM legacy_question_map WHERE question_id = ?", (question_id,)).fetchone()
    if legacy is None:
        raise ValueError(f"Question is missing legacy_question_map row: {question_id}")

    paper_links = conn.execute(
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
        WHERE pq.question_id = ?
        ORDER BY p.year, p.paper_name, pq.question_number
        """,
        (question_id,),
    ).fetchall()
    if len(paper_links) != 1:
        raise ValueError(
            f"{question_id} currently has {len(paper_links)} paper_question rows; "
            "this sync script requires exactly one confirmed relation."
        )

    return {
        "question": dict(question),
        "legacy": dict(legacy),
        "paper_link": dict(paper_links[0]),
    }


def target_legacy_path(context: dict[str, Any]) -> Path:
    legacy = context["legacy"]
    paper_link = context["paper_link"]
    old_path = PROJECT_ROOT / str(legacy["legacy_file_path"])
    ensure_inside_project(old_path)

    topic = str(
        legacy.get("detected_topic")
        or legacy.get("detected_chapter")
        or old_path.stem.split("-")[-1]
        or ""
    ).strip()
    filename = (
        f"{paper_link.get('year') or legacy.get('detected_year') or ''}-"
        f"{paper_link.get('paper_series') or 'G'}-"
        f"{paper_link.get('source_name') or paper_link.get('paper_name') or legacy.get('detected_source') or ''}-"
        f"{paper_link.get('question_number') or legacy.get('detected_question_number') or ''}-"
        f"{topic}.tex"
    )
    target = old_path.with_name(filename).resolve()
    ensure_inside_project(target)
    return target


def backup_legacy_file(old_path: Path, backup_root: Path) -> str:
    if not old_path.exists():
        return ""
    target = backup_root / "legacy_before_sync" / old_path.relative_to(PROJECT_ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(old_path, target)
    return relative_to_root(target)


def insert_revision(
    conn: sqlite3.Connection,
    question_id: str,
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    note: str,
) -> str:
    revision_id = stable_id("QR", question_id, datetime.now().isoformat(), note)
    conn.execute(
        """
        INSERT INTO question_revision(
            revision_id, question_id, change_source, changed_fields_json,
            before_json, after_json, operator, note, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            revision_id,
            question_id,
            "manual_source_metadata_sync",
            json.dumps(
                ["legacy_file_path", "raw_source_tex", "canonical_tex"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            json.dumps(before, ensure_ascii=False, separators=(",", ":")),
            json.dumps(after, ensure_ascii=False, separators=(",", ":")),
            "maintenance",
            note,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    return revision_id


def sync_question(db_path: Path, question_id: str, *, apply: bool, stamp: str) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database does not exist: {db_path}")

    backup_root = BACKUP_ROOT / stamp
    backup_db = backup_root / "mathcyclus_before_source_sync.sqlite3"

    with connect_database(db_path) as conn:
        context = fetch_context(conn, question_id)
        old_path = PROJECT_ROOT / str(context["legacy"]["legacy_file_path"])
        ensure_inside_project(old_path)
        new_path = target_legacy_path(context)
        paper_link = context["paper_link"]
        source_name = str(paper_link.get("source_name") or paper_link.get("paper_name") or "").strip()
        target_number = str(paper_link.get("question_number") or "").strip()

    report: dict[str, Any] = {
        "stamp": stamp,
        "mode": "apply" if apply else "dry_run",
        "database": relative_to_root(db_path),
        "database_backup": "",
        "question_id": question_id,
        "old_legacy_file_path": relative_to_root(old_path),
        "new_legacy_file_path": relative_to_root(new_path),
        "target_source_name": source_name,
        "target_question_number": target_number,
        "legacy_file_backup": "",
        "revision_id": "",
        "renamed_file": False,
        "integrity_check": "not_run_in_dry_run",
        "foreign_key_errors": [],
    }
    if not apply:
        return report

    if new_path != old_path and new_path.exists():
        raise FileExistsError(f"Target legacy TeX file already exists, refusing to overwrite: {new_path}")

    copy_sqlite_database(db_path, backup_db)
    report["database_backup"] = relative_to_root(backup_db)
    report["legacy_file_backup"] = backup_legacy_file(old_path, backup_root)

    with connect_database(db_path) as conn:
        context = fetch_context(conn, question_id)
        question = context["question"]
        legacy = context["legacy"]
        paper_link = context["paper_link"]
        topic = str(legacy.get("detected_topic") or legacy.get("detected_chapter") or "").strip()
        source_name = str(paper_link.get("source_name") or paper_link.get("paper_name") or "").strip()
        target_number = str(paper_link.get("question_number") or "").strip()
        old_path = PROJECT_ROOT / str(legacy["legacy_file_path"])
        new_path = target_legacy_path(context)

        raw_before = question.get("raw_source_tex") or ""
        canonical_before = question.get("canonical_tex") or ""
        file_before = old_path.read_text(encoding="utf-8") if old_path.exists() else raw_before or canonical_before

        header_context = {
            "year": paper_link.get("year"),
            "paper_series": str(paper_link.get("paper_series") or "G"),
            "source_name": source_name,
            "question_number": target_number,
            "topic": topic,
        }
        raw_after = rewrite_problem_header(raw_before, **header_context)
        canonical_after = rewrite_problem_header(canonical_before, **header_context)
        file_after = rewrite_problem_header(file_before, **header_context)

        if old_path.exists() and new_path != old_path:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
            report["renamed_file"] = True
        new_path.write_text(file_after, encoding="utf-8")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        before = {
            "legacy_file_path": legacy["legacy_file_path"],
            "detected_source": legacy["detected_source"],
            "detected_question_number": legacy["detected_question_number"],
            "raw_source_tex": raw_before,
            "canonical_tex": canonical_before,
        }
        after = {
            "legacy_file_path": relative_to_root(new_path),
            "detected_source": source_name,
            "detected_question_number": target_number,
            "raw_source_tex": raw_after,
            "canonical_tex": canonical_after,
        }
        conn.execute(
            """
            UPDATE question
            SET legacy_file_path = ?, raw_source_tex = ?, canonical_tex = ?,
                updated_at = ?, last_manual_edit_at = ?
            WHERE question_id = ?
            """,
            (relative_to_root(new_path), raw_after, canonical_after, now, now, question_id),
        )
        conn.execute(
            """
            UPDATE legacy_question_map
            SET legacy_file_path = ?, detected_source = ?, detected_question_number = ?,
                content_hash = ?, updated_at = ?
            WHERE question_id = ?
            """,
            (relative_to_root(new_path), source_name, target_number, text_hash(file_after), now, question_id),
        )
        report["revision_id"] = insert_revision(
            conn,
            question_id,
            before=before,
            after=after,
            note=f"Synced legacy source metadata from confirmed paper_question relation: {source_name} #{target_number}.",
        )
        report["integrity_check"] = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        report["foreign_key_errors"] = [dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
        conn.commit()

    manifest_path = backup_root / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    report["manifest"] = relative_to_root(manifest_path)
    manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def write_markdown_report(report: dict[str, Any], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        f"""# Legacy Source Metadata Sync Report

> Mode: `{report['mode']}`  
> Database: `{report['database']}`  
> Database backup: `{report.get('database_backup') or 'not generated in dry-run'}`

## Sync Item

| question_id | Target source | Target question number | Old legacy path | New legacy path |
| --- | --- | --- | --- | --- |
| `{report['question_id']}` | {report['target_source_name']} | {report['target_question_number']} | `{report['old_legacy_file_path']}` | `{report['new_legacy_file_path']}` |

## Files And Revision

- Legacy TeX backup: `{report.get('legacy_file_backup') or 'not generated in dry-run'}`
- Renamed legacy TeX: `{report.get('renamed_file')}`
- Revision ID: `{report.get('revision_id') or 'not generated in dry-run'}`

## Integrity

- `PRAGMA integrity_check`: `{report['integrity_check']}`
- Foreign key errors: {len(report['foreign_key_errors'])}
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync legacy TeX filename, problem header, and legacy mapping from one confirmed paper_question relation."
    )
    parser.add_argument("question_id", help="Question ID to sync.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path.")
    parser.add_argument("--apply", action="store_true", help="Write changes. Default only performs a dry-run.")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="Report/backup stamp.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = resolve_db_path(args.db)
    report = sync_question(db_path, args.question_id.strip(), apply=bool(args.apply), stamp=args.stamp)
    report_path = REPORTS_DIR / f"sync_legacy_source_{args.stamp}.md"
    write_markdown_report(report, report_path)
    print(f"mode={report['mode']}")
    print(f"question_id={report['question_id']}")
    print(f"old_legacy_file_path={report['old_legacy_file_path']}")
    print(f"new_legacy_file_path={report['new_legacy_file_path']}")
    print(f"report={relative_to_root(report_path)}")
    if report.get("database_backup"):
        print(f"database_backup={report['database_backup']}")


if __name__ == "__main__":
    main()
