from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.asset_service import preferred_asset_alias

ROOT = Path(__file__).resolve().parents[1]
QUESTION_IDS = ["Q000480", "Q000547", "Q000896", "Q000897"]


def backup_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def add_placeholders(text: str, aliases: list[str]) -> str:
    content = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    existing = set(re.findall(r"\\questionasset\{([^{}]+)\}", content))
    additions = [f"\\questionasset{{{alias}}}" for alias in aliases if alias not in existing]
    if not additions:
        return content
    block = "\n\n".join(additions)
    problem_end = re.search(r"\\end\{problem\}", content)
    if problem_end:
        return content[: problem_end.start()].rstrip() + "\n\n" + block + "\n" + content[problem_end.start() :]
    return content.rstrip() + "\n\n" + block + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/mathcyclus.sqlite3")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    args = parser.parse_args()
    db_path = (ROOT / args.db).resolve() if not Path(args.db).is_absolute() else Path(args.db).resolve()
    backup_root = ROOT / ".backups" / "confirmed_asset_references" / args.stamp
    backup_path = backup_root / "mathcyclus_before_asset_references.sqlite3"
    backup_database(db_path, backup_path)

    changes = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        for question_id in QUESTION_IDS:
            question = conn.execute("SELECT * FROM question WHERE question_id = ?", (question_id,)).fetchone()
            if question is None:
                raise ValueError(f"question not found: {question_id}")
            assets = conn.execute(
                "SELECT * FROM question_asset WHERE question_id = ? ORDER BY sort_order, asset_id",
                (question_id,),
            ).fetchall()
            aliases = [preferred_asset_alias(dict(asset)) for asset in assets]
            aliases = [alias for alias in aliases if alias]
            before = {
                "stem_tex": question["stem_tex"] or "",
                "canonical_tex": question["canonical_tex"] or "",
                "raw_source_tex": question["raw_source_tex"] or "",
            }
            after_stem = add_placeholders(before["stem_tex"], aliases)
            after_canonical = add_placeholders(before["canonical_tex"], aliases)
            after_raw = add_placeholders(before["raw_source_tex"], aliases)
            legacy_path = ROOT / str(question["legacy_file_path"])
            if legacy_path.exists():
                legacy_path.write_text(after_raw, encoding="utf-8")
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """
                UPDATE question
                SET stem_tex = ?, canonical_tex = ?, raw_source_tex = ?,
                    updated_at = ?, last_manual_edit_at = ?
                WHERE question_id = ?
                """,
                (after_stem, after_canonical, after_raw, now, now, question_id),
            )
            revision_id = "QR" + hashlib.sha1((question_id + args.stamp).encode("utf-8")).hexdigest()[:14]
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
                    "asset_reference_cleanup",
                    json.dumps(["stem_tex", "canonical_tex", "raw_source_tex", "questionasset_refs"], ensure_ascii=False),
                    json.dumps(before, ensure_ascii=False),
                    json.dumps({"aliases": aliases, "questionasset_refs": aliases}, ensure_ascii=False),
                    "maintenance",
                    "为已登记图片资源补充 questionasset 引用",
                ),
            )
            changes.append({"question_id": question_id, "asset_count": len(aliases), "aliases": aliases, "legacy_file": str(legacy_path.relative_to(ROOT)).replace("\\", "/")})
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = [dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(f"integrity failure: {integrity}, {foreign_keys}")
        conn.commit()

    manifest = {
        "database_backup": str(backup_path.relative_to(ROOT)).replace("\\", "/"),
        "changes": changes,
        "integrity_check": integrity,
        "foreign_key_errors": foreign_keys,
    }
    backup_root.mkdir(parents=True, exist_ok=True)
    (backup_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
