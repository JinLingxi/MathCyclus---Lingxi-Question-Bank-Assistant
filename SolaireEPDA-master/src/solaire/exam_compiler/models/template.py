"""Pydantic models for template.yaml."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from solaire.exam_compiler.merge_util import deep_merge

Layout = Literal["double_column", "single_column"]

# 模板小节：非考查 text + group（混编题组）+ 各题型
SectionKind = Literal[
    "text",
    "group",
    "choice",
    "fill",
    "judge",
    "short_answer",
    "reasoning",
    "essay",
]


class PrimeBrushPdfOptions(BaseModel):
    """PDF 中 ```primebrush`` 生成插图的 \\includegraphics 宽度（由合并后的 metadata 读取）。"""

    latex_width: str = Field(
        default=r"0.9\linewidth",
        description="PDF 中 PrimeBrush 插图的 width=…",
    )


class MermaidPdfOptions(BaseModel):
    """PDF 中 ```mermaid`` 生成 PNG 的 \\includegraphics 尺寸（由合并后的 metadata 读取）。"""

    landscape_width: str = Field(default=r"0.62\linewidth")
    portrait_width: str = Field(default=r"0.52\linewidth")
    portrait_max_height: str = Field(default=r"0.40\textheight")


class TemplateSection(BaseModel):
    section_id: str
    type: SectionKind
    required_count: int = Field(ge=0)
    score_per_item: float = Field(ge=0)
    describe: str | None = None

    @model_validator(mode="after")
    def text_section_rules(self) -> TemplateSection:
        if self.type == "text":
            if self.required_count != 0:
                raise ValueError("sections with type 'text' must have required_count 0 (no questions in this block)")
        return self


class ExamTemplate(BaseModel):
    """模板结构节 + 默认 metadata（版式、插图尺寸等均由 LaTeX 基架按 key 解释，核心不写死键名）。"""

    template_id: str
    layout: Layout = "single_column"
    latex_base: str = "exam-zh-base.tex.j2"
    sections: list[TemplateSection]
    metadata_defaults: dict[str, Any] = Field(
        default_factory=dict,
        description="与 exam.yaml metadata 同形；组卷时与试卷 metadata 深度合并，后者覆盖前者",
    )

    @model_validator(mode="before")
    @classmethod
    def absorb_legacy_layout_options(cls, data: Any) -> Any:
        """兼容旧版 template.yaml 顶层的 layout_options：并入 metadata_defaults 后丢弃。"""
        if not isinstance(data, dict):
            return data
        lo = data.get("layout_options")
        if isinstance(lo, dict) and lo:
            md = dict(data.get("metadata_defaults") or {})
            data["metadata_defaults"] = deep_merge(md, lo)
            del data["layout_options"]
        return data
