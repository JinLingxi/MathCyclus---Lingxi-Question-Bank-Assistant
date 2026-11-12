"""Journaled PDF deduplication preserving every existing task pathname."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import time
import zipfile
from pathlib import Path

from services.source_pdf_storage_service import (
    sha256_file, publish_object, protect_source, source_object_path,
)


def write_manifest(path: Path, value: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=".journal-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.1 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def _inside(root: Path, path: Path) -> None:
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("来源路径超出指定工作区")
    if path.is_symlink() or path.is_junction():
        raise ValueError("不迁移符号链接或目录联接")


def plan_source_pdf_migration(project: Path) -> dict:
    import fitz

    imports = project / "data" / "imports"
    storage = project / "data" / "source_pdfs"
    groups, skipped = {}, []
    paths = sorted(imports.rglob("source.pdf"))
    for source in paths:
        _inside(imports, source)
        manifest_path = source.parent / "job_manifest.json"
        if not source.is_file() or not manifest_path.is_file():
            skipped.append({"path": source.relative_to(project).as_posix(), "reason": "missing source or job manifest"})
            continue
        metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
        digest = sha256_file(source)
        expected = str((metadata.get("source") or {}).get("sha256") or "")
        if not expected or digest != expected:
            raise ValueError("任务来源哈希缺失或不一致：" + str(source))
        obj = source_object_path(digest, storage)
        if obj.exists() and os.path.samefile(source, obj):
            if source.stat().st_mode & stat.S_IWUSR:
                raise ValueError("共享来源未处于只读状态")
            continue
        info = source.stat()
        if digest not in groups:
            with fitz.open(source) as document:
                if document.needs_pass or document.page_count == 0:
                    raise ValueError("来源 PDF 无法直接读取")
                groups[digest] = {"sha256": digest, "size": info.st_size, "page_count": document.page_count,
                                  "representative": source.relative_to(project).as_posix(), "files": []}
        groups[digest]["files"].append({
            "path": source.relative_to(project).as_posix(), "mode": stat.S_IMODE(info.st_mode),
            "mtime_ns": info.st_mtime_ns, "manifest_sha256": sha256_file(manifest_path),
        })
    return {"version": 1, "project": str(project.resolve()), "groups": list(groups.values()),
            "skipped": skipped, "state": "dry_run", "deleted_task_paths": 0}


def _unchanged_source(project, group, item):
    path = project / item["path"]
    _inside(project / "data" / "imports", path)
    if path.name != "source.pdf" or sha256_file(path) != group["sha256"]:
        raise ValueError("来源在预演后发生变化")
    if sha256_file(path.parent / "job_manifest.json") != item["manifest_sha256"]:
        raise ValueError("任务清单在预演后发生变化")
    return path


def apply_source_pdf_migration(plan: dict, journal: Path, backup: Path) -> dict:
    project = Path(plan["project"])
    storage = project / "data" / "source_pdfs"
    if journal.exists() or backup.exists():
        raise FileExistsError("迁移日志或备份路径已存在")
    journal.parent.mkdir(parents=True, exist_ok=True)
    backup.parent.mkdir(parents=True, exist_ok=True)
    # Store one independent original per unique digest before touching any path.
    with zipfile.ZipFile(backup, "x", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("plan.json", json.dumps(plan, ensure_ascii=False, indent=2))
        for group in plan["groups"]:
            for item in group["files"]:
                _unchanged_source(project, group, item)
        for group in plan["groups"]:
            archive.write(project / group["representative"], group["sha256"] + ".pdf")
    with zipfile.ZipFile(backup) as archive:
        for group in plan["groups"]:
            import hashlib
            with archive.open(group["sha256"] + ".pdf") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            if digest != group["sha256"]:
                raise ValueError("来源恢复包验证失败")
    result = {**plan, "state": "applying", "backup": str(backup.resolve()), "operations": []}
    write_manifest(journal, result)
    try:
        for group in plan["groups"]:
            representative = project / group["representative"]
            obj = publish_object(representative, group["sha256"], storage)
            if obj.stat().st_dev != representative.stat().st_dev:
                raise ValueError("不在同一卷，拒绝执行历史去重")
            if sha256_file(obj) != group["sha256"]:
                raise ValueError("集中来源对象验证失败")
            protect_source(obj)
            for item in group["files"]:
                path = _unchanged_source(project, group, item)
                operation = {**item, "sha256": group["sha256"], "state": "prepared"}
                result["operations"].append(operation)
                write_manifest(journal, result)
                temporary = path.with_name(".source-link-" + group["sha256"][:16] + ".tmp")
                if temporary.exists():
                    raise FileExistsError(temporary)
                try:
                    os.link(obj, temporary)
                    if os.path.samefile(path, obj):
                        raise ValueError("任务路径已由其他操作迁移")
                    # Windows refuses replacing a read-only path. Clear the
                    # shared read-only bit only for the atomic replace window;
                    # callers must stop the app during migration.
                    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
                    try:
                        os.replace(temporary, path)
                    except Exception:
                        raise
                    finally:
                        protect_source(obj)
                    protect_source(path)
                finally:
                    if temporary.exists():
                        # Remove only this new link; do not change shared flags.
                        temporary.unlink()
                if not os.path.samefile(path, obj) or sha256_file(path) != group["sha256"]:
                    raise ValueError("迁移后来源校验失败")
                operation["state"] = "applied"
                write_manifest(journal, result)
        result["state"] = "complete"
        write_manifest(journal, result)
        return result
    except Exception as exc:
        result["state"] = "interrupted"
        result["error"] = str(exc)
        write_manifest(journal, result)
        raise


def rollback_source_pdf_migration(journal: Path) -> dict:
    result = json.loads(journal.read_text(encoding="utf-8"))
    project = Path(result["project"])
    # Validate all preconditions before restoring a single path.
    for item in result["operations"]:
        path = project / item["path"]
        _inside(project / "data" / "imports", path)
        if not path.is_file():
            raise FileNotFoundError(path)
        if sha256_file(path) != item["sha256"]:
            raise ValueError("迁移后来源已被修改，拒绝覆盖")
    with zipfile.ZipFile(result["backup"]) as archive:
        import hashlib
        for digest in {item["sha256"] for item in result["operations"]}:
            with archive.open(digest + ".pdf") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != digest:
                    raise ValueError("恢复包哈希不一致")
        for item in result["operations"]:
            if item["state"] == "rolled_back":
                continue
            path = project / item["path"]
            fd, name = tempfile.mkstemp(prefix=".restore-", suffix=".tmp", dir=path.parent)
            temporary = Path(name)
            obj = source_object_path(item["sha256"], project / "data" / "source_pdfs")
            try:
                with os.fdopen(fd, "wb") as output, archive.open(item["sha256"] + ".pdf") as source:
                    shutil.copyfileobj(source, output)
                if sha256_file(temporary) != item["sha256"]:
                    raise ValueError("恢复副本校验失败")
                # Windows readonly is shared by all links. Re-protect remaining
                # links immediately after replacing this one with an independent copy.
                path.chmod(stat.S_IRUSR | stat.S_IWUSR)
                try:
                    os.replace(temporary, path)
                finally:
                    if obj.exists():
                        protect_source(obj)
                path.chmod(item["mode"])
                os.utime(path, ns=(item["mtime_ns"], item["mtime_ns"]))
            finally:
                temporary.unlink(missing_ok=True)
            item["state"] = "rolled_back"
            write_manifest(journal, result)
    result["state"] = "rolled_back"
    write_manifest(journal, result)
    return result
