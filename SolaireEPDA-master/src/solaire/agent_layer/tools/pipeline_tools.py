"""Programmatic multi-step tool execution (limited, same guardrails as main loop)."""

from __future__ import annotations

from typing import Any

from solaire.agent_layer.guardrails import (
    SAFETY_MODE_VIVACE,
    check_tool_call,
    load_safety_mode,
    vivace_needs_fast_model_review,
)
from solaire.agent_layer.models import GuardrailDecision, InvocationContext, ToolResult


PIPELINE_TOOL_NAME = "agent.run_tool_pipeline"
_MAX_STEPS = 20


def tool_run_tool_pipeline(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    from solaire.agent_layer import registry as reg

    steps = args.get("steps")
    if not isinstance(steps, list) or not steps:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message="steps 须为非空数组")
    out: list[dict[str, Any]] = []
    for i, step in enumerate(steps[:_MAX_STEPS]):
        if not isinstance(step, dict):
            out.append({"index": i, "error": "步骤须为对象"})
            continue
        name = str(step.get("tool") or "").strip()
        raw_args = step.get("arguments")
        sargs: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
        if not name:
            out.append({"index": i, "error": "缺少 tool"})
            continue
        if name == reg.SUBTASK_TOOL_NAME or name == PIPELINE_TOOL_NAME:
            return ToolResult(
                status="failed",
                error_code="invalid_arguments",
                error_message="管道内不可包含子任务或嵌套管道",
            )
        dec = check_tool_call(name, sargs, ctx)
        if dec != GuardrailDecision.AUTO_APPROVE:
            return ToolResult(
                status="failed",
                error_code="needs_confirmation",
                error_message=f"第 {i} 步「{name}」需教师确认或当前模式不允许，请在主对话中分步执行。",
            )
        # Vivace：需异步快速复核的步骤无法在同步管道内执行，避免绕过高危复核直接调用工具。
        if load_safety_mode(ctx.project_root) == SAFETY_MODE_VIVACE and vivace_needs_fast_model_review(name):
            return ToolResult(
                status="failed",
                error_code="needs_confirmation",
                error_message=(
                    f"第 {i} 步「{name}」在当前安全模式下需先完成安全复核，"
                    "无法在并行管道内执行，请在主对话中单独发起该步骤。"
                ),
            )
        tr = reg.invoke_registered_tool(name, sargs, ctx)
        out.append(
            {
                "index": i,
                "tool": name,
                "status": tr.status,
                "data": tr.data if tr.status == "succeeded" else {"error": tr.error_message, "error_code": tr.error_code},
            }
        )
    return ToolResult(status="succeeded", data={"completed": len(out), "steps": out})
