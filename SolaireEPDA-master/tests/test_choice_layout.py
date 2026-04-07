"""choice_layout 启发式。"""

from solaire.exam_compiler.choice_layout import (
    choice_option_pairs,
    infer_choice_layout,
    option_visual_weight,
    resolve_choice_layout,
)


def test_option_visual_weight_basic() -> None:
    assert option_visual_weight("a") == 1.0
    assert option_visual_weight("中") == 2.0


def test_infer_short_four_inline() -> None:
    opts = {
        "A": r"$1$",
        "B": r"$2$",
        "C": r"$3$",
        "D": r"$4$",
    }
    assert infer_choice_layout(opts) == "inline_one_line"


def test_infer_long_four_stack() -> None:
    long = r"已知$\cos(\alpha+\beta)=m$，$\tan\alpha\tan\beta=2$，则$\cos(\alpha-\beta)=$" * 2
    opts = {k: long for k in "ABCD"}
    assert infer_choice_layout(opts) == "stack"


def test_infer_medium_four_grid() -> None:
    # 总长超过单行预算，但两两一行仍合适 → 双行两列
    chunk = "x" * 22
    opts = {L: chunk for L in "ABCD"}
    assert infer_choice_layout(opts) == "grid_two_rows"


def test_choice_option_pairs_order() -> None:
    opts = {"D": "d", "A": "a"}
    assert choice_option_pairs(opts) == [("A", "a"), ("D", "d")]


def test_gaokao_style_set_notation_inline() -> None:
    """与 gaokao.tex 集合选项类似：定界符与命令不应把总宽估爆。"""
    opts = {
        "A": r"$\{-1,0\}$",
        "B": r"$\{2,3\}$",
        "C": r"$\{-3,-1,0\}$",
        "D": r"$\{-1,0,2\}$",
    }
    assert infer_choice_layout(opts) == "inline_one_line"


def test_frac_uses_inner_width() -> None:
    w = option_visual_weight(r"$\dfrac{m}{3}$")
    assert w < 10.0
    assert option_visual_weight(r"$\dfrac{m}{3}$") < option_visual_weight(r"$\dfrac{mmmm}{3333}$")


def test_resolve_choice_layout_metadata_forces_stack() -> None:
    short = {"A": "$1$", "B": "$2$", "C": "$3$", "D": "$4$"}
    assert infer_choice_layout(short) == "inline_one_line"
    assert resolve_choice_layout({"choice_layout_mode": "stack"}, short) == "stack"
    assert resolve_choice_layout({"choice_layout_mode": "inline"}, short) == "inline_one_line"
    assert resolve_choice_layout({"choice_layout_mode": "grid"}, short) == "grid_two_rows"
