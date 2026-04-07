"""Pydantic models for Agent Harness (M3)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class GuardrailDecision(str, Enum):
    AUTO_APPROVE = "auto_approve"
    NEEDS_CONFIRMATION = "needs_confirmation"
    BLOCKED = "blocked"


class ToolRisk(str, Enum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


class ToolResult(BaseModel):
    """Structured result from a tool invocation."""

    status: Literal["succeeded", "failed"] = "succeeded"
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    summary_for_llm: str | None = None  # compact text for context


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    # 部分 OpenAI 兼容网关在 thinking 模式下要求 assistant/tool_calls 消息携带该字段。
    reasoning_content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class PendingConfirmation(BaseModel):
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    description: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SessionState(BaseModel):
    session_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    messages: list[ChatMessage] = Field(default_factory=list)
    pending_confirmations: dict[str, PendingConfirmation] = Field(default_factory=dict)
    approved_write_keys: list[str] = Field(default_factory=list)
    task_plan: list[dict[str, Any]] = Field(default_factory=list)
    total_tool_rounds: int = 0
    subagent_depth: int = 0
    # Incomplete assistant turn (OpenAI requires every tool_call_id to get a tool message)
    draft_assistant: dict[str, Any] | None = None
    draft_tool_results: list[dict[str, Any]] = Field(default_factory=list)
    # Phase 1: Focus Mode -- Agent 当前聚焦域，决定暴露哪些工具
    current_focus: str = ""
    # Phase 4: Plan Mode -- 编排层行为状态
    plan_mode_active: bool = False
    current_plan_path: str | None = None
    # 教师点「执行」时锁定的计划文件（项目内相对路径）；与 task_plan 对齐
    execution_plan_path: str | None = None
    # Phase 6: 已在本会话中激活的技能（去重）
    activated_skills: list[str] = Field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()


class InvocationContext(BaseModel):
    """Runtime context for tool execution (not persisted as whole)."""

    model_config = {"arbitrary_types_allowed": True}

    project_root: Path
    session_id: str
    mode: Literal["suggest", "execute"] = "execute"
    session: SessionState | None = None
    subagent: bool = False
    max_subagent_tool_rounds: int = 8

    def approved_key(self, tool_name: str, args: dict[str, Any]) -> str:
        import json

        return f"{tool_name}:{json.dumps(args, sort_keys=True, default=str)[:500]}"


class AgentEvent(BaseModel):
    """SSE / internal event payload."""

    event: str
    data: dict[str, Any] = Field(default_factory=dict)
