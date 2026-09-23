"""Centralized editable prompts used by the local AI workflows."""

from __future__ import annotations

import os
from pathlib import Path

from .file_service import atomic_write_text


PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROMPT_FILES = {
    "tags": PROJECT_ROOT / "tags_prompt.txt",
    "solution": PROJECT_ROOT / "solution_prompt.txt",
    "cloze": PROJECT_ROOT / "cloze_prompt.txt",
    "exam_polish": PROJECT_ROOT / "exam_polish_prompt.txt",
}

DEFAULT_PROMPTS = {
    "tags": """你是一名专业的高中数学教研专家。请分析下面 LaTeX 格式的数学题目，并生成难度星级和知识标签。

要求：
1. difficulty 是 0.0 到 6.0 的浮点数，步长为 0.5。
2. tags 提取 2-4 个最核心的中文考点标签，用中文逗号分隔。
3. 严格只输出 JSON，不要输出额外解释。

格式：
{{"difficulty": 3.5, "tags": "标签1，标签2，标签3"}}

题目内容：
{content}""",
    "solution": """请为下面的 LaTeX problem 生成答案与解析。

{mode_instructions}

严格只输出 JSON，且只包含 answer_tex 和 solutions_tex 两个字段。两个字段必须分别是完整的 \\begin{{answer}}...\\end{{answer}} 和 \\begin{{solutions}}...\\end{{solutions}} 环境。禁止输出 Markdown 代码块或额外解释。保持数学内容使用标准 LaTeX，换行使用真实换行。

problem_tex：
{problem_tex}""",
    "cloze": """你是一名高中数学教研专家。请把下面的原题制作成可供学生练习的 LaTeX 挖空题。

挖空类型：{cloze_type}
具体要求：{rule}

严格只输出 JSON，且只包含一个字段 cloze_tex。cloze_tex 必须包含完整的 problem、answer、solutions 环境，保留原题的条件、 小问、TikZ 图和其他必要排版。每个空只能使用 {blank_token}。不得输出 Markdown 或额外解释。原题如下：

{source_tex}""",
    "exam_polish": """你是一名资深的高中数学教研专家。请润色下面的组卷意图，使其更加专业、明确、有条理。

要求：
1. 保持原意不变，但让语言更精准。
2. 直接输出润色后的文本，不要添加评价、引号或解释。

原始组卷意图：
{intent_text}""",
}


def prompt_path(name: str) -> Path:
    if name not in PROMPT_FILES:
        raise KeyError(f"Unknown prompt: {name}")
    return PROMPT_FILES[name]


def load_prompt(name: str) -> str:
    path = prompt_path(name)
    try:
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        value = DEFAULT_PROMPTS[name]
    return value.strip() or DEFAULT_PROMPTS[name]


def save_prompt(name: str, value: str) -> None:
    normalized = (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        normalized = DEFAULT_PROMPTS[name]
    atomic_write_text(prompt_path(name), normalized + "\n", backup=False)


def prompt_values() -> dict[str, str]:
    return {name: load_prompt(name) for name in PROMPT_FILES}

