from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from services.asset_service import list_assets
from services.book_service import list_question_book_links
from services.import_service import list_import_batches
from services.paper_service import count_papers, list_question_paper_links
from services.question_db_service import (
    QuestionListFilters,
    count_questions,
    get_question_bundle,
    list_question_filter_options,
    list_questions_page,
)
from services.topic_service import list_question_topic_links, list_topic_groups, list_topics


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def check(name: str, ok: bool, detail: Any = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="烟测结构化题库数据库服务层。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    parser.add_argument("--limit", type=int, default=5, help="题目分页烟测数量。")
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
    question_total = count_questions(str(db_path))
    paper_total = count_papers(str(db_path))
    checks.append(check("question_count", question_total > 0, question_total))
    checks.append(check("paper_count", paper_total > 0, paper_total))

    options = list_question_filter_options(str(db_path))
    checks.append(check("filter_years", len(options["years"]) > 0, options["years"][:5]))
    checks.append(check("filter_chapters", len(options["chapters"]) > 0, options["chapters"][:5]))

    page = list_questions_page(str(db_path), QuestionListFilters(limit=args.limit, offset=0))
    checks.append(
        check(
            "question_page",
            page["total"] == question_total and 0 < len(page["items"]) <= args.limit,
            {"total": page["total"], "items": len(page["items"])},
        )
    )

    first_question_id = page["items"][0]["question_id"] if page["items"] else ""
    first_item = page["items"][0] if page["items"] else {}
    first_chapter = first_item.get("detected_chapter") or ""
    first_year = first_item.get("detected_year")
    first_source = first_item.get("detected_source") or ""
    if first_chapter and first_source:
        slash_page = list_questions_page(
            str(db_path),
            QuestionListFilters(keyword=f"{first_chapter}/{first_source}", limit=args.limit, offset=0),
        )
        checks.append(
            check(
                "slash_keyword_search",
                slash_page["total"] > 0,
                {"keyword": f"{first_chapter}/{first_source}", "total": slash_page["total"]},
            )
        )
    if first_chapter and first_year is not None:
        context_options = list_question_filter_options(
            str(db_path),
            QuestionListFilters(chapter=first_chapter, year=first_year, limit=1),
        )
        checks.append(
            check(
                "context_filter_sources",
                first_source in context_options.get("sources", []),
                {
                    "chapter": first_chapter,
                    "year": first_year,
                    "source": first_source,
                    "source_count": len(context_options.get("sources", [])),
                },
            )
        )
    if first_chapter and first_year is not None and first_source:
        type_options = list_question_filter_options(
            str(db_path),
            QuestionListFilters(chapter=first_chapter, year=first_year, source=first_source, limit=1),
        )
        type_ids = {item.get("question_type_id") for item in type_options.get("question_types", [])}
        checks.append(
            check(
                "context_filter_types",
                first_item.get("question_type_id") in type_ids,
                {"type_ids": sorted(type_id for type_id in type_ids if type_id is not None)},
            )
        )
    bundle = get_question_bundle(str(db_path), first_question_id) if first_question_id else {}
    checks.append(check("question_bundle", bool(bundle.get("question")), first_question_id))

    checks.append(check("paper_links_query", isinstance(list_question_paper_links(str(db_path), first_question_id), list)))
    checks.append(check("book_links_query", isinstance(list_question_book_links(str(db_path), first_question_id), list)))
    checks.append(check("topic_links_query", isinstance(list_question_topic_links(str(db_path), first_question_id), list)))
    topics = list_topics(str(db_path))
    if topics:
        checks.append(check("topic_groups_query", isinstance(list_topic_groups(str(db_path), topics[0]["topic_id"]), list)))
    checks.append(check("asset_query", isinstance(list_assets(str(db_path)), list)))
    checks.append(check("import_batch_query", isinstance(list_import_batches(str(db_path), limit=5), list)))

    failed = [item for item in checks if not item["ok"]]
    report = {
        "database": relative_to_root(db_path),
        "status": "failed" if failed else "ok",
        "checks": checks,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
