from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "exports" / "release_packages"


INCLUDE_FILES = [
    ".gitignore",
    "README.md",
    "requirements.txt",
    "env.example",
    "question_bank_app.py",
    "启动程序.bat",
    "启动程序.py",
    "MathCyclus_book.cls",
    "main.tex",
]

INCLUDE_DIRS = [
    "services",
    "scripts",
    "db",
    "docs",
    "templates",
    "utils",
    "fig",
    "cover",
    "Test Paper Group/主题模板",
]

PLACEHOLDER_FILES = [
    "data/.gitkeep",
    "data/backups/.gitkeep",
    "data/indexes/.gitkeep",
    "db/seed/.gitkeep",
    "assets/questions/.gitkeep",
    "reports/.gitkeep",
    "exports/.gitkeep",
    "chapters/.gitkeep",
]

DENY_PATTERNS = [
    ".git/**",
    ".venv/**",
    ".agents/**",
    ".codex/**",
    ".pytest_cache/**",
    ".ruff_cache/**",
    ".mypy_cache/**",
    "__pycache__/**",
    "**/__pycache__/**",
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.aux",
    "*.out",
    "*.toc",
    "*.bbl",
    "*.blg",
    "*.fls",
    "*.fdb_latexmk",
    "*.synctex.gz",
    "*.xdv",
    "*.sqlite",
    "*.sqlite3",
    "*.sqlite-*",
    "*.sqlite3-*",
    "*.db",
    "*.db-*",
    "*.pdf",
    ".env",
    ".env.*",
    "log.csv",
    "data/**",
    "db/seed/**",
    "assets/questions/**",
    "reports/**",
    "exports/**",
    "cloze_exports/**",
    "chapters/**",
    "Test Paper Group/导出文件/**",
]

ALLOW_DENY_OVERRIDES = set(PLACEHOLDER_FILES) | {"env.example"}

TRACKED_CLEANUP_PATTERNS = [
    "chapters/**",
    "Test Paper Group/导出文件/**",
    "data/**",
    "db/seed/**",
    "assets/questions/**",
    "reports/**",
    "exports/**",
    "cloze_exports/**",
    "*.sqlite",
    "*.sqlite3",
    "*.sqlite-*",
    "*.sqlite3-*",
    "*.db",
    "*.db-*",
    "*.pdf",
]

TRACKED_SAFE_EXCEPTIONS = set(PLACEHOLDER_FILES) | {"db/seed/.gitkeep"}


def normalize_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip("/")


def matches_any(path: str, patterns: list[str]) -> bool:
    normalized = normalize_path(path)
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def is_denied(path: str) -> bool:
    normalized = normalize_path(path)
    if normalized in ALLOW_DENY_OVERRIDES:
        return False
    return matches_any(normalized, DENY_PATTERNS)


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def iter_included_candidates() -> list[Path]:
    candidates: list[Path] = []
    for relative_file in INCLUDE_FILES + PLACEHOLDER_FILES:
        path = PROJECT_ROOT / relative_file
        if path.is_file():
            candidates.append(path)
    for relative_dir in INCLUDE_DIRS:
        directory = PROJECT_ROOT / relative_dir
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                candidates.append(path)
    unique: dict[str, Path] = {}
    for path in candidates:
        unique[relative_to_root(path)] = path
    return [unique[key] for key in sorted(unique)]


def build_manifest() -> dict[str, Any]:
    included: list[str] = []
    blocked_included: list[str] = []
    excluded_candidates: list[str] = []
    required_files = set(INCLUDE_FILES)
    for path in iter_included_candidates():
        relative = relative_to_root(path)
        if is_denied(relative):
            if relative in required_files:
                blocked_included.append(relative)
            else:
                excluded_candidates.append(relative)
            continue
        included.append(relative)
    return {
        "included_files": included,
        "blocked_included": blocked_included,
        "excluded_candidates": excluded_candidates,
        "missing_required": [
            path
            for path in INCLUDE_FILES
            if not (PROJECT_ROOT / path).is_file()
        ],
    }


def git_tracked_files() -> list[str]:
    try:
        output = subprocess.check_output(
            ["git", "-c", "core.quotepath=false", "ls-files", "-z"],
            cwd=PROJECT_ROOT,
        )
    except Exception:
        return []
    return [item.decode("utf-8", errors="replace") for item in output.split(b"\0") if item]


def tracked_cleanup_candidates() -> list[str]:
    candidates = []
    for path in git_tracked_files():
        normalized = normalize_path(path)
        if normalized in TRACKED_SAFE_EXCEPTIONS:
            continue
        if matches_any(normalized, TRACKED_CLEANUP_PATTERNS):
            candidates.append(normalized)
    return sorted(candidates)


def create_zip(included_files: list[str], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in included_files:
            archive.write(PROJECT_ROOT / relative, relative)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按白名单构建 MathCyclus 源码发布包，避免打入本地题库数据。")
    parser.add_argument("--create", action="store_true", help="实际生成 zip；默认只预览清单。")
    parser.add_argument("--output", default="", help="zip 输出路径；默认写入 exports/release_packages/。")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 报告。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_manifest()
    cleanup_candidates = tracked_cleanup_candidates()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR / f"mathcyclus_source_{stamp}.zip"
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    created = False
    if args.create and not manifest["blocked_included"] and not manifest["missing_required"]:
        create_zip(manifest["included_files"], output_path)
        created = True

    status = "blocked" if manifest["blocked_included"] or manifest["missing_required"] else "ok"
    report = {
        "status": status,
        "created": created,
        "package": relative_to_root(output_path),
        "included_count": len(manifest["included_files"]),
        "excluded_count": len(manifest["excluded_candidates"]),
        "excluded_candidates": manifest["excluded_candidates"],
        "blocked_included": manifest["blocked_included"],
        "missing_required": manifest["missing_required"],
        "tracked_cleanup_candidates": cleanup_candidates,
        "tracked_cleanup_count": len(cleanup_candidates),
        "uses_whitelist": True,
        "private_data_policy": "exclude local databases, API keys, migration seed data, reports, exports, question images, and legacy chapters data",
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"status={report['status']}")
        print(f"created={report['created']}")
        print(f"package={report['package']}")
        print(f"included_count={report['included_count']}")
        print(f"excluded_count={report['excluded_count']}")
        print(f"blocked_included={len(report['blocked_included'])}")
        print(f"missing_required={len(report['missing_required'])}")
        print(f"tracked_cleanup_count={report['tracked_cleanup_count']}")
    if status == "blocked":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
