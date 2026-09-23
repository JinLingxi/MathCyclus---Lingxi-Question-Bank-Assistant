from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from apply_confirmed_cleanup_decisions import (
    BACKUP_ROOT,
    PROJECT_ROOT,
    connect_database,
    copy_sqlite_database,
    delete_question,
    insert_revision,
    question_row,
    relative_to_root,
    transfer_knowledge_links,
    transfer_paper_relations,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply one explicitly confirmed question merge.")
    parser.add_argument("source_question_id")
    parser.add_argument("target_question_id")
    parser.add_argument("--db", default="data/mathcyclus.sqlite3")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    return parser.parse_args()


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def run(db_path: Path, source_id: str, target_id: str, *, apply: bool, stamp: str) -> dict:
    quarantine_root = BACKUP_ROOT / stamp
    report = {
        "mode": "apply" if apply else "dry_run",
        "database": relative_to_root(db_path),
        "source_question_id": source_id,
        "target_question_id": target_id,
        "database_backup": "",
        "knowledge_transfers": [],
        "paper_relation_transfers": [],
        "deleted_question": None,
        "revision_id": "",
        "integrity_check": "not_run_in_dry_run",
        "foreign_key_errors": [],
    }

    with connect_database(db_path) as conn:
        source = question_row(conn, source_id)
        target = question_row(conn, target_id)
        if source_id == target_id:
            raise ValueError("来源题和目标题不能相同")
        if not apply:
            report["source_snapshot"] = {
                "legacy_file_path": source.get("legacy_file_path"),
                "answer_present": bool(source.get("answer_tex")),
                "solution_present": bool(source.get("solution_tex")),
            }
            report["target_snapshot"] = {
                "legacy_file_path": target.get("legacy_file_path"),
                "answer_present": bool(target.get("answer_tex")),
                "solution_present": bool(target.get("solution_tex")),
            }
            return report

    copy_sqlite_database(db_path, quarantine_root / "mathcyclus_before_merge.sqlite3")
    report["database_backup"] = relative_to_root(quarantine_root / "mathcyclus_before_merge.sqlite3")

    with connect_database(db_path) as conn:
        source = question_row(conn, source_id)
        target = question_row(conn, target_id)
        source_before = {
            "question_id": source_id,
            "legacy_file_path": source.get("legacy_file_path"),
            "answer_tex": source.get("answer_tex") or "",
            "solution_tex": source.get("solution_tex") or "",
        }
        target_before = {"question_id": target_id, "legacy_file_path": target.get("legacy_file_path")}

        report["knowledge_transfers"] = transfer_knowledge_links(conn, source_id, target_id)
        report["paper_relation_transfers"] = transfer_paper_relations(conn, source_id, target_id)
        report["revision_id"] = insert_revision(
            conn,
            target_id,
            changed_fields=["merged_question_id", "paper_question", "question_knowledge_area"],
            before={"target": target_before, "source": source_before},
            after={
                "canonical_question_id": target_id,
                "merged_question_id": source_id,
                "reason": "same paper, year, question position and identical stem; target has complete answer/solution",
            },
            note=f"确认合并重复题 {source_id} 到 {target_id}",
        )
        report["deleted_question"] = delete_question(conn, source_id, quarantine_root)
        report["integrity_check"] = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        report["foreign_key_errors"] = [dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
        conn.commit()

    quarantine_root.mkdir(parents=True, exist_ok=True)
    (quarantine_root / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    args = parse_args()
    report = run(resolve_path(args.db), args.source_question_id, args.target_question_id, apply=args.apply, stamp=args.stamp)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report.get("foreign_key_errors") and report.get("integrity_check", "ok") in {"ok", "not_run_in_dry_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
