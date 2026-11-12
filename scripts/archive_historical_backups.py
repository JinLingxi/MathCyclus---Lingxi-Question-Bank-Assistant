"""Copy historical .backups into a verified cold archive; never prune originals."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_backup_retention import sha256_file, inspect_snapshot

MANIFEST = "_archive_manifest.json"


def inventory(project: Path) -> list[dict]:
    base = project / ".backups"
    if base.is_symlink() or base.is_junction():
        raise ValueError("不归档符号链接或目录联接")
    entries = []
    for directory, dirs, files in os.walk(base, followlinks=False):
        for name in dirs:
            candidate = Path(directory) / name
            if candidate.is_symlink() or candidate.is_junction():
                raise ValueError("备份树含链接，需单独核对")
        for name in sorted(files):
            path = Path(directory) / name
            if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
                raise ValueError("备份路径超出范围")
            info = path.stat()
            if path.name.endswith(("-wal", "-shm")):
                raise ValueError("含 SQLite sidecar 的备份需先做一致性快照")
            entries.append({"path": path.relative_to(base).as_posix(),
                            "bytes": info.st_size, "mtime_ns": info.st_mtime_ns,
                            "sha256": sha256_file(path)})
    return sorted(entries, key=lambda row: row["path"])


def build_archive(project: Path, target: Path, *, apply: bool = False) -> dict:
    base = project / ".backups"
    if target.resolve().is_relative_to(base.resolve()):
        raise ValueError("归档输出不能位于被归档目录")
    if target.exists():
        raise FileExistsError(target)
    entries = inventory(project)
    report = {"mode": "apply" if apply else "dry_run", "files": len(entries),
              "original_bytes": sum(item["bytes"] for item in entries),
              "source_directory": ".backups", "output": str(target),
              "deleted_files": 0, "original_paths_retained": True}
    if not apply:
        return {**report, "entries": entries}
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".archive-", suffix=".tmp", dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    manifest = {"version": 1, "created_at": datetime.now().astimezone().isoformat(),
                "source_directory": ".backups", "entries": entries}
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
            for entry in entries:
                source = base / entry["path"]
                if sha256_file(source) != entry["sha256"]:
                    raise ValueError("备份在归档期间发生变化")
                archive.write(source, entry["path"])
        report.update(verify_archive(temporary))
        # Recheck originals before publication, retaining every original path.
        if inventory(project) != entries:
            raise ValueError("归档期间备份目录发生变化，取消发布")
        # No overwrite, same filesystem publication.
        os.link(temporary, target)
        report["archive_bytes"] = target.stat().st_size
        report["archive_sha256"] = sha256_file(target)
        report["compression_ratio"] = round(report["archive_bytes"] / max(1, report["original_bytes"]), 4)
        return report
    finally:
        temporary.unlink(missing_ok=True)


def verify_archive(path: Path) -> dict:
    restored, database_ok, database_review = 0, 0, []
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory(prefix="backup_restore_check_") as directory:
        manifest = json.loads(archive.read(MANIFEST))
        if manifest.get("version") != 1:
            raise ValueError("不支持的归档格式")
        entries = manifest["entries"]
        names = [entry["path"] for entry in entries]
        if (len(set(names)) != len(names) or len(archive.namelist()) != len(names) + 1
                or set(archive.namelist()) != {MANIFEST, *names}):
            raise ValueError("归档文件清单不一致")
        for index, entry in enumerate(entries):
            relative = Path(entry["path"])
            if relative.is_absolute() or ".." in relative.parts or ":" in entry["path"] or "\\" in entry["path"]:
                raise ValueError("不安全的归档路径")
            # Restore one file at a time in an isolated temp directory. Never
            # extract to the working backup paths.
            restored_path = Path(directory) / (str(index) + relative.suffix)
            with archive.open(entry["path"]) as incoming, restored_path.open("xb") as output:
                while chunk := incoming.read(1024 * 1024):
                    output.write(chunk)
            if restored_path.stat().st_size != entry["bytes"] or sha256_file(restored_path) != entry["sha256"]:
                raise ValueError("恢复后的文件字节与原备份不同")
            if relative.suffix == ".sqlite3":
                status = inspect_snapshot(restored_path)
                if status["status"] == "ok":
                    database_ok += 1
                else:
                    database_review.append({"path": entry["path"], "snapshot": status})
            restored_path.unlink()
            restored += 1
    if database_review:
        raise ValueError("恢复后数据库校验未通过：" + json.dumps(database_review, ensure_ascii=False))
    return {"verified_restored_files": restored, "verified_restored_databases": database_ok,
            "verification": "sha256_and_sqlite_quick_check", "restore_destination": "isolated_temporary_directory"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    if args.verify:
        result = verify_archive(args.verify)
    else:
        target = args.archive or ROOT / "data" / "backups" / "cold_archives" / (
            "historical_backups_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".zip")
        result = build_archive(ROOT, target, apply=args.apply)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps({key: value for key, value in result.items() if key != "entries"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
