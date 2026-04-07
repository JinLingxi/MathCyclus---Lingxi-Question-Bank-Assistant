"""AgentLayer — unified LLM orchestration, tools, memory, and sessions (M3)."""

from solaire.agent_layer.registry import (
    invoke_registered_tool,
    openai_tools_payload,
    tool_descriptions_for_prompt,
)
from solaire.agent_layer.session import create_session, list_sessions, load_session, save_session

__all__ = [
    "create_session",
    "invoke_registered_tool",
    "list_sessions",
    "load_session",
    "openai_tools_payload",
    "save_session",
    "tool_descriptions_for_prompt",
]
