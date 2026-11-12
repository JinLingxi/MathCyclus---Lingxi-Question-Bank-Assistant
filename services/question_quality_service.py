"""Non-blocking quality audits for structured questions."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from services.asset_service import collect_asset_reference_issues
from services.question_db_service import QuestionListFilters, get_question_bundle, list_questions_page


TYPE_LABELS = {
    1: "单选题",
    2: "多选题",
    3: "填空题",
    4: "解答题",
    5: "其他",
    6: "判断题",
}
_BEGIN_PROBLEM = re.compile(r"\\begin\s*\{problem\}")
_END_PROBLEM = re.compile(r"\\end\s*\{problem\}")
_CHOICE_COMMAND = re.compile(r"(?<![A-Za-z])\\choice\s*\{")


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _unescaped_brace_balance(value: str) -> int:
    balance = 0
    escaped = False
    for char in str(value or ""):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == "{":
            balance += 1
        elif char == "}":
            balance -= 1
    return balance


def audit_question_bundle(bundle: dict[str, Any], *, project_root: str = "") -> dict[str, Any]:
    question = bundle.get("question") or {}
    question_id = str(question.get("question_id") or "")
    errors: list[str] = []
    warnings: list[str] = []
    stem = str(question.get("stem_tex") or "").strip()
    canonical = str(question.get("canonical_tex") or "").strip()
    tex = canonical or stem
    type_id = question.get("question_type_id")
    try:
        type_id = int(type_id) if type_id not in (None, "") else None
    except (TypeError, ValueError):
        type_id = None
    choices = _json_list(question.get("choices_json"))

    if not stem:
        errors.append("题干为空")
    if type_id is None:
        warnings.append("题型未设置")
    type_label = TYPE_LABELS.get(type_id, str(type_id or "未设置"))
    if type_id in {1, 2} and len([item for item in choices if str(item).strip()]) < 2:
        errors.append(f"{type_label}选项少于 2 个")
    if type_id not in {1, 2} and choices:
        warnings.append(f"{type_label}仍登记了 {len(choices)} 个选项")
    if not str(question.get("answer_tex") or "").strip():
        warnings.append("答案为空")
    if not str(question.get("solution_tex") or "").strip():
        warnings.append("解析为空")
    if tex and _unescaped_brace_balance(tex) != 0:
        errors.append("TeX 花括号不平衡")
    if canonical and (_BEGIN_PROBLEM.search(canonical) is None or _END_PROBLEM.search(canonical) is None):
        warnings.append("canonical_tex 缺少完整 problem 环境")
    choice_commands = len(_CHOICE_COMMAND.findall(tex))
    if type_id in {1, 2} and choices and choice_commands and choice_commands != len(choices):
        warnings.append(f"TeX 中有 {choice_commands} 个 \\choice，结构化选项有 {len(choices)} 个")

    asset_issues = collect_asset_reference_issues(
        question,
        list(bundle.get("assets") or []),
        project_root=project_root or None,
        source_file=question.get("legacy_file_path") or "",
    )
    if asset_issues.get("missing_includegraphics"):
        errors.append(f"缺失 includegraphics 文件 {len(asset_issues['missing_includegraphics'])} 个")
    if asset_issues.get("unresolved_questionasset"):
        errors.append(f"未登记 questionasset {len(asset_issues['unresolved_questionasset'])} 个")
    if asset_issues.get("missing_asset_files"):
        errors.append(f"登记资源文件缺失 {len(asset_issues['missing_asset_files'])} 个")
    if asset_issues.get("integrity_issues"):
        errors.append(f"资源内容变化或无法读取 {len(asset_issues['integrity_issues'])} 个")
    if asset_issues.get("unreferenced_assets"):
        warnings.append(f"有 {len(asset_issues['unreferenced_assets'])} 个资源未被引用")
    if not (bundle.get("paper_links") or bundle.get("book_links") or bundle.get("topic_links")):
        warnings.append("没有来源或专题关系")

    status = "blocker" if errors else "warning" if warnings else "ok"
    return {
        "question_id": question_id,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "issue_count": len(errors) + len(warnings),
        "type": type_label,
        "source_count": len(bundle.get("paper_links") or []) + len(bundle.get("book_links") or []) + len(bundle.get("topic_links") or []),
    }


def audit_question_bank(
    db_path: str | None = None,
    *,
    filters: QuestionListFilters | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Audit a bounded page of questions; missing answers remain warnings."""
    safe_limit = max(1, min(int(limit or 100), 1000))
    base = filters or QuestionListFilters(limit=safe_limit, offset=0)
    page = list_questions_page(
        db_path,
        QuestionListFilters(
            keyword=base.keyword,
            year=base.year,
            chapter=base.chapter,
            source_kind=base.source_kind,
            paper_series=base.paper_series,
            source=base.source,
            question_number=base.question_number,
            question_type_id=base.question_type_id,
            difficulty=base.difficulty,
            limit=safe_limit,
            offset=base.offset,
        ),
    )
    rows = []
    counts = Counter()
    for item in page.get("items") or []:
        question_id = str(item.get("question_id") or "")
        result = audit_question_bundle(get_question_bundle(db_path, question_id))
        result["source"] = " · ".join(filter(None, [str(item.get("detected_year") or ""), str(item.get("detected_source") or "")]))
        rows.append(result)
        counts[result["status"]] += 1
    return {
        "total_matching": int(page.get("total") or 0),
        "audited": len(rows),
        "counts": dict(counts),
        "rows": rows,
        "limit": safe_limit,
        "offset": int(base.offset or 0),
    }
