from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def backup_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def remove_placeholder(text: str, alias: str) -> str:
    pattern = re.compile(rf"\s*\\questionasset\{{{re.escape(alias)}\}}\s*", re.MULTILINE)
    result = pattern.sub("\n\n", str(text or ""))
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/mathcyclus.sqlite3")
    parser.add_argument("--question-id", default="Q000547")
    parser.add_argument("--alias", default="2024-G-上海卷-12-数列，集合 图1")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    args = parser.parse_args()

    db_path = (ROOT / args.db).resolve() if not Path(args.db).is_absolute() else Path(args.db).resolve()
    backup_root = ROOT / ".backups" / "remove_redundant_tikz_asset_reference" / args.stamp
    backup_path = backup_root / "mathcyclus_before.sqlite3"
    backup_database(db_path, backup_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM question WHERE question_id = ?", (args.question_id,)).fetchone()
        if row is None:
            raise SystemExit(f"question not found: {args.question_id}")

        fields = ("stem_tex", "canonical_tex", "raw_source_tex")
        before = {field: row[field] or "" for field in fields}
        after = {field: remove_placeholder(value, args.alias) for field, value in before.items()}
        changed = [field for field in fields if before[field] != after[field]]
        if not changed:
            print("no change")
            return 0

        legacy_path = ROOT / str(row["legacy_file_path"] or "")
        if legacy_path.is_file():
            legacy_backup = backup_root / "legacy" / legacy_path.relative_to(ROOT)
            legacy_backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_path, legacy_backup)
            legacy_path.write_text(after["raw_source_tex"], encoding="utf-8")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """
            UPDATE question
            SET stem_tex = ?, canonical_tex = ?, raw_source_tex = ?,
                updated_at = ?, last_manual_edit_at = ?
            WHERE question_id = ?
            """,
            (after["stem_tex"], after["canonical_tex"], after["raw_source_tex"], now, now, args.question_id),
        )
        revision_id = "QR" + hashlib.sha1((args.question_id + args.stamp).encode("utf-8")).hexdigest()[:14]
        conn.execute(
            """
            INSERT INTO question_revision(
                revision_id, question_id, change_source, changed_fields_json,
                before_json, after_json, operator, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                revision_id,
                args.question_id,
                "tikz_asset_reference_cleanup",
                json.dumps(changed + ["tikz_derived_asset"], ensure_ascii=False),
                json.dumps(before, ensure_ascii=False),
                json.dumps(after, ensure_ascii=False),
                "maintenance",
                "移除与题内原生 TikZ 重复的辅助图片占位符，保留 TikZ 辅助 PNG 文件",
            ),
        )
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = [dict(item) for item in conn.execute("PRAGMA foreign_key_check").fetchall()]
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(f"integrity failure: {integrity}, {foreign_keys}")
        conn.commit()

    manifest = {
        "database_backup": str(backup_path.relative_to(ROOT)).replace("\\", "/"),
        "question_id": args.question_id,
        "removed_alias": args.alias,
        "changed_fields": changed,
        "revision_id": revision_id,
        "integrity_check": integrity,
        "foreign_key_errors": foreign_keys,
        "asset_policy": "TikZ auxiliary PNG remains cached but is excluded from questionasset rendering and ordinary audits",
    }
    backup_root.mkdir(parents=True, exist_ok=True)
    (backup_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
