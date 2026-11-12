"""Durable, content-addressed storage for draft attachments.

Keep source filenames for TeX aliases and captions. Original task files are never
deleted, and existing managed objects are never overwritten.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from services.asset_service import file_hash
from services.database_service import BASE_DIR, resolve_database_path

PROJECT_ROOT = Path(BASE_DIR)


def draft_storage_root(db_path: str | None = None) -> Path:
    database = Path(resolve_database_path(db_path)).resolve()
    # Temporary databases outside the workspace get isolated test storage.
    if database.is_relative_to(PROJECT_ROOT.resolve()):
        return PROJECT_ROOT / "data" / "draft_assets"
    return database.parent / "draft_assets"


def resolve_draft_source(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def stored_draft_path(path: Path) -> str:
    resolved = path.resolve()
    if resolved.is_relative_to(PROJECT_ROOT.resolve()):
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    return resolved.as_posix()


def plan_draft_asset_storage(asset: dict, db_path: str | None = None) -> dict | None:
    """Plan only an existing attachment with unambiguous source/planned paths."""
    source_text = str(asset.get("source_path") or asset.get("path") or "").strip()
    if not source_text:
        return None
    source = resolve_draft_source(source_text)
    if not source.is_file():
        return None  # Preserve the existing validation of missing attachments.
    planned = str(asset.get("planned_file_path") or "").strip()
    if planned and resolve_draft_source(planned).resolve() != source.resolve():
        return None  # A distinct planned destination requires separate review.
    digest = file_hash(source)
    expected = str(asset.get("file_hash") or "").strip()
    if expected and expected.lower() != digest:
        raise ValueError("图片内容与登记哈希不一致，不能通过迁移覆盖原校验")
    root = draft_storage_root(db_path).resolve()
    target = root / digest[:2] / digest / source.name
    if not target.resolve().is_relative_to(root):
        raise ValueError("草稿资源目标超出稳定目录")
    if source.resolve() == target.resolve():
        return None
    return {"source": source, "target": target, "sha256": digest,
            "source_path": stored_draft_path(target),
            "planned_file_path": stored_draft_path(target) if planned else ""}


def copy_planned_draft_asset(plan: dict) -> None:
    """Publish a verified copy atomically; interruption cannot leave a partial object."""
    source, target, digest = plan["source"], plan["target"], plan["sha256"]
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if file_hash(target) != digest:
            raise ValueError("稳定资源目录存在内容冲突，拒绝覆盖")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".copy-", suffix=".tmp", dir=target.parent)
    temp = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, output)
            output.flush()
            os.fsync(output.fileno())
        if file_hash(temp) != digest:
            raise ValueError("复制期间来源内容变化，已取消迁移")
        # Link is only an atomic no-overwrite publication of our temporary copy.
        # It never links the task source to the durable object.
        try:
            os.link(temp, target)
        except FileExistsError:
            if file_hash(target) != digest:
                raise ValueError("稳定资源并发写入冲突")
    finally:
        temp.unlink(missing_ok=True)


def stabilize_draft_asset(asset: dict, db_path: str | None = None) -> dict:
    """Return a new mapping; do not mutate caller payloads or their source file."""
    plan = plan_draft_asset_storage(asset, db_path)
    if plan is None:
        return dict(asset)
    copy_planned_draft_asset(plan)
    return {**asset, "source_path": plan["source_path"],
            "planned_file_path": plan["planned_file_path"], "file_hash": plan["sha256"]}
