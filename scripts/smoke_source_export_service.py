from __future__ import annotations

import argparse
import json
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

from services.export_service import (
    export_filtered_questions_to_tex,
    export_legacy_tree_to_tex,
    export_source_to_tex,
    format_choice_item,
    list_source_export_options,
)
from services.choice_format_service import unwrap_choice_item
from services.question_db_service import QuestionListFilters, count_questions, list_question_filter_options


SOURCE_ID_KEYS = {
    "paper": "paper_id",
    "book": "book_id",
    "topic": "topic_id",
}


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def check(name: str, ok: bool, detail: Any = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="烟测 SQLite 按来源导出服务；只写入临时目录。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    db_path = db_path.resolve()
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")

    checks: list[dict[str, Any]] = []
    question_count_before = count_questions(str(db_path))
    checks.append(
        check(
            "choice_item_unwraps_wrapped_tex",
            unwrap_choice_item(r"{$\dfrac{\pi}{4}$}") == r"$\dfrac{\pi}{4}$",
            unwrap_choice_item(r"{$\dfrac{\pi}{4}$}"),
        )
    )
    checks.append(
        check(
            "choice_item_wraps_inner_tex",
            format_choice_item(r"$\dfrac{\pi}{4}$") == r"{$\dfrac{\pi}{4}$}",
            format_choice_item(r"$\dfrac{\pi}{4}$"),
        )
    )
    checks.append(
        check(
            "choice_item_keeps_wrapped_tex",
            format_choice_item(r"{$\dfrac{\pi}{4}$}") == r"{$\dfrac{\pi}{4}$}",
            format_choice_item(r"{$\dfrac{\pi}{4}$}"),
        )
    )

    with tempfile.TemporaryDirectory(prefix="mathcyclus_source_export_smoke_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        for source_kind, id_key in SOURCE_ID_KEYS.items():
            options = list_source_export_options(str(db_path), source_kind, limit=20)
            checks.append(check(f"{source_kind}_source_options", bool(options), len(options)))
            if not options:
                continue

            source = options[0]
            source_id = str(source.get(id_key) or "")
            output_path = tmp_root / f"{source_kind}.tex"
            result = export_source_to_tex(
                str(db_path),
                source_kind,
                source_id,
                output_path,
                project_root=PROJECT_ROOT,
                resolve_questionassets=True,
            )
            exported_tex = output_path.read_text(encoding="utf-8")
            checks.append(
                check(
                    f"{source_kind}_export_file",
                    output_path.exists() and "\\begin{problem}" in exported_tex,
                    {
                        "source_id": source_id,
                        "question_count": result.get("question_count"),
                        "output_path": str(output_path),
                    },
                )
            )
            checks.append(
                check(
                    f"{source_kind}_export_count",
                    int(result.get("question_count") or 0) == int(source.get("question_count") or 0),
                    {
                        "expected": source.get("question_count"),
                        "actual": result.get("question_count"),
                    },
                )
            )

        filter_options = list_question_filter_options(str(db_path))
        sample_year = filter_options["years"][0] if filter_options.get("years") else None
        filtered_output_path = tmp_root / "filtered.tex"
        filtered_result = export_filtered_questions_to_tex(
            str(db_path),
            QuestionListFilters(year=sample_year, limit=20, offset=0),
            filtered_output_path,
            project_root=PROJECT_ROOT,
            max_questions=20,
            resolve_questionassets=True,
        )
        filtered_tex = filtered_output_path.read_text(encoding="utf-8")
        checks.append(
            check(
                "filtered_export_file",
                filtered_output_path.exists() and "\\begin{problem}" in filtered_tex,
                {
                    "year": sample_year,
                    "question_count": filtered_result.get("question_count"),
                    "output_path": str(filtered_output_path),
                },
            )
        )
        checks.append(
            check(
                "filtered_export_limit",
                0 < int(filtered_result.get("question_count") or 0) <= 20,
                filtered_result.get("question_count"),
            )
        )

        legacy_tree_dir = tmp_root / "legacy_tree"
        legacy_tree_result = export_legacy_tree_to_tex(
            str(db_path),
            legacy_tree_dir,
            QuestionListFilters(year=sample_year, limit=5, offset=0),
            project_root=PROJECT_ROOT,
            max_questions=5,
            resolve_questionassets=True,
        )
        legacy_files = legacy_tree_result.get("files") or []
        first_legacy_file = Path(legacy_files[0]["output_path"]) if legacy_files else Path()
        first_legacy_tex = first_legacy_file.read_text(encoding="utf-8") if first_legacy_file.exists() else ""
        checks.append(
            check(
                "legacy_tree_export_files",
                len(legacy_files) == 5 and first_legacy_file.exists() and "\\begin{problem}" in first_legacy_tex,
                {
                    "question_count": legacy_tree_result.get("question_count"),
                    "first_file": str(first_legacy_file),
                },
            )
        )
        checks.append(
            check(
                "legacy_tree_mirrors_chapters",
                any("chapters" in str(file_item.get("relative_output_path") or file_item.get("output_path") or "") for file_item in legacy_files),
                [str(file_item.get("relative_output_path") or file_item.get("output_path") or "") for file_item in legacy_files[:3]],
            )
        )

    question_count_after = count_questions(str(db_path))
    checks.append(
        check(
            "source_database_unchanged",
            question_count_after == question_count_before,
            {"before": question_count_before, "after": question_count_after},
        )
    )

    failed = [item for item in checks if not item["ok"]]
    report = {
        "source_database": relative_to_root(db_path),
        "status": "failed" if failed else "ok",
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
