"""Choice item helpers for storage normalization and TeX export."""

from __future__ import annotations

from typing import Any


def is_wrapped_choice_value(value: Any) -> bool:
    text = str(value or "").strip()
    if not text.startswith("{") or not text.endswith("}"):
        return False
    depth = 0
    for index, char in enumerate(text):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
            if depth == 0 and index != len(text) - 1:
                return False
    return depth == 0


def wrap_choice_item(choice: Any) -> str:
    text = str(choice or "").strip()
    if not text:
        return ""
    if is_wrapped_choice_value(text):
        return text
    return "{" + text + "}"


def unwrap_choice_item(choice: Any) -> str:
    text = str(choice or "").strip()
    if not text:
        return ""
    if is_wrapped_choice_value(text):
        return text[1:-1].strip()
    return text


def normalize_choice_items(choices: Any) -> list[str]:
    if not isinstance(choices, list):
        return []
    return [unwrap_choice_item(choice) for choice in choices if str(choice or "").strip()]
