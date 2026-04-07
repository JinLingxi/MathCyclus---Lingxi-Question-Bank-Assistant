"""Session-scoped agent tools: task plan, focus switching, plan mode, skill activation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from solaire.agent_layer.models import InvocationContext, ToolResult
from solaire.agent_layer.task_tracker import set_plan, update_step


def tool_set_task_plan(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    if ctx.session is None:
        return ToolResult(status="failed", error_message="无会话状态")
    raw = args.get("steps")
    if not isinstance(raw, list):
        return ToolResult(status="failed", error_message="steps 须为步骤列表")
    set_plan(ctx.session, raw)
    return ToolResult(data={"ok": True, "steps": ctx.session.task_plan})


def tool_update_task_step(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    if ctx.session is None:
        return ToolResult(status="failed", error_message="无会话状态")
    try:
        index = int(args.get("index", -1))
    except (TypeError, ValueError):
        return ToolResult(status="failed", error_message="index 无效")
    status = str(args.get("status", "done"))
    if index < 0 or index >= len(ctx.session.task_plan):
        return ToolResult(status="failed", error_message="步骤序号超出范围")
    update_step(ctx.session, index, status)
    return ToolResult(data={"ok": True, "steps": ctx.session.task_plan})


# ---------------------------------------------------------------------------
# Phase 1: Focus Mode -- agent.switch_focus
# ---------------------------------------------------------------------------

_FOCUS_LABELS: dict[str, str] = {
    "general": "通用",
    "bank": "题库管理",
    "graph": "知识图谱",
    "analysis": "成绩分析",
    "compose": "组卷与导出",
    "doc_process": "文档处理",
}


def tool_switch_focus(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    if ctx.session is None:
        return ToolResult(status="failed", error_message="无会话状态")
    domain = str(args.get("domain") or "general").strip()
    from solaire.agent_layer.registry import FOCUS_PRESETS

    if domain not in FOCUS_PRESETS:
        return ToolResult(
            status="failed",
            error_message=f"未知聚焦域: {domain}，可选: {', '.join(FOCUS_PRESETS.keys())}",
        )
    ctx.session.current_focus = domain
    label = _FOCUS_LABELS.get(domain, domain)
    return ToolResult(data={
        "ok": True,
        "focus": domain,
        "label": label,
        "message": f"已切换到「{label}」聚焦态，当前工具集已更新。",
    })


# ---------------------------------------------------------------------------
# Phase 4: Plan Mode -- agent.enter_plan_mode / agent.exit_plan_mode
# ---------------------------------------------------------------------------

_PLAN_MODE_INSTRUCTIONS = """\
你已进入计划模式（与 Cursor 类 harness 类似：先只读探索，再将计划落盘到项目内）。

1. 仅允许调用只读工具了解当前状况。
2. 禁止执行写入或破坏性操作；唯一例外：用 `file.write` 写入 `.solaire/agent/plans/` 下的 `.md` 计划文件，或用 `file.edit` 修改该目录内已有计划。
3. 计划文件必须以 YAML 围栏开头：首行 ---，YAML 内须含 name、overview、todos；再以独占一行的 --- 结束围栏，其后为 Markdown 正文。todos 为列表，建议每项含 id、content、status。
4. 落盘后调用 `agent.exit_plan_mode`，传入 plan_file_path 为本文件的项目内相对路径（如 .solaire/agent/plans/xxx.md）。

请开始分析当前任务并制定计划。"""


def tool_enter_plan_mode(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    if ctx.session is None:
        return ToolResult(status="failed", error_message="无会话状态")
    if ctx.session.plan_mode_active:
        return ToolResult(status="failed", error_message="已在计划模式中")
    ctx.session.plan_mode_active = True
    return ToolResult(data={"ok": True, "instructions": _PLAN_MODE_INSTRUCTIONS})


def tool_exit_plan_mode(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    if ctx.session is None:
        return ToolResult(status="failed", error_message="无会话状态")
    if not ctx.session.plan_mode_active:
        return ToolResult(status="failed", error_message="当前不在计划模式中")
    plan_path = str(args.get("plan_file_path") or "").strip()
    ctx.session.plan_mode_active = False
    ctx.session.current_plan_path = plan_path or None
    return ToolResult(data={
        "ok": True,
        "plan_file_path": plan_path,
        "message": "计划模式已退出，等待教师审批。",
    })


# ---------------------------------------------------------------------------
# Phase 6: Skill Activation -- agent.activate_skill
# ---------------------------------------------------------------------------

def tool_activate_skill(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    if ctx.session is None:
        return ToolResult(status="failed", error_message="无会话状态")
    name = str(args.get("name") or "").strip()
    if not name:
        return ToolResult(status="failed", error_message="name 参数必填")
    if name in ctx.session.activated_skills:
        return ToolResult(data={"ok": True, "already_active": True, "message": f"技能「{name}」已在本会话中激活。"})

    from solaire.agent_layer.skills import load_skill_content

    content = load_skill_content(name, ctx.project_root)
    if content is None:
        return ToolResult(status="failed", error_message=f"未找到技能: {name}")
    ctx.session.activated_skills.append(name)
    return ToolResult(data={
        "ok": True,
        "name": name,
        "instructions": content,
        "message": f"已激活技能「{name}」，请按指令执行。",
    })


def tool_read_skill_reference(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    """Read a reference file from a skill package directory (builtin or project .solaire/skills)."""
    name = str(args.get("name") or "").strip()
    rel = str(args.get("path") or "").strip()
    if not name or not rel:
        return ToolResult(status="failed", error_message="name 与 path 参数必填")
    raw = rel.replace("\\", "/").strip().lstrip("/")
    if not raw or ".." in raw.split("/"):
        return ToolResult(status="failed", error_message="path 无效")

    from solaire.agent_layer.skills import get_skill

    sk = get_skill(name, ctx.project_root)
    if sk is None:
        return ToolResult(status="failed", error_message=f"未找到技能: {name}")
    base = sk.skill_dir.resolve()
    target = (sk.skill_dir / raw).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return ToolResult(status="failed", error_message="path 越界")
    if not target.is_file():
        return ToolResult(status="failed", error_message=f"文件不存在: {rel}")
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return ToolResult(status="failed", error_message=f"读取失败: {e}")
    offset = int(args.get("offset") or 0)
    limit = args.get("limit")
    lines = text.splitlines(keepends=True)
    total = len(lines)
    if offset > 0:
        lines = lines[offset:]
    if limit is not None:
        lines = lines[: int(limit)]
    content = "".join(lines)
    return ToolResult(data={
        "skill": name,
        "path": rel,
        "total_lines": total,
        "content": content,
    })
