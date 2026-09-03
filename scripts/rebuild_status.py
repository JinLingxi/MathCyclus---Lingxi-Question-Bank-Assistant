from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INITIAL_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_20260901_initial.sqlite3"
KNOWLEDGE_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_20260902_with_knowledge.sqlite3"
MAPPED_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_paper_mapped_20260902_initial.sqlite3"
PAPER_CORRECTED_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_paper_corrected_20260902_initial.sqlite3"
ASSET_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_assets_20260902_initial.sqlite3"
EQUIVALENCE_REVIEW_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_equivalence_review_20260902_final_review.sqlite3"
IMPORT_DRAFT_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_import_drafts_20260902_initial.sqlite3"
DRAFT_COMMIT_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_draft_commit_20260902_initial.sqlite3"
BOOK_IMPORT_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_book_import_20260902_initial.sqlite3"
TOPIC_IMPORT_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_topic_import_20260902_initial.sqlite3"
COMBINED_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_combined_20260902_initial.sqlite3"
COMBINED_COMMIT_PREVIEW_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_combined_20260902_initial_commit_preview.sqlite3"
DATA_WARNING_REVIEW_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_warning_review_20260902_warning_review.sqlite3"
PROMOTION_PLAN = PROJECT_ROOT / "docs" / "planning" / "sqlite_promotion_flow.md"
PROMOTION_SCRIPT = PROJECT_ROOT / "scripts" / "promote_preview_to_database.py"
FORMAL_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
SEED_REVIEW_SCRIPT = PROJECT_ROOT / "scripts" / "audit_seed_review_status.py"
SEED_REVIEW_REPORT = PROJECT_ROOT / "reports" / "seed_review_status_20260902_initial.md"
PAPER_REVIEW_HELPER = PROJECT_ROOT / "scripts" / "review_paper_mapping.py"
EQUIVALENCE_REVIEW_HELPER = PROJECT_ROOT / "scripts" / "review_equivalence_decisions.py"
PREVIEW_PIPELINE = PROJECT_ROOT / "scripts" / "rebuild_preview_pipeline.py"
PROJECT_HYGIENE_SCRIPT = PROJECT_ROOT / "scripts" / "check_project_hygiene.py"
RELEASE_READINESS_SCRIPT = PROJECT_ROOT / "scripts" / "release_readiness.py"
SOURCE_RELEASE_PACKAGE_SCRIPT = PROJECT_ROOT / "scripts" / "build_source_release_package.py"
TRACKED_PRIVATE_AUDIT_SCRIPT = PROJECT_ROOT / "scripts" / "audit_tracked_private_files.py"
DATABASE_SERVICE_SMOKE_SCRIPT = PROJECT_ROOT / "scripts" / "smoke_database_services.py"
DATA_WARNING_REVIEW_PACK = PROJECT_ROOT / "scripts" / "generate_data_warning_review_pack.py"
DATA_WARNING_REVIEW_DRY_RUN = PROJECT_ROOT / "scripts" / "apply_data_warning_review_dry_run.py"
PAPER_QUESTION_CORRECTIONS = PROJECT_ROOT / "db" / "seed" / "paper_question_corrections_20260902_final_review.csv"
PAPER_QUESTION_CORRECTIONS_SCRIPT = PROJECT_ROOT / "scripts" / "apply_paper_question_corrections_dry_run.py"
QUESTION_TEX_CORRECTIONS = PROJECT_ROOT / "db" / "seed" / "question_tex_corrections_20260902_final_review.csv"
PROGRESS_ESTIMATE = "99.99%"
FORMAL_DB_TABLES = [
    "question",
    "paper",
    "paper_question",
    "knowledge_area",
    "question_knowledge_area",
    "question_equivalence",
    "question_asset",
    "book",
    "book_section",
    "book_exercise_question",
    "topic_module",
    "topic",
    "topic_question",
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="查看 MathCyclus SQLite 重构进度。")
    parser.add_argument("--brief", action="store_true", help="只输出当前收口摘要，不展开所有历史预览库。")
    return parser.parse_args()


def count_table(db_path: Path, table: str) -> int:
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        ).fetchone()
        if row is None:
            return 0
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def exists(path: str) -> str:
    return "yes" if (PROJECT_ROOT / path).exists() else "no"


def report_count(pattern: str) -> int:
    return len(list((PROJECT_ROOT / "reports").glob(pattern)))


def formal_db_health() -> dict[str, object]:
    if not FORMAL_DB.exists():
        return {"exists": False, "integrity": "missing", "foreign_key_errors": 0}
    conn = sqlite3.connect(FORMAL_DB)
    try:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_errors = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    finally:
        conn.close()
    return {"exists": True, "integrity": integrity, "foreign_key_errors": foreign_key_errors}


def print_current_summary() -> None:
    health = formal_db_health()
    print("Current summary")
    print("---------------")
    print(f"progress estimate: {PROGRESS_ESTIMATE}")
    print(f"formal sqlite db: {health['exists']}")
    print(f"integrity_check: {health['integrity']}")
    print(f"foreign_key_errors: {health['foreign_key_errors']}")
    if FORMAL_DB.exists():
        print(f"formal question count: {count_table(FORMAL_DB, 'question')}")
        print(f"formal paper count: {count_table(FORMAL_DB, 'paper')}")
        print(f"formal paper_question count: {count_table(FORMAL_DB, 'paper_question')}")
        print(f"formal asset count: {count_table(FORMAL_DB, 'question_asset')}")
        print(f"formal book link count: {count_table(FORMAL_DB, 'book_exercise_question')}")
        print(f"formal topic link count: {count_table(FORMAL_DB, 'topic_question')}")
    print("next focus: 发布白名单复核、旧跟踪文件清理、独立启动器或打包版（可选）")


def main() -> None:
    args = parse_args()
    initial_counts = {
        "question": count_table(INITIAL_DB, "question"),
        "paper": count_table(INITIAL_DB, "paper"),
        "paper_question": count_table(INITIAL_DB, "paper_question"),
    }
    mapped_counts = {
        "question": count_table(MAPPED_DB, "question"),
        "paper": count_table(MAPPED_DB, "paper"),
        "paper_question": count_table(MAPPED_DB, "paper_question"),
    }

    print("MathCyclus database rebuild status")
    print("===================================")
    print_current_summary()
    if args.brief:
        return
    print("")
    print(f"schema: {exists('db/schema.sql')}")
    print(f"question id rules: {exists('docs/planning/question_id_rules.md')}")
    print(f"schema notes: {exists('docs/planning/database_schema_notes.md')}")
    print(f"sqlite promotion flow: {PROMOTION_PLAN.exists()}")
    print(f"sqlite promotion script: {PROMOTION_SCRIPT.exists()}")
    print(f"seed review script: {SEED_REVIEW_SCRIPT.exists()}")
    print(f"seed review report: {SEED_REVIEW_REPORT.exists()}")
    print(f"paper review helper: {PAPER_REVIEW_HELPER.exists()}")
    print(f"equivalence review helper: {EQUIVALENCE_REVIEW_HELPER.exists()}")
    print(f"preview rebuild pipeline: {PREVIEW_PIPELINE.exists()}")
    print(f"project hygiene script: {PROJECT_HYGIENE_SCRIPT.exists()}")
    print(f"project hygiene reports: {report_count('project_hygiene_*.md')}")
    print(f"release readiness script: {RELEASE_READINESS_SCRIPT.exists()}")
    print(f"source release package script: {SOURCE_RELEASE_PACKAGE_SCRIPT.exists()}")
    print(f"tracked private audit script: {TRACKED_PRIVATE_AUDIT_SCRIPT.exists()}")
    print(f"release readiness reports: {report_count('release_readiness_*.md')}")
    print(f"database service smoke script: {DATABASE_SERVICE_SMOKE_SCRIPT.exists()}")
    print(f"data warning review pack script: {DATA_WARNING_REVIEW_PACK.exists()}")
    print(f"data warning review pack reports: {report_count('data_warning_review_pack_*.md')}")
    print(f"data warning review dry-run script: {DATA_WARNING_REVIEW_DRY_RUN.exists()}")
    print(f"data warning review dry-run reports: {report_count('data_warning_review_dry_run_*.md')}")
    print(f"paper question corrections csv: {PAPER_QUESTION_CORRECTIONS.exists()}")
    print(f"paper question corrections script: {PAPER_QUESTION_CORRECTIONS_SCRIPT.exists()}")
    print(f"paper question corrections reports: {report_count('paper_question_corrections_dry_run_*.md')}")
    print(f"question tex corrections csv: {QUESTION_TEX_CORRECTIONS.exists()}")
    print(f"paper mapping csv: {exists('db/seed/paper_name_mapping.csv')}")
    print(f"paper position review csv: {exists('db/seed/paper_position_review_20260902_warning_review.csv')}")
    print(f"missing asset review csv: {exists('db/seed/missing_asset_review_20260902_warning_review.csv')}")
    print(f"import draft review csv: {exists('db/seed/import_draft_review_20260902_warning_review.csv')}")
    print(f"initial preview db: {INITIAL_DB.exists()}")
    print(f"knowledge preview db: {KNOWLEDGE_DB.exists()}")
    print(f"mapped preview db: {MAPPED_DB.exists()}")
    print(f"paper-corrected preview db: {PAPER_CORRECTED_DB.exists()}")
    print(f"asset preview db: {ASSET_DB.exists()}")
    print(f"equivalence review preview db: {EQUIVALENCE_REVIEW_DB.exists()}")
    print(f"import draft preview db: {IMPORT_DRAFT_DB.exists()}")
    print(f"draft commit preview db: {DRAFT_COMMIT_DB.exists()}")
    print(f"book import preview db: {BOOK_IMPORT_DB.exists()}")
    print(f"topic import preview db: {TOPIC_IMPORT_DB.exists()}")
    print(f"combined preview db: {COMBINED_DB.exists()}")
    print(f"combined commit preview db: {COMBINED_COMMIT_PREVIEW_DB.exists()}")
    print(f"data warning review preview db: {DATA_WARNING_REVIEW_DB.exists()}")
    print(f"formal sqlite db: {FORMAL_DB.exists()}")
    print(f"backup dir: {(PROJECT_ROOT / 'data' / 'backups').exists()}")
    print("")
    print("Initial preview database")
    for key, value in initial_counts.items():
        print(f"- {key}: {value}")
    print("")
    print("Paper-mapped preview database")
    for key, value in mapped_counts.items():
        print(f"- {key}: {value}")
    if MAPPED_DB.exists():
        print(f"- knowledge_area: {count_table(MAPPED_DB, 'knowledge_area')}")
        print(f"- question_knowledge_area: {count_table(MAPPED_DB, 'question_knowledge_area')}")
        print(f"- question_equivalence: {count_table(MAPPED_DB, 'question_equivalence')}")
    if ASSET_DB.exists():
        print("")
        print("Asset preview database")
        print(f"- question: {count_table(ASSET_DB, 'question')}")
        print(f"- question_asset: {count_table(ASSET_DB, 'question_asset')}")
    if PAPER_CORRECTED_DB.exists():
        print("")
        print("Paper-corrected preview database")
        print(f"- question: {count_table(PAPER_CORRECTED_DB, 'question')}")
        print(f"- paper: {count_table(PAPER_CORRECTED_DB, 'paper')}")
        print(f"- paper_question: {count_table(PAPER_CORRECTED_DB, 'paper_question')}")
        print(f"- question_equivalence: {count_table(PAPER_CORRECTED_DB, 'question_equivalence')}")
    if EQUIVALENCE_REVIEW_DB.exists():
        print("")
        print("Equivalence-review preview database")
        print(f"- question: {count_table(EQUIVALENCE_REVIEW_DB, 'question')}")
        print(f"- question_equivalence: {count_table(EQUIVALENCE_REVIEW_DB, 'question_equivalence')}")
        print(f"- question_knowledge_area: {count_table(EQUIVALENCE_REVIEW_DB, 'question_knowledge_area')}")
    if IMPORT_DRAFT_DB.exists():
        print("")
        print("Import-draft preview database")
        print(f"- import_batch: {count_table(IMPORT_DRAFT_DB, 'import_batch')}")
        print(f"- question_import_draft: {count_table(IMPORT_DRAFT_DB, 'question_import_draft')}")
        print(f"- question_import_draft_asset: {count_table(IMPORT_DRAFT_DB, 'question_import_draft_asset')}")
        print(f"- import_report_item: {count_table(IMPORT_DRAFT_DB, 'import_report_item')}")
    if DRAFT_COMMIT_DB.exists():
        print("")
        print("Draft-commit preview database")
        print(f"- question: {count_table(DRAFT_COMMIT_DB, 'question')}")
        print(f"- question_asset: {count_table(DRAFT_COMMIT_DB, 'question_asset')}")
        print(f"- question_revision: {count_table(DRAFT_COMMIT_DB, 'question_revision')}")
        print(f"- question_import_draft: {count_table(DRAFT_COMMIT_DB, 'question_import_draft')}")
    if BOOK_IMPORT_DB.exists():
        print("")
        print("Book-import preview database")
        print(f"- book: {count_table(BOOK_IMPORT_DB, 'book')}")
        print(f"- book_section: {count_table(BOOK_IMPORT_DB, 'book_section')}")
        print(f"- book_exercise_question: {count_table(BOOK_IMPORT_DB, 'book_exercise_question')}")
    if TOPIC_IMPORT_DB.exists():
        print("")
        print("Topic-import preview database")
        print(f"- topic_module: {count_table(TOPIC_IMPORT_DB, 'topic_module')}")
        print(f"- topic: {count_table(TOPIC_IMPORT_DB, 'topic')}")
        print(f"- topic_question: {count_table(TOPIC_IMPORT_DB, 'topic_question')}")
    if COMBINED_DB.exists():
        print("")
        print("Combined preview database")
        for table in [
            "question",
            "paper",
            "paper_question",
            "knowledge_area",
            "question_knowledge_area",
            "question_equivalence",
            "question_asset",
            "import_batch",
            "question_import_draft",
            "question_import_draft_asset",
            "book",
            "book_section",
            "book_exercise_question",
            "topic_module",
            "topic",
            "topic_question",
        ]:
            print(f"- {table}: {count_table(COMBINED_DB, table)}")
    if DATA_WARNING_REVIEW_DB.exists():
        print("")
        print("Data-warning-review preview database")
        print(f"- question: {count_table(DATA_WARNING_REVIEW_DB, 'question')}")
        print(f"- paper_question: {count_table(DATA_WARNING_REVIEW_DB, 'paper_question')}")
        print(f"- question_equivalence: {count_table(DATA_WARNING_REVIEW_DB, 'question_equivalence')}")
        print(f"- question_asset: {count_table(DATA_WARNING_REVIEW_DB, 'question_asset')}")
        print(f"- question_import_draft: {count_table(DATA_WARNING_REVIEW_DB, 'question_import_draft')}")
    if FORMAL_DB.exists():
        print("")
        print("Formal SQLite database")
        for table in FORMAL_DB_TABLES:
            print(f"- {table}: {count_table(FORMAL_DB, table)}")
    if COMBINED_COMMIT_PREVIEW_DB.exists():
        print("")
        print("Combined commit preview database")
        print(f"- question: {count_table(COMBINED_COMMIT_PREVIEW_DB, 'question')}")
        print(f"- paper_question: {count_table(COMBINED_COMMIT_PREVIEW_DB, 'paper_question')}")
        print(f"- question_asset: {count_table(COMBINED_COMMIT_PREVIEW_DB, 'question_asset')}")
        print(f"- question_revision: {count_table(COMBINED_COMMIT_PREVIEW_DB, 'question_revision')}")
        print(f"- question_import_draft: {count_table(COMBINED_COMMIT_PREVIEW_DB, 'question_import_draft')}")
    print("")
    print("Tracked reports")
    for path in sorted((PROJECT_ROOT / "reports").glob("*.md")):
        print(f"- {path.relative_to(PROJECT_ROOT).as_posix()}")


if __name__ == "__main__":
    main()
