"""Prompt cache friendliness helpers (placeholder metrics)."""


def stable_prefix_hint() -> str:
    """Document: keep ROLE+GOAL+TOOLS+CONSTRAINTS stable across turns for provider caching."""
    return "stable_prefix"
