"""Canonical question/section `type` strings（仅接受下列枚举，不做旧名映射）。

**题目类型（题库 `QuestionItem.type` / 模板小题节 `TemplateSection.type`）：**
- ``choice`` — 选择
- ``fill`` — 填空
- ``judge`` — 判断（单独类型；版式可与选择题类似）
- ``short_answer`` — 简答，按得分要点给分
- ``reasoning`` — 推理（含计算、证明等）
- ``essay`` — 论述题

**题组（题库 ``type: group``）**：见 ``docs/reference/question-yaml-by-type.md``；``unified: false`` 为混编，否则为同型小题。

**模板小节 ``type: group``**：该节每条 ``question_ids`` 对应一道完整题组（混编）；不要求小题与节类型一致。

**仅模板结构节（不出题）：**
- ``text`` — 说明性文本，非考查内容；须 ``required_count: 0``

高考范围内：听力等选择题结构仍用 ``choice``；与阅读的差异在阅卷与 ``metadata``。
"""

from __future__ import annotations

# 题库与模板「小题」共用（题组内仅允许其中可组卷的子集）
QUESTION_TYPES: tuple[str, ...] = (
    "choice",
    "fill",
    "judge",
    "short_answer",
    "reasoning",
    "essay",
)

GROUP_MEMBER_TYPES: tuple[str, ...] = tuple(QUESTION_TYPES)

# 模板 sections：含非考查的 text 块 + 混编题组节
SECTION_TYPES: tuple[str, ...] = ("text", "group", *QUESTION_TYPES)
