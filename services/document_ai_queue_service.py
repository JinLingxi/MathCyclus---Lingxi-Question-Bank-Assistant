"""Persistent page-level AI recognition queue for document import jobs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.pdf_import_service import DEFAULT_JOBS_ROOT, load_pdf_import_job, resolve_job_dir, write_json


QUEUE_FILE_NAME = "ai_refine_queue.json"
QUEUE_STATUSES = {"paused", "running", "completed"}
ITEM_STATUSES = {"pending", "running", "succeeded", "failed", "skipped"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
        preserved_status = old.get("status") if preserve else "pending"
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
    queue["updated_at"] = _utc_now()
    write_json(_queue_path(job_id, jobs_root), queue)
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
    queue = load_queue(job_id, jobs_root=jobs_root) or create_or_refresh_queue(job_id, jobs_root=jobs_root)
    if current_page is not None:
        queue["current_page"] = max(0, int(current_page))
    if total_pages is not None:
        queue["total_pages"] = max(0, int(total_pages))
    if elapsed_seconds is not None:
        queue["elapsed_seconds"] = max(0.0, float(elapsed_seconds))
    if pause_requested is not None:
        queue["pause_requested"] = bool(pause_requested)
    queue["updated_at"] = _utc_now()
    write_json(_queue_path(job_id, jobs_root), queue)
    return queue


def retry_failed_items(job_id: str, *, jobs_root: str | Path = DEFAULT_JOBS_ROOT) -> dict[str, Any]:
    queue = load_queue(job_id, jobs_root=jobs_root) or create_or_refresh_queue(job_id, jobs_root=jobs_root)
    for item in queue.get("items") or []:
        if item.get("status") == "failed":
            item.update({"status": "pending", "error": "", "updated_at": _utc_now()})
    queue["status"] = "paused"
    queue["updated_at"] = _utc_now()
    write_json(_queue_path(job_id, jobs_root), queue)
    return queue


def reset_queue_range(
    job_id: str,
    start_position: int,
    end_position: int,
    *,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> dict[str, Any]:
    queue = load_queue(job_id, jobs_root=jobs_root) or create_or_refresh_queue(job_id, jobs_root=jobs_root)
    start = max(1, int(start_position))
    end = max(start, int(end_position))
    for item in queue.get("items") or []:
        position = int(item.get("index") or 0) + 1
        if start <= position <= end:
            item.update({"status": "pending", "error": "", "result": {}, "updated_at": _utc_now()})
    queue["status"] = "paused"
    queue["updated_at"] = _utc_now()
    write_json(_queue_path(job_id, jobs_root), queue)
    return queue


def next_queue_item(
    job_id: str,
    *,
    start_position: int | None = None,
    end_position: int | None = None,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> dict[str, Any]:
    queue = load_queue(job_id, jobs_root=jobs_root) or create_or_refresh_queue(job_id, jobs_root=jobs_root)
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
            item["updated_at"] = _utc_now()
            queue["updated_at"] = _utc_now()
            write_json(_queue_path(job_id, jobs_root), queue)
            return dict(item)
    if not any(item.get("status") in {"pending", "running"} for item in queue.get("items") or []):
        queue["status"] = "completed"
        queue["updated_at"] = _utc_now()
        write_json(_queue_path(job_id, jobs_root), queue)
    return {}


def finish_queue_item(
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
    target["result"] = dict(result or {}) if not error else {}
    target["updated_at"] = _utc_now()
    unfinished = [item for item in queue.get("items") or [] if item.get("status") in {"pending", "running"}]
    queue["status"] = "completed" if not unfinished else str(queue.get("status") or "paused")
    queue["updated_at"] = _utc_now()
    write_json(_queue_path(job_id, jobs_root), queue)
    return queue
