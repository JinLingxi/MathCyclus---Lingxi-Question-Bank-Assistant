"""materialize_metadata_defaults_for_editor and template editor builtins."""

from __future__ import annotations

from pathlib import Path

import yaml

from solaire.exam_compiler.loaders.template_loader import load_template
from solaire.exam_compiler.models.template import MermaidPdfOptions, PrimeBrushPdfOptions
from solaire.exam_compiler.template_editor_builtins import (
    TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS,
    TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS_ORDERED,
)
from solaire.exam_compiler.template_metadata_materialize import materialize_metadata_defaults_for_editor


def test_layout_builtin_keys_cover_expected() -> None:
    assert "mermaid_pdf" in TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS
    assert "margin_cm" in TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS
    assert len(TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS_ORDERED) == len(TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS)


def test_materialize_empty_matches_model_defaults() -> None:
    out = materialize_metadata_defaults_for_editor({})
    assert out["margin_cm"] == 2
    assert out["show_binding_line"] is False
    assert out["show_name_column"] is False
    assert out["mermaid_pdf"] == MermaidPdfOptions().model_dump()
    assert out["primebrush_pdf"] == PrimeBrushPdfOptions().model_dump()
    assert "body_font_size_pt" not in out


def test_materialize_merges_partial_pdf_options() -> None:
    out = materialize_metadata_defaults_for_editor(
        {"mermaid_pdf": {"landscape_width": r"0.5\linewidth"}, "primebrush_pdf": {"latex_width": r"0.8\linewidth"}},
    )
    assert out["mermaid_pdf"]["landscape_width"] == r"0.5\linewidth"
    assert out["mermaid_pdf"]["portrait_width"] == MermaidPdfOptions().portrait_width
    assert out["primebrush_pdf"]["latex_width"] == r"0.8\linewidth"


def test_load_template_layout_options_merged(tmp_path: Path) -> None:
    td = tmp_path / "templates"
    td.mkdir(parents=True)
    p = td / "t.yaml"
    p.write_text(
        yaml.dump(
            {
                "template_id": "t1",
                "layout": "single_column",
                "latex_base": "exam-zh-base.tex.j2",
                "layout_options": {"margin_cm": 2.5},
                "metadata_defaults": {"school": "X"},
                "sections": [
                    {"section_id": "一", "type": "text", "required_count": 0, "score_per_item": 0},
                ],
            },
        ),
        encoding="utf-8",
    )
    t = load_template(p)
    assert t.metadata_defaults.get("margin_cm") == 2.5
    assert t.metadata_defaults.get("school") == "X"


def test_load_template_defaults_yaml_merge(tmp_path: Path) -> None:
    td = tmp_path / "templates"
    td.mkdir(parents=True)
    (td / "defaults.yaml").write_text(
        yaml.dump({"metadata_defaults": {"margin_cm": 1.5, "school": "Base"}}),
        encoding="utf-8",
    )
    p = td / "t2.yaml"
    p.write_text(
        yaml.dump(
            {
                "template_id": "t2",
                "layout": "single_column",
                "latex_base": "exam-zh-base.tex.j2",
                "metadata_defaults": {"margin_cm": 2.8},
                "sections": [
                    {"section_id": "一", "type": "text", "required_count": 0, "score_per_item": 0},
                ],
            },
        ),
        encoding="utf-8",
    )
    t = load_template(p)
    assert t.metadata_defaults.get("margin_cm") == 2.8
    assert t.metadata_defaults.get("school") == "Base"
