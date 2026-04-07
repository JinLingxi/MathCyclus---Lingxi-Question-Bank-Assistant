"""Rough token counting for context budgeting."""

from __future__ import annotations

from typing import Any

try:
    import tiktoken
except ImportError:
    tiktoken = None  # type: ignore


def estimate_tokens(text: str, *, model_hint: str = "gpt-4o") -> int:
    if not text:
        return 0
    if tiktoken is None:
        return max(1, len(text) // 4)
    try:
        enc = tiktoken.encoding_for_model(model_hint)
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def estimate_messages_tokens(messages: list[dict[str, Any]], *, model_hint: str = "gpt-4o") -> int:
    total = 0
    for m in messages:
        total += estimate_tokens(str(m.get("content") or ""), model_hint=model_hint)
        if tc := m.get("tool_calls"):
            total += estimate_tokens(str(tc), model_hint=model_hint)
    return total
