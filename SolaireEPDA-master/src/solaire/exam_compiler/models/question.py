"""Pydantic models for per-file question YAML (standalone or type: group)."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self, Union

from pydantic import BaseModel, Field, model_validator

QuestionType = Literal["choice", "fill", "judge", "short_answer", "reasoning", "essay"]

# --- Unified group bodies (no `type` field; implied by parent.unified) ---


class ChoiceBody(BaseModel):
    content: str
    options: dict[str, str]
    answer: str
    analysis: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class FillBody(BaseModel):
    content: str
    answer: str
    analysis: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class JudgeBody(BaseModel):
    content: str
    answer: str
    analysis: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ShortAnswerBody(BaseModel):
    content: str
    answer: str
    analysis: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReasoningBody(BaseModel):
    content: str
    answer: str
    analysis: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class EssayBody(BaseModel):
    content: str
    answer: str
    analysis: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


UnifiedBody = Union[ChoiceBody, FillBody, JudgeBody, ShortAnswerBody, ReasoningBody, EssayBody]

# --- Mixed group items (each row has explicit `type`) ---


class TaggedChoice(BaseModel):
    type: Literal["choice"] = "choice"
    content: str
    options: dict[str, str]
    answer: str
    analysis: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _choice_opts(self) -> Self:
        if not self.options:
            raise ValueError("choice requires non-empty options")
        return self


class TaggedFill(BaseModel):
    type: Literal["fill"] = "fill"
    content: str
    answer: str
    analysis: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaggedJudge(BaseModel):
    type: Literal["judge"] = "judge"
    content: str
    answer: str
    analysis: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _tf(self) -> Self:
        if self.answer not in ("T", "F"):
            raise ValueError("judge answer must be T or F")
        return self


class TaggedShortAnswer(BaseModel):
    type: Literal["short_answer"] = "short_answer"
    content: str
    answer: str
    analysis: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaggedReasoning(BaseModel):
    type: Literal["reasoning"] = "reasoning"
    content: str
    answer: str
    analysis: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaggedEssay(BaseModel):
    type: Literal["essay"] = "essay"
    content: str
    answer: str
    analysis: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


GroupMixedSubItem = Annotated[
    Union[TaggedChoice, TaggedFill, TaggedJudge, TaggedShortAnswer, TaggedReasoning, TaggedEssay],
    Field(discriminator="type"),
]


class QuestionItem(BaseModel):
    """Standalone question (file root) or a synthetic row expanded from a group (hydrate-only extras)."""

    id: str
    type: QuestionType
    content: str
    options: dict[str, str] | None = None
    answer: str
    analysis: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Hydrate / pipeline only — omit from author YAML
    group_material: str | None = None
    unified: bool | str | None = None
    group_root_id: str | None = None
    group_member_index: int | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.type == "choice":
            if not self.options:
                raise ValueError("choice requires non-empty options")
        else:
            if self.options is not None:
                raise ValueError("non-choice must not have options key in bank YAML")
        if self.type == "judge" and self.answer not in ("T", "F"):
            raise ValueError("judge answer must be T or F")
        return self


def _tagged_to_question_item(
    t: GroupMixedSubItem,
    *,
    group_id: str,
    member_index: int,
    material: str,
    unified_false: bool,
) -> QuestionItem:
    base = {
        "id": f"{group_id}__{member_index:02d}",
        "content": t.content,
        "answer": t.answer,
        "analysis": t.analysis or "",
        "metadata": dict(t.metadata) if t.metadata else {},
        "group_material": material,
        "unified": False if unified_false else None,
        "group_root_id": group_id,
        "group_member_index": member_index,
    }
    if isinstance(t, TaggedChoice):
        return QuestionItem(type="choice", options=dict(t.options), **base)
    if isinstance(t, TaggedFill):
        return QuestionItem(type="fill", options=None, **base)
    if isinstance(t, TaggedJudge):
        return QuestionItem(type="judge", options=None, **base)
    if isinstance(t, TaggedShortAnswer):
        return QuestionItem(type="short_answer", options=None, **base)
    if isinstance(t, TaggedReasoning):
        return QuestionItem(type="reasoning", options=None, **base)
    return QuestionItem(type="essay", options=None, **base)


def _unified_body_to_question_item(
    body: UnifiedBody,
    *,
    ut: QuestionType,
    group_id: str,
    member_index: int,
    material: str,
    unified_val: str,
) -> QuestionItem:
    base = {
        "id": f"{group_id}__{member_index:02d}",
        "content": body.content,
        "answer": body.answer,
        "analysis": body.analysis or "",
        "metadata": dict(body.metadata) if body.metadata else {},
        "group_material": material,
        "unified": unified_val,
        "group_root_id": group_id,
        "group_member_index": member_index,
    }
    if ut == "choice":
        assert isinstance(body, ChoiceBody)
        return QuestionItem(type="choice", options=dict(body.options), **base)
    if ut == "fill":
        return QuestionItem(type="fill", options=None, **base)
    if ut == "judge":
        return QuestionItem(type="judge", options=None, **base)
    if ut == "short_answer":
        return QuestionItem(type="short_answer", options=None, **base)
    if ut == "reasoning":
        return QuestionItem(type="reasoning", options=None, **base)
    return QuestionItem(type="essay", options=None, **base)


class QuestionGroupRecord(BaseModel):
    """Root record: one file, one id for the whole passage."""

    id: str
    type: Literal["group"] = "group"
    material: str
    unified: bool | str
    items: list[Any]

    @model_validator(mode="before")
    @classmethod
    def _reject_true_unified(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("unified") is True:
            raise ValueError("unified cannot be true; use false or a question type name")
        return data

    @model_validator(mode="after")
    def _validate_items(self) -> Self:
        if not self.items:
            raise ValueError("group items must be non-empty")
        u = self.unified
        if u is False:
            parsed: list[GroupMixedSubItem] = []
            for it in self.items:
                if isinstance(it, dict) and it.get("type") == "group":
                    raise ValueError("nested group is not allowed")
                row = GroupMixedSubItem.model_validate(it)
                parsed.append(row)
            object.__setattr__(self, "items", parsed)
            return self
        if isinstance(u, str):
            if u == "group":
                raise ValueError("unified cannot be 'group'")
            if u not in (
                "choice",
                "fill",
                "judge",
                "short_answer",
                "reasoning",
                "essay",
            ):
                raise ValueError(f"invalid unified type: {u!r}")
            ut: QuestionType = u  # type: ignore[assignment]
            model = {
                "choice": ChoiceBody,
                "fill": FillBody,
                "judge": JudgeBody,
                "short_answer": ShortAnswerBody,
                "reasoning": ReasoningBody,
                "essay": EssayBody,
            }[ut]
            out: list[UnifiedBody] = []
            for it in self.items:
                if isinstance(it, dict) and it.get("type") is not None:
                    raise ValueError("unified group items must not have a 'type' field")
                body = model.model_validate(it)
                if ut == "judge" and body.answer not in ("T", "F"):
                    raise ValueError("judge answer must be T or F")
                if ut == "choice" and isinstance(body, ChoiceBody) and not body.options:
                    raise ValueError("choice requires non-empty options")
                out.append(body)  # type: ignore[arg-type]
            object.__setattr__(self, "items", out)
            return self
        raise ValueError("unified must be false or a question type name")

    def flatten(self) -> list[QuestionItem]:
        """Expand to per-row QuestionItem with hydrate fields set (for pipeline)."""
        rows: list[QuestionItem] = []
        if self.unified is False:
            for i, row in enumerate(self.items):
                rows.append(
                    _tagged_to_question_item(
                        row,
                        group_id=self.id,
                        member_index=i + 1,
                        material=self.material,
                        unified_false=True,
                    )
                )
            return rows
        ut = self.unified
        assert isinstance(ut, str)
        for i, body in enumerate(self.items):
            assert isinstance(
                body,
                (ChoiceBody, FillBody, JudgeBody, ShortAnswerBody, ReasoningBody, EssayBody),
            )
            rows.append(
                _unified_body_to_question_item(
                    body,
                    ut=ut,  # type: ignore[arg-type]
                    group_id=self.id,
                    member_index=i + 1,
                    material=self.material,
                    unified_val=ut,
                )
            )
        return rows


BankRecord = QuestionItem | QuestionGroupRecord


def parse_bank_root(data: dict[str, Any]) -> BankRecord:
    """Parse a single root object from one YAML file."""
    t = data.get("type")
    if t == "group":
        return QuestionGroupRecord.model_validate(data)
    if t in (
        "choice",
        "fill",
        "judge",
        "short_answer",
        "reasoning",
        "essay",
    ):
        return QuestionItem.model_validate(data)
    raise ValueError(f"unknown or missing type on question root: {t!r}")


def strip_hydrate_fields(item: QuestionItem) -> QuestionItem:
    """Author-roundtrip: drop pipeline-only fields."""
    return item.model_copy(
        update={
            "group_material": None,
            "unified": None,
            "group_root_id": None,
            "group_member_index": None,
        }
    )


def question_item_to_author_dict(item: QuestionItem) -> dict[str, Any]:
    """Serialize standalone question for YAML (no hydrate fields, no options for non-choice)."""
    q = strip_hydrate_fields(item)
    d = q.model_dump(mode="json", exclude_none=True)
    if q.type != "choice" and "options" in d:
        del d["options"]
    return d


def question_group_to_author_dict(g: QuestionGroupRecord) -> dict[str, Any]:
    """Serialize group root for YAML."""
    if g.unified is False:
        items_out: list[dict[str, Any]] = []
        for row in g.items:
            assert not isinstance(row, dict)
            items_out.append(row.model_dump(mode="json", exclude_none=True))
        return {
            "id": g.id,
            "type": "group",
            "material": g.material,
            "unified": False,
            "items": items_out,
        }
    ut = g.unified
    assert isinstance(ut, str)
    items_u: list[dict[str, Any]] = []
    for body in g.items:
        assert not isinstance(body, dict)
        items_u.append(body.model_dump(mode="json", exclude_none=True))
    return {
        "id": g.id,
        "type": "group",
        "material": g.material,
        "unified": ut,
        "items": items_u,
    }
