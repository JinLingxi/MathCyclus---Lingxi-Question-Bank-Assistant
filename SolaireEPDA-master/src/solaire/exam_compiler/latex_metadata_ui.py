"""与 ``*.tex.j2`` 同目录配套的 ``*.metadata_ui.yaml``：声明模板工作台可编辑的 metadata 扩展字段。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from solaire.exam_compiler.latex_jinja_paths import latex_jinja_loader_dirs

logger = logging.getLogger(__name__)


class MetadataUiSelectOption(BaseModel):
    value: str
    label: str


class MetadataUiField(BaseModel):
    """单字段；``kind`` 决定前端控件类型。"""

    key: str
    label: str
    kind: str  # text | textarea | select | number | checkbox
    hint: str | None = None
    placeholder: str | None = None
    rows: int | None = Field(default=None, ge=1, le=40)
    options: list[MetadataUiSelectOption] | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    # 若当前值等于列表中任一项（字符串化后比较），保存 YAML 时省略该键
    omit_values: list[Any] = Field(default_factory=list)


def metadata_ui_companion_filename(latex_base: str) -> str:
    """``exam-zh-base.tex.j2`` → ``exam-zh-base.metadata_ui.yaml``。"""
    if latex_base.endswith(".tex.j2"):
        stem = latex_base[: -len(".tex.j2")]
    else:
        stem = Path(latex_base).stem
    return f"{stem}.metadata_ui.yaml"


def load_latex_metadata_ui_fields(
    template_yaml_dir: Path,
    latex_base: str,
) -> tuple[list[dict[str, Any]], Path | None, list[str]]:
    """
    按 Jinja 搜索顺序（模板目录优先，其次内置目录）查找第一个存在的配套 YAML。

    Returns:
        (fields, source_path_or_none, warnings). Invalid field entries are skipped;
        each skip appends to ``warnings`` and is logged.

    文件格式::

        version: 1
        fields:
          - key: school
            label: 卷首抬头
            kind: textarea
            ...
    """
    dirs = latex_jinja_loader_dirs(template_yaml_dir.resolve(), latex_base)
    name = metadata_ui_companion_filename(latex_base)
    for d in dirs:
        p = (d / name).resolve()
        if p.is_file():
            with p.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            warnings: list[str] = []
            if not isinstance(data, dict):
                msg = f"metadata_ui root must be a mapping in {p}"
                logger.warning(msg)
                return [], p, [msg]
            raw_fields = data.get("fields")
            if raw_fields is None:
                inner = data.get("metadata_ui")
                if isinstance(inner, dict):
                    raw_fields = inner.get("fields")
            if not isinstance(raw_fields, list):
                return [], p, warnings
            out: list[dict[str, Any]] = []
            for item in raw_fields:
                if not isinstance(item, dict):
                    w = f"Skipping non-dict metadata_ui field entry in {p.name}: {item!r}"
                    warnings.append(w)
                    logger.warning(w)
                    continue
                try:
                    field = MetadataUiField.model_validate(item)
                except Exception as e:
                    key = item.get("key", "?")
                    w = f"Invalid metadata_ui field {key!r} in {p.name}: {e}"
                    warnings.append(w)
                    logger.warning(w, exc_info=True)
                    continue
                out.append(field.model_dump(mode="json", exclude_none=True))
            return out, p, warnings
    return [], None, []
