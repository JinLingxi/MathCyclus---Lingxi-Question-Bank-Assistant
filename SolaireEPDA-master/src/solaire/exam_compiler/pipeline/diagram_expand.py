"""Unified ```primebrush``` and ```mermaid``` fence expansion (source order)."""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Any, Literal

from solaire.exam_compiler.models.template import MermaidPdfOptions, PrimeBrushPdfOptions
from solaire.exam_compiler.pipeline.mermaid_expand import mermaid_stem, render_mermaid_to_svg_file
from solaire.exam_compiler.pipeline.primebrush_expand import (
    _resource_rel_posix,
    _svg_to_png,
    ensure_primebrush_block_files,
)

# ```primebrush``` or ```mermaid``` — body until closing ```
_FENCE = re.compile(r"```(primebrush|mermaid)\s*\n(.*?)```", re.DOTALL)

_EMBED_IMG_RE = re.compile(r":::EMBED_IMG:([^:]+):::")

_PRIMEBRUSH_WEB_PREFIX = ":::PRIMEBRUSH_IMG:"
_MERMAID_WEB_PREFIX = ":::MERMAID_IMG:"
_WEB_SUFFIX = ":::"


def project_root_from_library_root(lib_root: Path) -> Path:
    """Walk up from a question library root until ``resource/``; return its parent (project root)."""
    cur = lib_root.resolve()
    while cur.name != "resource":
        if cur.parent == cur:
            raise ValueError(f"Cannot resolve project root from library path: {lib_root}")
        cur = cur.parent
    return cur.parent


def expand_embed_img_markers_in_text(
    text: str,
    *,
    mode: Literal["latex", "web"],
    project_root: Path | None,
    primebrush_pdf: PrimeBrushPdfOptions | None = None,
) -> str:
    """
    Replace ``:::EMBED_IMG:<resource-relative-path>:::`` with ``\\includegraphics`` in LaTeX mode.

    Web mode leaves markers unchanged for the frontend. Missing or unsafe paths keep the marker.
    """
    if not text or ":::EMBED_IMG:" not in text:
        return text
    if mode == "web":
        return text
    if project_root is None:
        return text
    pp = primebrush_pdf if primebrush_pdf is not None else PrimeBrushPdfOptions()
    res_root = (project_root / "resource").resolve()

    def repl(m: re.Match[str]) -> str:
        rel = m.group(1).strip()
        if not rel or ".." in rel or rel.startswith(("/", "\\")):
            return m.group(0)
        path = (project_root / "resource" / rel).resolve()
        try:
            path.relative_to(res_root)
        except ValueError:
            return m.group(0)
        if not path.is_file():
            return m.group(0)
        basename = path.name
        inc = f"\\includegraphics[width={pp.latex_width},keepaspectratio]{{{basename}}}"
        return f"\n{inc}\n"

    return _EMBED_IMG_RE.sub(repl, text)


def primebrush_pdf_options_from_metadata(metadata: dict[str, Any] | None) -> PrimeBrushPdfOptions:
    """Resolve ``metadata['primebrush_pdf']`` for LaTeX PrimeBrush figures."""
    if not metadata:
        return PrimeBrushPdfOptions()
    raw = metadata.get("primebrush_pdf")
    if raw is None:
        return PrimeBrushPdfOptions()
    if isinstance(raw, dict):
        return PrimeBrushPdfOptions.model_validate(raw)
    return PrimeBrushPdfOptions()


def mermaid_pdf_options_from_metadata(metadata: dict[str, Any] | None) -> MermaidPdfOptions:
    """Resolve ``metadata['mermaid_pdf']`` for LaTeX Mermaid figures."""
    if not metadata:
        return MermaidPdfOptions()
    raw = metadata.get("mermaid_pdf")
    if raw is None:
        return MermaidPdfOptions()
    if isinstance(raw, dict):
        return MermaidPdfOptions.model_validate(raw)
    return MermaidPdfOptions()


def _png_pixel_size(png_path: Path) -> tuple[int, int] | None:
    """Read PNG IHDR width/height; returns None if not a valid PNG."""
    try:
        with png_path.open("rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                return None
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    return None
                length = struct.unpack(">I", hdr[:4])[0]
                ctype = hdr[4:8]
                chunk = f.read(length)
                f.read(4)
                if ctype == b"IHDR":
                    if len(chunk) < 8:
                        return None
                    w, h = struct.unpack(">II", chunk[:8])
                    return (int(w), int(h))
    except OSError:
        return None


def _latex_includegraphics_mermaid(png_name: str, png_path: Path, opts: MermaidPdfOptions) -> str:
    """\\includegraphics for Mermaid PNG: landscape → width only; portrait → width + max height."""
    sz = _png_pixel_size(png_path)
    if sz is None:
        return (
            f"\\includegraphics[width={opts.landscape_width},"
            f"height={opts.portrait_max_height},keepaspectratio]{{{png_name}}}"
        )
    w, h = sz
    if w >= h:
        return f"\\includegraphics[width={opts.landscape_width},keepaspectratio]{{{png_name}}}"
    return (
        f"\\includegraphics[width={opts.portrait_width},height={opts.portrait_max_height},"
        f"keepaspectratio]{{{png_name}}}"
    )


def ensure_mermaid_block_files(
    body: str,
    *,
    image_dir: Path,
    block_index: int,
    write_png: bool,
) -> tuple[str, str]:
    stem = mermaid_stem(body, block_index)
    image_dir.mkdir(parents=True, exist_ok=True)
    svg_path = image_dir / f"{stem}.svg"
    png_path = image_dir / f"{stem}.png"
    render_mermaid_to_svg_file(body, svg_path)
    if write_png:
        svg = svg_path.read_text(encoding="utf-8")
        _svg_to_png(svg, png_path)
    return stem, f"{stem}.png"


def expand_diagram_fences_in_text(
    text: str,
    *,
    image_dir: Path,
    mode: Literal["latex", "web"],
    project_root: Path | None = None,
    primebrush_start: int = 0,
    mermaid_start: int = 0,
    mermaid_pdf: MermaidPdfOptions | None = None,
    primebrush_pdf: PrimeBrushPdfOptions | None = None,
) -> tuple[str, int, int]:
    """
    Replace each ```primebrush``` / ```mermaid``` block in **source order**.

    Returns (new_text, next_primebrush_index, next_mermaid_index).
    """
    if not text or "```" not in text:
        return text, primebrush_start, mermaid_start
    if "```primebrush" not in text and "```mermaid" not in text:
        return text, primebrush_start, mermaid_start

    pi = primebrush_start
    mi = mermaid_start
    pos = 0
    out: list[str] = []

    for m in _FENCE.finditer(text):
        out.append(text[pos : m.start()])
        kind = m.group(1)
        body = m.group(2)
        if kind == "primebrush":
            stem, png_name = ensure_primebrush_block_files(
                body,
                image_dir=image_dir,
                block_index=pi,
                write_png=(mode == "latex"),
            )
            pi += 1
            if mode == "latex":
                pp = primebrush_pdf if primebrush_pdf is not None else PrimeBrushPdfOptions()
                inc = f"\\includegraphics[width={pp.latex_width},keepaspectratio]{{{png_name}}}"
                out.append(f"\n{inc}\n")
            else:
                if project_root is None:
                    raise ValueError("project_root is required for web diagram expansion")
                rel_base = _resource_rel_posix(image_dir, project_root)
                svg_rel = f"{rel_base}/{stem}.svg"
                out.append(f"\n{_PRIMEBRUSH_WEB_PREFIX}{svg_rel}{_WEB_SUFFIX}\n")
        else:
            # LaTeX 仍依赖 mmdr 生成 SVG→PNG；Web 若未装 mmdr 或渲染失败，保留 ```mermaid 围栏供前端用 mermaid.js 渲染，避免 API 500。
            if mode == "web":
                try:
                    stem, png_name = ensure_mermaid_block_files(
                        body,
                        image_dir=image_dir,
                        block_index=mi,
                        write_png=False,
                    )
                except Exception:
                    out.append(m.group(0))
                    mi += 1
                    pos = m.end()
                    continue
            else:
                stem, png_name = ensure_mermaid_block_files(
                    body,
                    image_dir=image_dir,
                    block_index=mi,
                    write_png=True,
                )
            mi += 1
            if mode == "latex":
                mp = mermaid_pdf if mermaid_pdf is not None else MermaidPdfOptions()
                png_path = image_dir / png_name
                inc = _latex_includegraphics_mermaid(png_name, png_path, mp)
                out.append(f"\n{inc}\n")
            else:
                if project_root is None:
                    raise ValueError("project_root is required for web diagram expansion")
                rel_base = _resource_rel_posix(image_dir, project_root)
                svg_rel = f"{rel_base}/{stem}.svg"
                out.append(f"\n{_MERMAID_WEB_PREFIX}{svg_rel}{_WEB_SUFFIX}\n")
        pos = m.end()

    out.append(text[pos:])
    return "".join(out), pi, mi


_EMBED_IMG_STRIP = re.compile(r":::EMBED_IMG:[^:]+:::")


def strip_diagram_fences_for_preview(text: str, max_len: int = 200) -> str:
    """Remove fenced primebrush / mermaid blocks and embed-image markers for one-line style previews."""
    t = _FENCE.sub(
        lambda m: " [插图] " if m.group(1) == "primebrush" else " [流程图] ",
        text,
    )
    t = _EMBED_IMG_STRIP.sub(" [图片] ", t)
    t = " ".join(t.split())
    return t if len(t) <= max_len else t[: max_len - 3] + "..."

