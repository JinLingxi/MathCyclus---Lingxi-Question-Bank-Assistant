"""HTTP integration tests for template editor APIs."""

from __future__ import annotations

from pathlib import Path

import yaml

from solaire.exam_compiler.models.template import MermaidPdfOptions, PrimeBrushPdfOptions
from solaire.exam_compiler.template_editor_builtins import TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS_ORDERED
from solaire.exam_compiler.template_metadata_materialize import materialize_metadata_defaults_for_editor


def test_editor_metadata_defaults_endpoint(web_client) -> None:
    r = web_client.get("/api/templates/editor-metadata-defaults")
    assert r.status_code == 200
    data = r.json()
    assert "metadata_defaults" in data
    md = data["metadata_defaults"]
    assert md["mermaid_pdf"] == MermaidPdfOptions().model_dump()
    assert md["primebrush_pdf"] == PrimeBrushPdfOptions().model_dump()
    assert md["margin_cm"] == 2


def test_templates_parsed_materializes(web_client, tmp_path: Path) -> None:
    td = tmp_path / "templates"
    td.mkdir(parents=True, exist_ok=True)
    p = td / "demo.yaml"
    p.write_text(
        yaml.dump(
            {
                "template_id": "demo",
                "layout": "single_column",
                "latex_base": "exam-zh-base.tex.j2",
                "metadata_defaults": {"school": "测试中学"},
                "sections": [
                    {"section_id": "一、说明", "type": "text", "required_count": 0, "score_per_item": 0},
                ],
            },
        ),
        encoding="utf-8",
    )
    r = web_client.get("/api/templates/parsed", params={"path": "templates/demo.yaml"})
    assert r.status_code == 200
    body = r.json()
    assert body["template_id"] == "demo"
    assert body["layout_builtin_keys"] == list(TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS_ORDERED)
    md = body["metadata_defaults"]
    assert md["school"] == "测试中学"
    assert md["mermaid_pdf"] == MermaidPdfOptions().model_dump()
    assert md["margin_cm"] == 2


def test_templates_raw_and_list_no_layout_options(web_client, tmp_path: Path) -> None:
    td = tmp_path / "templates"
    td.mkdir(parents=True, exist_ok=True)
    p = td / "x.yaml"
    p.write_text(
        yaml.dump(
            {
                "template_id": "x",
                "layout": "single_column",
                "latex_base": "exam-zh-base.tex.j2",
                "sections": [
                    {"section_id": "一", "type": "text", "required_count": 0, "score_per_item": 0},
                ],
            },
        ),
        encoding="utf-8",
    )
    lst = web_client.get("/api/templates")
    assert lst.status_code == 200
    rows = lst.json()["templates"]
    row = next(x for x in rows if x["id"] == "x")
    assert "layout_options" not in row

    raw = web_client.get("/api/templates/raw", params={"path": "templates/x.yaml"})
    assert raw.status_code == 200
    assert "template_id: x" in raw.json()["yaml"]


def test_latex_metadata_ui_returns_warnings(web_client, tmp_path: Path) -> None:
    td = tmp_path / "templates"
    td.mkdir(parents=True, exist_ok=True)
    bad_ui = td / "exam-zh-base.metadata_ui.yaml"
    bad_ui.write_text(
        yaml.dump(
            {
                "version": 1,
                "fields": [
                    {"key": "ok", "label": "OK", "kind": "text"},
                    {"key": "bad", "label": "Bad", "kind": "text", "rows": -1},
                ],
            },
        ),
        encoding="utf-8",
    )
    tpl = td / "with_ui.yaml"
    tpl.write_text(
        yaml.dump(
            {
                "template_id": "with_ui",
                "layout": "single_column",
                "latex_base": "exam-zh-base.tex.j2",
                "sections": [
                    {"section_id": "一", "type": "text", "required_count": 0, "score_per_item": 0},
                ],
            },
        ),
        encoding="utf-8",
    )
    r = web_client.get(
        "/api/templates/latex-metadata-ui",
        params={"template_path": "templates/with_ui.yaml", "latex_base": "exam-zh-base.tex.j2"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "warnings" in data
    assert any("bad" in w for w in data["warnings"])
    keys = [f["key"] for f in data["fields"]]
    assert "ok" in keys
    assert "bad" not in keys


def test_materialize_matches_compile_path_options() -> None:
    """Merged metadata used by editor should match diagram_expand option resolution for nested dicts."""
    from solaire.exam_compiler.pipeline.diagram_expand import (
        mermaid_pdf_options_from_metadata,
        primebrush_pdf_options_from_metadata,
    )

    md = materialize_metadata_defaults_for_editor({"mermaid_pdf": {"landscape_width": r"0.5\linewidth"}})
    mm = mermaid_pdf_options_from_metadata(md)
    assert mm.landscape_width == r"0.5\linewidth"
    assert mm.portrait_width == MermaidPdfOptions().portrait_width

    pp = primebrush_pdf_options_from_metadata(md)
    assert pp.latex_width == PrimeBrushPdfOptions().latex_width
