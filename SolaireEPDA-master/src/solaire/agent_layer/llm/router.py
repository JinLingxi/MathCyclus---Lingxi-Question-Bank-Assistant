"""Model routing from environment variables and optional project overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from solaire.agent_layer.llm.llm_overrides import load_overrides_raw
from solaire.agent_layer.llm.openai_compat import OpenAICompatAdapter


@dataclass
class LLMSettings:
    api_key: str | None
    base_url: str | None
    main_model: str
    fast_model: str
    max_tokens: int | None = None


def load_llm_settings(project_root: Path | None = None) -> LLMSettings:
    api_key = os.environ.get("SOLAIRE_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("SOLAIRE_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    main_model = os.environ.get("SOLAIRE_LLM_MODEL", "gpt-4o-mini")
    fast_model = os.environ.get("SOLAIRE_LLM_FAST_MODEL", os.environ.get("SOLAIRE_LLM_MODEL", "gpt-4o-mini"))

    max_tokens_str = os.environ.get("SOLAIRE_LLM_MAX_TOKENS")
    max_tokens: int | None = int(max_tokens_str) if max_tokens_str and max_tokens_str.isdigit() else None

    if project_root is not None:
        ov = load_overrides_raw(project_root)
        if ov.get("api_key"):
            api_key = ov["api_key"]
        if "base_url" in ov:
            base_url = ov["base_url"] or None
        if ov.get("main_model"):
            main_model = ov["main_model"]
        if ov.get("fast_model"):
            fast_model = ov["fast_model"]
        if ov.get("max_tokens") is not None and str(ov["max_tokens"]).strip() != "":
            try:
                max_tokens = int(ov["max_tokens"])
            except (ValueError, TypeError):
                pass

    if max_tokens is None:
        max_tokens = 4096

    return LLMSettings(
        api_key=api_key,
        base_url=base_url,
        main_model=main_model,
        fast_model=fast_model,
        max_tokens=max_tokens,
    )


class ModelRouter:
    def __init__(self, settings: LLMSettings | None = None, *, project_root: Path | None = None) -> None:
        if settings is not None:
            self.settings = settings
        else:
            self.settings = load_llm_settings(project_root)

    def main(self) -> OpenAICompatAdapter:
        return OpenAICompatAdapter(
            api_key=self.settings.api_key,
            base_url=self.settings.base_url,
            model=self.settings.main_model,
        )

    def fast(self) -> OpenAICompatAdapter:
        return OpenAICompatAdapter(
            api_key=self.settings.api_key,
            base_url=self.settings.base_url,
            model=self.settings.fast_model,
        )
