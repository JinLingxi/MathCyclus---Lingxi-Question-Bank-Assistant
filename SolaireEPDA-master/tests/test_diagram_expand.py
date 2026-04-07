"""Tests for unified primebrush + mermaid fence expansion."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from solaire.exam_compiler.models.template import MermaidPdfOptions, PrimeBrushPdfOptions
from solaire.exam_compiler.pipeline import diagram_expand as diagram_expand_mod
from solaire.exam_compiler.pipeline.diagram_expand import (
    expand_diagram_fences_in_text,
    expand_embed_img_markers_in_text,
    mermaid_pdf_options_from_metadata,
    primebrush_pdf_options_from_metadata,
    strip_diagram_fences_for_preview,
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


def test_interleaved_order_primebrush_then_mermaid(tmp_path: Path) -> None:
    project_root = tmp_path
    (project_root / "resource" / "x" / "y" / "image").mkdir(parents=True)
    image_dir = project_root / "resource" / "x" / "y" / "image"

    def fake_mermaid(body: str, svg_path: Path) -> None:
        svg_path.write_text(f"<svg><!-- {body[:20]} --></svg>", encoding="utf-8")

    text = (
        "序\n```primebrush\n"
        + _MINIMAL_GEO
        + "\n```\n中\n```mermaid\nflowchart TD\n  A-->B\n```\n尾"
    )
    with patch(
        "solaire.exam_compiler.pipeline.diagram_expand.render_mermaid_to_svg_file",
        side_effect=fake_mermaid,
    ):
        out, _, _ = expand_diagram_fences_in_text(
            text,
            image_dir=image_dir,
            mode="web",
            project_root=project_root,
            primebrush_start=0,
            mermaid_start=0,
        )
    assert out.index(":::PRIMEBRUSH_IMG:") < out.index(":::MERMAID_IMG:")
    assert ":::PRIMEBRUSH_IMG:" in out
    assert ":::MERMAID_IMG:" in out
    assert out.endswith("尾")


def test_mermaid_then_primebrush(tmp_path: Path) -> None:
    project_root = tmp_path
    (project_root / "resource" / "x" / "y" / "image").mkdir(parents=True)
    image_dir = project_root / "resource" / "x" / "y" / "image"

    def fake_mermaid(body: str, svg_path: Path) -> None:
        svg_path.write_text("<svg></svg>", encoding="utf-8")

    text = "```mermaid\nflowchart LR\n  X-->Y\n```\n然后\n```primebrush\n" + _MINIMAL_GEO + "\n```"
    with patch(
        "solaire.exam_compiler.pipeline.diagram_expand.render_mermaid_to_svg_file",
        side_effect=fake_mermaid,
    ):
        out, _, _ = expand_diagram_fences_in_text(
            text,
            image_dir=image_dir,
            mode="web",
            project_root=project_root,
        )
    assert out.index(":::MERMAID_IMG:") < out.index(":::PRIMEBRUSH_IMG:")


def test_web_mermaid_fallback_preserves_fence_when_render_fails(tmp_path: Path) -> None:
    """无 mmdr / 渲染失败时 Web 模式不抛错，保留围栏供浏览器渲染。"""
    project_root = tmp_path
    (project_root / "resource" / "a" / "b" / "image").mkdir(parents=True)
    image_dir = project_root / "resource" / "a" / "b" / "image"
    fence = "```mermaid\nflowchart TD\n  A-->B\n```"
    text = f"题面\n{fence}\n结尾"
    with patch(
        "solaire.exam_compiler.pipeline.diagram_expand.render_mermaid_to_svg_file",
        side_effect=RuntimeError("no mmdr"),
    ):
        out, _, _ = expand_diagram_fences_in_text(
            text,
            image_dir=image_dir,
            mode="web",
            project_root=project_root,
        )
    assert fence in out
    assert ":::MERMAID_IMG:" not in out
    assert out.endswith("结尾")


def test_mermaid_pdf_options_from_metadata_defaults() -> None:
    assert mermaid_pdf_options_from_metadata(None).landscape_width == r"0.62\linewidth"
    merged = mermaid_pdf_options_from_metadata({"mermaid_pdf": {"landscape_width": r"0.5\linewidth"}})
    assert merged.landscape_width == r"0.5\linewidth"
    assert r"0.52\linewidth" in merged.portrait_width


def test_primebrush_pdf_options_from_metadata_defaults() -> None:
    assert primebrush_pdf_options_from_metadata(None).latex_width == r"0.9\linewidth"
    o = primebrush_pdf_options_from_metadata({"primebrush_pdf": {"latex_width": r"0.75\linewidth"}})
    assert o.latex_width == r"0.75\linewidth"


def test_latex_includegraphics_mermaid_landscape_vs_portrait() -> None:
    opts = MermaidPdfOptions()
    png = Path("dummy.png")
    with patch.object(diagram_expand_mod, "_png_pixel_size", return_value=(800, 400)):
        s = diagram_expand_mod._latex_includegraphics_mermaid("x.png", png, opts)
    assert r"width=0.62\linewidth" in s
    assert r"0.40\textheight" not in s
    assert "keepaspectratio" in s
    with patch.object(diagram_expand_mod, "_png_pixel_size", return_value=(400, 900)):
        s2 = diagram_expand_mod._latex_includegraphics_mermaid("x.png", png, opts)
    assert r"width=0.52\linewidth" in s2
    assert r"height=0.40\textheight" in s2


def test_embed_img_latex_expand_includegraphics(tmp_path: Path) -> None:
    project_root = tmp_path
    rel = "数学/模拟题/image/abc.png"
    img = project_root / "resource" / rel
    img.parent.mkdir(parents=True)
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    text = f"前 :::EMBED_IMG:{rel}::: 后"
    out = expand_embed_img_markers_in_text(
        text,
        mode="latex",
        project_root=project_root,
        primebrush_pdf=PrimeBrushPdfOptions(latex_width=r"0.88\linewidth"),
    )
    assert "前" in out and "后" in out
    assert r"\includegraphics[width=0.88\linewidth,keepaspectratio]{abc.png}" in out
    assert ":::EMBED_IMG:" not in out


def test_embed_img_path_traversal_unchanged(tmp_path: Path) -> None:
    project_root = tmp_path
    (project_root / "resource" / "safe").mkdir(parents=True)
    marker = ":::EMBED_IMG:../../etc/passwd:::"
    out = expand_embed_img_markers_in_text(marker, mode="latex", project_root=project_root)
    assert out == marker


def test_embed_img_web_mode_unchanged() -> None:
    t = ":::EMBED_IMG:x/y/z.png:::"
    assert expand_embed_img_markers_in_text(t, mode="web", project_root=None) == t


def test_strip_preview_replaces_embed_marker() -> None:
    s = strip_diagram_fences_for_preview("题干 :::EMBED_IMG:a/b.png::: 尾", max_len=500)
    assert "[图片]" in s
    assert "EMBED_IMG" not in s


def test_latex_includegraphics_mermaid_unknown_png_size() -> None:
    opts = MermaidPdfOptions()
    png = Path("dummy.png")
    with patch.object(diagram_expand_mod, "_png_pixel_size", return_value=None):
        s = diagram_expand_mod._latex_includegraphics_mermaid("x.png", png, opts)
    assert "keepaspectratio" in s
    assert r"width=0.62\linewidth" in s
    assert r"height=0.40\textheight" in s
