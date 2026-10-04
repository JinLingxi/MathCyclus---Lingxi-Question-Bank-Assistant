"""Persistent page-level AI recognition queue for document import jobs."""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.pdf_import_service import DEFAULT_JOBS_ROOT, load_pdf_import_job, resolve_job_dir, write_json


QUEUE_FILE_NAME = "ai_refine_queue.json"
QUEUE_STATUSES = {"paused", "running", "completed"}
ITEM_STATUSES = {"pending", "running", "succeeded", "failed", "skipped"}
DEFAULT_STALE_AFTER_SECONDS = 15 * 60


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _queue_lock(path: Path):
    """Serialize queue read-modify-write operations across Streamlit workers."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    with lock_path.open("r+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _parse_timestamp(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _is_stale(value: Any, *, stale_after_seconds: int) -> bool:
    timestamp = _parse_timestamp(value)
    return bool(timestamp and time.time() - timestamp >= max(1, int(stale_after_seconds)))


def classify_queue_error(error: str) -> tuple[str, bool]:
    """Classify a failed item for review and decide whether retry is sensible."""
    text = str(error or "").strip()
    lowered = text.lower()
    if any(token in lowered for token in ("timeout", "timed out", "连接", "网络", "429", "502", "503", "504")):
        return "network_timeout", True
    if any(token in text for token in ("未返回", "不完整", "tex", "题号映射")):
        return "ai_incomplete", True
    if any(token in text for token in ("文件", "图片", "读取", "路径")):
        return "local_file", False
    if "题号" in text or "索引" in text:
        return "question_mapping", False
    return "unknown", False


def _question_fingerprint(question: dict[str, Any]) -> str:
    extra = question.get("extra") if isinstance(question.get("extra"), dict) else {}
    payload = {
        "source_item_id": question.get("source_item_id") or "",
        "question_number": extra.get("question_number") or "",
        "raw_source_text": question.get("raw_source_text") or "",
        "question_crop_paths": extra.get("question_crop_paths") or [],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _unassigned_page_task(block: dict[str, Any]) -> dict[str, Any]:
    page_number = int(block.get("page_number") or 0)
    source_item_id = f"page_{page_number:03d}_unassigned"
    raw_text = str(block.get("raw_text") or "")
    raw = json.dumps(
        {"source_item_id": source_item_id, "page_number": page_number, "raw_text": raw_text},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "source_item_id": source_item_id,
        "question_number": "",
        "page_number": page_number,
        "kind": "unassigned_page",
        "fingerprint": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }


def _queue_path(job_id: str, jobs_root: str | Path = DEFAULT_JOBS_ROOT) -> Path:
    return resolve_job_dir(job_id, jobs_root) / QUEUE_FILE_NAME


def queue_summary(queue: dict[str, Any]) -> dict[str, int | str]:
    items = [item for item in queue.get("items") or [] if isinstance(item, dict)]
    counts = {status: 0 for status in ITEM_STATUSES}
    for item in items:
        status = str(item.get("status") or "pending")
        counts[status if status in counts else "pending"] += 1
    finished = counts["succeeded"] + counts["failed"] + counts["skipped"]
    return {"status": str(queue.get("status") or "paused"), "total": len(items), "finished": finished, **counts}


def recover_stale_items(
    queue: dict[str, Any],
    *,
    stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
) -> int:
    """Return abandoned running items to pending without losing their history."""
    recovered = 0
    for item in queue.get("items") or []:
        if item.get("status") != "running":
            continue
        heartbeat = item.get("heartbeat_at") or item.get("updated_at")
        if not _is_stale(heartbeat, stale_after_seconds=stale_after_seconds):
            continue
        item.update(
            {
                "status": "pending",
                "error": "任务心跳已超时，已自动恢复为待处理",
                "error_category": "stale_worker",
                "retryable": True,
                "updated_at": _utc_now(),
            }
        )
        recovered += 1
    return recovered


def create_or_refresh_queue(
    job_id: str,
    *,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
    reset: bool = False,
) -> dict[str, Any]:
    loaded = load_pdf_import_job(job_id, jobs_root)
    questions = [item for item in loaded["draft_payload"].get("questions") or [] if isinstance(item, dict)]
    path = _queue_path(job_id, jobs_root)
    existing = load_queue(job_id, jobs_root=jobs_root) if path.is_file() and not reset else {}
    existing_by_id = {str(item.get("source_item_id") or ""): item for item in existing.get("items") or []}
    items = []
    for index, question in enumerate(questions):
        source_item_id = str(question.get("source_item_id") or f"question_{index + 1:03d}")
        extra = question.get("extra") if isinstance(question.get("extra"), dict) else {}
        fingerprint = _question_fingerprint(question)
        old = existing_by_id.get(source_item_id) or {}
        preserve = old.get("fingerprint") == fingerprint and old.get("status") in ITEM_STATUSES
        recognition_status = str(question.get("recognition_status") or "")
        preserved_status = (
            "succeeded"
            if old.get("status") == "succeeded" or recognition_status == "ai_succeeded"
            else old.get("status") if preserve else "pending"
        )
        if preserved_status == "running":
            preserved_status = "pending"
        items.append(
            {
                "index": index,
                "source_item_id": source_item_id,
                "question_number": str(extra.get("question_number") or index + 1),
                "fingerprint": fingerprint,
                "status": preserved_status,
                "attempts": int(old.get("attempts") or 0) if preserve else 0,
                "error": str(old.get("error") or "") if preserve else "",
                "result": dict(old.get("result") or {}) if preserve else {},
                "updated_at": str(old.get("updated_at") or "") if preserve else "",
                "heartbeat_at": str(old.get("heartbeat_at") or "") if preserve else "",
                "error_category": str(old.get("error_category") or "") if preserve else "",
                "retryable": bool(old.get("retryable", False)) if preserve else False,
            }
        )
    for block in loaded["draft_payload"].get("unassigned_blocks") or []:
        if not isinstance(block, dict):
            continue
        task = _unassigned_page_task(block)
        source_item_id = task["source_item_id"]
        old = existing_by_id.get(source_item_id) or {}
        preserve = old.get("fingerprint") == task["fingerprint"] and old.get("status") in ITEM_STATUSES
        # A completed page task remains complete across payload refreshes. The
        # unassigned block can gain harmless metadata after AI generation;
        # that must not cause the same page request to run again.
        preserved_status = old.get("status") if (preserve or old.get("status") == "succeeded") else "pending"
        if preserved_status == "running":
            preserved_status = "pending"
        items.append(
            {
                "index": len(items),
                "source_item_id": source_item_id,
                "question_number": "",
                "page_number": task["page_number"],
                "kind": "unassigned_page",
                "fingerprint": task["fingerprint"],
                "status": preserved_status,
                "attempts": int(old.get("attempts") or 0) if preserve else 0,
                "error": str(old.get("error") or "") if preserve else "",
                "result": dict(old.get("result") or {}) if preserve else {},
                "updated_at": str(old.get("updated_at") or "") if preserve else "",
                "heartbeat_at": str(old.get("heartbeat_at") or "") if preserve else "",
                "error_category": str(old.get("error_category") or "") if preserve else "",
                "retryable": bool(old.get("retryable", False)) if preserve else False,
            }
        )
    queue = {
        "schema_version": 1,
        "job_id": job_id,
        "status": "paused" if existing.get("status") != "completed" else "completed",
        "created_at": existing.get("created_at") or _utc_now(),
        "started_at": existing.get("started_at") or "",
        "finished_at": existing.get("finished_at") or "",
        "elapsed_seconds": float(existing.get("elapsed_seconds") or 0),
        "current_page": int(existing.get("current_page") or 0),
        "total_pages": int(existing.get("total_pages") or 0),
        "pause_requested": bool(existing.get("pause_requested", False)),
        "heartbeat_at": str(existing.get("heartbeat_at") or ""),
        "last_error_category": str(existing.get("last_error_category") or ""),
        "updated_at": _utc_now(),
        "items": items,
    }
    if all(item["status"] in {"succeeded", "skipped"} for item in items) and items:
        queue["status"] = "completed"
    write_json(path, queue)
    return queue


def load_queue(job_id: str, *, jobs_root: str | Path = DEFAULT_JOBS_ROOT) -> dict[str, Any]:
    path = _queue_path(job_id, jobs_root)
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("job_id") != job_id:
        raise ValueError("AI 队列文件格式无效。")
    return payload


def set_queue_status(job_id: str, status: str, *, jobs_root: str | Path = DEFAULT_JOBS_ROOT) -> dict[str, Any]:
    if status not in QUEUE_STATUSES:
        raise ValueError(f"不支持 AI 队列状态：{status}")
    path = _queue_path(job_id, jobs_root)
    with _queue_lock(path):
        queue = load_queue(job_id, jobs_root=jobs_root) or create_or_refresh_queue(job_id, jobs_root=jobs_root)
        queue["status"] = status
        if status == "running" and not queue.get("started_at"):
            queue["started_at"] = _utc_now()
            queue["finished_at"] = ""
            queue["pause_requested"] = False
        elif status == "paused":
            queue["pause_requested"] = False
        elif status == "completed":
            queue["finished_at"] = _utc_now()
            queue["pause_requested"] = False
        queue["heartbeat_at"] = _utc_now()
        queue["updated_at"] = _utc_now()
        write_json(path, queue)
    return queue


def update_queue_progress(
    job_id: str,
    *,
    current_page: int | None = None,
    total_pages: int | None = None,
    elapsed_seconds: float | None = None,
    pause_requested: bool | None = None,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> dict[str, Any]:
    """Persist page progress so the UI can recover it after a rerun."""
    path = _queue_path(job_id, jobs_root)
    with _queue_lock(path):
        queue = load_queue(job_id, jobs_root=jobs_root) or create_or_refresh_queue(job_id, jobs_root=jobs_root)
        if current_page is not None:
            queue["current_page"] = max(0, int(current_page))
        if total_pages is not None:
            queue["total_pages"] = max(0, int(total_pages))
        if elapsed_seconds is not None:
            queue["elapsed_seconds"] = max(0.0, float(elapsed_seconds))
        if pause_requested is not None:
            queue["pause_requested"] = bool(pause_requested)
        queue["heartbeat_at"] = _utc_now()
        queue["updated_at"] = _utc_now()
        write_json(path, queue)
    return queue


def retry_failed_items(job_id: str, *, jobs_root: str | Path = DEFAULT_JOBS_ROOT) -> dict[str, Any]:
    path = _queue_path(job_id, jobs_root)
    with _queue_lock(path):
        queue = load_queue(job_id, jobs_root=jobs_root) or create_or_refresh_queue(job_id, jobs_root=jobs_root)
        for item in queue.get("items") or []:
            if item.get("status") == "failed" and item.get("retryable", True):
                item.update({"status": "pending", "error": "", "error_category": "", "updated_at": _utc_now()})
        queue["status"] = "paused"
        queue["updated_at"] = _utc_now()
        write_json(path, queue)
    return queue


def reset_queue_range(
    job_id: str,
    start_position: int,
    end_position: int,
    *,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> dict[str, Any]:
    path = _queue_path(job_id, jobs_root)
    with _queue_lock(path):
        queue = load_queue(job_id, jobs_root=jobs_root) or create_or_refresh_queue(job_id, jobs_root=jobs_root)
        start = max(1, int(start_position))
        end = max(start, int(end_position))
        for item in queue.get("items") or []:
            position = int(item.get("index") or 0) + 1
            if start <= position <= end:
                item.update({"status": "pending", "error": "", "error_category": "", "result": {}, "updated_at": _utc_now()})
        queue["status"] = "paused"
        queue["updated_at"] = _utc_now()
        write_json(path, queue)
    return queue


def next_queue_item(
    job_id: str,
    *,
    start_position: int | None = None,
    end_position: int | None = None,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> dict[str, Any]:
    path = _queue_path(job_id, jobs_root)
    with _queue_lock(path):
        queue = load_queue(job_id, jobs_root=jobs_root) or create_or_refresh_queue(job_id, jobs_root=jobs_root)
        recover_stale_items(queue)
        if queue.get("status") != "running":
            return {}
        for item in queue.get("items") or []:
            position = int(item.get("index") or 0) + 1
            if start_position is not None and position < int(start_position):
                continue
            if end_position is not None and position > int(end_position):
                continue
            if item.get("status") == "running":
                return dict(item)
            if item.get("status") == "pending":
                item["status"] = "running"
                item["attempts"] = int(item.get("attempts") or 0) + 1
                item["heartbeat_at"] = _utc_now()
                item["updated_at"] = _utc_now()
                queue["heartbeat_at"] = _utc_now()
                queue["updated_at"] = _utc_now()
                write_json(path, queue)
                return dict(item)
        if not any(item.get("status") in {"pending", "running"} for item in queue.get("items") or []):
            queue["status"] = "completed"
            queue["updated_at"] = _utc_now()
            write_json(path, queue)
        return {}


def _finish_queue_item_unlocked(
    job_id: str,
    source_item_id: str,
    *,
    result: dict[str, Any] | None = None,
    error: str = "",
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> dict[str, Any]:
    queue = load_queue(job_id, jobs_root=jobs_root)
    if not queue:
        raise FileNotFoundError("AI 队列尚未创建。")
    target = next((item for item in queue.get("items") or [] if item.get("source_item_id") == source_item_id), None)
    if target is None:
        raise KeyError(f"AI 队列题目不存在：{source_item_id}")
    target["status"] = "failed" if error else "succeeded"
    target["error"] = str(error or "")
    category, retryable = classify_queue_error(error) if error else ("", False)
    target["error_category"] = category
    target["retryable"] = retryable
    target["result"] = dict(result or {}) if not error else {}
    target["heartbeat_at"] = _utc_now()
    target["updated_at"] = _utc_now()
    items = [item for item in queue.get("items") or [] if isinstance(item, dict)]
    active_items = [item for item in items if item.get("status") in {"pending", "running"}]
    failed_items = [item for item in items if item.get("status") == "failed"]
    if not items or failed_items:
        queue["status"] = "paused"
    elif active_items:
        queue["status"] = str(queue.get("status") or "paused")
    else:
        queue["status"] = "completed"
    queue["last_error_category"] = category
    queue["heartbeat_at"] = _utc_now()
    queue["updated_at"] = _utc_now()
    write_json(_queue_path(job_id, jobs_root), queue)
    return queue


def finish_queue_item(
    job_id: str,
    source_item_id: str,
    *,
    result: dict[str, Any] | None = None,
    error: str = "",
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> dict[str, Any]:
    """Atomically persist one recognition result and update queue status."""
    path = _queue_path(job_id, jobs_root)
    with _queue_lock(path):
        return _finish_queue_item_unlocked(
            job_id,
            source_item_id,
            result=result,
            error=error,
            jobs_root=jobs_root,
        )


def skip_queue_item(
    job_id: str,
    source_item_id: str,
    *,
    reason: str,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> dict[str, Any]:
    """Mark a non-question page task as intentionally skipped."""
    path = _queue_path(job_id, jobs_root)
    with _queue_lock(path):
        queue = load_queue(job_id, jobs_root=jobs_root)
        if not queue:
            raise FileNotFoundError("AI queue does not exist")
        target = next((item for item in queue.get("items") or [] if item.get("source_item_id") == source_item_id), None)
        if target is None:
            raise KeyError(f"AI queue item does not exist: {source_item_id}")
        target.update(
            {
                "status": "skipped",
                "error": "",
                "error_category": "",
                "retryable": False,
                "result": {"skipped": True, "reason": str(reason or "")},
                "heartbeat_at": _utc_now(),
                "updated_at": _utc_now(),
            }
        )
        active_items = [item for item in queue.get("items") or [] if item.get("status") in {"pending", "running"}]
        queue["status"] = "paused" if active_items else "completed"
        queue["heartbeat_at"] = _utc_now()
        queue["updated_at"] = _utc_now()
        write_json(path, queue)
    return queue


def touch_queue_item(
    job_id: str,
    source_item_id: str,
    *,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> dict[str, Any]:
    """Refresh one item's heartbeat during a long-running recognition call."""
    path = _queue_path(job_id, jobs_root)
    with _queue_lock(path):
        queue = load_queue(job_id, jobs_root=jobs_root)
        if not queue:
            raise FileNotFoundError("AI queue does not exist")
        target = next((item for item in queue.get("items") or [] if item.get("source_item_id") == source_item_id), None)
        if target is None:
            raise KeyError(f"AI queue item does not exist: {source_item_id}")
        now = _utc_now()
        target["heartbeat_at"] = now
        target["updated_at"] = now
        queue["heartbeat_at"] = now
        queue["updated_at"] = now
        write_json(path, queue)
    return queue
