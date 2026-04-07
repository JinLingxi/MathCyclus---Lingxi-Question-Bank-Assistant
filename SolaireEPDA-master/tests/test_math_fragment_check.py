"""Math delimiter static checks (M1)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from solaire.exam_compiler.loaders.questions import LoadedQuestions
from solaire.exam_compiler.models import QuestionItem, parse_bank_root
from solaire.exam_compiler.pipeline.math_fragment_check import analyze_math_static_for_loaded


def test_analyze_math_warns_unbalanced_inline() -> None:
    lq = LoadedQuestions()
    lq.by_qualified["ns/q1"] = QuestionItem(
        id="q1",
        type="fill",
        content=r"未闭合 $x",
        answer="1",
        analysis="",
    )
    w = analyze_math_static_for_loaded(lq)
    assert w
    assert w[0].get("code") == "math_delimiter"


def test_analyze_math_ok_balanced() -> None:
    lq = LoadedQuestions()
    lq.by_qualified["ns/q1"] = QuestionItem(
        id="q1",
        type="fill",
        content=r"行内公式 $x+1$ 结束",
        answer="1",
        analysis="",
    )
    w = analyze_math_static_for_loaded(lq)
    assert not w


def test_warns_underscore_in_plain_text_fill_blank() -> None:
    lq = LoadedQuestions()
    lq.by_qualified["ns/q1"] = QuestionItem(
        id="q1",
        type="fill",
        content=r"最大值为 ______。",
        answer="2",
        analysis="",
    )
    w = analyze_math_static_for_loaded(lq)
    assert any(x["code"] == "latex_underscore" for x in w)


def test_underscore_inside_math_allowed() -> None:
    lq = LoadedQuestions()
    lq.by_qualified["ns/q1"] = QuestionItem(
        id="q1",
        type="fill",
        content=r"令 $x_1$ 与 $y^2$ 满足条件",
        answer="1",
        analysis="",
    )
    w = analyze_math_static_for_loaded(lq)
    assert not any(x["code"] == "latex_underscore" for x in w)
    assert not any(x["code"] == "latex_caret" for x in w)


@pytest.mark.xfail(
    reason="题干中 \\underline 与静态下划线规则的预期尚未对齐；保留样例作回归锚点",
    strict=False,
)
def test_qz2024_fill_001_sample_flags_content_underscore() -> None:
    p = Path(__file__).resolve().parent / "fixtures" / "qz2024_fill_001.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    rec = parse_bank_root(raw)
    lq = LoadedQuestions()
    lq.by_qualified["数学/qz2024_fill_001"] = rec
    w = analyze_math_static_for_loaded(lq)
    assert any(x["field"] == "content" and x["code"] == "latex_underscore" for x in w)
