"""Pydantic models for GET /api/templates/parsed and related editor APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from solaire.exam_compiler.models.template import ExamTemplate, Layout, SectionKind


class TemplateSectionPayload(BaseModel):
    section_id: str
    type: SectionKind
    required_count: int = Field(ge=0)
    score_per_item: float = Field(ge=0)
    describe: str | None = None


class TemplateParsedResponse(BaseModel):
    """Normalized template for the visual editor (metadata_defaults is materialized)."""

    template_id: str
    layout: Layout
    latex_base: str
    sections: list[TemplateSectionPayload]
    metadata_defaults: dict[str, Any]
    layout_builtin_keys: list[str] = Field(
        ...,
        description="Keys managed by the built-in layout form; others are extension fields.",
    )

    @classmethod
    def from_exam_template(
        cls,
        t: ExamTemplate,
        *,
        layout_builtin_keys: list[str],
        materialized_metadata: dict[str, Any],
    ) -> TemplateParsedResponse:
        return cls(
            template_id=t.template_id,
            layout=t.layout,
            latex_base=t.latex_base,
            sections=[TemplateSectionPayload.model_validate(s.model_dump()) for s in t.sections],
            metadata_defaults=materialized_metadata,
            layout_builtin_keys=list(layout_builtin_keys),
        )


class EditorMetadataDefaultsBody(BaseModel):
    """Response for GET /api/templates/editor-metadata-defaults."""

    metadata_defaults: dict[str, Any]
