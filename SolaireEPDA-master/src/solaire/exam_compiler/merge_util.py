"""Shallow-recursive dict merge for template defaults and exam metadata."""

from __future__ import annotations

from typing import Any


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge override into base; nested dicts are merged recursively. None values in override are skipped."""
    out = dict(base)
    for k, v in override.items():
        if v is None:
            continue
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out
