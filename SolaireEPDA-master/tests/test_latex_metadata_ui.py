"""latex_base 配套 metadata_ui YAML 加载。"""

from pathlib import Path

from solaire.exam_compiler.latex_jinja_paths import bundled_latex_dir
from solaire.exam_compiler.latex_metadata_ui import (
    load_latex_metadata_ui_fields,
    metadata_ui_companion_filename,
)


def test_companion_filename() -> None:
    assert metadata_ui_companion_filename("exam-zh-base.tex.j2") == "exam-zh-base.metadata_ui.yaml"


def test_load_shipped_exam_zh_base() -> None:
    bundled = bundled_latex_dir()
    fields, src, warnings = load_latex_metadata_ui_fields(bundled, "exam-zh-base.tex.j2")
    assert not warnings
    assert src is not None
    assert src.name == "exam-zh-base.metadata_ui.yaml"
    keys = [f["key"] for f in fields]
    assert "school" in keys
    assert "title_block_style" in keys
    school = next(f for f in fields if f["key"] == "school")
    assert school["kind"] == "textarea"
