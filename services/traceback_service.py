"""Read-only traceback helpers for one structured SQLite question."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.asset_service import collect_asset_reference_issues
from services.question_db_service import get_question_bundle


ASSET_ISSUE_LABELS: tuple[tuple[str, str], ...] = (
    ("缺失 includegraphics", "missing_includegraphics"),
    ("未登记 questionasset", "unresolved_questionasset"),
    ("附件文件缺失", "missing_asset_files"),
    ("已登记但未被 questionasset 引用", "unreferenced_assets"),
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _join_parts(parts: list[str]) -> str:
    return " · ".join(part for part in parts if part)


def _paper_row(link: dict) -> str:
    number = _clean(link.get("question_number"))
    sub_number = _clean(link.get("sub_number"))
    number_text = f"第{number}{sub_number}题" if number or sub_number else ""
    return _join_parts(
        [
            _clean(link.get("year")),
            _clean(link.get("paper_name")),
            _clean(link.get("track")),
            number_text,
        ]
    )


def _book_row(link: dict) -> str:
    page_number = _clean(link.get("page_number"))
    exercise_number = _clean(link.get("exercise_number"))
    sub_number = _clean(link.get("sub_number"))
    exercise_text = exercise_number
    if exercise_text and sub_number:
        exercise_text = f"{exercise_text}({sub_number})"
    elif sub_number:
        exercise_text = f"小题{sub_number}"
    return _join_parts(
        [
            _clean(link.get("title")),
            _clean(link.get("section_title")),
            f"P{page_number}" if page_number else "",
            _clean(link.get("column_name")),
            exercise_text,
        ]
    )


def _topic_row(link: dict) -> str:
    return _join_parts(
        [
            _clean(link.get("module_name")),
            _clean(link.get("topic_name")),
            _clean(link.get("group_name")),
        ]
    )


def _asset_issue_rows(asset_issues: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for label, key in ASSET_ISSUE_LABELS:
        count = len(asset_issues.get(key) or [])
        if count:
            rows.append(f"{label}：{count} 个")
    if not rows and (
        asset_issues.get("includegraphics_refs")
        or asset_issues.get("questionasset_refs")
        or asset_issues.get("registered_asset_count")
    ):
        rows.append("图片引用检查通过")
    return rows


def build_question_traceback(bundle: dict, *, project_root: str | Path | None = None) -> dict[str, Any]:
    """Build display-ready traceback information from a question bundle."""
    question = bundle.get("question") or {}
    paper_links = list(bundle.get("paper_links") or [])
    book_links = list(bundle.get("book_links") or [])
    topic_links = list(bundle.get("topic_links") or [])
    assets = list(bundle.get("assets") or [])

    source_rows = [_paper_row(link) for link in paper_links]
    source_rows.extend(_book_row(link) for link in book_links)
    source_rows.extend(_topic_row(link) for link in topic_links)
    source_rows = [row for row in source_rows if row]

    asset_issues = collect_asset_reference_issues(
        question,
        assets,
        project_root=project_root,
        source_file=question.get("legacy_file_path") or "",
    )
    asset_issues["registered_asset_count"] = len(assets)
    issue_rows = _asset_issue_rows(asset_issues)

    counts = {
        "paper": len(paper_links),
        "book": len(book_links),
        "topic": len(topic_links),
        "source": len(paper_links) + len(book_links) + len(topic_links),
        "asset": len(assets),
        "asset_issue": sum(len(asset_issues.get(key) or []) for _, key in ASSET_ISSUE_LABELS),
    }
    summary_bits = []
    if counts["source"]:
        summary_bits.append(f"试卷{counts['paper']} / 教材{counts['book']} / 专题{counts['topic']}")
    if counts["asset"]:
        summary_bits.append(f"{counts['asset']} 个资源")
    if counts["asset_issue"]:
        summary_bits.append("有待检查项")

    return {
        "question_id": _clean(question.get("question_id")),
        "exists": bool(question),
        "question": question,
        "paper_links": paper_links,
        "book_links": book_links,
        "topic_links": topic_links,
        "assets": assets,
        "source_rows": source_rows,
        "asset_issue_rows": issue_rows,
        "asset_issues": asset_issues,
        "counts": counts,
        "summary": " · ".join(summary_bits) or "暂无资料",
    }


def get_question_traceback(
    db_path: str | None,
    question_id: str,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return one question's read-only traceback information."""
    return build_question_traceback(
        get_question_bundle(db_path, question_id),
        project_root=project_root,
    )
