"""Memory tools: skeptical read path."""

from __future__ import annotations

from typing import Any

from solaire.agent_layer.memory import read_index, read_topic, search_topics
from solaire.agent_layer.models import InvocationContext, ToolResult


def tool_read_index(ctx: InvocationContext, _args: dict[str, Any]) -> ToolResult:
    text = read_index(ctx.project_root)
    return ToolResult(status="succeeded", data={"content": text})


def tool_read_topic(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    topic = str(args.get("topic") or "").strip()
    if not topic.endswith(".md"):
        topic = f"{topic}.md" if "." not in topic else topic
    try:
        body = read_topic(ctx.project_root, topic)
    except ValueError as e:
        return ToolResult(status="failed", data={}, error_code="invalid_arguments", error_message=str(e))
    return ToolResult(status="succeeded", data={"topic": topic, "content": body})


def tool_search(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    q = str(args.get("query") or "")
    hits = search_topics(ctx.project_root, q, max_hits=int(args.get("max_hits", 20)))
    return ToolResult(status="succeeded", data={"hits": hits})
