from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
EXPORTS_DIR = PROJECT_ROOT / "exports"
REPORTS_DIR = PROJECT_ROOT / "reports"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.export_service import (
    collect_asset_placeholder_export_status,
    collect_graphics_export_status,
    copy_graphics_for_export,
    copy_questionassets_for_export,
    export_legacy_tree_to_tex,
    export_source_to_tex,
    get_source_export_bundle,
    question_to_legacy_tex,
    sanitize_tex_filename_component,
    source_export_default_filename,
)
from services.question_db_service import QuestionListFilters, count_questions, get_question, list_questions


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def write_question_tex(
    db_path: str,
    question_id: str,
    output_dir: Path,
    copy_graphics: bool = False,
    resolve_questionassets: bool = False,
) -> dict[str, object]:
    question = get_question(db_path, question_id)
    if not question:
        raise KeyError(f"question not found: {question_id}")

    output_path = output_dir / f"{question_id}.tex"
    tex = question_to_legacy_tex(question)
    graphics = collect_graphics_export_status(question, PROJECT_ROOT)
    asset_placeholders = collect_asset_placeholder_export_status(question, PROJECT_ROOT, db_path)
    if copy_graphics:
        tex, graphics = copy_graphics_for_export(question, tex, output_dir, PROJECT_ROOT)
    if resolve_questionassets:
        tex, asset_placeholders = copy_questionassets_for_export(
            question,
            tex,
            output_dir,
            PROJECT_ROOT,
            db_path=db_path,
        )
    output_path.write_text(tex, encoding="utf-8")
    return {
        "question_id": question_id,
        "output_path": relative_to_root(output_path),
        "graphics": graphics + asset_placeholders,
    }


def export_single(
    db_path: str,
    question_id: str,
    output_dir: Path,
    copy_graphics: bool = False,
    resolve_questionassets: bool = False,
) -> list[dict[str, object]]:
    return [write_question_tex(db_path, question_id, output_dir, copy_graphics, resolve_questionassets)]


def export_batch(
    db_path: str,
    output_dir: Path,
    limit: int,
    copy_graphics: bool = False,
    resolve_questionassets: bool = False,
    filters: QuestionListFilters | None = None,
) -> list[dict[str, object]]:
    filters = filters or QuestionListFilters()
    total = count_questions(db_path, filters)
    safe_limit = total if limit <= 0 else min(limit, total)
    page_filters = QuestionListFilters(
        keyword=filters.keyword,
        year=filters.year,
        chapter=filters.chapter,
        source=filters.source,
        question_number=filters.question_number,
        question_type_id=filters.question_type_id,
        difficulty=filters.difficulty,
        limit=safe_limit,
        offset=0,
    )
    rows = list_questions(db_path, page_filters)
    return [
        write_question_tex(db_path, row["question_id"], output_dir, copy_graphics, resolve_questionassets)
        for row in rows
    ]


def export_source_group(
    db_path: str,
    source_kind: str,
    source_id: str,
    output_dir: Path,
    *,
    section_id: str = "",
    group_name: str = "",
    copy_graphics: bool = False,
    resolve_questionassets: bool = False,
) -> list[dict[str, object]]:
    bundle = get_source_export_bundle(
        db_path,
        source_kind,
        source_id,
        section_id=section_id,
        group_name=group_name,
    )
    filename = source_export_default_filename(source_kind, bundle["source"])
    if section_id:
        stem = sanitize_tex_filename_component(Path(filename).stem + f"_section_{section_id}", "book_section_export")
        filename = stem + ".tex"
    if group_name:
        stem = sanitize_tex_filename_component(Path(filename).stem + f"_group_{group_name}", "topic_group_export")
        filename = stem + ".tex"
    result = export_source_to_tex(
        db_path,
        source_kind,
        source_id,
        output_dir / filename,
        project_root=PROJECT_ROOT,
        section_id=section_id,
        group_name=group_name,
        copy_graphics=copy_graphics,
        resolve_questionassets=resolve_questionassets,
    )
    result["output_path"] = relative_to_root(Path(result["output_path"]))
    return [result]


def write_report(exported: list[dict[str, object]], db_path: Path, report_path: Path) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def sample_line(item: dict[str, object]) -> str:
        if item.get("question_id"):
            return f"- `{item['question_id']}` -> `{item['output_path']}`"
        if item.get("source_kind") == "legacy_tree":
            return (
                f"- `旧目录结构` -> `{item.get('output_dir', '')}` "
                f"({item.get('question_count') or 0} 个文件)"
            )
        label = item.get("source_label") or item.get("source_id") or "unknown source"
        kind = item.get("source_kind_label") or item.get("source_kind") or "source"
        count = item.get("question_count") or 0
        return f"- `{kind}` `{label}` -> `{item.get('output_path', '')}` ({count} 题)"

    sample = "\n".join(sample_line(item) for item in exported[:30]) or "None"
    if len(exported) > 30:
        sample += f"\n- {len(exported) - 30} more exported files are omitted here."

    graphics_rows = []
    for item in exported:
        for graphic in item.get("graphics", []):
            question_id = graphic.get("question_id") or item.get("question_id") or item.get("source_id") or ""
            graphics_rows.append((question_id, graphic))
    graphics_sample = "\n".join(
        f"- `{question_id}`: `{graphic['ref']}` -> `{graphic['status']}`"
        + (
            f" ; `{graphic.get('output_path') or graphic.get('resolved_path')}`"
            if graphic.get("output_path") or graphic.get("resolved_path")
            else ""
        )
        for question_id, graphic in graphics_rows[:30]
    ) or "None"

    report_path.write_text(
        f"""# SQLite to TeX Export Report

> Generated at: {now}  
> Source database: `{relative_to_root(db_path)}`  
> Export target: `exports/`; this never overwrites `chapters/`.

## Summary

| Metric | Count |
| --- | ---: |
| Exported questions | {len(exported)} |
| Graphics references | {len(graphics_rows)} |
| Missing graphics | {sum(1 for _, graphic in graphics_rows if graphic['status'] == 'missing')} |

## Exported Samples

{sample}

## Graphics Handling

{graphics_sample}

## Notes

- This report verifies that structured SQLite records can be rendered back to legacy-compatible TeX.
- The exporter detects `\\includegraphics` references.
- With `--copy-graphics`, resolvable image files are copied to `figures/` and paths are rewritten.
- With `--resolve-questionassets`, `\\questionasset{{alias}}` placeholders are converted to `\\includegraphics`.
- `--paper-id` / `--book-id` / `--topic-id` export one source group into one ordered TeX file.
- `--legacy-tree` mirrors legacy `chapters/.../*.tex` paths under `exports/`.
""",
        encoding="utf-8",
    )


def filters_from_args(args: argparse.Namespace, limit: int = 20, offset: int = 0) -> QuestionListFilters:
    return QuestionListFilters(
        keyword=(args.keyword or "").strip(),
        year=args.year,
        chapter=(args.chapter or "").strip(),
        source=(args.source or "").strip(),
        question_type_id=args.question_type_id,
        difficulty=args.difficulty,
        limit=limit,
        offset=offset,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export TeX files from the preview SQLite database.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path.")
    parser.add_argument("--question-id", default="", help="Export only one question ID.")
    parser.add_argument("--paper-id", default="", help="Export one paper and its linked questions into one TeX file.")
    parser.add_argument("--book-id", default="", help="Export one book and its linked questions into one TeX file.")
    parser.add_argument("--book-section-id", default="", help="Restrict --book-id export to one section_id.")
    parser.add_argument("--topic-id", default="", help="Export one topic and its linked questions into one TeX file.")
    parser.add_argument("--topic-group-name", default="", help="Restrict --topic-id export to one group_name.")
    parser.add_argument("--source-kind", choices=["paper", "book", "topic"], default="", help="Generic source kind for grouped export.")
    parser.add_argument("--source-id", default="", help="Generic source ID for grouped export.")
    parser.add_argument("--legacy-tree", action="store_true", help="Mirror legacy chapters/... paths under exports instead of flat question IDs.")
    parser.add_argument("--keyword", default="", help="Optional keyword filter for batch or legacy-tree export.")
    parser.add_argument("--year", type=int, default=None, help="Optional year filter for batch or legacy-tree export.")
    parser.add_argument("--chapter", default="", help="Optional chapter filter for batch or legacy-tree export.")
    parser.add_argument("--source", default="", help="Optional detected source filter for batch or legacy-tree export.")
    parser.add_argument("--question-type-id", type=int, default=None, help="Optional question type filter for batch or legacy-tree export.")
    parser.add_argument("--difficulty", type=int, default=None, help="Optional difficulty filter for batch or legacy-tree export.")
    parser.add_argument("--limit", type=int, default=5, help="Export first N questions; 0 exports all.")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="Output timestamp.")
    parser.add_argument("--copy-graphics", action="store_true", help="Copy graphics and rewrite includegraphics paths.")
    parser.add_argument("--resolve-questionassets", action="store_true", help="Resolve questionasset placeholders through question_asset.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    db_path = db_path.resolve()
    if not db_path.exists():
        raise SystemExit(f"Database does not exist: {db_path}")

    output_dir = EXPORTS_DIR / f"db_to_tex_{args.stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    source_requests = []
    if args.paper_id:
        source_requests.append(("paper", args.paper_id))
    if args.book_id:
        source_requests.append(("book", args.book_id))
    if args.topic_id:
        source_requests.append(("topic", args.topic_id))
    if args.source_kind or args.source_id:
        if not args.source_kind or not args.source_id:
            raise SystemExit("--source-kind and --source-id must be provided together.")
        source_requests.append((args.source_kind, args.source_id))

    if args.question_id and (source_requests or args.legacy_tree):
        raise SystemExit("--question-id cannot be combined with grouped source or legacy-tree export options.")
    if args.legacy_tree and source_requests:
        raise SystemExit("--legacy-tree cannot be combined with grouped source export options.")
    if len(source_requests) > 1:
        raise SystemExit("Only one grouped source export can be requested at a time.")

    batch_filters = filters_from_args(args, limit=max(1, args.limit if args.limit > 0 else 100), offset=0)

    if args.legacy_tree:
        result = export_legacy_tree_to_tex(
            str(db_path),
            output_dir,
            batch_filters,
            project_root=PROJECT_ROOT,
            max_questions=args.limit,
            copy_graphics=args.copy_graphics,
            resolve_questionassets=args.resolve_questionassets,
        )
        result["output_dir"] = relative_to_root(Path(result["output_dir"]))
        for file_item in result.get("files", []):
            file_item["output_path"] = relative_to_root(Path(file_item["output_path"]))
        exported = [result]
    elif source_requests:
        source_kind, source_id = source_requests[0]
        exported = export_source_group(
            str(db_path),
            source_kind,
            source_id,
            output_dir,
            section_id=args.book_section_id if source_kind == "book" else "",
            group_name=args.topic_group_name if source_kind == "topic" else "",
            copy_graphics=args.copy_graphics,
            resolve_questionassets=args.resolve_questionassets,
        )
    elif args.question_id:
        exported = export_single(
            str(db_path),
            args.question_id,
            output_dir,
            args.copy_graphics,
            args.resolve_questionassets,
        )
    else:
        exported = export_batch(
            str(db_path),
            output_dir,
            args.limit,
            args.copy_graphics,
            args.resolve_questionassets,
            batch_filters,
        )

    report_path = REPORTS_DIR / f"db_to_tex_export_{args.stamp}.md"
    write_report(exported, db_path, report_path)

    print(f"exported={len(exported)}")
    if exported and exported[0].get("question_count"):
        print(f"exported_questions={exported[0].get('question_count')}")
    print(f"output_dir={relative_to_root(output_dir)}")
    print(f"report={relative_to_root(report_path)}")


if __name__ == "__main__":
    main()
