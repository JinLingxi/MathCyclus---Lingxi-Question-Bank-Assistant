"""Pure OCR/TeX parsing helpers for manual and batch draft entry."""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, Callable

from utils.latex_ops import generate_filename, parse_meta_data


ProblemFilenameBuilder = Callable[[str, str, str, str, str], str]


@dataclass(frozen=True)
class ProblemHeader:
    year: str = ""
    type: str = ""
    paper: str = ""
    number: str = ""
    subject: str = ""

    def as_batch_info(self) -> dict[str, str]:
        return {"year": self.year, "type": self.type, "paper": self.paper}


@dataclass(frozen=True)
class SingleOcrParseResult:
    normalized_text: str
    header: ProblemHeader | None = None
    subject_list: list[str] = field(default_factory=list)
    warning: str = ""


@dataclass(frozen=True)
class BatchOcrParseResult:
    normalized_text: str
    first_info: dict[str, str] | None = None
    item_count: int = 0


def sanitize_ocr_text(text: str) -> str:
    """Normalize punctuation and remove AI file separators from OCR output."""
    cleaned = str(text or "")
    cleaned = re.sub(r"\$(\s*)。", r"$\1.", cleaned)
    cleaned = re.sub(r"\$\$(\s*)。", r"$$\1.", cleaned)
    cleaned = re.sub(r"---.*?\.tex---\n*", "", cleaned).strip()
    return cleaned


def parse_problem_header(text: str) -> ProblemHeader | None:
    match = re.search(
        r"\\begin\{problem\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}\{(.*?)\}",
        text or "",
        re.DOTALL,
    )
    if not match:
        return None
    year, p_type, paper, number, subject = (value.strip() for value in match.groups())
    return ProblemHeader(year=year, type=p_type, paper=paper, number=number, subject=subject)


def normalize_paper_type(value: str, paper_types: dict[str, str] | None = None) -> tuple[str, bool]:
    """Return a canonical paper type code when possible."""
    text = str(value or "").strip()
    if not text:
        return "", False
    if not paper_types:
        return text, True

    clean = text.split("(")[0].split("（")[0].strip()
    for key, label in paper_types.items():
        if key == clean or label == clean or key == text or label == text:
            return key, True
    return text, False


def extract_subject_list(subject_text: str, valid_subjects: list[str] | tuple[str, ...] | None = None) -> list[str]:
    subjects = [item.strip() for item in str(subject_text or "").split("，") if item.strip()]
    if not valid_subjects:
        return subjects
    valid = set(valid_subjects)
    return [subject for subject in subjects if subject in valid]


def normalize_single_problem_structure(
    text: str,
    s_year: str = "?",
    s_type: str = "?",
    s_paper: str = "?",
    s_num: str = "?",
    s_subj: str = "?",
) -> str:
    r"""Rebuild a single problem as problem + answer + solutions environments."""
    ans_match = re.search(r"\\begin\{answer\}(.*?)\\end\{answer\}", text or "", re.DOTALL)
    ans_text = ans_match.group(0) if ans_match else ""

    sol_match = re.search(r"\\begin\{solutions?\}(.*?)\\end\{solutions?\}", text or "", re.DOTALL)
    sol_text = sol_match.group(0) if sol_match else ""

    stem_text = str(text or "")
    if ans_text:
        stem_text = stem_text.replace(ans_text, "")
    if sol_text:
        stem_text = stem_text.replace(sol_text, "")

    old_params_match = re.search(
        r"\\begin\{problem\}(\{.*?\})?(\{.*?\})?(\{.*?\})?(\{.*?\})?(\{.*?\})?",
        stem_text,
    )
    if old_params_match and s_year == "?":
        params = [param.strip("{}") if param else "?" for param in old_params_match.groups()]
        s_year, s_type, s_paper, s_num, s_subj = (params + ["?", "?", "?", "?", "?"])[:5]

    stem_text = re.sub(r"\\begin\{problem\}(\{.*?\}){0,5}", "", stem_text)
    stem_text = stem_text.replace(r"\end{problem}", "")
    stem_text = stem_text.strip()

    full_text = (
        f"\\begin{{problem}}{{{s_year}}}{{{s_type}}}{{{s_paper}}}{{{s_num}}}{{{s_subj}}}\n"
        f"{stem_text}\n"
        "\\end{problem}"
    )

    if ans_text:
        full_text += f"\n\n{ans_text}"
    else:
        full_text += "\n\n\\begin{answer}\n\n\\end{answer}"

    if sol_text:
        full_text += f"\n\n{sol_text}"
    else:
        full_text += "\n\n\\begin{solutions}\n\n\\end{solutions}"

    if r"\begin{choices}" in full_text:
        parts = full_text.split(r"\begin{choices}")
        for index in range(len(parts) - 1):
            prefix = parts[index].rstrip()
            if prefix.endswith("()") or prefix.endswith("（）"):
                prefix = prefix[:-2]
            if not prefix.endswith(r"\hspace{1cm})"):
                prefix += r" (\hspace{1cm})"
            parts[index] = prefix + "\n"
        full_text = r"\begin{choices}".join(parts)

    return full_text


def fix_problem_format(text: str) -> str:
    r"""Fix common non-standard \begin{problem} headers and choice line breaks."""
    fixed = str(text or "")

    pattern1 = r"\\begin\{problem\}\[(.*?)\]\[(.*?)\]\[(.*?)\]\s*\|\|(.*?)\|\|(.*?)\]"

    def repl1(match: re.Match[str]) -> str:
        return (
            f"\\begin{{problem}}{{{match.group(1)}}}{{{match.group(2)}}}"
            f"{{{match.group(3)}}}{{{match.group(4)}}}{{{match.group(5)}}}"
        )

    fixed = re.sub(pattern1, repl1, fixed)

    pattern2 = r"\\begin\{problem\}\[(.*?)\]\[(.*?)\]\[(.*?)\]\s*\[(.*?)\]\[(.*?)\]"

    def repl2(match: re.Match[str]) -> str:
        return (
            f"\\begin{{problem}}{{{match.group(1)}}}{{{match.group(2)}}}"
            f"{{{match.group(3)}}}{{{match.group(4)}}}{{{match.group(5)}}}"
        )

    fixed = re.sub(pattern2, repl2, fixed)
    fixed = re.sub(r"\\begin\{problem\}(?!\{)", r"\\begin{problem}{?}{?}{?}{?}{?}", fixed)

    def fix_choice_newlines(match: re.Match[str]) -> str:
        inner_content = match.group(1).replace("\n", " ")
        return f"\\choice{{{{{inner_content}}}}}"

    return re.sub(r"\\choice\{\{(.*?)\}\}", fix_choice_newlines, fixed, flags=re.DOTALL)


def increment_question_number(number: str, offset: int = 1) -> str:
    value = str(number or "").strip()
    if value.isdigit():
        return str(int(value) + offset)
    return f"{value}-{offset + 1}" if value else str(offset + 1)


def split_problem_block_by_choices(problem_block: str) -> list[str]:
    """Split an OCR block only when repeated choice environments give clear boundaries."""
    choices = list(re.finditer(r"\\begin\{choices\}", problem_block or ""))
    if len(choices) < 2:
        return [problem_block]

    for env_name in ("answer", "solutions", "solution"):
        match = re.search(rf"\\begin\{{{env_name}\}}(.*?)\\end\{{{env_name}\}}", problem_block or "", re.DOTALL)
        if match and match.group(1).strip():
            return [problem_block]

    boundaries = []
    for choice_start in choices[1:]:
        previous_end = problem_block.rfind(r"\end{choices}", 0, choice_start.start())
        if previous_end < 0:
            return [problem_block]
        boundary = previous_end + len(r"\end{choices}")
        between = problem_block[boundary:choice_start.start()]
        if not re.search(r"[^\s\\{}%]", between):
            return [problem_block]
        boundaries.append(boundary)

    pieces = []
    starts = [0] + boundaries
    ends = boundaries + [len(problem_block)]
    for start, end in zip(starts, ends):
        piece = problem_block[start:end].strip()
        if piece:
            pieces.append(piece)
    return pieces if len(pieces) == len(choices) else [problem_block]


def parse_single_ocr_result(
    ocr_result: str,
    *,
    paper_types: dict[str, str] | None = None,
    valid_subjects: list[str] | tuple[str, ...] | None = None,
) -> SingleOcrParseResult:
    cleaned = fix_problem_format(sanitize_ocr_text(ocr_result))
    header = parse_problem_header(cleaned)
    if not header:
        return SingleOcrParseResult(
            normalized_text=normalize_single_problem_structure(cleaned),
            warning="识别内容未包含标准 problem 结构，已自动进行结构重组。",
        )

    normalized_type, found_type = normalize_paper_type(header.type, paper_types)
    paper = header.paper
    if paper_types and not found_type:
        normalized_type = "G"
        if header.type:
            paper = f"{header.type}-{paper}"

    normalized_header = ProblemHeader(
        year=header.year,
        type=normalized_type,
        paper=paper,
        number=header.number,
        subject=header.subject,
    )
    normalized_text = normalize_single_problem_structure(
        cleaned,
        normalized_header.year,
        normalized_header.type,
        normalized_header.paper,
        normalized_header.number,
        normalized_header.subject,
    )
    return SingleOcrParseResult(
        normalized_text=normalized_text,
        header=normalized_header,
        subject_list=extract_subject_list(normalized_header.subject, valid_subjects),
    )


def process_batch_ocr_result(
    ocr_result: str,
    *,
    start_id: int = 1,
    filename_builder: ProblemFilenameBuilder = generate_filename,
) -> BatchOcrParseResult:
    """Normalize OCR output into one independently editable block per problem."""
    fixed = fix_problem_format(ocr_result)
    problem_starts = list(re.finditer(r"\\begin\{problem\}", fixed))
    if not problem_starts:
        return BatchOcrParseResult(normalized_text=fixed.strip(), item_count=0)

    current_id = int(start_id or 1)
    normalized_items: list[str] = []
    first_info: dict[str, str] | None = None

    for index, problem_start in enumerate(problem_starts):
        problem_end = problem_starts[index + 1].start() if index + 1 < len(problem_starts) else len(fixed)
        problem_block = fixed[problem_start.start():problem_end]
        problem_block = re.sub(r"\n?---[^\n]*?\.tex---\s*$", "", problem_block).strip()
        header = parse_problem_header(problem_block)
        if not header:
            continue

        if first_info is None:
            first_info = header.as_batch_info()

        fragments = split_problem_block_by_choices(problem_block)
        used_numbers: set[str] = set()
        for fragment_index, fragment in enumerate(fragments):
            fragment_number = header.number if fragment_index == 0 else increment_question_number(header.number, fragment_index)
            while fragment_number in used_numbers:
                fragment_number = increment_question_number(fragment_number)
            used_numbers.add(fragment_number)

            if len(fragments) == 1:
                fragment_content = fragment
            else:
                fragment_content = normalize_single_problem_structure(
                    fragment,
                    header.year,
                    header.type,
                    header.paper,
                    fragment_number,
                    header.subject or "未分类",
                )
            filename = filename_builder(header.year, header.type, header.paper, fragment_number, header.subject or "未分类")
            label_data = (
                "% === Begin Label Data ===\n"
                f"% ID: {current_id}\n"
                "% 难度星级: \n"
                "% 标签: \n"
                "% 备注: \n"
                "% 组卷引用次数: 0\n"
                "% === End  Label Data ==="
            )
            current_id += 1
            normalized_items.append(f"---{filename}---\n\n{label_data}\n\n{fragment_content}")

    return BatchOcrParseResult(
        normalized_text="\n\n".join(normalized_items).strip() if normalized_items else fixed.strip(),
        first_info=first_info,
        item_count=len(normalized_items),
    )


def extract_batch_info_from_ocr(ocr_result: str) -> dict[str, str] | None:
    header = parse_problem_header(ocr_result)
    return header.as_batch_info() if header else None


def result_to_form_fields(
    result: SingleOcrParseResult,
) -> dict[str, Any]:
    """Convert a single OCR parse result into Streamlit session-state field values."""
    if not result.header:
        return {"entry_content": result.normalized_text}
    return {
        "entry_year": result.header.year,
        "entry_p_type": result.header.type,
        "entry_paper_name": result.header.paper,
        "entry_number": result.header.number,
        "entry_subject_multi": result.subject_list,
        "entry_content": result.normalized_text,
    }


def split_text_list(value: str) -> list[str]:
    text = str(value or "")
    return [item.strip() for item in text.replace("，", "\n").replace(",", "\n").splitlines() if item.strip()]


def parse_asset_lines(value: str) -> list[dict[str, str]]:
    assets = []
    valid_roles = {"problem", "answer", "solution", "source", "thumbnail"}
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) == 1:
            role, source_path, caption, note = "problem", parts[0], "", ""
        elif parts[0] in valid_roles:
            role = parts[0]
            source_path = parts[1] if len(parts) > 1 else ""
            caption = parts[2] if len(parts) > 2 else ""
            note = " | ".join(parts[3:]).strip() if len(parts) > 3 else ""
        else:
            role = "problem"
            source_path = parts[0]
            caption = parts[1] if len(parts) > 1 else ""
            note = " | ".join(parts[2:]).strip() if len(parts) > 2 else ""
        if source_path:
            assets.append({"role": role, "source_path": source_path, "caption": caption, "note": note})
    return assets


def asset_caption_from_source_path(source_path: str) -> str:
    filename = PurePath(str(source_path or "").replace("\\", "/")).name.strip()
    if not filename:
        return ""
    return filename.rsplit(".", 1)[0].strip() if "." in filename else filename


def json_list_text(value: str, separator: str = "\n") -> str:
    try:
        parsed = json.loads(value or "[]")
    except Exception:
        return ""
    if not isinstance(parsed, list):
        return ""
    return separator.join(str(item).strip() for item in parsed if str(item).strip())


def extra_dict(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def read_balanced_argument(text: str, start_brace: int) -> tuple[str | None, int]:
    if start_brace < 0 or start_brace >= len(text) or text[start_brace] != "{":
        return None, start_brace
    depth = 0
    for index in range(start_brace, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start_brace + 1:index].strip(), index + 1
    return None, start_brace


def extract_choice_items(choices_inner: str) -> list[str]:
    choices = []
    cursor = 0
    while True:
        choice_index = choices_inner.find(r"\choice", cursor)
        if choice_index == -1:
            break
        brace_index = choices_inner.find("{", choice_index + len(r"\choice"))
        if brace_index == -1:
            break
        between = choices_inner[choice_index + len(r"\choice"):brace_index]
        if between.strip():
            cursor = choice_index + len(r"\choice")
            continue
        value, next_cursor = read_balanced_argument(choices_inner, brace_index)
        if value:
            choices.append(value)
        cursor = max(next_cursor, choice_index + len(r"\choice"))
    return choices


def extract_choices_from_stem(stem_tex: str) -> tuple[str, list[str]]:
    collected_choices: list[str] = []

    def replace_choices(match: re.Match[str]) -> str:
        collected_choices.extend(extract_choice_items(match.group(1) or ""))
        return ""

    cleaned = re.sub(
        r"\\begin\{choices\}(?:\[[^\]]*\])?([\s\S]*?)\\end\{choices\}",
        replace_choices,
        stem_tex or "",
        count=1,
    )
    return cleaned.strip(), collected_choices


def extract_env_inner_text(tex: str, env_pattern: str) -> str:
    if not tex:
        return ""
    match = re.search(rf"\\begin\{{{env_pattern}\}}(?:\[[^\]]*\])?([\s\S]*?)\\end\{{{env_pattern}\}}", tex)
    return (match.group(1) or "").strip() if match else ""


def strip_label_data_for_export(tex: str) -> str:
    try:
        _, clean_content = parse_meta_data(tex or "")
        return clean_content.strip()
    except Exception:
        return re.sub(
            r"%(?: === Meta Data ===| === Begin Label Data ===)\r?\n([\s\S]*?)%(?: === End Meta ===| === End\s+Label Data ===)\r?\n",
            "",
            tex or "",
            flags=re.DOTALL,
        ).strip()


def problem_header_fields(text: str, paper_types: dict[str, str] | None = None) -> dict[str, str]:
    header = parse_problem_header(text)
    if not header:
        return {}
    p_type = header.type
    if paper_types:
        normalized_type, found_type = normalize_paper_type(header.type, paper_types)
        if found_type:
            p_type = normalized_type
    return {
        "year": header.year,
        "p_type": p_type,
        "paper": header.paper,
        "number": header.number,
        "subject_str": header.subject,
    }


def strip_problem_body(tex: str, paper_types: dict[str, str] | None = None) -> tuple[dict[str, str], str, list[str], str, str]:
    source = strip_label_data_for_export(tex or "")
    fields = problem_header_fields(source, paper_types)
    answer_tex = extract_env_inner_text(source, "answer")
    solution_tex = extract_env_inner_text(source, "solutions?")
    without_answer = re.sub(r"\\begin\{answer\}[\s\S]*?\\end\{answer\}", "", source).strip()
    without_solution = re.sub(r"\\begin\{solutions?\}[\s\S]*?\\end\{solutions?\}", "", without_answer).strip()
    problem_match = re.search(
        r"\\begin\{problem\}(?:\s*\{.*?\}){5}([\s\S]*?)\\end\{problem\}",
        without_solution,
        flags=re.DOTALL,
    )
    if problem_match:
        stem_tex = problem_match.group(1).strip()
    else:
        stem_tex = re.sub(r"\\begin\{problem\}(?:\s*\{.*?\}){0,5}", "", without_solution, flags=re.DOTALL)
        stem_tex = stem_tex.replace(r"\end{problem}", "").strip()
    stem_tex, choices = extract_choices_from_stem(stem_tex)
    return fields, stem_tex, choices, answer_tex, solution_tex


def split_input_items(text: str) -> list[dict[str, str]]:
    source = (text or "").strip()
    if not source:
        return []
    delimiter_parts = re.split(r"---\s*(.+?\.tex)\s*---\s*", source, flags=re.DOTALL)
    if len(delimiter_parts) > 1:
        items = []
        for index in range(1, len(delimiter_parts), 2):
            body = delimiter_parts[index + 1] if index + 1 < len(delimiter_parts) else ""
            if body.strip():
                items.append({"label": delimiter_parts[index].strip(), "tex": body.strip()})
        if items:
            return items
    starts = [match.start() for match in re.finditer(r"\\begin\{problem\}", source)]
    if starts:
        items = []
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(source)
            block = source[start:end].strip()
            if block:
                items.append({"label": f"第 {index + 1} 题", "tex": block})
        return items
    return [{"label": "第 1 题", "tex": source}]


def source_label(source_kind: str, year: str, source_name: str, question_number: str, fallback: str = "") -> str:
    label = (fallback or "").strip()
    if label:
        return label
    return " · ".join(
        part
        for part in [source_kind, year, source_name, question_number]
        if str(part or "").strip()
    ) or "手动录入草稿"


def join_number_and_sub_number(number: str, sub_number: str) -> str:
    number_text = str(number or "").strip()
    sub_text = str(sub_number or "").strip()
    if not sub_text:
        return number_text
    if not number_text:
        return sub_text
    if f"({sub_text})" in number_text or f"（{sub_text}）" in number_text:
        return number_text
    return f"{number_text}({sub_text})"

