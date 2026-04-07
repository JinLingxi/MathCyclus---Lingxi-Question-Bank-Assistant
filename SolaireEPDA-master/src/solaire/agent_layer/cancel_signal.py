"""进程内取消标记：与磁盘上的会话 JSON 解耦，供流式编排与 HTTP 停止按钮共用。"""

from __future__ import annotations

_cancels: set[str] = set()


def request_cancel(session_id: str) -> None:
    _cancels.add(session_id)


def is_cancelled(session_id: str) -> bool:
    return session_id in _cancels


def clear_cancel(session_id: str) -> None:
    _cancels.discard(session_id)
