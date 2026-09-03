from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from services.paper_service import (
    PaperListFilters,
    count_papers,
    get_paper,
    list_paper_questions,
    list_paper_tracks,
    list_paper_years,
    list_papers,
    list_question_paper_links,
)
from services.question_db_service import (
    QuestionListFilters,
    count_questions,
    get_question,
    get_question_bundle,
    list_question_filter_options,
    list_questions_page,
)
from services.asset_service import list_assets
from services.knowledge_service import (
    list_equivalence_candidates,
    list_knowledge_areas,
    list_questions_by_knowledge_area,
)
from services.equivalence_service import (
    count_equivalence_relations,
    list_equivalence_relations,
    list_review_decisions,
    summarize_review_decisions,
)
from services.import_service import (
    count_draft_questions,
    list_draft_questions,
    list_import_batches,
    summarize_batch,
)
from services.revision_service import list_question_revisions
from services.question_edit_service import get_question_edit_state
from services.book_service import (
    BookListFilters,
    count_book_questions,
    count_books,
    get_book,
    list_book_questions,
    list_book_sections,
    list_books,
    list_question_book_links,
)
from services.topic_service import (
    TopicListFilters,
    count_topic_questions,
    count_topics,
    get_topic,
    list_question_topic_links,
    list_topic_modules,
    list_topic_questions,
    list_topics,
)


def print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_summary(db_path: str) -> None:
    data = {
        "questions": count_questions(db_path),
        "papers": count_papers(db_path),
        "years": list_paper_years(db_path),
        "tracks": list_paper_tracks(db_path),
    }
    print_json(data)


def cmd_papers(args: argparse.Namespace, db_path: str) -> None:
    filters = PaperListFilters(
        year=args.year,
        track=args.track or "",
        keyword=args.keyword or "",
        limit=args.limit,
        offset=args.offset,
    )
    print_json(list_papers(db_path, filters))


def cmd_paper(args: argparse.Namespace, db_path: str) -> None:
    paper = get_paper(db_path, args.paper_id)
    questions = list_paper_questions(db_path, args.paper_id)
    print_json({"paper": paper, "questions": questions})


def cmd_questions(args: argparse.Namespace, db_path: str) -> None:
    filters = QuestionListFilters(
        keyword=args.keyword or "",
        year=args.year,
        chapter=args.chapter or "",
        source=args.source or "",
        question_number=args.question_number or "",
        question_type_id=args.question_type_id,
        difficulty=args.difficulty,
        limit=args.limit,
        offset=args.offset,
    )
    print_json(list_questions_page(db_path, filters))


def cmd_question(args: argparse.Namespace, db_path: str) -> None:
    question = get_question(db_path, args.question_id)
    paper_links = list_question_paper_links(db_path, args.question_id)
    print_json({"question": question, "paper_links": paper_links})


def cmd_question_bundle(args: argparse.Namespace, db_path: str) -> None:
    print_json(get_question_bundle(db_path, args.question_id))


def cmd_question_filters(db_path: str) -> None:
    print_json(list_question_filter_options(db_path))


def cmd_knowledge(args: argparse.Namespace, db_path: str) -> None:
    print_json(list_knowledge_areas(db_path))


def cmd_knowledge_questions(args: argparse.Namespace, db_path: str) -> None:
    print_json(
        list_questions_by_knowledge_area(
            db_path,
            args.knowledge_area_id,
            limit=args.limit,
            offset=args.offset,
        )
    )


def cmd_equivalence(args: argparse.Namespace, db_path: str) -> None:
    print_json(
        {
            "total": count_equivalence_relations(
                db_path,
                review_status=args.review_status or "",
                relation_type=args.relation_type or "",
            ),
            "items": list_equivalence_relations(
                db_path,
                review_status=args.review_status or "",
                relation_type=args.relation_type or "",
                limit=args.limit,
                offset=args.offset,
            ),
        }
    )


def cmd_equivalence_candidates(args: argparse.Namespace, db_path: str) -> None:
    print_json(list_equivalence_candidates(db_path))


def cmd_equivalence_decisions(args: argparse.Namespace) -> None:
    print_json(
        {
            "summary": summarize_review_decisions(args.decisions or None),
            "items": list_review_decisions(args.decisions or None),
        }
    )


def cmd_assets(args: argparse.Namespace, db_path: str) -> None:
    print_json(list_assets(db_path, question_id=args.question_id or None))


def cmd_import_batches(args: argparse.Namespace, db_path: str) -> None:
    print_json(list_import_batches(db_path, limit=args.limit))


def cmd_import_batch(args: argparse.Namespace, db_path: str) -> None:
    print_json(summarize_batch(db_path, args.batch_id))


def cmd_import_drafts(args: argparse.Namespace, db_path: str) -> None:
    print_json(
        {
            "total": count_draft_questions(
                db_path,
                batch_id=args.batch_id or "",
                review_status=args.review_status or "",
            ),
            "items": list_draft_questions(
                db_path,
                batch_id=args.batch_id or "",
                review_status=args.review_status or "",
                limit=args.limit,
                offset=args.offset,
            ),
        }
    )


def cmd_revisions(args: argparse.Namespace, db_path: str) -> None:
    print_json(
        list_question_revisions(
            db_path,
            question_id=args.question_id or "",
            limit=args.limit,
        )
    )


def cmd_question_edit_state(args: argparse.Namespace, db_path: str) -> None:
    print_json(get_question_edit_state(db_path, args.question_id, revision_limit=args.revision_limit))


def cmd_books(args: argparse.Namespace, db_path: str) -> None:
    filters = BookListFilters(
        keyword=args.keyword or "",
        publisher=args.publisher or "",
        grade=args.grade or "",
        volume=args.volume or "",
        limit=args.limit,
        offset=args.offset,
    )
    print_json({"total": count_books(db_path, filters), "items": list_books(db_path, filters)})


def cmd_book(args: argparse.Namespace, db_path: str) -> None:
    print_json(
        {
            "book": get_book(db_path, args.book_id),
            "sections": list_book_sections(db_path, args.book_id),
        }
    )


def cmd_book_questions(args: argparse.Namespace, db_path: str) -> None:
    print_json(
        {
            "total": count_book_questions(db_path, args.book_id, args.section_id or ""),
            "items": list_book_questions(
                db_path,
                args.book_id,
                section_id=args.section_id or "",
                limit=args.limit,
                offset=args.offset,
            ),
        }
    )


def cmd_question_books(args: argparse.Namespace, db_path: str) -> None:
    print_json(list_question_book_links(db_path, args.question_id))


def cmd_topic_modules(args: argparse.Namespace, db_path: str) -> None:
    print_json(list_topic_modules(db_path))


def cmd_topics(args: argparse.Namespace, db_path: str) -> None:
    filters = TopicListFilters(
        module_id=args.module_id or "",
        keyword=args.keyword or "",
        limit=args.limit,
        offset=args.offset,
    )
    print_json({"total": count_topics(db_path, filters), "items": list_topics(db_path, filters)})


def cmd_topic(args: argparse.Namespace, db_path: str) -> None:
    print_json(get_topic(db_path, args.topic_id))


def cmd_topic_questions(args: argparse.Namespace, db_path: str) -> None:
    print_json(
        {
            "total": count_topic_questions(db_path, args.topic_id, args.group_name or ""),
            "items": list_topic_questions(
                db_path,
                args.topic_id,
                group_name=args.group_name or "",
                limit=args.limit,
                offset=args.offset,
            ),
        }
    )


def cmd_question_topics(args: argparse.Namespace, db_path: str) -> None:
    print_json(list_question_topic_links(db_path, args.question_id))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读浏览结构化题库 SQLite 数据库。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("summary", help="查看题库摘要。")

    papers = subparsers.add_parser("papers", help="列出试卷。")
    papers.add_argument("--year", type=int)
    papers.add_argument("--track", default="")
    papers.add_argument("--keyword", default="")
    papers.add_argument("--limit", type=int, default=20)
    papers.add_argument("--offset", type=int, default=0)

    paper = subparsers.add_parser("paper", help="查看一张试卷及其题目。")
    paper.add_argument("paper_id")

    questions = subparsers.add_parser("questions", help="列出题目。")
    questions.add_argument("--year", type=int)
    questions.add_argument("--chapter", default="")
    questions.add_argument("--source", default="")
    questions.add_argument("--question-number", default="")
    questions.add_argument("--question-type-id", type=int)
    questions.add_argument("--difficulty", type=int)
    questions.add_argument("--keyword", default="")
    questions.add_argument("--limit", type=int, default=20)
    questions.add_argument("--offset", type=int, default=0)

    question = subparsers.add_parser("question", help="查看一道题及其试卷反查。")
    question.add_argument("question_id")

    question_bundle = subparsers.add_parser("question-bundle", help="查看一道题的完整来源与资源包。")
    question_bundle.add_argument("question_id")

    subparsers.add_parser("question-filters", help="列出题目筛选选项。")

    subparsers.add_parser("knowledge", help="列出知识板块。")

    knowledge_questions = subparsers.add_parser("knowledge-questions", help="查看某知识板块下的题目。")
    knowledge_questions.add_argument("knowledge_area_id")
    knowledge_questions.add_argument("--limit", type=int, default=20)
    knowledge_questions.add_argument("--offset", type=int, default=0)

    equivalence = subparsers.add_parser("equivalence", help="列出同题关系。")
    equivalence.add_argument("--review-status", default="")
    equivalence.add_argument("--relation-type", default="")
    equivalence.add_argument("--limit", type=int, default=50)
    equivalence.add_argument("--offset", type=int, default=0)

    subparsers.add_parser("equivalence-candidates", help="列出疑似同题候选。")

    equivalence_decisions = subparsers.add_parser("equivalence-decisions", help="查看同题人工决策表。")
    equivalence_decisions.add_argument("--decisions", default="")

    assets = subparsers.add_parser("assets", help="列出图片/附件资产。")
    assets.add_argument("--question-id", default="")

    import_batches = subparsers.add_parser("import-batches", help="列出导入批次。")
    import_batches.add_argument("--limit", type=int, default=20)

    import_batch = subparsers.add_parser("import-batch", help="查看一个导入批次摘要。")
    import_batch.add_argument("batch_id")

    import_drafts = subparsers.add_parser("import-drafts", help="列出 AI/OCR 导入草稿。")
    import_drafts.add_argument("--batch-id", default="")
    import_drafts.add_argument("--review-status", default="")
    import_drafts.add_argument("--limit", type=int, default=50)
    import_drafts.add_argument("--offset", type=int, default=0)

    revisions = subparsers.add_parser("revisions", help="列出题目修订记录。")
    revisions.add_argument("--question-id", default="")
    revisions.add_argument("--limit", type=int, default=50)

    question_edit_state = subparsers.add_parser("question-edit-state", help="查看题目编辑表单预备状态。")
    question_edit_state.add_argument("question_id")
    question_edit_state.add_argument("--revision-limit", type=int, default=20)

    books = subparsers.add_parser("books", help="列出教材。")
    books.add_argument("--keyword", default="")
    books.add_argument("--publisher", default="")
    books.add_argument("--grade", default="")
    books.add_argument("--volume", default="")
    books.add_argument("--limit", type=int, default=50)
    books.add_argument("--offset", type=int, default=0)

    book = subparsers.add_parser("book", help="查看教材和章节。")
    book.add_argument("book_id")

    book_questions = subparsers.add_parser("book-questions", help="查看教材关联题目。")
    book_questions.add_argument("book_id")
    book_questions.add_argument("--section-id", default="")
    book_questions.add_argument("--limit", type=int, default=100)
    book_questions.add_argument("--offset", type=int, default=0)

    question_books = subparsers.add_parser("question-books", help="从题目反查教材来源。")
    question_books.add_argument("question_id")

    subparsers.add_parser("topic-modules", help="列出专题模块。")

    topics = subparsers.add_parser("topics", help="列出专题。")
    topics.add_argument("--module-id", default="")
    topics.add_argument("--keyword", default="")
    topics.add_argument("--limit", type=int, default=50)
    topics.add_argument("--offset", type=int, default=0)

    topic = subparsers.add_parser("topic", help="查看专题。")
    topic.add_argument("topic_id")

    topic_questions = subparsers.add_parser("topic-questions", help="查看专题关联题目。")
    topic_questions.add_argument("topic_id")
    topic_questions.add_argument("--group-name", default="")
    topic_questions.add_argument("--limit", type=int, default=100)
    topic_questions.add_argument("--offset", type=int, default=0)

    question_topics = subparsers.add_parser("question-topics", help="从题目反查专题来源。")
    question_topics.add_argument("question_id")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    db_path = db_path.resolve()
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")

    command = args.command
    if command == "summary":
        cmd_summary(str(db_path))
    elif command == "papers":
        cmd_papers(args, str(db_path))
    elif command == "paper":
        cmd_paper(args, str(db_path))
    elif command == "questions":
        cmd_questions(args, str(db_path))
    elif command == "question":
        cmd_question(args, str(db_path))
    elif command == "question-bundle":
        cmd_question_bundle(args, str(db_path))
    elif command == "question-filters":
        cmd_question_filters(str(db_path))
    elif command == "knowledge":
        cmd_knowledge(args, str(db_path))
    elif command == "knowledge-questions":
        cmd_knowledge_questions(args, str(db_path))
    elif command == "equivalence":
        cmd_equivalence(args, str(db_path))
    elif command == "equivalence-candidates":
        cmd_equivalence_candidates(args, str(db_path))
    elif command == "equivalence-decisions":
        cmd_equivalence_decisions(args)
    elif command == "assets":
        cmd_assets(args, str(db_path))
    elif command == "import-batches":
        cmd_import_batches(args, str(db_path))
    elif command == "import-batch":
        cmd_import_batch(args, str(db_path))
    elif command == "import-drafts":
        cmd_import_drafts(args, str(db_path))
    elif command == "revisions":
        cmd_revisions(args, str(db_path))
    elif command == "question-edit-state":
        cmd_question_edit_state(args, str(db_path))
    elif command == "books":
        cmd_books(args, str(db_path))
    elif command == "book":
        cmd_book(args, str(db_path))
    elif command == "book-questions":
        cmd_book_questions(args, str(db_path))
    elif command == "question-books":
        cmd_question_books(args, str(db_path))
    elif command == "topic-modules":
        cmd_topic_modules(args, str(db_path))
    elif command == "topics":
        cmd_topics(args, str(db_path))
    elif command == "topic":
        cmd_topic(args, str(db_path))
    elif command == "topic-questions":
        cmd_topic_questions(args, str(db_path))
    elif command == "question-topics":
        cmd_question_topics(args, str(db_path))
    else:
        raise SystemExit(f"未知命令：{command}")


if __name__ == "__main__":
    main()
