"""OpenAI-compatible chat (async), tools + streaming for orchestrator."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from solaire.agent_layer.llm.adapter import ChatChunk, ChatResponse


def _ensure_assistant_tool_calls_have_reasoning(messages: list[dict[str, Any]]) -> None:
    """部分兼容网关在 thinking 模式下要求 assistant+tool_calls 携带 reasoning_content（可为空串）。"""
    for m in messages:
        if m.get("role") != "assistant" or not m.get("tool_calls"):
            continue
        rc = m.get("reasoning_content")
        if rc is None:
            m["reasoning_content"] = ""
        else:
            m["reasoning_content"] = str(rc)


class OpenAICompatAdapter:
    def __init__(self, *, api_key: str | None, base_url: str | None, model: str) -> None:
        self.model = model
        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> ChatResponse:
        if stream:
            raise NotImplementedError("use chat_stream")
        _ensure_assistant_tool_calls_have_reasoning(messages)
        req: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            req["max_tokens"] = max_tokens
        if tools:
            req["tools"] = tools
            req["tool_choice"] = "auto"
            req["parallel_tool_calls"] = True
        resp = await self._client.chat.completions.create(**req)
        choice = resp.choices[0]
        msg = choice.message
        tool_calls: list[dict[str, Any]] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    }
                )
        usage: dict[str, int] = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens or 0,
                "completion_tokens": resp.usage.completion_tokens or 0,
                "total_tokens": resp.usage.total_tokens or 0,
            }
        reasoning: str | None = None
        if msg is not None:
            raw_r = getattr(msg, "reasoning_content", None)
            if raw_r is None:
                raw_r = getattr(msg, "reasoning", None)
            if raw_r is not None:
                reasoning = str(raw_r)
        return ChatResponse(
            content=msg.content,
            reasoning_content=reasoning,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            usage=usage,
        )

    async def chat_stream_text(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.3,
    ):
        """Yield text deltas only (final assistant message without tools)."""
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        async for event in stream:
            if not event.choices:
                continue
            delta = event.choices[0].delta
            if delta.content:
                yield delta.content

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> AsyncIterator[ChatChunk]:
        """Stream completion; yields text chunks then one terminal chunk with finish_reason / tool_calls / usage."""
        _ensure_assistant_tool_calls_have_reasoning(messages)
        req: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            req["max_tokens"] = max_tokens
        if tools:
            req["tools"] = tools
            req["tool_choice"] = "auto"
            req["parallel_tool_calls"] = True
        try:
            req["stream_options"] = {"include_usage": True}
            stream = await self._client.chat.completions.create(**req)
        except TypeError:
            req.pop("stream_options", None)
            stream = await self._client.chat.completions.create(**req)

        tc_parts: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        usage: dict[str, int] | None = None
        reasoning_buf = ""

        async for event in stream:
            if getattr(event, "usage", None) is not None and event.usage is not None:
                u = event.usage
                usage = {
                    "prompt_tokens": getattr(u, "prompt_tokens", None) or 0,
                    "completion_tokens": getattr(u, "completion_tokens", None) or 0,
                    "total_tokens": getattr(u, "total_tokens", None) or 0,
                }
            if not event.choices:
                continue
            ch0 = event.choices[0]
            delta = ch0.delta
            if delta.content:
                yield ChatChunk(delta_content=delta.content)
            dr = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
            if dr:
                piece = str(dr)
                reasoning_buf += piece
                yield ChatChunk(delta_reasoning=piece)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = int(tc.index)
                    if idx not in tc_parts:
                        tc_parts[idx] = {"id": "", "name": "", "arguments": ""}
                    if getattr(tc, "id", None):
                        tc_parts[idx]["id"] = tc.id or tc_parts[idx]["id"]
                    fn = tc.function
                    if fn is not None:
                        if getattr(fn, "name", None):
                            tc_parts[idx]["name"] += fn.name or ""
                        if getattr(fn, "arguments", None):
                            tc_parts[idx]["arguments"] += fn.arguments or ""
            if ch0.finish_reason:
                finish_reason = ch0.finish_reason

        assembled: list[dict[str, Any]] = []
        for idx in sorted(tc_parts.keys()):
            p = tc_parts[idx]
            assembled.append(
                {
                    "id": p["id"] or f"call_{idx}",
                    "type": "function",
                    "function": {
                        "name": p["name"],
                        "arguments": p["arguments"] or "{}",
                    },
                }
            )

        raw_finish = finish_reason
        if assembled:
            fr = raw_finish or "tool_calls"
        else:
            fr = raw_finish or "stop"

        # 部分流式网关末包未带 finish_reason；若 usage 显示已达本次 max_tokens，按截断处理以便编排层续写
        if raw_finish is None and max_tokens and usage is not None:
            ct = int(usage.get("completion_tokens") or 0)
            if ct >= max_tokens:
                fr = "length"

        yield ChatChunk(
            finish_reason=fr,
            raw_tool_calls=assembled,
            usage=usage,
            accumulated_reasoning=reasoning_buf,
        )
