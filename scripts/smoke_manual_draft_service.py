from __future__ import annotations

import argparse
import json
import shutil
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

from services.import_service import (
    add_draft_asset,
    commit_draft_to_question,
    count_draft_questions,
    create_manual_entry_draft,
    create_manual_entry_drafts,
    delete_draft_asset,
    get_draft_question,
    update_draft_asset_fields,
)
from services.question_db_service import count_questions


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def check(name: str, ok: bool, detail: Any = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="烟测手动录入草稿服务；只写入临时数据库副本。")
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
    with tempfile.TemporaryDirectory(prefix="mathcyclus_manual_draft_smoke_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        temp_db = tmp_root / source_db.name
        shutil.copy2(source_db, temp_db)
        asset_source = tmp_root / "draft-source.png"
        asset_source.write_bytes(b"not-a-real-image-but-valid-draft-path")
        extra_asset_source = tmp_root / "draft-extra.png"
        extra_asset_source.write_bytes(b"not-a-real-image-but-valid-extra-draft-path")

        question_count_before = count_questions(str(temp_db))
        draft_count_before = count_draft_questions(str(temp_db))
        result = create_manual_entry_draft(
            str(temp_db),
            {
                "source_item_id": "smoke-manual-entry",
                "source_label": "smoke 手动录入草稿",
                "question_type_id": 4,
                "stem_tex": r"已知函数 $f(x)=x^2$，求 $f'(x)$。",
                "choices": [r"{$2x$}", r"{$x$}"],
                "answer_tex": r"$2x$",
                "solution_tex": r"由幂函数求导公式得 $f'(x)=2x$。",
                "difficulty": 1,
                "tags": ["smoke", "导数"],
                "note": "临时副本写入测试；不进入正式题表",
                "assets": [
                    {
                        "role": "source",
                        "source_path": str(asset_source),
                        "caption": "smoke 来源图",
                    }
                ],
                "extra": {"source_kind": "manual_smoke"},
            },
            stamp="smoke_manual_draft_service",
        )
        draft = result.get("draft") or {}
        checks.append(check("draft_id_created", bool(result.get("draft_id")), result.get("draft_id")))
        checks.append(
            check(
                "draft_persisted",
                bool(draft) and draft.get("review_status") == "needs_review",
                {
                    "review_status": draft.get("review_status"),
                    "validation": result.get("validation"),
                },
            )
        )
        persisted_choices = json.loads(draft.get("choices_json") or "[]")
        checks.append(
            check(
                "draft_choices_persisted",
                persisted_choices == [r"{$2x$}", r"{$x$}"],
                persisted_choices,
            )
        )
        checks.append(
            check(
                "draft_asset_persisted",
                len(draft.get("assets") or []) == 1,
                draft.get("assets"),
            )
        )
        add_asset_result = add_draft_asset(
            str(temp_db),
            result["draft_id"],
            {
                "role": "solution",
                "source_path": str(extra_asset_source),
                "caption": "smoke 解析图",
                "review_status": "ready",
            },
        )
        draft_after_add = get_draft_question(str(temp_db), result["draft_id"])
        checks.append(
            check(
                "draft_asset_added_after_entry",
                len(draft_after_add.get("assets") or []) == 2 and bool(add_asset_result.get("draft_asset_id")),
                add_asset_result,
            )
        )
        update_asset_result = update_draft_asset_fields(
            str(temp_db),
            add_asset_result["draft_asset_id"],
            {"caption": "smoke 解析图已校订", "sort_order": 9},
        )
        checks.append(
            check(
                "draft_asset_updated_after_entry",
                {"caption", "sort_order"}.issubset(set(update_asset_result.get("changed_fields") or []))
                and update_asset_result.get("asset", {}).get("caption") == "smoke 解析图已校订",
                update_asset_result,
            )
        )
        delete_asset_result = delete_draft_asset(str(temp_db), add_asset_result["draft_asset_id"])
        draft_after_delete = get_draft_question(str(temp_db), result["draft_id"])
        checks.append(
            check(
                "draft_asset_deleted_after_entry",
                delete_asset_result.get("deleted")
                and len(draft_after_delete.get("assets") or []) == 1
                and extra_asset_source.exists(),
                delete_asset_result,
            )
        )
        checks.append(
            check(
                "formal_question_count_unchanged",
                count_questions(str(temp_db)) == question_count_before,
                {
                    "before": question_count_before,
                    "after": count_questions(str(temp_db)),
                },
            )
        )
        checks.append(
            check(
                "draft_count_incremented",
                count_draft_questions(str(temp_db)) == draft_count_before + 1,
                {
                    "before": draft_count_before,
                    "after": count_draft_questions(str(temp_db)),
                },
            )
        )

        batch_result = create_manual_entry_drafts(
            str(temp_db),
            [
                {
                    "source_item_id": "smoke-manual-batch-1",
                    "source_label": "smoke 批量录入草稿 1",
                    "question_type_id": 4,
                    "stem_tex": r"已知 $a_1=1,d=2$，求 $a_3$。",
                    "answer_tex": r"$5$",
                    "solution_tex": r"$a_3=a_1+2d=5$。",
                    "difficulty": 1,
                    "tags": ["smoke", "数列"],
                    "extra": {"source_kind": "manual_batch_smoke"},
                },
                {
                    "source_item_id": "smoke-manual-batch-2",
                    "source_label": "smoke 批量录入草稿 2",
                    "question_type_id": 1,
                    "stem_tex": r"函数 $y=x$ 的图象是",
                    "choices": [r"{直线}", r"{抛物线}", r"{圆}", r"{双曲线}"],
                    "answer_tex": r"A",
                    "solution_tex": r"$y=x$ 为过原点的一次函数。",
                    "difficulty": 1,
                    "tags": ["smoke", "函数"],
                    "extra": {"source_kind": "manual_batch_smoke"},
                },
            ],
            mode="smoke_manual_drafts",
            stamp="smoke_manual_draft_batch",
            summary="smoke 批量草稿",
        )
        checks.append(
            check(
                "batch_drafts_created",
                batch_result.get("draft_count") == 2 and len(batch_result.get("results") or []) == 2,
                batch_result,
            )
        )
        checks.append(
            check(
                "draft_count_batch_incremented",
                count_draft_questions(str(temp_db)) == draft_count_before + 3,
                {
                    "before": draft_count_before,
                    "after": count_draft_questions(str(temp_db)),
                },
            )
        )

        gate_draft_result = create_manual_entry_draft(
            str(temp_db),
            {
                "source_item_id": "smoke-manual-gate",
                "source_label": "smoke 图片门禁草稿",
                "question_type_id": 4,
                "stem_tex": r"题干中有图：\includegraphics{missing-gate.png}",
                "choices": [r"{$A$}", r"{$B$}"],
                "answer_tex": r"$A$",
                "solution_tex": r"略",
                "difficulty": 1,
                "tags": ["smoke"],
                "note": "用于验证图片引用门禁",
                "extra": {"source_kind": "manual_smoke"},
                "review_status": "ready",
            },
            stamp="smoke_manual_draft_gate",
        )
        gate_draft = gate_draft_result.get("draft") or {}
        checks.append(
            check(
                "gate_draft_blocked",
                gate_draft.get("review_status") == "blocked"
                and "missing includegraphics" in str(gate_draft.get("review_reason") or "").lower()
                or "缺失 includegraphics 图片引用" in str(gate_draft.get("review_reason") or ""),
                {
                    "review_status": gate_draft.get("review_status"),
                    "review_reason": gate_draft.get("review_reason"),
                },
            )
        )
        try:
            commit_draft_to_question(str(temp_db), gate_draft_result["draft_id"], operator="smoke_draft_commit")
            gate_commit_blocked = False
        except Exception:
            gate_commit_blocked = True
        checks.append(
            check(
                "gate_commit_blocked",
                gate_commit_blocked,
                gate_draft_result.get("draft_id"),
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
