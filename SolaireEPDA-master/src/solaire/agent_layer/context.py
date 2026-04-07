"""Build chat messages with token budget and compaction hooks."""

from __future__ import annotations

import json
from typing import Any

from solaire.agent_layer.compactor import compact_for_llm
from solaire.agent_layer.llm.openai_compat import _ensure_assistant_tool_calls_have_reasoning
from solaire.agent_layer.memory import read_index
from solaire.agent_layer.models import ChatMessage, SessionState
from solaire.agent_layer.prompts import build_system_prompt
from solaire.agent_layer.registry import RegisteredTool, all_registered_tools, tool_descriptions_for_prompt
from solaire.agent_layer.task_tracker import plan_to_prompt_block
from solaire.agent_layer.llm.token_budget import estimate_messages_tokens


class ContextManager:
    TOKEN_BUDGET_TOTAL = 28000

    def __init__(self, *, include_subtask_tool: bool = True) -> None:
        self.include_subtask_tool = include_subtask_tool

    def build_system_content(
        self,
        project_ctx: dict[str, Any],
        *,
        tools: list[RegisteredTool] | None = None,
        skill_guidance: str | None = None,
        current_focus: str | None = None,
        plan_mode_active: bool = False,
        execution_plan_path: str | None = None,
        skill_catalog: str | None = None,
    ) -> str:
        tlist = tools
        if tlist is None:
            tlist = all_registered_tools(include_subtask=self.include_subtask_tool)
        desc = tool_descriptions_for_prompt(tlist)
        root = project_ctx.get("_project_root")
        mem_excerpt = ""
        if root is not None:
            try:
                mem_excerpt = read_index(root)[:2500]
            except Exception:
                mem_excerpt = ""
        public_ctx = {k: v for k, v in project_ctx.items() if not str(k).startswith("_")}
        return build_system_prompt(
            tool_descriptions=desc,
            memory_index_excerpt=mem_excerpt,
            project_ctx=public_ctx,
            skill_guidance=skill_guidance,
            current_focus=current_focus,
            plan_mode_active=plan_mode_active,
            execution_plan_path=execution_plan_path,
            skill_catalog=skill_catalog,
            project_root=root,
        )

    def session_to_api_messages(self, session: SessionState) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in session.messages:
            d: dict[str, Any] = {"role": m.role}
            if m.content is not None:
                d["content"] = m.content
            if m.reasoning_content is not None:
                d["reasoning_content"] = m.reasoning_content
            if m.tool_calls:
                d["tool_calls"] = m.tool_calls
                # 某些兼容网关在 thinking 开启时要求 assistant+tool_calls 含 reasoning_content。
                if m.role == "assistant" and "reasoning_content" not in d:
                    d["reasoning_content"] = ""
            if m.tool_call_id:
                d["tool_call_id"] = m.tool_call_id
            if m.name:
                d["name"] = m.name
            out.append(d)
        _ensure_assistant_tool_calls_have_reasoning(out)
        return out

    def build_messages(
        self,
        *,
        system_content: str,
        session: SessionState,
        user_message: str,
    ) -> list[dict[str, Any]]:
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
        plan = plan_to_prompt_block(session)
        if plan:
            msgs.append({"role": "system", "content": plan})
        for m in session.messages:
            d: dict[str, Any] = {"role": m.role}
            if m.role == "tool":
                d["content"] = m.content or ""
                d["tool_call_id"] = m.tool_call_id or ""
                if m.name:
                    d["name"] = m.name
            else:
                if m.content is not None:
                    d["content"] = m.content
                if m.reasoning_content is not None:
                    d["reasoning_content"] = m.reasoning_content
                if m.tool_calls:
                    d["tool_calls"] = m.tool_calls
                    if m.role == "assistant" and "reasoning_content" not in d:
                        d["reasoning_content"] = ""
            msgs.append(d)
        if user_message.strip():
            msgs.append({"role": "user", "content": user_message.strip()})
        self._maybe_compact(msgs)
        _ensure_assistant_tool_calls_have_reasoning(msgs)
        return msgs

    def _maybe_compact(self, messages: list[dict[str, Any]]) -> None:
        """L2: fold oldest tool outputs into stubs; then drop oldest turns if still over budget."""
        stub = "[较早的工具输出已折叠；如需细节请重新运行相应工具。]"
        while estimate_messages_tokens(messages) > self.TOKEN_BUDGET_TOTAL and len(messages) > 4:
            stubbed = False
            for i in range(2, max(2, len(messages) - 1)):
                m = messages[i]
                if m.get("role") == "tool" and (m.get("content") or "") != stub:
                    m["content"] = stub
                    stubbed = True
                    break
            if stubbed:
                continue
            if len(messages) > 3:
                messages.pop(2)
            else:
                break


def tool_result_to_content(tool_name: str, data: dict[str, Any]) -> str:
    payload, _ = compact_for_llm(data, max_chars=10000)
    return json.dumps({"tool": tool_name, "result": payload}, ensure_ascii=False, default=str)
