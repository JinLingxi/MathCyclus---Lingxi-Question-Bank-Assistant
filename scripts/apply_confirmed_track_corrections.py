from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "mathcyclus.sqlite3"
PAPER_IDS = ["P82f82692b27522", "P643625fe6081bc", "Pb0cade67d36147"]
PAPER_MERGES = {"P82f82692b27522": "P54aba85b99"}
NEW_TRACK = "\u65b0\u9ad8\u8003"


def stable_id(*values: object) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return "QR" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def backup_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    args = parser.parse_args()
    db_path = Path(args.db).resolve()
    backup_root = ROOT / ".backups" / "confirmed_track_corrections" / args.stamp
    backup_path = backup_root / "mathcyclus_before_track_corrections.sqlite3"
    backup_database(db_path, backup_path)

    changes = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        for paper_id in PAPER_IDS:
            paper = conn.execute("SELECT * FROM paper WHERE paper_id = ?", (paper_id,)).fetchone()
            if paper is None:
                raise ValueError(f"paper not found: {paper_id}")
            before_track = str(paper["track"] or "")
            questions = conn.execute(
                "SELECT * FROM paper_question WHERE paper_id = ? ORDER BY question_id",
                (paper_id,),
            ).fetchall()
            target_paper_id = PAPER_MERGES.get(paper_id)
            if target_paper_id:
                target = conn.execute("SELECT * FROM paper WHERE paper_id = ?", (target_paper_id,)).fetchone()
                if target is None or str(target["track"] or "") != NEW_TRACK:
                    raise ValueError(f"invalid merge target: {target_paper_id}")
                for relation in questions:
                    duplicate = conn.execute(
                        """
                        SELECT paper_question_id FROM paper_question
                        WHERE paper_id = ? AND question_id = ? AND question_number = ? AND sub_number = ?
                        """,
                        (target_paper_id, relation["question_id"], relation["question_number"], relation["sub_number"]),
                    ).fetchone()
                    if duplicate:
                        conn.execute("DELETE FROM paper_question WHERE paper_question_id = ?", (relation["paper_question_id"],))
                    else:
                        conn.execute(
                            "UPDATE paper_question SET paper_id = ?, updated_at = CURRENT_TIMESTAMP WHERE paper_question_id = ?",
                            (target_paper_id, relation["paper_question_id"]),
                        )
                conn.execute("DELETE FROM paper WHERE paper_id = ?", (paper_id,))
                after_track = NEW_TRACK
            else:
                conn.execute(
                    "UPDATE paper SET track = ?, updated_at = CURRENT_TIMESTAMP WHERE paper_id = ?",
                    (NEW_TRACK, paper_id),
                )
                after_track = NEW_TRACK
            for row in questions:
                question_id = str(row["question_id"])
                revision_id = stable_id(question_id, paper_id, before_track, NEW_TRACK, args.stamp)
                conn.execute(
                    """
                    INSERT INTO question_revision(
                        revision_id, question_id, change_source, changed_fields_json,
                        before_json, after_json, operator, note, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        revision_id,
                        question_id,
                        "paper_track_cleanup",
                        json.dumps(["paper.track"], ensure_ascii=False),
                        json.dumps({"paper_id": paper_id, "track": before_track}, ensure_ascii=False),
                        json.dumps({"paper_id": target_paper_id or paper_id, "track": after_track}, ensure_ascii=False),
                        "maintenance",
                        f"confirmed track correction for paper {paper_id}",
                    ),
                )
            changes.append(
                {
                    "paper_id": paper_id,
                    "year": paper["year"],
                    "paper_name": paper["paper_name"],
                    "before_track": before_track,
                    "after_track": after_track,
                    "merged_into": target_paper_id or "",
                    "question_count": len(questions),
                }
            )
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_errors = [dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
        if integrity != "ok" or foreign_key_errors:
            raise RuntimeError(f"database integrity failure: {integrity}, {foreign_key_errors}")
        conn.commit()

    manifest = {
        "database": str(db_path),
        "database_backup": str(backup_path),
        "new_track": NEW_TRACK,
        "changes": changes,
        "integrity_check": integrity,
        "foreign_key_errors": foreign_key_errors,
    }
    backup_root.mkdir(parents=True, exist_ok=True)
    (backup_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
