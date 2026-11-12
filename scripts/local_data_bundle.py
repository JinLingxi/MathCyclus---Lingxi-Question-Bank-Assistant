"""Export, inspect, and restore local MathCyclus data bundles.

The bundle is for moving a user's private data between machines.  It is not a
GitHub release artifact and should normally be written under ``data/backups/``,
which is ignored by Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import PurePosixPath, PureWindowsPath
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "mathcyclus_local_bundle_manifest.json"

DEFAULT_ITEMS = [
    ("formal_database", "data/mathcyclus.sqlite3"),
    ("local_preferences", "data/local_preferences.json"),
    ("question_assets", "assets/questions"),
    ("draft_assets", "data/draft_assets"),
    ("source_pdfs", "data/source_pdfs"),
    ("csv_cache", "utils/题库索引表.csv"),
]

OPTIONAL_ITEMS = {
    "ingestion": ("ingestion_tasks", "data/imports"),
    "legacy_tex": ("legacy_tex", "chapters"),
    "reports": ("reports", "reports"),
    "exports": ("exports", "exports"),
}

RESTORE_ALLOWED_EXACT = {
    "data/mathcyclus.sqlite3",
    "data/local_preferences.json",
    "utils/题库索引表.csv",
}

RESTORE_ALLOWED_PREFIXES = (
    "data/imports/",
    "data/draft_assets/",
    "data/source_pdfs/",
    "assets/questions/",
    "chapters/",
    "reports/",
    "exports/",
)


@dataclass(frozen=True)
class BundleItem:
    kind: str
    relative_path: str
    source_path: Path
    size: int
    sha256: str


def relative_to_root(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_project_path(project_root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def ensure_inside_project(project_root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError(f"路径不在项目目录内：{path}") from exc


def safe_zip_relative_path(path: str) -> str:
    normalized = str(path or "").replace("\\", "/")
    if (not normalized or normalized.startswith("/") or "\x00" in normalized
            or ":" in normalized or ".." in PurePosixPath(normalized).parts
            or PureWindowsPath(normalized).drive
            or any(part.rstrip(" .") != part or part in {"", "."} for part in normalized.split("/"))):
        raise ValueError(f"非法压缩包路径：{path}")
    if Path(normalized).is_absolute():
        raise ValueError(f"压缩包路径不能是绝对路径：{path}")
    return normalized


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def database_schema_version(path: Path) -> int:
    """Read the schema version without importing the application's database layer."""
    if not path.is_file():
        return 0
    try:
        conn = sqlite3.connect(path)
        try:
            row = conn.execute(
                "SELECT value FROM app_meta WHERE key = 'schema_version'"
            ).fetchone()
        finally:
            conn.close()
        raw = str(row[0] if row else "").strip()
        return int(raw) if raw.isdigit() else 0
    except (OSError, sqlite3.Error, ValueError):
        return 0


def supported_schema_version(project_root: Path) -> int:
    """Return the highest migration shipped with this source checkout."""
    migrations_dir = project_root / "db" / "migrations"
    versions = []
    for path in migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"):
        try:
            versions.append(int(path.name[:4]))
        except ValueError:
            continue
    if versions:
        return max(versions)
    return database_schema_version(project_root / "db" / "schema.sql")


def iter_files(path: Path) -> Iterable[Path]:
    if path.is_symlink() or path.is_junction():
        raise ValueError(f"迁移包不支持目录链接：{path}")
    if path.is_file():
        yield path
        return
    if not path.exists():
        return
    for directory, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if name != "__pycache__"]
        for name in dirs + files:
            item = Path(directory) / name
            if item.is_symlink() or item.is_junction():
                raise ValueError(f"迁移包不支持文件/目录链接：{item}")
        for name in sorted(files):
            item = Path(directory) / name
            if name.endswith(("-wal", "-shm")):
                continue
            yield item


def collect_items(
    project_root: Path,
    *,
    include_legacy_tex: bool = False,
    include_reports: bool = False,
    include_exports: bool = False,
    include_ingestion: bool = False,
) -> tuple[list[BundleItem], list[dict[str, str]]]:
    specs = list(DEFAULT_ITEMS)
    if include_ingestion:
        specs.append(OPTIONAL_ITEMS["ingestion"])
    if include_legacy_tex:
        specs.append(OPTIONAL_ITEMS["legacy_tex"])
    if include_reports:
        specs.append(OPTIONAL_ITEMS["reports"])
    if include_exports:
        specs.append(OPTIONAL_ITEMS["exports"])

    items: list[BundleItem] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for kind, relative in specs:
        source = resolve_project_path(project_root, relative)
        ensure_inside_project(project_root, source)
        if not source.exists():
            skipped.append({"kind": kind, "path": relative, "reason": "missing"})
            continue
        for file_path in iter_files(source):
            ensure_inside_project(project_root, file_path)
            rel = safe_zip_relative_path(relative_to_root(file_path, project_root))
            if file_path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
                wal = file_path.with_name(file_path.name + "-wal")
                if wal.exists() and wal.stat().st_size and rel != "data/mathcyclus.sqlite3":
                    raise ValueError(f"任务数据库含未合并 WAL，需先做一致性快照：{rel}")
            if rel in seen:
                continue
            seen.add(rel)
            items.append(
                BundleItem(
                    kind=kind,
                    relative_path=rel,
                    source_path=file_path,
                    size=file_path.stat().st_size,
                    sha256=file_sha256(file_path),
                )
            )
    return items, skipped


def default_output_path(project_root: Path, stamp: str) -> Path:
    return project_root / "data" / "backups" / f"mathcyclus_local_bundle_{stamp}.zip"


def make_manifest(
    project_root: Path,
    output_path: Path,
    items: list[BundleItem],
    skipped: list[dict[str, str]],
    *,
    include_legacy_tex: bool,
    include_reports: bool,
    include_exports: bool,
    schema_version: int,
    supported_version: int,
    include_ingestion: bool = False,
) -> dict[str, Any]:
    counts_by_kind: dict[str, int] = {}
    bytes_by_kind: dict[str, int] = {}
    for item in items:
        counts_by_kind[item.kind] = counts_by_kind.get(item.kind, 0) + 1
        bytes_by_kind[item.kind] = bytes_by_kind.get(item.kind, 0) + item.size
    return {
        "format": "mathcyclus-local-data-bundle",
        "format_version": 1,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_root_at_export": str(project_root),
        "output": relative_to_root(output_path, project_root),
        "contains_personal_data": True,
        "intended_for_git": False,
        "schema_version": int(schema_version or 0),
        "supported_schema_version_at_export": int(supported_version or 0),
        "include_legacy_tex": include_legacy_tex,
        "include_reports": include_reports,
        "include_exports": include_exports,
        "include_ingestion": include_ingestion,
        "restore_scope": "local_data_with_ingestion_tasks" if include_ingestion else "local_data",
        "portability_note": "Absolute paths in task payloads are preserved; relocation to another project root requires a separate path migration.",
        "item_count": len(items),
        "total_bytes": sum(item.size for item in items),
        "counts_by_kind": counts_by_kind,
        "bytes_by_kind": bytes_by_kind,
        "skipped": skipped,
        "items": [
            {
                "kind": item.kind,
                "path": item.relative_path,
                "size": item.size,
                "sha256": item.sha256,
            }
            for item in items
        ],
    }


def export_bundle(
    *,
    project_root: str | Path = PROJECT_ROOT,
    output: str | Path | None = None,
    include_legacy_tex: bool = False,
    include_reports: bool = False,
    include_exports: bool = False,
    include_ingestion: bool = False,
    dry_run: bool = False,
    stamp: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    safe_stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = resolve_project_path(root, output) if output else default_output_path(root, safe_stamp)
    ensure_inside_project(root, output_path)
    if output_path.exists() and not dry_run:
        raise FileExistsError(output_path)

    items, skipped = collect_items(
        root,
        include_legacy_tex=include_legacy_tex,
        include_reports=include_reports,
        include_exports=include_exports,
        include_ingestion=include_ingestion,
    )
    output_relative = relative_to_root(output_path, root)
    items = [item for item in items if item.relative_path != output_relative]
    database_path = root / "data" / "mathcyclus.sqlite3"
    schema_version = database_schema_version(database_path)
    supported_version = supported_schema_version(root)
    manifest = make_manifest(
        root,
        output_path,
        items,
        skipped,
        include_legacy_tex=include_legacy_tex,
        include_reports=include_reports,
        include_exports=include_exports,
        schema_version=schema_version,
        supported_version=supported_version,
        include_ingestion=include_ingestion,
    )

    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="bundle_snapshot_") as workspace:
            staged_items = []
            for index, item in enumerate(items):
                if item.relative_path == "data/mathcyclus.sqlite3":
                    snapshot = Path(workspace) / f"{index}.sqlite3"
                    source_conn = sqlite3.connect(item.source_path.resolve().as_uri() + "?mode=ro", uri=True)
                    target_conn = sqlite3.connect(snapshot)
                    try:
                        source_conn.backup(target_conn)
                        if target_conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                            raise ValueError("数据库快照校验失败")
                    finally:
                        target_conn.close()
                        source_conn.close()
                    staged_items.append(BundleItem(item.kind, item.relative_path, snapshot,
                                                   snapshot.stat().st_size, file_sha256(snapshot)))
                else:
                    staged_items.append(item)
            manifest = make_manifest(root, output_path, staged_items, skipped,
                include_legacy_tex=include_legacy_tex, include_reports=include_reports,
                include_exports=include_exports, include_ingestion=include_ingestion,
                schema_version=schema_version, supported_version=supported_version)
            temporary = output_path.parent / (output_path.name + "." + os.urandom(8).hex() + ".tmp")
            try:
                with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
                    for item in staged_items:
                        with item.source_path.open("rb") as source, archive.open(item.relative_path, "w", force_zip64=True) as target:
                            digest = hashlib.sha256()
                            size = 0
                            while chunk := source.read(1024 * 1024):
                                target.write(chunk)
                                digest.update(chunk)
                                size += len(chunk)
                        if digest.hexdigest() != item.sha256 or size != item.size:
                            raise ValueError("打包期间文件内容发生变化：" + item.relative_path)
                os.link(temporary, output_path)
            finally:
                temporary.unlink(missing_ok=True)
        manifest["bundle_sha256"] = file_sha256(output_path)
        manifest["bundle_size"] = output_path.stat().st_size
    else:
        manifest["bundle_sha256"] = ""
        manifest["bundle_size"] = 0
    manifest["dry_run"] = dry_run
    return manifest


def read_manifest(bundle_path: str | Path) -> dict[str, Any]:
    path = Path(bundle_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"迁移包不存在：{path}")
    with zipfile.ZipFile(path, "r") as archive:
        if MANIFEST_NAME not in archive.namelist():
            raise ValueError(f"迁移包缺少清单：{MANIFEST_NAME}")
        with archive.open(MANIFEST_NAME) as file_obj:
            manifest = json.loads(file_obj.read().decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("迁移包清单必须是 JSON 对象")
    if manifest.get("format") != "mathcyclus-local-data-bundle":
        raise ValueError(f"不支持的迁移包格式：{manifest.get('format')}")
    if int(manifest.get("format_version") or 0) != 1:
        raise ValueError(f"不支持的迁移包版本：{manifest.get('format_version')}")
    if not isinstance(manifest.get("items"), list):
        raise ValueError("迁移包清单缺少 items 数组")
    return manifest


def backup_existing_database(project_root: Path, database_path: Path) -> str:
    """Create a consistent SQLite backup before an overwrite restore."""
    backup_dir = project_root / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"mathcyclus_before_restore_{stamp}.sqlite3"
    suffix = 1
    while backup_path.exists():
        backup_path = backup_dir / f"mathcyclus_before_restore_{stamp}_{suffix}.sqlite3"
        suffix += 1
    source_conn = sqlite3.connect(database_path)
    target_conn = sqlite3.connect(backup_path)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()
    return backup_path.relative_to(project_root).as_posix()


def inspect_bundle(bundle_path: str | Path) -> dict[str, Any]:
    path = Path(bundle_path).resolve()
    manifest = read_manifest(path)
    return {
        "status": "ok",
        "bundle": str(path),
        "bundle_size": path.stat().st_size,
        "bundle_sha256": file_sha256(path),
        "format": manifest.get("format"),
        "format_version": manifest.get("format_version"),
        "created_at": manifest.get("created_at"),
        "item_count": manifest.get("item_count", 0),
        "total_bytes": manifest.get("total_bytes", 0),
        "counts_by_kind": manifest.get("counts_by_kind", {}),
        "contains_personal_data": manifest.get("contains_personal_data", True),
        "intended_for_git": manifest.get("intended_for_git", False),
        "schema_version": manifest.get("schema_version", 0),
        "supported_schema_version_at_export": manifest.get("supported_schema_version_at_export", 0),
    }


def is_restore_allowed(relative_path: str) -> bool:
    rel = safe_zip_relative_path(relative_path)
    if rel in RESTORE_ALLOWED_EXACT:
        return True
    return any(rel.startswith(prefix) for prefix in RESTORE_ALLOWED_PREFIXES)


def restore_bundle(
    *,
    project_root: str | Path = PROJECT_ROOT,
    bundle: str | Path,
    apply: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    bundle_path = Path(bundle).resolve()
    if not bundle_path.exists():
        raise FileNotFoundError(f"迁移包不存在：{bundle_path}")

    restored: list[str] = []
    conflicts: list[str] = []
    skipped: list[dict[str, str]] = []
    blocked: list[str] = []

    with zipfile.ZipFile(bundle_path, "r") as archive:
        names = archive.namelist()
        if MANIFEST_NAME not in names:
            raise ValueError(f"迁移包缺少清单：{MANIFEST_NAME}")

        manifest = read_manifest(bundle_path)
        bundle_schema_version = int(manifest.get("schema_version") or 0)
        supported_version = supported_schema_version(root)
        if bundle_schema_version > supported_version:
            blocked.append(
                f"迁移包 schema version {bundle_schema_version} 高于当前程序支持的 {supported_version}，请先更新程序。"
            )
        target_database = root / "data" / "mathcyclus.sqlite3"
        target_schema_version = database_schema_version(target_database)
        manifest_items = {
            safe_zip_relative_path(str(item.get("path") or "")): item
            for item in manifest.get("items", [])
            if item.get("path")
        }
        listed_items = manifest.get("items", [])
        if len(manifest_items) != len(listed_items):
            blocked.append("迁移包清单包含重复或空路径")
        if len(set(names)) != len(names):
            blocked.append("迁移包包含重复 ZIP 路径")
        # Validate everything before any write, even for --overwrite. This also
        # makes dry-run verify bytes rather than merely list destinations.
        preflight_conflicts = []
        for name in names:
            if name == MANIFEST_NAME or name.endswith("/"):
                continue
            try:
                rel = safe_zip_relative_path(name)
                if not is_restore_allowed(rel):
                    continue
                item = manifest_items.get(rel)
                if not item:
                    blocked.append(f"bundle manifest missing file: {rel}")
                    continue
                target = root / rel
                ensure_inside_project(root, target)
                cursor = target
                while cursor != root:
                    if cursor.is_symlink() or cursor.is_junction():
                        raise ValueError(f"恢复目标包含链接：{rel}")
                    cursor = cursor.parent
                if target.exists() and not overwrite:
                    preflight_conflicts.append(rel)
                digest = hashlib.sha256()
                size = 0
                with archive.open(name) as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                if size != int(item.get("size", -1)) or digest.hexdigest() != item.get("sha256"):
                    blocked.append(f"bundle checksum validation failed: {rel}")
                if rel == "data/mathcyclus.sqlite3":
                    with tempfile.TemporaryDirectory(prefix="restore_db_preflight_") as directory:
                        db_copy = Path(directory) / "snapshot.sqlite3"
                        with archive.open(name) as source, db_copy.open("xb") as output:
                            shutil.copyfileobj(source, output)
                        check = sqlite3.connect(db_copy.as_uri() + "?mode=ro&immutable=1", uri=True)
                        try:
                            if check.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                                blocked.append("SQLite preflight validation failed")
                        finally:
                            check.close()
            except (ValueError, OSError, sqlite3.Error, zipfile.BadZipFile) as exc:
                blocked.append(str(exc))

        for rel, item in manifest_items.items():
            if not is_restore_allowed(rel):
                continue
            if rel not in names:
                blocked.append(f"bundle manifest item missing from archive: {rel}")
            if int(item.get("size", -1)) < 0 or not str(item.get("sha256") or ""):
                blocked.append(f"bundle manifest item missing checksum: {rel}")

        if blocked or preflight_conflicts:
            return {
                "status": "blocked", "dry_run": not apply, "bundle": str(bundle_path),
                "project_root": str(root), "restored_count": 0,
                "conflict_count": len(preflight_conflicts), "skipped_count": 0,
                "blocked_count": len(blocked), "restored": [], "conflicts": preflight_conflicts[:80],
                "skipped": [], "blocked": blocked[:80], "overwrite": overwrite,
                "database_backup": "", "bundle_schema_version": bundle_schema_version,
                "target_schema_version": target_schema_version, "supported_schema_version": supported_version,
                "migration_needed_after_restore": False, "deletes_files": False,
            }

        database_backup = ""
        database_target = (root / "data" / "mathcyclus.sqlite3").resolve()
        if apply and overwrite and database_target.is_file() and "data/mathcyclus.sqlite3" in manifest_items:
            database_backup = backup_existing_database(root, database_target)

        for name in names:
            if name == MANIFEST_NAME or name.endswith("/"):
                continue
            try:
                rel = safe_zip_relative_path(name)
            except ValueError as exc:
                blocked.append(str(exc))
                continue
            if not is_restore_allowed(rel):
                skipped.append({"path": rel, "reason": "not_allowed"})
                continue

            target = (root / rel).resolve()
            try:
                ensure_inside_project(root, target)
            except ValueError as exc:
                blocked.append(str(exc))
                continue

            if target.exists() and not overwrite:
                conflicts.append(rel)
                continue

            if apply:
                target.parent.mkdir(parents=True, exist_ok=True)
                manifest_item = manifest_items.get(rel)
                if not manifest_item:
                    blocked.append(f"bundle manifest missing file: {rel}")
                    continue
                expected_size = int(manifest_item.get("size", -1))
                expected_hash = str(manifest_item.get("sha256") or "")

                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="wb",
                        prefix=f".{target.name}.",
                        suffix=".restore-tmp",
                        dir=target.parent,
                        delete=False,
                    ) as temporary:
                        temp_path = Path(temporary.name)
                        with archive.open(name) as source:
                            shutil.copyfileobj(source, temporary)
                    if temp_path.stat().st_size != expected_size or file_sha256(temp_path) != expected_hash:
                        blocked.append(f"bundle checksum validation failed: {rel}")
                        continue
                    if target.name == "mathcyclus.sqlite3":
                        check_conn = sqlite3.connect(temp_path)
                        try:
                            integrity = str(check_conn.execute("PRAGMA integrity_check").fetchone()[0])
                        finally:
                            check_conn.close()
                        if integrity != "ok":
                            blocked.append(f"SQLite integrity validation failed: {rel}")
                            continue
                    os.replace(temp_path, target)
                    temp_path = None
                finally:
                    if temp_path and temp_path.exists():
                        temp_path.unlink()
            restored.append(rel)

    status = "blocked" if blocked or conflicts else "ok"
    return {
        "status": status,
        "dry_run": not apply,
        "bundle": str(bundle_path),
        "project_root": str(root),
        "restored_count": len(restored),
        "conflict_count": len(conflicts),
        "skipped_count": len(skipped),
        "blocked_count": len(blocked),
        "restored": restored[:80],
        "conflicts": conflicts[:80],
        "skipped": skipped[:80],
        "blocked": blocked[:80],
        "overwrite": overwrite,
        "database_backup": database_backup,
        "bundle_schema_version": bundle_schema_version,
        "target_schema_version": target_schema_version,
        "supported_schema_version": supported_version,
        "migration_needed_after_restore": bool(
            not blocked and bundle_schema_version < supported_version
        ),
        "deletes_files": False,
    }


def print_summary(report: dict[str, Any], *, command: str) -> None:
    print(f"status={report.get('status', 'ok')}")
    if command == "export":
        print(f"dry_run={report.get('dry_run')}")
        print(f"output={report.get('output')}")
        print(f"item_count={report.get('item_count')}")
        print(f"total_bytes={report.get('total_bytes')}")
        print(f"contains_personal_data={report.get('contains_personal_data')}")
        print(f"intended_for_git={report.get('intended_for_git')}")
        print(f"schema_version={report.get('schema_version')}")
        print(f"bundle_size={report.get('bundle_size')}")
    elif command == "inspect":
        print(f"bundle={report.get('bundle')}")
        print(f"item_count={report.get('item_count')}")
        print(f"total_bytes={report.get('total_bytes')}")
        print(f"counts_by_kind={json.dumps(report.get('counts_by_kind', {}), ensure_ascii=False)}")
        print(f"contains_personal_data={report.get('contains_personal_data')}")
        print(f"intended_for_git={report.get('intended_for_git')}")
        print(f"schema_version={report.get('schema_version')}")
    elif command == "restore":
        print(f"dry_run={report.get('dry_run')}")
        print(f"restored_count={report.get('restored_count')}")
        print(f"conflict_count={report.get('conflict_count')}")
        print(f"skipped_count={report.get('skipped_count')}")
        print(f"blocked_count={report.get('blocked_count')}")
        print(f"bundle_schema_version={report.get('bundle_schema_version')}")
        print(f"supported_schema_version={report.get('supported_schema_version')}")
        if report.get("conflicts"):
            print("conflicts=" + ",".join(report["conflicts"]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导出、检查或恢复 MathCyclus 本地数据迁移包。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="导出本地数据迁移包。")
    export_parser.add_argument("--project-root", default=str(PROJECT_ROOT), help="项目根目录。")
    export_parser.add_argument("--output", default="", help="输出 zip 路径，默认 data/backups。")
    export_parser.add_argument("--stamp", default="", help="输出时间戳。")
    export_parser.add_argument("--include-legacy-tex", action="store_true", help="包含旧 chapters 题源。")
    export_parser.add_argument("--include-reports", action="store_true", help="包含 reports，默认不包含。")
    export_parser.add_argument("--include-exports", action="store_true", help="包含 exports，默认不包含。")
    export_parser.add_argument("--include-ingestion", action="store_true", help="包含完整 data/imports 任务目录；可能很大，导出时需暂停录题写入。")
    export_parser.add_argument("--dry-run", action="store_true", help="只统计，不写 zip。")
    export_parser.add_argument("--json", action="store_true", help="输出完整 JSON。")

    inspect_parser = subparsers.add_parser("inspect", help="检查迁移包清单。")
    inspect_parser.add_argument("bundle", help="迁移包 zip 路径。")
    inspect_parser.add_argument("--json", action="store_true", help="输出完整 JSON。")

    restore_parser = subparsers.add_parser("restore", help="恢复迁移包到本地项目。")
    restore_parser.add_argument("bundle", help="迁移包 zip 路径。")
    restore_parser.add_argument("--project-root", default=str(PROJECT_ROOT), help="目标项目根目录。")
    restore_parser.add_argument("--apply", action="store_true", help="真正写入文件；默认只 dry-run。")
    restore_parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有文件。默认不覆盖。")
    restore_parser.add_argument("--json", action="store_true", help="输出完整 JSON。")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "export":
        report = export_bundle(
            project_root=args.project_root,
            output=args.output or None,
            include_legacy_tex=args.include_legacy_tex,
            include_reports=args.include_reports,
            include_exports=args.include_exports,
            include_ingestion=args.include_ingestion,
            dry_run=args.dry_run,
            stamp=args.stamp or None,
        )
        report.setdefault("status", "ok")
    elif args.command == "inspect":
        report = inspect_bundle(args.bundle)
    elif args.command == "restore":
        report = restore_bundle(
            project_root=args.project_root,
            bundle=args.bundle,
            apply=args.apply,
            overwrite=args.overwrite,
        )
    else:
        parser.error("未知命令")
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_summary(report, command=args.command)
    return 0 if report.get("status") != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
