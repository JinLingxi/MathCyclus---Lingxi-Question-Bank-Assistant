"""Fill template metadata_defaults for the web editor (complete nested PDF options, Jinja-aligned defaults)."""

from __future__ import annotations

from typing import Any

from solaire.exam_compiler.merge_util import deep_merge
from solaire.exam_compiler.models.template import MermaidPdfOptions, PrimeBrushPdfOptions

# Matches exam-zh-base.tex.j2: metadata.get('margin_cm', 2)
_DEFAULT_MARGIN_CM = 2


def materialize_metadata_defaults_for_editor(md: dict[str, Any] | None) -> dict[str, Any]:
    """
    Return a copy of metadata_defaults suitable for binding to the template workspace form.

    - Merges sparse ``mermaid_pdf`` / ``primebrush_pdf`` with Pydantic model defaults (same as compile path).
    - Sets ``margin_cm`` when missing or null (Jinja default 2 cm).
    - Sets ``show_binding_line`` / ``show_name_column`` to bool when missing (explicit false).
    - Does not inject ``body_font_size_pt`` when absent (LaTeX only applies font size when the key exists).
    """
    out: dict[str, Any] = dict(md or {})

    raw_m = out.get("mermaid_pdf")
    if isinstance(raw_m, dict):
        out["mermaid_pdf"] = deep_merge(MermaidPdfOptions().model_dump(), dict(raw_m))
    else:
        out["mermaid_pdf"] = MermaidPdfOptions().model_dump()

    raw_p = out.get("primebrush_pdf")
    if isinstance(raw_p, dict):
        out["primebrush_pdf"] = deep_merge(PrimeBrushPdfOptions().model_dump(), dict(raw_p))
    else:
        out["primebrush_pdf"] = PrimeBrushPdfOptions().model_dump()

    if out.get("margin_cm") is None:
        out["margin_cm"] = _DEFAULT_MARGIN_CM

    if "show_binding_line" not in out or out["show_binding_line"] is None:
        out["show_binding_line"] = False
    else:
        out["show_binding_line"] = bool(out["show_binding_line"])

    if "show_name_column" not in out or out["show_name_column"] is None:
        out["show_name_column"] = False
    else:
        out["show_name_column"] = bool(out["show_name_column"])

    return out
