"""Pydantic models for exam.yaml."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class QuestionLibraryRef(BaseModel):
    path: str
    namespace: str


class SelectedSection(BaseModel):
    section_id: str
    question_ids: list[str]
    score_per_item: float | None = None
    """Override template default per-section score when set."""
    score_overrides: dict[str, float] | None = None
    """Per-question scores by qualified_id; keys must be ids from question_ids."""


class ExamConfig(BaseModel):
    exam_id: str
    template_ref: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    question_libraries: list[QuestionLibraryRef] = Field(default_factory=list)
    template_path: str | None = None
    selected_items: list[SelectedSection]

    @model_validator(mode="after")
    def unique_section_ids(self) -> "ExamConfig":
        ids = [s.section_id for s in self.selected_items]
        if len(ids) != len(set(ids)):
            raise ValueError("selected_items contains duplicate section_id values")
        return self
