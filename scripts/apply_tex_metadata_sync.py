"""Synchronize selected structured metadata from legacy TeX into SQLite.

The operation intentionally leaves difficulty, notes, TikZ detection, and
solution detection untouched. Legacy/manual knowledge-area links are kept;
only links previously produced by the directory migration are rebuilt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from audit_legacy_sqlite_consistency import COMPARE_FIELDS, load_legacy_tex_rows, normalize_project_path
from services.import_service import normalize_question_type_id
from services.revision_service import insert_question_revision_from_conn


TOPIC_SPLIT_RE = re.compile(r"[\uFF0C,\u3001;；|]+")
TAG_SPLIT_RE = re.compile(r"[\uFF0C,\u3001;；|\n]+")
MANAGED_KNOWLEDGE_SOURCES = {"legacy_directory", "legacy_tex"}
PATH_FIELD = COMPARE_FIELDS[2]
TOPIC_FIELD = COMPARE_FIELDS[7]
TYPE_FIELD = COMPARE_FIELDS[8]
TAGS_FIELD = COMPARE_FIELDS[10]
USAGE_FIELD = COMPARE_FIELDS[14]


def stable_id(name: str) -> str:
    return "KA" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]


def split_values(value: Any, pattern: re.Pattern[str]) -> list[str]:
    result: list[str] = []
    for item in pattern.split(str(value or "")):
        normalized = re.sub(r"\s+", " ", item).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value or "").strip()))
    except (TypeError, ValueError):
        return default


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync selected metadata from TeX into SQLite")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--root", default=str(PROJECT_ROOT / "chapters"))
    parser.add_argument("--apply", action="store_true", help="write changes; default is dry-run")
    return parser.parse_args()


def load_rows_by_path(root: Path) -> dict[str, dict[str, str]]:
    rows, _ = load_legacy_tex_rows(root)
    return {normalize_project_path(row[PATH_FIELD]): row for row in rows}


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    root = Path(args.root)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    db_path = db_path.resolve()
    root = root.resolve()
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")

    tex_rows = load_rows_by_path(root)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    report = {
        "apply": bool(args.apply),
        "question_count": 0,
        "question_updates": 0,
        "field_updates": {"question_type_id": 0, "tags_json": 0, "usage_count": 0},
        "knowledge_link_additions": 0,
        "knowledge_link_removals": 0,
        "new_knowledge_areas": 0,
        "revisions": 0,
    }

    try:
        question_rows = conn.execute(
            "SELECT * FROM question WHERE legacy_file_path IS NOT NULL AND trim(legacy_file_path) != ''"
        ).fetchall()
        report["question_count"] = len(question_rows)
        if args.apply:
            conn.execute("BEGIN IMMEDIATE")

        area_ids = {
            str(row["name"]): str(row["knowledge_area_id"])
            for row in conn.execute("SELECT knowledge_area_id, name FROM knowledge_area")
        }

        for row in question_rows:
            path = normalize_project_path(row["legacy_file_path"])
            tex = tex_rows.get(path)
            if not tex:
                continue

            updates: dict[str, Any] = {}
            tex_type_id = normalize_question_type_id(None, tex.get(TYPE_FIELD, ""))
            if tex_type_id != row["question_type_id"]:
                updates["question_type_id"] = tex_type_id

            tags = split_values(tex.get(TAGS_FIELD, ""), TAG_SPLIT_RE)
            tags_json = compact(tags)
            if tags_json != (row["tags_json"] or "[]"):
                updates["tags_json"] = tags_json

            usage_count = coerce_int(tex.get(USAGE_FIELD, "0"))
            if usage_count != int(row["usage_count"] or 0):
                updates["usage_count"] = usage_count

            before = dict(row)
            after = dict(before)
            after.update(updates)
            if updates:
                report["question_updates"] += 1
                for field in updates:
                    report["field_updates"][field] += 1
                if args.apply:
                    assignments = ", ".join(f"{field} = ?" for field in updates)
                    conn.execute(
                        f"UPDATE question SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE question_id = ?",
                        [*updates.values(), row["question_id"]],
                    )

            topic_names = split_values(tex.get(TOPIC_FIELD, ""), TOPIC_SPLIT_RE)
            existing = conn.execute(
                "SELECT ka.name, qka.knowledge_area_id, qka.source FROM question_knowledge_area qka "
                "JOIN knowledge_area ka ON ka.knowledge_area_id = qka.knowledge_area_id "
                "WHERE qka.question_id = ?",
                (row["question_id"],),
            ).fetchall()
            managed_existing = {str(item["name"]): item for item in existing if item["source"] in MANAGED_KNOWLEDGE_SOURCES}
            desired = set(topic_names)
            for topic_name in topic_names:
                area_id = area_ids.get(topic_name)
                if not area_id:
                    area_id = stable_id(topic_name)
                    area_ids[topic_name] = area_id
                    report["new_knowledge_areas"] += 1
                    if args.apply:
                        conn.execute(
                            "INSERT INTO knowledge_area(knowledge_area_id, name, sort_order) VALUES (?, ?, ?)",
                            (area_id, topic_name, len(area_ids)),
                        )
                if topic_name not in managed_existing:
                    report["knowledge_link_additions"] += 1
                    if args.apply:
                        conn.execute(
                            "INSERT OR IGNORE INTO question_knowledge_area(question_id, knowledge_area_id, source, confidence, is_primary) "
                            "VALUES (?, ?, 'legacy_tex', 1.0, ?)",
                            (row["question_id"], area_id, 1 if topic_name == topic_names[0] else 0),
                        )
            for topic_name, item in managed_existing.items():
                if topic_name not in desired:
                    report["knowledge_link_removals"] += 1
                    if args.apply:
                        conn.execute(
                            "DELETE FROM question_knowledge_area WHERE question_id = ? AND knowledge_area_id = ? AND source IN ('legacy_directory', 'legacy_tex')",
                            (row["question_id"], item["knowledge_area_id"]),
                        )
            if args.apply and (updates or topic_names != list(managed_existing)):
                revision_before = dict(before)
                revision_after = dict(after)
                revision_before["knowledge_areas"] = [str(item["name"]) for item in existing]
                revision_after["knowledge_areas"] = topic_names
                insert_question_revision_from_conn(
                    conn,
                    question_id=str(row["question_id"]),
                    change_source="legacy_tex_metadata_sync",
                    before=revision_before,
                    after=revision_after,
                    operator="maintenance",
                    note="题型、标签、组卷引用次数及 TeX 知识板块同步；难度、备注、TikZ、解析状态保留 SQLite 值",
                    changed_field_names=[*updates.keys(), "knowledge_areas"] if topic_names != list(managed_existing) else list(updates),
                )
                report["revisions"] += 1

        if args.apply:
            conn.commit()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        if args.apply:
            conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
