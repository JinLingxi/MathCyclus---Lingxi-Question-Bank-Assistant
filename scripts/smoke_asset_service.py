from __future__ import annotations

import argparse
import base64
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from services.asset_service import (
    asset_placeholder,
    attach_asset_to_question,
    collect_asset_reference_issues,
    delete_asset,
    get_asset,
    update_asset_fields,
)
from services.question_db_service import QuestionListFilters, list_questions_page


ONE_PIXEL_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB"
    "/6XgmioAAAAASUVORK5CYII="
)


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def check(name: str, ok: bool, detail: Any = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="烟测题目图片资源 attach 服务；只写入临时数据库副本。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_db = Path(args.db)
    if not source_db.is_absolute():
        source_db = PROJECT_ROOT / source_db
    source_db = source_db.resolve()
    if not source_db.exists():
        raise SystemExit(f"数据库不存在：{source_db}")

    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mathcyclus_asset_smoke_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        temp_db = tmp_root / source_db.name
        shutil.copy2(source_db, temp_db)

        page = list_questions_page(str(temp_db), QuestionListFilters(limit=1, offset=0))
        question_id = page["items"][0]["question_id"] if page["items"] else ""
        checks.append(check("find_sample_question", bool(question_id), question_id))

        source_asset = tmp_root / "source.png"
        source_asset.write_bytes(base64.b64decode(ONE_PIXEL_PNG))
        asset_root = tmp_root / "assets" / "questions"
        attach_result = attach_asset_to_question(
            str(temp_db),
            question_id,
            source_asset,
            role="problem",
            caption="smoke 临时图片",
            asset_root=asset_root,
        )
        stored_path = Path(attach_result["file_path"])
        checks.append(
            check(
                "copy_asset_file",
                stored_path.exists() and stored_path.is_file(),
                attach_result["file_path"],
            )
        )
        checks.append(
            check(
                "detect_image_metadata",
                attach_result["mime_type"] == "image/png"
                and attach_result["width"] == 1
                and attach_result["height"] == 1,
                {
                    "mime_type": attach_result["mime_type"],
                    "width": attach_result["width"],
                    "height": attach_result["height"],
                },
            )
        )

        conn = sqlite3.connect(temp_db)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT *
                FROM question_asset
                WHERE asset_id = ? AND question_id = ?
                """,
                (attach_result["asset_id"], question_id),
            ).fetchone()
        finally:
            conn.close()
        checks.append(
            check(
                "asset_record_written",
                bool(row) and row["caption"] == "smoke 临时图片",
                dict(row) if row else "",
            )
        )
        checks.append(
            check(
                "asset_placeholder",
                bool(row) and asset_placeholder(dict(row)) == attach_result["placeholder"],
                attach_result.get("placeholder"),
            )
        )

        update_result = update_asset_fields(
            str(temp_db),
            attach_result["asset_id"],
            {"caption": "smoke 临时图片已更新", "sort_order": 7},
            operator="smoke",
        )
        updated_asset = get_asset(str(temp_db), attach_result["asset_id"])
        checks.append(
            check(
                "update_asset_metadata",
                update_result["changed_fields"] == ["caption", "sort_order"]
                and updated_asset.get("caption") == "smoke 临时图片已更新"
                and int(updated_asset.get("sort_order") or 0) == 7,
                {
                    "changed_fields": update_result["changed_fields"],
                    "revision_id": update_result["revision_id"],
                },
            )
        )
        reference_ok = collect_asset_reference_issues(
            {"stem_tex": f"图见 {attach_result['placeholder']}。", "answer_tex": "", "solution_tex": ""},
            [updated_asset],
            project_root=PROJECT_ROOT,
        )
        checks.append(
            check(
                "questionasset_reference_resolved",
                not reference_ok["has_blockers"] and reference_ok["questionasset_refs"] == [attach_result["alias"]],
                reference_ok,
            )
        )
        reference_missing = collect_asset_reference_issues(
            {"stem_tex": r"图见 \questionasset{missing_alias}。", "answer_tex": "", "solution_tex": ""},
            [updated_asset],
            project_root=PROJECT_ROOT,
        )
        checks.append(
            check(
                "questionasset_reference_missing_detected",
                bool(reference_missing["unresolved_questionasset"]) and reference_missing["has_blockers"],
                reference_missing,
            )
        )

        delete_result = delete_asset(str(temp_db), attach_result["asset_id"], operator="smoke")
        deleted_asset = get_asset(str(temp_db), attach_result["asset_id"])
        checks.append(
            check(
                "delete_asset_record_only",
                bool(delete_result.get("revision_id")) and not deleted_asset and stored_path.exists(),
                {
                    "revision_id": delete_result.get("revision_id"),
                    "file_still_exists": stored_path.exists(),
                },
            )
        )

    failed = [item for item in checks if not item["ok"]]
    report = {
        "source_database": relative_to_root(source_db),
        "status": "failed" if failed else "ok",
        "checks": checks,
        "writes_formal_database": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
