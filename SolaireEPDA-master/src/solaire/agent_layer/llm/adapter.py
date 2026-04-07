"""LLM adapter protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from pydantic import BaseModel, Field


class ChatChunk(BaseModel):
    """Streaming chunk."""

    delta_content: str | None = None
    finish_reason: str | None = None
    raw_tool_calls: list[dict[str, Any]] | None = None
    usage: dict[str, int] | None = None
    # 思考链：流式增量与回合结束时的完整内容（供下一轮请求回放）
    delta_reasoning: str | None = None
    accumulated_reasoning: str | None = None


class ChatResponse(BaseModel):
    """Non-streaming completion."""

    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)


class LLMAdapter(Protocol):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> ChatResponse | AsyncIterator[ChatChunk]: ...
