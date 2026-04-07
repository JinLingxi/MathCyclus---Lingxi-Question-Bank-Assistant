"""Post-turn memory / analysis history writes (extracted from orchestrator)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from solaire.agent_layer.audit import append_audit
from solaire.agent_layer.memory import append_session_digest_line, merge_index_bullet, read_topic, write_topic
from solaire.agent_layer.models import SessionState

EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]


def append_analysis_history_line(project_root: Path, line: str) -> None:
    from datetime import datetime, timezone

    from solaire.agent_layer import memory as mem_mod

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    prev = read_topic(project_root, "analysis_history.md")
    block = (prev.strip() + "\n\n" if prev.strip() else "") + f"- {ts} UTC — {line}\n"
    write_topic(project_root, "analysis_history.md", block)
    idx = mem_mod.read_index(project_root)
    if "暂无条目" in idx or len(idx) < 40:
        mem_mod.write_index(
            project_root,
            "## 记忆索引\n"
            "- [分析记录](analysis_history.md): 助手自动追加的对话摘要条目\n",
        )


async def emit_memory_after_assistant_turn(
    project_root: Path,
    session: SessionState,
    *,
    user_message: str | None,
    assistant_text: str,
    emit: EmitFn,
) -> None:
    """Append analysis history / digest when there is both a user line and assistant reply."""
    last_user_text = user_message
    if not (last_user_text and last_user_text.strip()):
        for m in reversed(session.messages):
            if m.role == "user" and (m.content or "").strip():
                last_user_text = m.content.strip()
                break
    if not (last_user_text and assistant_text.strip()):
        return
    try:
        snippet = f"用户：{last_user_text[:120]}… / 助手摘要：{assistant_text[:160]}…"
        append_analysis_history_line(project_root, snippet)
        changed = ["analysis_history.md"]
        append_session_digest_line(
            project_root,
            f"{last_user_text[:80]}… → {assistant_text[:120]}…",
        )
        changed.append("session_digest.md")
        bullet = f"[分析记录](analysis_history.md) {assistant_text[:200]}".strip()
        if len(bullet) > 240:
            bullet = bullet[:237] + "…"
        if merge_index_bullet(project_root, bullet):
            changed.append("INDEX.md")
        await emit("memory_updated", {"topics_changed": changed})
    except Exception as e:
        await emit("memory_update_failed", {"message": str(e)})
        append_audit(
            project_root,
            session_id=session.session_id,
            tool_name=None,
            status="memory_update_failed",
            detail={"error": str(e)},
        )
