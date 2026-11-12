"""Verified immutable PDF objects with compatible job-local source.pdf paths."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PDF_ROOT = PROJECT_ROOT / "data" / "source_pdfs"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_object_path(digest: str, root: str | Path) -> Path:
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("PDF 来源 SHA-256 格式无效")
    return Path(root) / digest[:2] / (digest + ".pdf")


def publish_object(source: Path, digest: str, root: str | Path) -> Path:
    """Copy bytes independently of the caller's writable source."""
    target = source_object_path(digest, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256_file(target) != digest:
            raise ValueError("来源存储存在哈希冲突，拒绝覆盖")
        return target
    fd, name = tempfile.mkstemp(prefix=".publish-", suffix=".tmp", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, output)
            output.flush()
            os.fsync(output.fileno())
        if sha256_file(temporary) != digest:
            raise ValueError("来源在复制期间发生变化")
        try:
            os.link(temporary, target)
        except FileExistsError:
            if sha256_file(target) != digest:
                raise ValueError("来源存储并发冲突")
    finally:
        temporary.unlink(missing_ok=True)
    return target


def protect_source(path: Path) -> None:
    path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def store_job_source(source: Path, destination: Path, *, root: Path) -> dict:
    """Keep the existing pathname, read-only, with a cross-volume copy fallback."""
    if destination.exists():
        raise FileExistsError(destination)
    digest = sha256_file(source)
    obj = publish_object(source, digest, root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(obj, destination)
        mode = "hardlink"
    except OSError:
        # Destination is new. No pre-existing task file is overwritten.
        with destination.open("xb") as output, obj.open("rb") as incoming:
            shutil.copyfileobj(incoming, output)
        if sha256_file(destination) != digest:
            raise ValueError("任务来源副本校验失败")
        mode = "copy"
    protect_source(obj)
    protect_source(destination)
    return {"sha256": digest, "object": obj, "mode": mode}


def storage_root_for_jobs(jobs_root: Path) -> Path:
    if jobs_root.resolve().is_relative_to(PROJECT_ROOT.resolve()):
        return PROJECT_ROOT / "data" / "source_pdfs"
    return jobs_root.parent / "source_pdfs"
