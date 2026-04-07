"""Validate exam selection against template constraints."""

from __future__ import annotations

from solaire.exam_compiler.models import ExamConfig, ExamTemplate, QuestionGroupRecord, QuestionItem, TemplateSection
from solaire.exam_compiler.loaders.questions import LoadedQuestions


def _section_by_id(template: ExamTemplate, section_id: str) -> TemplateSection:
    for s in template.sections:
        if s.section_id == section_id:
            return s
    raise ValueError(
        f"当前模板中不存在小节「{section_id}」（模板：{template.template_id}）。"
    )


def validate_exam(exam: ExamConfig, template: ExamTemplate, loaded: LoadedQuestions) -> None:
    if template.template_id != exam.template_ref:
        raise ValueError(
            "试卷绑定的版式与当前打开的模板不一致，请重新选择模板后再试。"
        )

    selected_ids = {s.section_id for s in exam.selected_items}
    template_ids = {s.section_id for s in template.sections}
    if selected_ids != template_ids:
        missing = template_ids - selected_ids
        extra = selected_ids - template_ids
        parts: list[str] = []
        if missing:
            parts.append("缺少小节：" + "、".join(sorted(missing)))
        if extra:
            parts.append("存在模板外的小节：" + "、".join(sorted(extra)))
        raise ValueError("选题结构与模板要求不一致（" + "；".join(parts) + "）。")

    for sel in exam.selected_items:
        sec = _section_by_id(template, sel.section_id)
        if sec.type == "text":
            if len(sel.question_ids) != 0:
                raise ValueError(
                    f"小节「{sel.section_id}」为卷面说明，不需要挂载题目，请移除本题小节下的选题。"
                )
            continue
        if len(sel.question_ids) != sec.required_count:
            raise ValueError(
                f"小节「{sel.section_id}」需要 {sec.required_count} 道题，当前已选 {len(sel.question_ids)} 道。"
            )
        for qid in sel.question_ids:
            entry = loaded.by_qualified.get(qid)
            if entry is None:
                raise ValueError(f"题库中未找到题目「{qid}」，请检查是否已加载或题目是否已被删除。")
            if sec.type == "group":
                if not isinstance(entry, QuestionGroupRecord):
                    raise ValueError(
                        f"小节「{sel.section_id}」须使用题组；「{qid}」不是题组条目。"
                    )
                if entry.unified is not False:
                    raise ValueError(
                        f"小节「{sec.section_id}」须选用混合题组；「{qid}」不符合该要求。"
                    )
                continue
            if isinstance(entry, QuestionGroupRecord):
                if entry.unified is False:
                    raise ValueError(
                        f"混合题组「{qid}」只能放在模板中题型为「题组」的小节里。"
                    )
                if entry.unified != sec.type:
                    raise ValueError(
                        f"题组「{qid}」的题型为「{entry.unified}」，与小节「{sel.section_id}」要求的「{sec.type}」不一致。"
                    )
            elif isinstance(entry, QuestionItem):
                if entry.type != sec.type:
                    raise ValueError(
                        f"题目「{qid}」的题型为「{entry.type}」，与小节「{sel.section_id}」要求的「{sec.type}」不一致。"
                    )
            else:
                raise ValueError(f"题目「{qid}」数据异常，无法参与组卷。")
