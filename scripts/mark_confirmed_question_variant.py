from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def stable_id(*values: object) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return "QE" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/mathcyclus.sqlite3")
    parser.add_argument("--left", default="Q000350")
    parser.add_argument("--right", default="Q000351")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    args = parser.parse_args()
    db_path = (ROOT / args.db).resolve() if not Path(args.db).is_absolute() else Path(args.db).resolve()
    backup_path = ROOT / ".backups" / "confirmed_question_variants" / args.stamp / "mathcyclus_before.sqlite3"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(db_path)
    backup = sqlite3.connect(backup_path)
    source.backup(backup)
    backup.close()
    source.close()

    left, right = sorted((args.left, args.right))
    relation_type = "variant_different_condition"
    note = "高度相似但条件不同：Q000350 为 a>1 且区间 [0,2a]，Q000351 为 |a|>1 且区间 [0,2|a|]；两题均保留，不合并。"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        for question_id in (left, right):
            if conn.execute("SELECT 1 FROM question WHERE question_id = ?", (question_id,)).fetchone() is None:
                raise ValueError(f"question not found: {question_id}")
        equivalence_id = stable_id(left, right, relation_type)
        conn.execute(
            """
            INSERT INTO question_equivalence(
                equivalence_id, question_id_a, question_id_b, relation_type,
                confidence, review_status, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(question_id_a, question_id_b, relation_type) DO UPDATE SET
                confidence = excluded.confidence,
                review_status = excluded.review_status,
                note = excluded.note
            """,
            (equivalence_id, left, right, relation_type, 1.0, "approved", note),
        )
        revision_id = "QR" + hashlib.sha1((equivalence_id + args.stamp).encode("utf-8")).hexdigest()[:14]
        for question_id in (left, right):
            conn.execute(
                """
                INSERT INTO question_revision(
                    revision_id, question_id, change_source, changed_fields_json,
                    before_json, after_json, operator, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    revision_id + question_id[-2:],
                    question_id,
                    "question_equivalence_review",
                    json.dumps(["question_equivalence"], ensure_ascii=False),
                    json.dumps({}, ensure_ascii=False),
                    json.dumps({"equivalence_id": equivalence_id, "relation_type": relation_type, "review_status": "approved"}, ensure_ascii=False),
                    "maintenance",
                    note,
                ),
            )
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = [dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(f"integrity failure: {integrity}, {foreign_keys}")
        conn.commit()

    report = {
        "equivalence_id": equivalence_id,
        "question_ids": [left, right],
        "relation_type": relation_type,
        "review_status": "approved",
        "database_backup": str(backup_path.relative_to(ROOT)).replace("\\", "/"),
        "integrity_check": integrity,
        "foreign_key_errors": foreign_keys,
    }
    (backup_path.parent / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
