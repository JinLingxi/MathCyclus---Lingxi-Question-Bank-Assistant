"""Prompt as Protocol: layered system prompt assembly (M3 Harness)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _layer_role() -> str:
    return (
        "## 角色\n"
        "你是 SolEdu 智能教学助手，协助教师完成题库维护、知识图谱、组卷与导出、"
        "考试结果分析与脚本诊断等全流程工作。"
        "回答使用简体中文，面向教师业务场景，避免暴露底层实现细节。"
    )


def _layer_goal() -> str:
    return (
        "## 任务范围\n"
        "在授权范围内：列举考试数据、运行内置分析、保存与运行分析脚本、查询作业结果、"
        "检索与维护题库中的独立题目、读取与维护知识图谱、将题目挂接到知识点、"
        "批量维护要点与挂接、读取项目内文件（写入能力视当前聚焦域而定）、文档格式转换（Word/PDF/OCR）、"
        "联网检索公开资料（可选配置）、"
        "以及组卷相关能力（校验与导出需确认）。"
        "超出工具能力时请明确说明，并建议教师手动操作路径。"
    )


def _ui_module_label(code: str) -> str:
    return {
        "compose": "组卷",
        "bank": "题库",
        "template": "试卷模板",
        "graph": "知识图谱",
        "analysis": "成绩分析",
        "help": "使用手册",
        "log": "运行日志",
        "settings": "设置",
    }.get(code, code)


_FOCUS_LABEL: dict[str, str] = {
    "general": "通用",
    "bank": "题库管理",
    "graph": "知识图谱",
    "analysis": "成绩分析",
    "compose": "组卷与导出",
    "doc_process": "文档处理",
}


def _layer_context(project_ctx: dict[str, Any]) -> str:
    lines = ["## 项目状态"]
    lines.append(f"- 项目路径：{project_ctx.get('project_label', '当前项目')}")
    if exams := project_ctx.get("exam_summary"):
        lines.append(f"- 考试数据概览：{exams}")
    if "template_count" in project_ctx:
        lines.append(f"- 可用试卷模板数量：{project_ctx.get('template_count')}")
    if "graph_node_count" in project_ctx:
        lines.append(f"- 知识图谱节点数量：{project_ctx.get('graph_node_count')}")
    pc = project_ctx.get("page_context")
    if isinstance(pc, dict) and pc:
        lines.append("## 教师当前界面")
        cp = pc.get("current_page")
        if cp:
            lines.append(f"- 所在模块：{_ui_module_label(str(cp))}")
        sm = pc.get("summary")
        if sm:
            lines.append(f"- 场景说明：{sm}")
        rt = pc.get("selected_resource_type")
        ri = pc.get("selected_resource_id")
        if rt or ri:
            lines.append(f"- 当前对象：{rt or '—'} / {ri or '—'}")
        lines.append("- 宜结合上述场景作答；跨领域能力可通过 `agent.switch_focus` 切换聚焦域获取。")
    return "\n".join(lines)


def _layer_focus(current_focus: str | None) -> str:
    focus = current_focus or "general"
    label = _FOCUS_LABEL.get(focus, focus)
    lines = [
        "## 聚焦态",
        f"- 当前聚焦域：**{label}**（`{focus}`）",
        "- 可用工具集已根据聚焦域自动筛选。",
        "- 若需的能力不在当前工具集中，请用 `agent.switch_focus` 切换域，或用 `agent.activate_skill` 激活技能——"
        "**勿将「工具未列出」描述为「平台无此能力」或「无权限」。**",
        f"  可选域：{', '.join(_FOCUS_LABEL.keys())}",
    ]
    return "\n".join(lines)


def _layer_tools(tool_descriptions: str) -> str:
    return (
        f"## 可用能力（通过工具调用）\n{tool_descriptions.strip()}\n"
        "- 仅能调用上表所列能力。若需的能力不在当前工具集中，请先用 `agent.switch_focus` 切换到合适的聚焦域。"
    )


def _layer_constraints() -> str:
    return (
        "## 行为约束（必须遵守）\n"
        "- 严禁编造不存在的考试数据或分析结果。\n"
        "- 严禁在未获教师确认的情况下执行删除、覆盖或导出试卷等高风险操作。\n"
        "- 严禁猜测资源标识；应先通过列举类工具确认。\n"
        "- 引用记忆中的历史结论前，须先使用记忆读取工具核对原文。\n"
        "- 工具失败须如实说明原因与建议下一步。\n"
    )


def _layer_risk_policy() -> str:
    return (
        "## 风险与确认\n"
        "- 只读类操作可直接执行。\n"
        "- 写入类操作可能需要教师确认；同一会话内教师已批准的同类操作可自动放行。\n"
        "- 破坏性操作一律需要教师确认。\n"
        "- 勿将「需确认」描述为「无权限」或「禁止操作」。\n"
    )


def _layer_output_format() -> str:
    return (
        "## 输出规范\n"
        "- 分析结论须注明数据来源（考试标识、批次、样本量等）。\n"
        "- 建议分为「可立即执行」与「需进一步确认」两类。\n"
        "- 生成的分析脚本须符合平台沙箱限制（允许的模块列表见工具说明）。\n"
    )


def _layer_decision_rules() -> str:
    return (
        "## 决策规则\n"
        "- 复杂、多轮试错或大体量数据综合任务，优先使用子任务深度分析工具，避免主对话上下文膨胀。\n"
        "- 若单次工具输出过长，应依赖系统已做的摘要；需要明细时再调用相应只读工具。\n"
        "- 对于复杂的多步任务，可调用 `agent.enter_plan_mode` 先制定计划再执行。\n"
    )


def _layer_compose_hints() -> str:
    return (
        "## 组卷与导出\n"
        "- 若版式编译未通过或导出失败，请根据工具返回的报错与题干内容调整题目或模板，"
        "避免在相同条件下反复调用校验而不改内容。\n"
        "- 需要确认版式能否生成时，在校验工具中开启版式编译试跑；结构通过仅代表选题与模板匹配，"
        "不等于版式已试跑通过。\n"
    )


def _layer_plan_mode() -> str:
    return (
        "## 计划模式（当前激活）\n"
        "你正处于计划模式（对齐 Cursor 等 harness：先只读探索，再落盘结构化计划文件）。\n"
        "流程：\n"
        "1. 仅允许调用只读工具了解当前状况。\n"
        "2. 禁止执行写入或破坏性操作；**唯一例外**是使用 `file.write` 将计划写入 `.solaire/agent/plans/` 下，"
        "或使用 `file.edit` 修正该目录下已有计划文件。\n"
        "3. 计划文件须为 `.md`，且以 **YAML 围栏** 开头：首行 `---`，随后 YAML（须含 `name`、`overview`、`todos`），"
        "再以独占一行的 `---` 结束围栏；围栏后为正文（任务分解、风险、验收等）。\n"
        "`todos` 为列表，建议每项含 `id`、`content`、`status`（如 pending）。\n"
        "4. 落盘后调用 `agent.exit_plan_mode`，参数 `plan_file_path` 为本次写入的**项目内相对路径**（如 `.solaire/agent/plans/xxx.md`）。\n"
        "\n"
        "结构示例（占位须替换为真实内容）：\n"
        "```\n"
        "---\n"
        "name: 计划标题\n"
        "overview: 一句话概述\n"
        "todos:\n"
        "  - id: step-1\n"
        "    content: 第一步要做什么\n"
        "    status: pending\n"
        "---\n"
        "\n"
        "## 正文\n"
        "…\n"
        "```\n"
    )


def _layer_plan_execution(execution_plan_path: str) -> str:
    path = execution_plan_path.strip()
    return (
        "## 计划执行（当前生效）\n"
        f"- 已批准按计划文件执行：项目内路径 `{path}`。\n"
        "- 请严格按下方「当前任务步骤」逐项推进；每完成一步请调用 `agent.update_task_step` 更新序号与状态。\n"
        "- 全部步骤完成后再作总结答复。\n"
    )


def _layer_memory(memory_index_excerpt: str) -> str:
    body = memory_index_excerpt.strip() or "（暂无记忆索引）"
    return f"## 记忆索引（提示性质，引用前须用工具核对）\n{body}"


def _layer_skill_catalog(skill_catalog: str | None) -> str:
    if not skill_catalog or not skill_catalog.strip():
        return ""
    return (
        "## 可用技能目录\n"
        "以下技能提供特定任务的专业指引。当任务匹配某个技能的描述时，"
        "调用 `agent.activate_skill` 加载完整指令。\n\n"
        + skill_catalog.strip()
    )


def _load_prompt_overrides(project_root: Path | None) -> str:
    """Phase 5: Load project-level prompt overrides from .solaire/agent/system_prompt_overrides.md"""
    if project_root is None:
        return ""
    p = project_root / ".solaire" / "agent" / "system_prompt_overrides.md"
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _apply_overrides(base_prompt: str, overrides: str) -> str:
    """Replace or append sections based on ## headings in the override file."""
    if not overrides:
        return base_prompt
    import re

    override_sections: dict[str, str] = {}
    current_heading = None
    current_lines: list[str] = []

    for line in overrides.split("\n"):
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            if current_heading:
                override_sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = m.group(1).strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_heading:
        override_sections[current_heading] = "\n".join(current_lines).strip()

    result = base_prompt
    for heading, content in override_sections.items():
        pattern = re.compile(
            rf"(## {re.escape(heading)}\n).*?(?=\n## |\Z)",
            re.DOTALL,
        )
        if pattern.search(result):
            result = pattern.sub(content, result, count=1)
        else:
            result = result.rstrip() + "\n\n" + content

    return result


def build_system_prompt(
    *,
    tool_descriptions: str,
    memory_index_excerpt: str,
    project_ctx: dict[str, Any],
    skill_guidance: str | None = None,
    current_focus: str | None = None,
    plan_mode_active: bool = False,
    execution_plan_path: str | None = None,
    skill_catalog: str | None = None,
    project_root: Path | None = None,
) -> str:
    """Assemble full system prompt (protocol stack)."""
    parts = [
        _layer_role(),
        _layer_goal(),
        _layer_context(project_ctx),
        _layer_focus(current_focus),
        _layer_tools(tool_descriptions),
        _layer_constraints(),
        _layer_risk_policy(),
        _layer_output_format(),
        _layer_decision_rules(),
        _layer_memory(memory_index_excerpt),
    ]
    if skill_guidance and skill_guidance.strip():
        parts.insert(4, "## 当前协助重点\n" + skill_guidance.strip())
    if (current_focus or "").strip() == "compose":
        parts.insert(4, _layer_compose_hints())
    if plan_mode_active:
        parts.insert(4, _layer_plan_mode())
    if execution_plan_path and execution_plan_path.strip():
        parts.insert(4, _layer_plan_execution(execution_plan_path))
    catalog_section = _layer_skill_catalog(skill_catalog)
    if catalog_section:
        parts.append(catalog_section)

    base = "\n\n".join(parts)

    overrides = _load_prompt_overrides(project_root)
    if overrides:
        base = _apply_overrides(base, overrides)

    return base
