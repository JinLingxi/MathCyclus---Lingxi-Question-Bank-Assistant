"""Task plan tracking for multi-step agent work."""

from __future__ import annotations

from typing import Any

from solaire.agent_layer.models import SessionState


def set_plan(session: SessionState, steps: list[dict[str, Any]]) -> None:
    session.task_plan = [{"title": s.get("title", ""), "status": s.get("status", "pending")} for s in steps]
    session.touch()


def update_step(session: SessionState, index: int, status: str) -> None:
    if 0 <= index < len(session.task_plan):
        session.task_plan[index]["status"] = status
        session.touch()


def plan_to_prompt_block(session: SessionState) -> str:
    if not session.task_plan:
        return ""
    lines = ["当前任务步骤："]
    for i, s in enumerate(session.task_plan, start=1):
        lines.append(f"{i}. [{s.get('status', '?')}] {s.get('title', '')}")
    return "\n".join(lines)
