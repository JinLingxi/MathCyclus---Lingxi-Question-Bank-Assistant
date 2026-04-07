"""Project-local LLM overrides (`.solaire/agent/llm_overrides.json`)."""

from __future__ import annotations

import json
from pathlib import Path
from solaire.common.security import assert_within_project

_OVERRIDES_NAME = "llm_overrides.json"


def overrides_file(project_root: Path) -> Path:
    p = (project_root / ".solaire" / "agent" / _OVERRIDES_NAME).resolve()
    assert_within_project(project_root, p)
    return p


def load_overrides_raw(project_root: Path) -> dict[str, str]:
    """Return only keys stored in the project override file (not merged with env)."""
    path = overrides_file(project_root)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k in ("api_key", "base_url", "main_model", "fast_model", "max_tokens"):
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out


def save_overrides_raw(project_root: Path, data: dict[str, str]) -> None:
    path = overrides_file(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not data:
        if path.is_file():
            path.unlink()
        return
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mask_api_key(key: str | None) -> str | None:
    if not key:
        return None
    if len(key) <= 8:
        return "********"
    return f"********{key[-4:]}"
