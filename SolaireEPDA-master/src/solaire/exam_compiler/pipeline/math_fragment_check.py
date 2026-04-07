"""Static checks on math delimiters and LaTeX plain-text hazards (M1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solaire.exam_compiler.loaders.questions import LoadedQuestions

from solaire.exam_compiler.models import BankRecord, QuestionGroupRecord, QuestionItem

# 扫描模式：正文（out）| 行内 $...$（in）| 显示 $$...$$（disp）
_OUT, _IN, _DISP = "out", "in", "disp"


def _collect_text_fields(rec: BankRecord) -> list[tuple[str, str]]:
    """(field_label, text) for math scanning."""
    if isinstance(rec, QuestionItem):
        parts: list[tuple[str, str]] = [
            ("content", rec.content),
            ("answer", rec.answer),
            ("analysis", rec.analysis),
        ]
        if rec.options:
            for k, v in rec.options.items():
                parts.append((f"option_{k}", v))
        return [(a, b) for a, b in parts if (b or "").strip()]
    if isinstance(rec, QuestionGroupRecord):
        out: list[tuple[str, str]] = [("material", rec.material)]
        for qi in rec.flatten():
            out.append(("content", qi.content))
            out.append(("answer", qi.answer))
            out.append(("analysis", qi.analysis))
            if qi.options:
                for k, v in qi.options.items():
                    out.append((f"option_{k}", v))
        return [(a, b) for a, b in out if (b or "").strip()]
    return []


def _unescaped_dollar_count(seg: str) -> int:
    n = 0
    i = 0
    while i < len(seg):
        if seg[i] == "\\" and i + 1 < len(seg):
            i += 2
            continue
        if seg[i] == "$":
            n += 1
        i += 1
    return n


def _check_dollar_balance(text: str) -> list[str]:
    """Detect unbalanced $ / $$ (ignores escaped \\$)."""
    warnings: list[str] = []
    if "$$" in text and text.count("$$") % 2 != 0:
        warnings.append("`$$` 出现次数为奇数，可能存在未闭合的显示公式。")
    parts = text.split("$$")
    for i in range(0, len(parts), 2):
        seg = parts[i]
        if _unescaped_dollar_count(seg) % 2 != 0:
            warnings.append("在显示公式块之外，单个 `$` 未成对，请检查行内公式。")
            break
    return warnings


def _check_latex_special_chars_outside_math(text: str) -> list[tuple[str, str]]:
    """
    在 LaTeX 中，正文（非数学模式）下 `_` `^` `%` 等会引发错误或吞掉后续内容。
    按行内 `$...$` 与 `$$...$$` 切换状态，仅在正文段中报警（`\\` 视为转义下一字符）。
    返回 (code, message) 列表，每种 code 至多一条。
    """
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    mode = _OUT
    i = 0
    n = len(text)

    while i < n:
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue

        if mode == _OUT:
            if i + 1 < n and text[i : i + 2] == "$$":
                mode = _DISP
                i += 2
                continue
            if text[i] == "$":
                mode = _IN
                i += 1
                continue
            if text[i] == "_" and "latex_underscore" not in seen:
                out.append(
                    (
                        "latex_underscore",
                        "正文（非数学模式）中出现未转义的下划线 `_`，LaTeX 版式可能报错；"
                        "填空横线请用 `\\_` 连续书写或 `\\underline{...}`。",
                    )
                )
                seen.add("latex_underscore")
            elif text[i] == "^" and "latex_caret" not in seen:
                out.append(
                    (
                        "latex_caret",
                        "正文（非数学模式）中出现未转义的 `^`，LaTeX 版式可能报错；请用 `\\^{}` 或放入数学公式中。",
                    )
                )
                seen.add("latex_caret")
            elif text[i] == "%" and "latex_percent" not in seen:
                out.append(
                    (
                        "latex_percent",
                        "正文（非数学模式）中出现未转义的 `%`，LaTeX 会将其视为注释起始；请改为 `\\%`。",
                    )
                )
                seen.add("latex_percent")
            i += 1
            continue

        if mode == _IN:
            if text[i] == "$":
                mode = _OUT
                i += 1
                continue
            i += 1
            continue

        # _DISP
        if i + 1 < n and text[i : i + 2] == "$$":
            mode = _OUT
            i += 2
            continue
        i += 1

    return out


def analyze_math_static_for_loaded(loaded: LoadedQuestions) -> list[dict[str, str]]:
    """
    Return a list of warning dicts: qualified_id, field, code, message.

    code 含义：
    - math_delimiter：$ / $$ 定界符疑似不成对
    - latex_underscore / latex_caret / latex_percent：正文模式下未转义的 TeX 特殊字符
    """
    results: list[dict[str, str]] = []
    for qid, rec in loaded.by_qualified.items():
        for field, text in _collect_text_fields(rec):
            for code, msg in _check_latex_special_chars_outside_math(text):
                results.append(
                    {
                        "qualified_id": qid,
                        "field": field,
                        "code": code,
                        "message": msg,
                    }
                )
            if "$" not in text and "$$" not in text:
                continue
            for msg in _check_dollar_balance(text):
                results.append(
                    {
                        "qualified_id": qid,
                        "field": field,
                        "code": "math_delimiter",
                        "message": msg,
                    }
                )
    return results
