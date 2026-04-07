"""Tests for exam_compiler PrimeBrush fence expansion."""

from __future__ import annotations

from pathlib import Path

import pytest

from solaire.exam_compiler.pipeline.primebrush_expand import (
    expand_primebrush_in_text,
    strip_primebrush_fences_for_preview,
)

_MINIMAL_GEO = """
primebrush:
  type: geometry_2d
  seed: 42
  canvas: { width: 200, height: 160, unit: px }
  constructions:
    - op: triangle
      id: T1
      nodes: [A, B, C]
      attr: { type: random, min_angle: 30 }
"""


def test_strip_primebrush_fences_for_preview() -> None:
    raw = "题干\n```primebrush\n" + _MINIMAL_GEO + "\n```\n尾部"
    s = strip_primebrush_fences_for_preview(raw, max_len=500)
    assert "[插图]" in s
    assert "constructions" not in s
    assert "尾部" in s


def test_expand_web_writes_svg_and_marker(tmp_path: Path) -> None:
    project_root = tmp_path
    (project_root / "resource" / "数学" / "模拟题" / "image").mkdir(parents=True)
    image_dir = project_root / "resource" / "数学" / "模拟题" / "image"
    text = "如图\n```primebrush\n" + _MINIMAL_GEO + "\n```\n完"
    out, _ = expand_primebrush_in_text(
        text,
        image_dir=image_dir,
        mode="web",
        project_root=project_root,
        starting_block_index=0,
    )
    assert ":::PRIMEBRUSH_IMG:" in out
    assert out.endswith("完")
    svgs = list(image_dir.glob("primebrush_*.svg"))
    assert len(svgs) == 1
    assert svgs[0].read_text(encoding="utf-8").lstrip().startswith("<svg")


def test_expand_latex_writes_png_when_cairosvg(tmp_path: Path) -> None:
    pytest.importorskip("cairosvg")
    image_dir = tmp_path / "image"
    text = "```primebrush\n" + _MINIMAL_GEO + "\n```"
    out, _ = expand_primebrush_in_text(text, image_dir=image_dir, mode="latex", starting_block_index=0)
    assert "\\includegraphics" in out
    assert ".png}" in out
    assert any(image_dir.glob("primebrush_*.png"))
