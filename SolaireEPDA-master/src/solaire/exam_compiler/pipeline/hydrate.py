"""Assemble hydrated exam model for rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from solaire.exam_compiler.loaders.questions import LoadedQuestions
from solaire.exam_compiler.merge_util import deep_merge
from solaire.exam_compiler.models import ExamConfig, ExamTemplate, QuestionGroupRecord, QuestionItem
from solaire.exam_compiler.qualified_id import namespace_of_qualified


@dataclass
class HydratedQuestion:
    qualified_id: str
    item: QuestionItem
    """Same qualified_id for every row expanded from one group file."""
    item_score: float
    """Resolved score for this row (section default or override)."""


@dataclass
class HydratedSection:
    section_id: str
    type: str
    score_per_item: float
    """Section default score (after exam/template merge)."""
    questions: list[HydratedQuestion]
    describe: str | None = None
    score_overrides: dict[str, float] | None = None
    """Original per-id overrides from exam config, if any."""


@dataclass
class HydratedExam:
    """hydrated.metadata = 模板 metadata_defaults 与试卷 metadata 深度合并。"""

    exam_id: str
    metadata: dict[str, Any]
    sections: list[HydratedSection]
    graphicspath_roots: list[Path] = field(default_factory=list)


def hydrate(exam: ExamConfig, template: ExamTemplate, loaded: LoadedQuestions) -> HydratedExam:
    sec_map = {s.section_id: s for s in template.sections}
    sections: list[HydratedSection] = []
    namespaces_used: set[str] = set()

    for sel in exam.selected_items:
        sec_def = sec_map[sel.section_id]
        base_score = sel.score_per_item if sel.score_per_item is not None else sec_def.score_per_item
        overrides = sel.score_overrides or {}

        def resolved_score(qid: str) -> float:
            if qid in overrides:
                return float(overrides[qid])
            return float(base_score)

        hqs: list[HydratedQuestion] = []
        for qid in sel.question_ids:
            entry = loaded.by_qualified[qid]
            sc = resolved_score(qid)
            if isinstance(entry, QuestionItem):
                hqs.append(HydratedQuestion(qualified_id=qid, item=entry, item_score=sc))
                namespaces_used.add(namespace_of_qualified(qid))
            else:
                assert isinstance(entry, QuestionGroupRecord)
                for row in entry.flatten():
                    hqs.append(HydratedQuestion(qualified_id=qid, item=row, item_score=sc))
                    namespaces_used.add(namespace_of_qualified(qid))
        sections.append(
            HydratedSection(
                section_id=sel.section_id,
                type=sec_def.type,
                score_per_item=base_score,
                questions=hqs,
                describe=sec_def.describe,
                score_overrides=sel.score_overrides,
            )
        )

    roots: list[Path] = []
    for ns in sorted(namespaces_used):
        r = loaded.library_roots.get(ns)
        if r is not None and r not in roots:
            roots.append(r)

    merged_meta = deep_merge({}, template.metadata_defaults or {})
    merged_meta = deep_merge(merged_meta, exam.metadata or {})

    return HydratedExam(
        exam_id=exam.exam_id,
        metadata=merged_meta,
        sections=sections,
        graphicspath_roots=roots,
    )
