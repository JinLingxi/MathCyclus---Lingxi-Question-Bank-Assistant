from __future__ import annotations

from pathlib import Path

import pytest

from solaire.primebrush.api import parse_primebrush, render

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "rel_yaml,rel_expected",
    [
        ("examples/primebrush/geometry_2d/median_line.yaml", "examples/primebrush/geometry_2d/median_line.expected.svg"),
        ("examples/primebrush/plot_2d/sin_and_point.yaml", "examples/primebrush/plot_2d/sin_and_point.expected.svg"),
        ("examples/primebrush/chart/bar_scores.yaml", "examples/primebrush/chart/bar_scores.expected.svg"),
    ],
)
def test_golden_svg_matches(rel_yaml: str, rel_expected: str) -> None:
    ypath = ROOT / rel_yaml
    epath = ROOT / rel_expected
    doc = parse_primebrush(ypath)
    svg = render(doc, seed=42)
    expected = epath.read_text(encoding="utf-8")
    assert svg == expected


def test_parse_plot_2d_alias() -> None:
    raw = "primebrush:\n  type: plot_2d\n  axes: {x: {range: [0,1]}, y: {range: [0,1]}}\n  elements: []\n"
    doc = parse_primebrush(raw)
    assert doc.type == "plot_2D"


def test_chemistry_molecule_placeholder_svg() -> None:
    raw = (
        "primebrush:\n  type: chemistry_molecule\n  notation: SMILES\n  value: 'CCO'\n"
    )
    doc = parse_primebrush(raw)
    svg = render(doc, seed=42)
    assert "<svg" in svg.lower() or svg.strip().startswith("<?xml")


def test_expr_sin() -> None:
    import numpy as np
    from solaire.primebrush.plots.expr import eval_expr

    x = np.linspace(0, 1, 5)
    y = eval_expr("sin(x)", x)
    assert y.shape == x.shape


def test_cli_build(tmp_path: Path) -> None:
    from solaire.primebrush.cli import main

    src = ROOT / "examples/primebrush/chart/bar_scores.yaml"
    out = tmp_path / "out.svg"
    code = main(["build", str(src), "-o", str(out), "--seed", "42"])
    assert code == 0
    assert out.is_file()
    assert "<svg" in out.read_text(encoding="utf-8")
