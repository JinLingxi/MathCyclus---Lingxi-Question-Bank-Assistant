"""Read-only adapters from SQLite questions to legacy UI/index shapes.

This module is intentionally not wired into the old browse or exam-selection
pages yet.  It provides a narrow compatibility layer so the future migration
can be smoke-tested before replacing the legacy CSV / ``chapters`` data source.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from services.database_service import readonly_database_connection
from services.export_service import question_to_legacy_tex
from services.question_db_service import QuestionListFilters, count_questions, get_question_bundle, list_questions


LEGACY_CSV_HEADERS = [
    "题目ID",
    "文件名称",
    "相对文件路径",
    "年份",
    "试卷类型",
    "试卷名称",
    "原卷题号",
    "知识板块",
    "标签",
    "包含TikZ绘图",
    "题型",
    "难度星级",
    "包含解析",
    "组卷引用次数",
    "备注",
    "来源题目ID",
    "挖空类型",
    "生成时间",
    "初次录入的时间",
    "最后修改时间",
    "题干",
    "答案",
    "解析",
]


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        parsed = []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _question_type_map(db_path: str | None = None) -> dict[int, str]:
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute("SELECT question_type_id, code, name FROM question_type").fetchall()
    labels: dict[int, str] = {}
    for row in rows:
        code = str(row["code"] or "")
        raw_name = str(row["name"] or "")
        if code in {"single_choice", "multiple_choice"}:
            label = "选择题"
        elif code == "fill_blank":
            label = "填空题"
        elif code == "solution":
            label = "解答题"
        else:
            label = raw_name or "其他"
        labels[int(row["question_type_id"])] = label
    return labels


def _source_from_bundle(bundle: dict) -> dict[str, str]:
    question = bundle.get("question") or {}
    paper_links = bundle.get("paper_links") or []
    paper = paper_links[0] if paper_links else {}
    year = paper.get("year") or question.get("detected_year") or ""
    paper_type = paper.get("paper_series") or question.get("paper_series") or ""
    paper_name = question.get("detected_source") or paper.get("paper_name") or question.get("paper_name") or ""
    question_number = (
        paper.get("question_number")
        or question.get("question_number")
        or question.get("detected_question_number")
        or ""
    )
    sub_number = paper.get("sub_number") or question.get("sub_number") or ""
    if sub_number and str(sub_number) not in str(question_number):
        question_number = f"{question_number}{sub_number}"
    topic = question.get("detected_chapter") or question.get("detected_topic") or ""
    return {
        "year": str(year or ""),
        "paper_type": str(paper_type or ""),
        "paper_name": str(paper_name or ""),
        "question_number": str(question_number or ""),
        "topic": str(topic or ""),
    }


def _legacy_file_stem(question: dict, source: dict[str, str]) -> str:
    legacy_path = str(question.get("legacy_file_path") or "").strip()
    if legacy_path:
        return Path(legacy_path).stem
    parts = [
        source.get("year") or "未设年份",
        source.get("paper_type") or "X",
        source.get("paper_name") or "未设来源",
        source.get("question_number") or "未设题号",
        source.get("topic") or "未分类",
    ]
    safe_parts = [part.replace("/", "_").replace("\\", "_").strip() or "未设置" for part in parts]
    return "-".join(safe_parts)


def _legacy_title_from_row(row: dict[str, str]) -> str:
    year = row.get("年份") or ""
    paper = row.get("试卷名称") or ""
    number = row.get("原卷题号") or ""
    topic = row.get("知识板块") or ""
    if year or paper or number:
        return f"【{year} {paper} 第{number}题】 ({topic})".strip()
    return row.get("文件名称") or row.get("SQLite题目ID") or "未命名题目"


def sqlite_bundle_to_legacy_row(
    bundle: dict,
    *,
    question_type_labels: dict[int, str] | None = None,
) -> dict[str, str]:
    """Convert one SQLite question bundle to the old CSV-index row shape."""
    question = bundle.get("question") or {}
    source = _source_from_bundle(bundle)
    legacy_tex = question_to_legacy_tex(question)
    tags = "，".join(_json_list(question.get("tags_json")))
    question_type_id = question.get("question_type_id")
    question_type = ""
    if question_type_id is not None:
        try:
            question_type = (question_type_labels or {}).get(int(question_type_id), "")
        except Exception:
            question_type = ""
    filename = _legacy_file_stem(question, source)
    row = {
        "题目ID": str(question.get("legacy_id") or question.get("question_id") or ""),
        "文件名称": filename,
        "相对文件路径": str(question.get("legacy_file_path") or ""),
        "年份": source["year"],
        "试卷类型": source["paper_type"],
        "试卷名称": source["paper_name"],
        "原卷题号": source["question_number"],
        "知识板块": source["topic"],
        "标签": tags,
        "包含TikZ绘图": "是" if "tikzpicture" in legacy_tex else "否",
        "题型": question_type,
        "难度星级": "" if question.get("difficulty") is None else str(question.get("difficulty")),
        "包含解析": "是" if str(question.get("solution_tex") or "").strip() else "否",
        "组卷引用次数": str(question.get("usage_count") or 0),
        "备注": str(question.get("note") or ""),
        "来源题目ID": "",
        "挖空类型": "",
        "生成时间": "",
        "初次录入的时间": str(question.get("created_at") or ""),
        "最后修改时间": str(question.get("updated_at") or ""),
        "题干": str(question.get("stem_tex") or ""),
        "答案": str(question.get("answer_tex") or ""),
        "解析": str(question.get("solution_tex") or ""),
        "SQLite题目ID": str(question.get("question_id") or ""),
        "legacy_tex": legacy_tex,
    }
    for header in LEGACY_CSV_HEADERS:
        row.setdefault(header, "")
    return row


def sqlite_summary_to_legacy_row(
    summary: dict[str, Any],
    *,
    question_type_labels: dict[int, str] | None = None,
) -> dict[str, str]:
    """Convert one SQLite summary row to old CSV-index fields.

    Unlike ``sqlite_bundle_to_legacy_row``, this does not synthesize full TeX
    and does not load source relations/assets. It is intended for search and
    selection candidate pools.
    """
    legacy_path = str(summary.get("legacy_file_path") or "").strip()
    source = {
        "year": str(summary.get("detected_year") or ""),
        "paper_type": str(summary.get("paper_series") or ""),
        "paper_name": str(summary.get("detected_source") or ""),
        "question_number": str(summary.get("detected_question_number") or ""),
        "topic": str(summary.get("detected_chapter") or summary.get("detected_topic") or ""),
    }
    if legacy_path:
        legacy_parts = Path(legacy_path).stem.split("-")
        if len(legacy_parts) >= 5:
            source["year"] = source["year"] or legacy_parts[0]
            source["paper_type"] = source["paper_type"] or legacy_parts[1]
            source["paper_name"] = source["paper_name"] or legacy_parts[2]
            source["question_number"] = source["question_number"] or legacy_parts[3]
            source["topic"] = source["topic"] or legacy_parts[4]
    if legacy_path:
        filename = Path(legacy_path).stem
    else:
        filename = _legacy_file_stem(summary, source)

    question_type_id = summary.get("question_type_id")
    question_type = ""
    if question_type_id is not None:
        try:
            question_type = (question_type_labels or {}).get(int(question_type_id), "")
        except Exception:
            question_type = ""

    stem_tex = str(summary.get("stem_tex") or "")
    answer_tex = str(summary.get("answer_tex") or "")
    solution_tex = str(summary.get("solution_tex") or "")
    combined_tex = "\n".join([stem_tex, answer_tex, solution_tex])
    row = {
        "题目ID": str(summary.get("legacy_id") or summary.get("question_id") or ""),
        "文件名称": filename,
        "相对文件路径": legacy_path,
        "年份": source["year"],
        "试卷类型": source["paper_type"],
        "试卷名称": source["paper_name"],
        "原卷题号": source["question_number"],
        "知识板块": source["topic"],
        "标签": "，".join(_json_list(summary.get("tags_json"))),
        "包含TikZ绘图": "是" if "tikzpicture" in combined_tex else "否",
        "题型": question_type,
        "难度星级": "" if summary.get("difficulty") is None else str(summary.get("difficulty")),
        "包含解析": "是" if solution_tex.strip() else "否",
        "组卷引用次数": str(summary.get("usage_count") or 0),
        "备注": str(summary.get("note") or ""),
        "来源题目ID": "",
        "挖空类型": "",
        "生成时间": "",
        "初次录入的时间": str(summary.get("created_at") or ""),
        "最后修改时间": str(summary.get("updated_at") or ""),
        "题干": stem_tex,
        "答案": answer_tex,
        "解析": solution_tex,
        "SQLite题目ID": str(summary.get("question_id") or ""),
    }
    for header in LEGACY_CSV_HEADERS:
        row.setdefault(header, "")
    return row


def sqlite_bundle_to_legacy_card(
    bundle: dict,
    *,
    question_type_labels: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Convert one SQLite bundle to a future old-card-compatible payload."""
    row = sqlite_bundle_to_legacy_row(bundle, question_type_labels=question_type_labels)
    question_id = row.get("SQLite题目ID") or row.get("题目ID") or ""
    legacy_path = row.get("相对文件路径") or ""
    return {
        "question_id": question_id,
        "label": _legacy_title_from_row(row),
        "content": row.get("legacy_tex") or "",
        "file": f"{row.get('文件名称') or question_id}.tex",
        "path": legacy_path or f"sqlite://{question_id}",
        "subject": row.get("知识板块") or "未分类",
        "row": row,
        "source": "sqlite",
    }


def resolve_legacy_card_file_path(card: dict[str, Any], project_root: str | os.PathLike[str] | None = None) -> str:
    """Return an existing project file path for a legacy-shaped SQLite card.

    The old browse/exam UI still works with real ``.tex`` files.  During the
    transition, only cards that map back to an existing project file are safe
    to send into those workflows.
    """
    raw_path = str(card.get("path") or (card.get("row") or {}).get("相对文件路径") or "").strip()
    if not raw_path or raw_path.startswith("sqlite://"):
        return ""

    root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
    candidates: list[Path] = []
    raw = Path(raw_path)
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(root / raw_path)
        if not raw_path.replace("\\", "/").startswith("chapters/"):
            candidates.append(root / "chapters" / raw_path)

    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            common = os.path.commonpath([str(root), str(resolved)])
        except ValueError:
            continue
        if common == str(root) and resolved.is_file():
            return str(resolved)
    return ""


def list_sqlite_legacy_cards(
    db_path: str | None = None,
    filters: QuestionListFilters | None = None,
) -> list[dict[str, Any]]:
    """Return SQLite questions shaped for future legacy browse/exam migration."""
    filters = filters or QuestionListFilters()
    summaries = list_questions(db_path, filters)
    type_labels = _question_type_map(db_path)
    cards = []
    for summary in summaries:
        question_id = str(summary.get("question_id") or "")
        if not question_id:
            continue
        bundle = get_question_bundle(db_path, question_id)
        cards.append(sqlite_bundle_to_legacy_card(bundle, question_type_labels=type_labels))
    return cards


def _copy_filters(filters: QuestionListFilters, *, limit: int, offset: int) -> QuestionListFilters:
    return QuestionListFilters(
        keyword=filters.keyword,
        year=filters.year,
        chapter=filters.chapter,
        source=filters.source,
        question_number=filters.question_number,
        question_type_id=filters.question_type_id,
        difficulty=filters.difficulty,
        limit=limit,
        offset=offset,
    )


def list_sqlite_legacy_rows(
    db_path: str | None = None,
    filters: QuestionListFilters | None = None,
    *,
    max_rows: int | None = None,
) -> list[dict[str, str]]:
    """Return SQLite summaries shaped like old CSV rows.

    ``max_rows=None`` respects the supplied filter's own pagination.  Passing a
    positive ``max_rows`` pages through summaries up to that cap.  Passing
    ``max_rows=0`` scans all matching summaries.
    """
    filters = filters or QuestionListFilters()
    type_labels = _question_type_map(db_path)
    if max_rows is None:
        return [
            sqlite_summary_to_legacy_row(summary, question_type_labels=type_labels)
            for summary in list_questions(db_path, filters)
        ]

    target = count_questions(db_path, filters) if max_rows <= 0 else min(max_rows, count_questions(db_path, filters))
    rows: list[dict[str, str]] = []
    offset = int(filters.offset or 0)
    while len(rows) < target:
        batch_limit = min(100, target - len(rows))
        summaries = list_questions(db_path, _copy_filters(filters, limit=batch_limit, offset=offset))
        if not summaries:
            break
        rows.extend(sqlite_summary_to_legacy_row(summary, question_type_labels=type_labels) for summary in summaries)
        offset += len(summaries)
    return rows


def list_resolved_legacy_card_paths(
    db_path: str | None = None,
    filters: QuestionListFilters | None = None,
    *,
    project_root: str | os.PathLike[str] | None = None,
) -> list[str]:
    """Return existing legacy ``.tex`` paths for SQLite summaries.

    This intentionally reads only summary rows instead of full bundles, so UI
    bulk actions can use SQLite as an index without pre-rendering many
    questions.
    """
    filters = filters or QuestionListFilters()
    paths: list[str] = []
    seen: set[str] = set()
    for summary in list_questions(db_path, filters):
        path = resolve_legacy_card_file_path({"path": summary.get("legacy_file_path") or ""}, project_root)
        if path and path not in seen:
            paths.append(path)
            seen.add(path)
    return paths
