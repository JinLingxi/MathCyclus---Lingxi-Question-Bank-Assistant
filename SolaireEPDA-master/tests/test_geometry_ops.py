from __future__ import annotations

from pathlib import Path

import pytest

from solaire.primebrush.api import parse_primebrush, render

ROOT = Path(__file__).resolve().parents[1]


def test_advanced_geometry_ops_render() -> None:
    p = ROOT / "examples/primebrush/geometry_2d/advanced_ops.yaml"
    doc = parse_primebrush(p)
    svg = render(doc, seed=42)
    assert "<svg" in svg
    assert "ellipse" in svg
    assert "<circle" in svg


def test_ruler_compass_yaml_renders() -> None:
    p = ROOT / "examples/primebrush/geometry_2d/ruler_compass.yaml"
    doc = parse_primebrush(p)
    svg = render(doc, seed=7)
    assert "<svg" in svg
    assert "<circle" in svg
    assert len(svg) > 500


def test_unknown_op_raises() -> None:
    raw = """
primebrush:
  type: geometry_2d
  seed: 1
  constructions:
    - op: triangle
      nodes: [A, B, C]
      attr: { type: random, min_angle: 30 }
    - op: not_a_real_op
      x: 1
"""
    doc = parse_primebrush(raw)
    with pytest.raises(ValueError, match="unknown construction op"):
        render(doc, seed=1)
