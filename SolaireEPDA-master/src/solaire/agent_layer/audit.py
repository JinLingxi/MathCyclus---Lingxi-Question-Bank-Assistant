"""Append-only audit log for agent tool invocations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def audit_file(project_root: Path) -> Path:
    d = project_root / ".solaire" / "agent"
    d.mkdir(parents=True, exist_ok=True)
    return d / "audit.jsonl"


def append_audit(
    project_root: Path,
    *,
    session_id: str,
    tool_name: str | None,
    status: str,
    detail: dict[str, Any] | None = None,
) -> None:
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "tool_name": tool_name,
        "status": status,
        "detail": detail or {},
    }
    p = audit_file(project_root)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
