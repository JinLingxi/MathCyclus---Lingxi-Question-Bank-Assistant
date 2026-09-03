from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from services.draft_parse_service import (
    asset_caption_from_source_path,
    extra_dict,
    fix_problem_format,
    join_number_and_sub_number,
    json_list_text,
    parse_asset_lines,
    parse_single_ocr_result,
    process_batch_ocr_result,
    read_balanced_argument,
    source_label,
    split_input_items,
    split_text_list,
    strip_problem_body,
)


PAPER_TYPES = {"G": "高考题", "M": "模拟题", "J": "教材题"}
SUBJECTS = ["函数", "导数", "立体几何"]


def check(name: str, ok: bool, detail: Any = "") -> dict[str, Any]:
    if is_dataclass(detail):
        detail = asdict(detail)
    return {"name": name, "ok": ok, "detail": detail}


def main() -> None:
    checks: list[dict[str, Any]] = []

    single_raw = r"""---tmp.tex---
\begin{problem}{2025}{高考题}{全国甲卷}{3}{函数，未知板块}
已知函数 $f(x)=x^2$，求 $f(1)$。()
\begin{choices}
\choice{{$0$}}
\choice{{$
1
$}}
\end{choices}
\end{problem}"""
    single = parse_single_ocr_result(single_raw, paper_types=PAPER_TYPES, valid_subjects=SUBJECTS)
    checks.append(
        check(
            "single_header_normalized",
            bool(single.header)
            and single.header.year == "2025"
            and single.header.type == "G"
            and single.header.paper == "全国甲卷"
            and single.header.number == "3",
            single.header,
        )
    )
    checks.append(check("single_subject_filtered", single.subject_list == ["函数"], single.subject_list))
    checks.append(check("single_has_answer_env", r"\begin{answer}" in single.normalized_text, single.normalized_text))
    checks.append(check("single_has_solution_env", r"\begin{solutions}" in single.normalized_text, single.normalized_text))
    checks.append(check("single_choice_gap_added", r"(\hspace{1cm})" in single.normalized_text, single.normalized_text))
    checks.append(check("single_math_period_fixed", "$f(1)$." in single.normalized_text, single.normalized_text))
    checks.append(check("single_choice_newline_fixed", r"\choice{{$ 1 $}}" in single.normalized_text, single.normalized_text))

    malformed = r"\begin{problem}[2024][G][新高考I卷] [9][导数] 设函数 $f(x)=x$。\end{problem}"
    fixed = fix_problem_format(malformed)
    checks.append(
        check(
            "malformed_header_fixed",
            r"\begin{problem}{2024}{G}{新高考I卷}{9}{导数}" in fixed,
            fixed,
        )
    )

    batch_raw = r"""\begin{problem}{2025}{G}{全国I卷}{1}{函数}
若 $a/b=1$，求 $a-b$。
\end{problem}

\begin{problem}{2025}{G}{全国I卷}{2}{导数}
求函数 $f(x)=x^3$ 的导数。
\end{problem}"""
    batch = process_batch_ocr_result(batch_raw, start_id=100)
    checks.append(check("batch_item_count", batch.item_count == 2, batch.item_count))
    checks.append(check("batch_first_info", batch.first_info == {"year": "2025", "type": "G", "paper": "全国I卷"}, batch.first_info))
    checks.append(check("batch_first_id", "% ID: 100" in batch.normalized_text, batch.normalized_text))
    checks.append(check("batch_second_id", "% ID: 101" in batch.normalized_text, batch.normalized_text))
    checks.append(check("batch_slash_content_kept", "$a/b=1$" in batch.normalized_text, batch.normalized_text))

    packed_choices = r"""\begin{problem}{2025}{G}{全国II卷}{7}{函数}
第一题题干
\begin{choices}
\choice{{$A$}}
\choice{{$B$}}
\end{choices}
第二题题干
\begin{choices}
\choice{{$C$}}
\choice{{$D$}}
\end{choices}
\end{problem}"""
    split_batch = process_batch_ocr_result(packed_choices, start_id=200)
    checks.append(check("choice_block_split_count", split_batch.item_count == 2, split_batch.normalized_text))
    checks.append(check("choice_block_next_number", "{全国II卷}{8}{函数}" in split_batch.normalized_text, split_batch.normalized_text))
    checks.append(check("choice_wrapper_kept", r"\choice{{$A$}}" in split_batch.normalized_text, split_batch.normalized_text))

    checks.append(
        check(
            "field_text_list_split",
            split_text_list("函数，导数, 立体几何\n概率") == ["函数", "导数", "立体几何", "概率"],
            split_text_list("函数，导数, 立体几何\n概率"),
        )
    )
    assets = parse_asset_lines(r"solution | C:\tmp\sol.png | 解答图 | 第2页 | 裁剪后" + "\n" + r"D:/tmp/problem.png | 题图")
    checks.append(
        check(
            "asset_lines_parsed",
            assets == [
                {"role": "solution", "source_path": r"C:\tmp\sol.png", "caption": "解答图", "note": "第2页 | 裁剪后"},
                {"role": "problem", "source_path": "D:/tmp/problem.png", "caption": "题图", "note": ""},
            ],
            assets,
        )
    )
    checks.append(
        check(
            "asset_caption_from_path",
            asset_caption_from_source_path(r"C:\tmp\my.figure.png") == "my.figure",
            asset_caption_from_source_path(r"C:\tmp\my.figure.png"),
        )
    )
    checks.append(check("json_list_text", json_list_text('["A", " B ", ""]', separator="，") == "A，B", json_list_text('["A", " B ", ""]', separator="，")))
    checks.append(check("extra_dict", extra_dict('{"source_kind": "试卷"}') == {"source_kind": "试卷"}, extra_dict('{"source_kind": "试卷"}')))
    balanced_value, balanced_cursor = read_balanced_argument(r"{{\frac{1}{2}}} tail", 0)
    checks.append(check("balanced_argument", balanced_value == r"{\frac{1}{2}}" and balanced_cursor == 15, {"value": balanced_value, "cursor": balanced_cursor}))

    body_tex = r"""% === Begin Label Data ===
% ID: 1
% === End  Label Data ===
\begin{problem}{2024}{高考题}{全国卷}{12}{函数}
题干文字
\begin{choices}
\choice{{$1$}}
\choice{{$2$}}
\end{choices}
\end{problem}
\begin{answer}
B
\end{answer}
\begin{solutions}
解析文字
\end{solutions}"""
    fields, stem_tex, choices, answer_tex, solution_tex = strip_problem_body(body_tex, paper_types=PAPER_TYPES)
    checks.append(
        check(
            "strip_problem_body",
            fields.get("p_type") == "G"
            and stem_tex == "题干文字"
            and choices == [r"{$1$}", r"{$2$}"]
            and answer_tex == "B"
            and solution_tex == "解析文字",
            {"fields": fields, "stem": stem_tex, "choices": choices, "answer": answer_tex, "solution": solution_tex},
        )
    )
    split_items = split_input_items("---a.tex---\nA\n---b.tex---\nB")
    checks.append(check("split_input_items_delimiter", split_items == [{"label": "a.tex", "tex": "A"}, {"label": "b.tex", "tex": "B"}], split_items))
    checks.append(check("source_label_fallback", source_label("试卷", "2025", "全国卷", "3") == "试卷 · 2025 · 全国卷 · 3", source_label("试卷", "2025", "全国卷", "3")))
    checks.append(check("join_sub_number", join_number_and_sub_number("12", "1") == "12(1)", join_number_and_sub_number("12", "1")))

    failed = [item for item in checks if not item["ok"]]
    report = {
        "status": "failed" if failed else "ok",
        "checks": checks,
        "writes_database": False,
        "writes_legacy_tex": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
