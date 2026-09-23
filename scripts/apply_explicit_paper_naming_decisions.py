"""Apply explicitly confirmed paper naming decisions with a database backup."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "mathcyclus.sqlite3"


def normalize_confirmed_name(year: int | None, name: str) -> str:
    value = str(name or "").strip()
    if year == 2014 and value == "课标全国II卷":
        return "新课标II卷"
    replacements = {
        "全国一卷": "全国I卷",
        "全国卷I": "全国I卷",
        "全国卷Ⅱ": "全国II卷",
        "全国卷II": "全国II卷",
        "全国卷Ⅲ": "全国III卷",
        "全国卷III": "全国III卷",
    }
    return replacements.get(value, value)


def normalize_source(year: int | None, source: str, old_name: str, new_name: str) -> str:
    value = str(source or "").strip()
    if not value:
        return new_name
    old_base = str(old_name or "").strip()
    if value == old_base:
        return new_name
    if value.startswith(old_base):
        return new_name + value[len(old_base):]
    return value


def stable_backup_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT / ".backups" / "paper_naming_decisions" / stamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    return backup_dir / "mathcyclus_before.sqlite3"


def merge_paper(conn: sqlite3.Connection, source_id: str, target_id: str) -> None:
    links = conn.execute(
        "SELECT * FROM paper_question WHERE paper_id = ? ORDER BY paper_question_id",
        (source_id,),
    ).fetchall()
    for link in links:
        duplicate = conn.execute(
            """
            SELECT paper_question_id FROM paper_question
            WHERE paper_id = ? AND question_id = ? AND question_number = ? AND sub_number = ?
            """,
            (target_id, link["question_id"], link["question_number"], link["sub_number"]),
        ).fetchone()
        if duplicate:
            conn.execute("DELETE FROM paper_question WHERE paper_question_id = ?", (link["paper_question_id"],))
        else:
            conn.execute(
                "UPDATE paper_question SET paper_id = ?, updated_at = CURRENT_TIMESTAMP WHERE paper_question_id = ?",
                (target_id, link["paper_question_id"]),
            )
    conn.execute("DELETE FROM paper WHERE paper_id = ?", (source_id,))


def main() -> int:
    backup_path = stable_backup_path()
    shutil.copy2(DB_PATH, backup_path)
    changed = []
    merged = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN")
        try:
            papers = conn.execute("SELECT * FROM paper ORDER BY year, paper_id").fetchall()
            for paper in papers:
                new_name = normalize_confirmed_name(paper["year"], paper["paper_name"])
                new_source = normalize_source(paper["year"], paper["source_name"], paper["paper_name"], new_name)
                if new_name == paper["paper_name"] and new_source == paper["source_name"]:
                    continue
                target = conn.execute(
                    """
                    SELECT * FROM paper
                    WHERE paper_id != ? AND year IS ? AND paper_series = ? AND track = ? AND paper_name = ?
                    """,
                    (paper["paper_id"], paper["year"], paper["paper_series"], paper["track"], new_name),
                ).fetchone()
                if target:
                    merge_paper(conn, paper["paper_id"], target["paper_id"])
                    merged.append({"from": paper["paper_id"], "to": target["paper_id"], "new_name": new_name})
                    continue
                conn.execute(
                    "UPDATE paper SET paper_name = ?, source_name = ?, updated_at = CURRENT_TIMESTAMP WHERE paper_id = ?",
                    (new_name, new_source, paper["paper_id"]),
                )
                conn.execute(
                    "UPDATE paper_standard_catalog SET paper_name = ?, source_name = ?, updated_at = CURRENT_TIMESTAMP WHERE paper_id = ?",
                    (new_name, new_source, paper["paper_id"]),
                )
                changed.append(
                    {
                        "paper_id": paper["paper_id"],
                        "year": paper["year"],
                        "old_name": paper["paper_name"],
                        "new_name": new_name,
                        "old_source": paper["source_name"],
                        "new_source": new_source,
                    }
                )

            # Keep the standard catalog aligned with the surviving paper rows.
            conn.execute(
                """
                UPDATE paper_standard_catalog
                SET paper_id = (SELECT p.paper_id FROM paper p WHERE p.year IS paper_standard_catalog.year
                                AND p.paper_series = paper_standard_catalog.paper_series
                                AND p.track = paper_standard_catalog.track
                                AND p.paper_name = paper_standard_catalog.paper_name),
                    updated_at = CURRENT_TIMESTAMP
                WHERE paper_id IS NOT NULL
                """
            )
            conn.execute("DELETE FROM paper_standard_catalog WHERE paper_id IS NULL AND status = 'confirmed'")
            conn.execute("PRAGMA foreign_key_check")
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    report = {
        "backup": str(backup_path.relative_to(ROOT)),
        "changed": changed,
        "merged": merged,
        "summary": {"changed": len(changed), "merged": len(merged)},
    }
    report_path = ROOT / "reports" / f"paper_naming_decisions_applied_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"backup={backup_path.relative_to(ROOT).as_posix()}")
    print(f"report={report_path.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
