"""Bridge to edu_analysis.invoke_tool."""

from __future__ import annotations

from typing import Any

from solaire.agent_layer.models import InvocationContext, ToolResult
from solaire.edu_analysis.core import invoke_tool


def run_analysis_tool(ctx: InvocationContext, tool_name: str, args: dict[str, Any]) -> ToolResult:
    try:
        out = invoke_tool(ctx.project_root, tool_name, args)
        return ToolResult(status="succeeded", data=out, summary_for_llm=None)
    except Exception as e:
        return ToolResult(
            status="failed",
            data={},
            error_code="runtime_error",
            error_message=str(e),
            summary_for_llm=str(e),
        )


def post_check_python_script(code: str) -> tuple[bool, str]:
    return validate_python_syntax(code)


def validate_python_syntax(code: str) -> tuple[bool, str]:
    import ast

    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"语法错误: {e}"
