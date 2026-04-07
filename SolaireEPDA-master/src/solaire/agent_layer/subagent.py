"""Isolated sub-agent run: shared tools, clean message stack, returns final text summary."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from solaire.agent_layer.audit import append_audit
from solaire.agent_layer.compactor import summarize_tool_result
from solaire.agent_layer.context import tool_result_to_content
from solaire.agent_layer.guardrails import check_tool_call
from solaire.agent_layer.models import GuardrailDecision, InvocationContext
from solaire.agent_layer.registry import (
    all_registered_tools,
    invoke_registered_tool,
    openai_tools_payload,
)
from solaire.agent_layer.utils import parse_tool_arguments


async def run_subagent(
    *,
    ctx: InvocationContext,
    objective: str,
    allowed_prefixes: list[str] | None,
    llm_chat: Callable[..., Awaitable[Any]],
    max_rounds: int = 8,
    emit: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
) -> str:
    """Run inner tool loop; return concise final answer for parent context."""
    tools = all_registered_tools(include_subtask=False)
    if allowed_prefixes:
        pfx = tuple(allowed_prefixes)

        def _ok(name: str) -> bool:
            return any(name.startswith(x.rstrip("*")) or name.startswith(x) for x in pfx)

        tools = [t for t in tools if _ok(t.name)]
    otools = openai_tools_payload(tools)

    inner_ctx = ctx.model_copy(update={"subagent": True, "session": ctx.session})
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "你是 SolEdu 子任务分析助手。在尽量少轮次内完成目标，"
                "仅输出最终结论，过程性说明保持简短。使用提供的工具获取事实数据。"
            ),
        },
        {"role": "user", "content": objective},
    ]

    for round_i in range(max_rounds):
        resp = await llm_chat(messages, tools=otools, temperature=0.2)
        if resp.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": resp.content,
                    "reasoning_content": getattr(resp, "reasoning_content", None) or "",
                    "tool_calls": resp.tool_calls,
                }
            )
            for tc in resp.tool_calls:
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                raw_args = fn.get("arguments") or "{}"
                args = parse_tool_arguments(raw_args)
                tid = tc.get("id") or f"sub-{round_i}"
                if emit:
                    await emit(
                        "tool_start",
                        {"tool_name": name, "arguments": args, "subagent": True, "round": round_i},
                    )
                dec = check_tool_call(name, args, inner_ctx)
                if dec != GuardrailDecision.AUTO_APPROVE:
                    msg = "子任务中该工具需确认，已中止；请回到主对话授权后重试。"
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tid,
                            "name": name,
                            "content": json.dumps({"error": msg}, ensure_ascii=False),
                        }
                    )
                    continue
                tr = invoke_registered_tool(name, args, inner_ctx)
                payload = tr.data if tr.status == "succeeded" else {"error": tr.error_message}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tid,
                        "name": name,
                        "content": tool_result_to_content(name, payload),
                    }
                )
                summ = summarize_tool_result(name, payload)
                if emit:
                    await emit(
                        "tool_result",
                        {
                            "tool_name": name,
                            "status": tr.status,
                            "summary": summ,
                            "subagent": True,
                            "round": round_i,
                        },
                    )
                append_audit(
                    ctx.project_root,
                    session_id=ctx.session_id,
                    tool_name=name,
                    status=tr.status,
                    detail={"subagent": True, "summary": summ},
                )
            continue
        text = (resp.content or "").strip()
        if text:
            return text[:8000]
        return "（子任务未产生文本结论）"
    return "（子任务达到最大轮次，请缩小目标后重试）"


async def run_subagents_parallel(
    *,
    ctx: InvocationContext,
    objectives: list[str],
    allowed_prefixes: list[str] | None,
    llm_chat: Callable[..., Awaitable[Any]],
    max_rounds: int = 8,
    emit: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
) -> list[str]:
    """Run multiple isolated sub-agents concurrently; returns summaries in input order."""

    async def _one(obj: str) -> str:
        return await run_subagent(
            ctx=ctx,
            objective=obj,
            allowed_prefixes=allowed_prefixes,
            llm_chat=llm_chat,
            max_rounds=max_rounds,
            emit=emit,
        )

    return list(await asyncio.gather(*[_one(o) for o in objectives]))
