"""Export, inspect, and restore local MathCyclus data bundles.

The bundle is for moving a user's private data between machines.  It is not a
GitHub release artifact and should normally be written under ``data/backups/``,
which is ignored by Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
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
    ("csv_cache", "utils/题库索引表.csv"),
]

OPTIONAL_ITEMS = {
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
    normalized = str(path or "").replace("\\", "/").strip("/")
    if not normalized or normalized.startswith("../") or "/../" in normalized or normalized == "..":
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


def iter_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    if not path.exists():
        return
    for item in sorted(path.rglob("*")):
        if item.is_file() and "__pycache__" not in item.parts:
            yield item


def collect_items(
    project_root: Path,
    *,
    include_legacy_tex: bool = False,
    include_reports: bool = False,
    include_exports: bool = False,
) -> tuple[list[BundleItem], list[dict[str, str]]]:
    specs = list(DEFAULT_ITEMS)
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
        "include_legacy_tex": include_legacy_tex,
        "include_reports": include_reports,
        "include_exports": include_exports,
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
    dry_run: bool = False,
    stamp: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    safe_stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = resolve_project_path(root, output) if output else default_output_path(root, safe_stamp)
    ensure_inside_project(root, output_path)

    items, skipped = collect_items(
        root,
        include_legacy_tex=include_legacy_tex,
        include_reports=include_reports,
        include_exports=include_exports,
    )
    output_relative = relative_to_root(output_path, root)
    items = [item for item in items if item.relative_path != output_relative]
    manifest = make_manifest(
        root,
        output_path,
        items,
        skipped,
        include_legacy_tex=include_legacy_tex,
        include_reports=include_reports,
        include_exports=include_exports,
    )

    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
            for item in items:
                archive.write(item.source_path, item.relative_path)
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
            return json.loads(file_obj.read().decode("utf-8"))


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
                with archive.open(name) as source, target.open("wb") as destination:
                    destination.write(source.read())
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
        print(f"bundle_size={report.get('bundle_size')}")
    elif command == "inspect":
        print(f"bundle={report.get('bundle')}")
        print(f"item_count={report.get('item_count')}")
        print(f"total_bytes={report.get('total_bytes')}")
        print(f"counts_by_kind={json.dumps(report.get('counts_by_kind', {}), ensure_ascii=False)}")
        print(f"contains_personal_data={report.get('contains_personal_data')}")
        print(f"intended_for_git={report.get('intended_for_git')}")
    elif command == "restore":
        print(f"dry_run={report.get('dry_run')}")
        print(f"restored_count={report.get('restored_count')}")
        print(f"conflict_count={report.get('conflict_count')}")
        print(f"skipped_count={report.get('skipped_count')}")
        print(f"blocked_count={report.get('blocked_count')}")
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
