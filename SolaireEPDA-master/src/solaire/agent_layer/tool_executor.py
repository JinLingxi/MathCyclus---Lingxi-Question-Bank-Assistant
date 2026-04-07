"""Draft tool-call loop: parallel read batch, subagent, guardrails, confirmations."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from solaire.agent_layer.audit import append_audit
from solaire.agent_layer.cancel_signal import clear_cancel, is_cancelled
from solaire.agent_layer.compactor import summarize_tool_result
from solaire.agent_layer.context import tool_result_to_content
from solaire.agent_layer.guardrails import (
    SAFETY_MODE_VIVACE,
    check_tool_call,
    human_confirmation_message,
    vivace_needs_fast_model_review,
)
from solaire.agent_layer.models import (
    ChatMessage,
    GuardrailDecision,
    InvocationContext,
    PendingConfirmation,
    SessionState,
    ToolRisk,
)
from solaire.agent_layer.registry import (
    SUBTASK_TOOL_NAME,
    get_registered_tool,
    invoke_registered_tool,
)
from solaire.agent_layer.session import save_session
from solaire.agent_layer.subagent import run_subagent
from solaire.agent_layer.tools import analysis_tools
from solaire.agent_layer.utils import parse_tool_arguments as _parse_args

EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]


def flush_draft_to_messages(session: SessionState) -> None:
    d = session.draft_assistant
    if not d:
        session.draft_tool_results = []
        return
    tcs = d.get("tool_calls") or []
    results = session.draft_tool_results
    rc = d.get("reasoning_content")
    if tcs and rc is None:
        rc = ""
    session.messages.append(
        ChatMessage(
            role="assistant",
            content=d.get("content"),
            reasoning_content=rc,
            tool_calls=list(tcs),
        )
    )
    for tr in results:
        session.messages.append(
            ChatMessage(
                role="tool",
                content=tr.get("content", ""),
                tool_call_id=tr.get("tool_call_id"),
                name=tr.get("name"),
            )
        )
    session.draft_assistant = None
    session.draft_tool_results = []
    session.touch()


def consecutive_read_tool_indices(
    tcs: list[dict[str, Any]],
    start: int,
    ctx: InvocationContext,
    safety_mode: str,
) -> list[int]:
    indices: list[int] = []
    j = start
    while j < len(tcs):
        tc = tcs[j]
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        if name == SUBTASK_TOOL_NAME:
            break
        rt = get_registered_tool(name)
        if not rt or rt.risk != ToolRisk.READ:
            break
        args = _parse_args(fn.get("arguments"))
        dec = check_tool_call(name, args, ctx, safety_mode=safety_mode)
        if dec != GuardrailDecision.AUTO_APPROVE:
            break
        indices.append(j)
        j += 1
    return indices


def consecutive_subtask_tool_indices(
    tcs: list[dict[str, Any]],
    start: int,
    ctx: InvocationContext,
    safety_mode: str,
) -> list[int]:
    """Collect consecutive agent.run_subtask calls that are all auto-approved (for parallel run)."""
    indices: list[int] = []
    j = start
    while j < len(tcs):
        tc = tcs[j]
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        if name != SUBTASK_TOOL_NAME:
            break
        args = _parse_args(fn.get("arguments"))
        dec = check_tool_call(name, args, ctx, safety_mode=safety_mode)
        if dec != GuardrailDecision.AUTO_APPROVE:
            break
        indices.append(j)
        j += 1
    return indices


def thinking_label_for_tool(tool_name: str) -> str:
    rt = get_registered_tool(tool_name)
    if rt and rt.ui_label:
        return rt.ui_label
    return "正在执行操作…"


async def vivace_fast_review(
    *,
    fast_adapter: Any,
    tool_name: str,
    args: dict[str, Any],
) -> tuple[bool, str]:
    try:
        prompt = (
            "你是安全复核器。判断下面操作是否可能造成较大风险。"
            "若需要人工确认，只输出 RISKY:原因；否则输出 SAFE:原因。\n"
            f"操作: {tool_name}\n参数: {json.dumps(args, ensure_ascii=False, default=str)[:1200]}"
        )
        resp = await fast_adapter.chat(
            [
                {"role": "system", "content": "只输出一行，格式必须是 SAFE:... 或 RISKY:..."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        txt = (resp.content or "").strip()
        upper = txt.upper()
        if upper.startswith("RISKY:"):
            return True, (txt.split(":", 1)[1] or "存在潜在风险").strip()
        return False, (txt.split(":", 1)[1] if ":" in txt else txt or "风险较低，可直接执行").strip()
    except Exception:
        return True, "快速复核异常，已转为人工确认以保证安全。"


async def run_draft_tool_loop(
    *,
    project_root: Path,
    session: SessionState,
    ctx: InvocationContext,
    safety_mode: str,
    adapter: Any,
    fast_adapter: Any,
    emit: EmitFn,
) -> bool:
    """Returns True if stopped for confirmation or cancel."""
    d = session.draft_assistant
    if not d:
        return False
    tcs = d.get("tool_calls") or []
    k = len(session.draft_tool_results)
    while k < len(tcs):
        if is_cancelled(session.session_id):
            clear_cancel(session.session_id)
            session.draft_assistant = None
            session.draft_tool_results = []
            await emit("error", {"code": "cancelled", "message": "已按您的操作停止。"})
            await emit("done", {"usage": {}, "cancelled": True})
            save_session(project_root, session)
            return True
        read_batch = consecutive_read_tool_indices(tcs, k, ctx, safety_mode)
        if len(read_batch) >= 2:
            for idx in read_batch:
                tc0 = tcs[idx]
                fn0 = tc0.get("function") or {}
                name0 = fn0.get("name") or ""
                args0 = _parse_args(fn0.get("arguments"))
                await emit("thinking", {"message": thinking_label_for_tool(name0)})
                await emit("tool_start", {"tool_name": name0, "arguments": args0})

            async def _invoke_read(i: int) -> tuple[int, str, str, Any]:
                tc_i = tcs[i]
                fn_i = tc_i.get("function") or {}
                n = fn_i.get("name") or ""
                a = _parse_args(fn_i.get("arguments"))
                tid_i = tc_i.get("id") or f"call-{i}"
                tr_i = await asyncio.to_thread(invoke_registered_tool, n, a, ctx)
                return i, n, tid_i, tr_i

            parts = await asyncio.gather(*[_invoke_read(i) for i in read_batch])
            for _i, name, tid, tr in sorted(parts, key=lambda x: x[0]):
                payload = tr.data if tr.status == "succeeded" else {"error": tr.error_message, "error_code": tr.error_code}
                session.draft_tool_results.append(
                    {
                        "tool_call_id": tid,
                        "name": name,
                        "content": tool_result_to_content(name, payload),
                    }
                )
                append_audit(
                    project_root,
                    session_id=session.session_id,
                    tool_name=name,
                    status=tr.status,
                    detail={"summary": summarize_tool_result(name, payload)},
                )
                await emit(
                    "tool_result",
                    {
                        "tool_name": name,
                        "status": tr.status,
                        "summary": summarize_tool_result(name, payload),
                    },
                )
                if ctx.session and name in ("agent.set_task_plan", "agent.update_task_step"):
                    await emit("task_update", {"steps": list(ctx.session.task_plan)})
            k += len(read_batch)
            continue
        subtask_batch = consecutive_subtask_tool_indices(tcs, k, ctx, safety_mode)
        if len(subtask_batch) >= 2:
            for idx in subtask_batch:
                tc0 = tcs[idx]
                fn0 = tc0.get("function") or {}
                name0 = fn0.get("name") or ""
                args0 = _parse_args(fn0.get("arguments"))
                await emit("thinking", {"message": thinking_label_for_tool(name0)})
                await emit("tool_start", {"tool_name": name0, "arguments": args0})

            async def _run_subtask_one(i: int) -> tuple[int, str, str]:
                tc_i = tcs[i]
                fn_i = tc_i.get("function") or {}
                a = _parse_args(fn_i.get("arguments"))
                tid_i = tc_i.get("id") or f"call-{i}"
                objective = str(a.get("objective") or "")
                pfx = a.get("allowed_tool_prefixes")
                prefixes = [str(x) for x in pfx] if isinstance(pfx, list) else None

                async def sub_emit(ev: str, data: dict[str, Any]) -> None:
                    await emit(ev, {**data, "parallel_subtask": True, "parallel_index": i})

                await emit(
                    "subagent_start",
                    {"task_description": objective[:500], "parallel_subtask": True, "parallel_index": i},
                )
                summary = await run_subagent(
                    ctx=ctx,
                    objective=objective,
                    allowed_prefixes=prefixes,
                    llm_chat=adapter.chat,
                    max_rounds=ctx.max_subagent_tool_rounds,
                    emit=sub_emit,
                )
                return i, tid_i, summary

            parts = await asyncio.gather(*[_run_subtask_one(i) for i in subtask_batch])
            for i, tid_i, summary in sorted(parts, key=lambda x: x[0]):
                await emit("subagent_done", {"summary": summary[:2000], "parallel_subtask": True})
                session.draft_tool_results.append(
                    {
                        "tool_call_id": tid_i,
                        "name": SUBTASK_TOOL_NAME,
                        "content": json.dumps(
                            {"tool": SUBTASK_TOOL_NAME, "result": {"summary": summary}},
                            ensure_ascii=False,
                        ),
                    }
                )
                append_audit(
                    project_root,
                    session_id=session.session_id,
                    tool_name=SUBTASK_TOOL_NAME,
                    status="succeeded",
                    detail={"subagent": True, "parallel_subtask": True},
                )
            k += len(subtask_batch)
            continue
        tc = tcs[k]
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        args = _parse_args(fn.get("arguments"))
        tid = tc.get("id") or f"call-{k}"
        await emit("thinking", {"message": thinking_label_for_tool(name)})
        await emit("tool_start", {"tool_name": name, "arguments": args})
        if name == SUBTASK_TOOL_NAME:
            objective = str(args.get("objective") or "")
            pfx = args.get("allowed_tool_prefixes")
            prefixes = [str(x) for x in pfx] if isinstance(pfx, list) else None
            await emit("subagent_start", {"task_description": objective[:500]})

            async def sub_emit(ev: str, data: dict[str, Any]) -> None:
                await emit(ev, data)

            summary = await run_subagent(
                ctx=ctx,
                objective=objective,
                allowed_prefixes=prefixes,
                llm_chat=adapter.chat,
                max_rounds=ctx.max_subagent_tool_rounds,
                emit=sub_emit,
            )
            await emit("subagent_done", {"summary": summary[:2000]})
            session.draft_tool_results.append(
                {
                    "tool_call_id": tid,
                    "name": name,
                    "content": json.dumps(
                        {"tool": name, "result": {"summary": summary}},
                        ensure_ascii=False,
                    ),
                }
            )
            append_audit(
                project_root,
                session_id=session.session_id,
                tool_name=name,
                status="succeeded",
                detail={"subagent": True},
            )
            k += 1
            continue
        dec = check_tool_call(name, args, ctx, safety_mode=safety_mode)
        confirm_extra = ""
        if dec == GuardrailDecision.AUTO_APPROVE and safety_mode == SAFETY_MODE_VIVACE and vivace_needs_fast_model_review(
            name
        ):
            need_confirm, reason = await vivace_fast_review(
                fast_adapter=fast_adapter,
                tool_name=name,
                args=args,
            )
            if need_confirm:
                dec = GuardrailDecision.NEEDS_CONFIRMATION
                confirm_extra = f"（安全复核提示：{reason}）"
                await emit("thinking", {"message": f"已触发安全复核：{reason}"})
        if dec != GuardrailDecision.AUTO_APPROVE:
            aid = uuid.uuid4().hex
            session.pending_confirmations[aid] = PendingConfirmation(
                tool_call_id=tid,
                tool_name=name,
                arguments=args,
                description=human_confirmation_message(name, args) + confirm_extra,
            )
            await emit(
                "confirm_needed",
                {
                    "action_id": aid,
                    "tool_name": name,
                    "description": session.pending_confirmations[aid].description,
                    "risk": "write_or_destructive",
                },
            )
            save_session(project_root, session)
            return True
        if name == "analysis.save_script" and args.get("code"):
            ok, err = analysis_tools.validate_python_syntax(str(args["code"]))
            if not ok:
                session.draft_tool_results.append(
                    {
                        "tool_call_id": tid,
                        "name": name,
                        "content": json.dumps(
                            {"tool": name, "error": err},
                            ensure_ascii=False,
                        ),
                    }
                )
                k += 1
                continue
        tr = invoke_registered_tool(name, args, ctx)
        payload = tr.data if tr.status == "succeeded" else {"error": tr.error_message, "error_code": tr.error_code}
        session.draft_tool_results.append(
            {
                "tool_call_id": tid,
                "name": name,
                "content": tool_result_to_content(name, payload),
            }
        )
        append_audit(
            project_root,
            session_id=session.session_id,
            tool_name=name,
            status=tr.status,
            detail={"summary": summarize_tool_result(name, payload)},
        )
        await emit(
            "tool_result",
            {
                "tool_name": name,
                "status": tr.status,
                "summary": summarize_tool_result(name, payload),
            },
        )
        if ctx.session and name in ("agent.set_task_plan", "agent.update_task_step"):
            await emit("task_update", {"steps": list(ctx.session.task_plan)})
        k += 1
    flush_draft_to_messages(session)
    return False
