"""Expand ```primebrush fenced blocks: render SVG + PNG under library image/, replace body for LaTeX or Web."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from solaire.primebrush.api import parse_primebrush, render as primebrush_render

if TYPE_CHECKING:
    from solaire.exam_compiler.loaders.questions import LoadedQuestions
    from solaire.exam_compiler.pipeline.hydrate import HydratedExam

_CAIROSVG_HINT = (
    "PrimeBrush 插图需要 SVG 转 PNG（供 LaTeX 使用）。请安装：pip install 'solaire-education[primebrush-pdf]'"
    " 或 pip install cairosvg"
)


def _norm_yaml_for_hash(body: str) -> str:
    return body.strip().replace("\r\n", "\n")


def _block_stem(body: str, block_index: int) -> str:
    h = hashlib.sha256(_norm_yaml_for_hash(body).encode("utf-8")).hexdigest()[:16]
    return f"primebrush_{h}_{block_index}"


def _svg_to_png(svg: str, png_path: Path) -> None:
    try:
        import cairosvg  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError(_CAIROSVG_HINT) from e
    png_path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(png_path))


def _resource_rel_posix(image_dir: Path, project_root: Path) -> str:
    """Path under resource/ for Web URLs, e.g. 数学/模拟题/image/foo.svg"""
    img = image_dir.resolve()
    res = (project_root / "resource").resolve()
    rel = img.relative_to(res)
    return rel.as_posix()


def ensure_primebrush_block_files(
    body: str,
    *,
    image_dir: Path,
    block_index: int,
    write_png: bool,
) -> tuple[str, str]:
    """
    Render one fenced body to SVG (+ optional PNG). Returns (svg_stem, png_filename).
    """
    stem = _block_stem(body, block_index)
    image_dir.mkdir(parents=True, exist_ok=True)
    svg_path = image_dir / f"{stem}.svg"
    png_path = image_dir / f"{stem}.png"

    doc = parse_primebrush(body.strip())
    svg = primebrush_render(doc)
    svg_path.write_text(svg, encoding="utf-8")
    if write_png:
        _svg_to_png(svg, png_path)
    return stem, f"{stem}.png"


def expand_primebrush_in_text(
    text: str,
    *,
    image_dir: Path,
    mode: Literal["latex", "web"],
    project_root: Path | None = None,
    starting_block_index: int = 0,
) -> tuple[str, int]:
    """Replace ```primebrush``` and ```mermaid``` blocks (see diagram_expand)."""
    from solaire.exam_compiler.pipeline.diagram_expand import expand_diagram_fences_in_text

    out, pi, _mi = expand_diagram_fences_in_text(
        text,
        image_dir=image_dir,
        mode=mode,
        project_root=project_root,
        primebrush_start=starting_block_index,
        mermaid_start=0,
        mermaid_pdf=None,
        primebrush_pdf=None,
    )
    return out, pi


def strip_primebrush_fences_for_preview(text: str, max_len: int = 200) -> str:
    """Remove fenced primebrush / mermaid blocks for one-line style previews."""
    from solaire.exam_compiler.pipeline.diagram_expand import strip_diagram_fences_for_preview

    return strip_diagram_fences_for_preview(text, max_len=max_len)


def expand_hydrated_for_latex(hydrated: HydratedExam, loaded: LoadedQuestions) -> None:
    """Mutate question items in place: ```primebrush``` / ```mermaid``` → \\includegraphics; writes under each library's image/."""
    from solaire.exam_compiler.pipeline.diagram_expand import (
        expand_diagram_fences_in_text,
        expand_embed_img_markers_in_text,
        mermaid_pdf_options_from_metadata,
        primebrush_pdf_options_from_metadata,
        project_root_from_library_root,
    )
    from solaire.exam_compiler.qualified_id import namespace_of_qualified

    mermaid_pdf = mermaid_pdf_options_from_metadata(hydrated.metadata)
    primebrush_pdf = primebrush_pdf_options_from_metadata(hydrated.metadata)
    for sec in hydrated.sections:
        for hq in sec.questions:
            ns = namespace_of_qualified(hq.qualified_id)
            root = loaded.library_roots.get(ns)
            if root is None:
                continue
            image_dir = root / "image"
            pr = project_root_from_library_root(root)
            q = hq.item
            pi, mi = 0, 0
            q.content, pi, mi = expand_diagram_fences_in_text(
                q.content,
                image_dir=image_dir,
                mode="latex",
                primebrush_start=pi,
                mermaid_start=mi,
                mermaid_pdf=mermaid_pdf,
                primebrush_pdf=primebrush_pdf,
            )
            q.content = expand_embed_img_markers_in_text(
                q.content, mode="latex", project_root=pr, primebrush_pdf=primebrush_pdf
            )
            q.answer, pi, mi = expand_diagram_fences_in_text(
                q.answer,
                image_dir=image_dir,
                mode="latex",
                primebrush_start=pi,
                mermaid_start=mi,
                mermaid_pdf=mermaid_pdf,
                primebrush_pdf=primebrush_pdf,
            )
            q.answer = expand_embed_img_markers_in_text(
                q.answer, mode="latex", project_root=pr, primebrush_pdf=primebrush_pdf
            )
            q.analysis, pi, mi = expand_diagram_fences_in_text(
                q.analysis or "",
                image_dir=image_dir,
                mode="latex",
                primebrush_start=pi,
                mermaid_start=mi,
                mermaid_pdf=mermaid_pdf,
                primebrush_pdf=primebrush_pdf,
            )
            q.analysis = expand_embed_img_markers_in_text(
                q.analysis, mode="latex", project_root=pr, primebrush_pdf=primebrush_pdf
            )
            if q.group_material:
                q.group_material, _, _ = expand_diagram_fences_in_text(
                    q.group_material,
                    image_dir=image_dir,
                    mode="latex",
                    primebrush_start=pi,
                    mermaid_start=mi,
                    mermaid_pdf=mermaid_pdf,
                    primebrush_pdf=primebrush_pdf,
                )
                q.group_material = expand_embed_img_markers_in_text(
                    q.group_material, mode="latex", project_root=pr, primebrush_pdf=primebrush_pdf
                )
