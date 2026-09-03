from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"
FORMAL_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


DATABASE_PATTERNS = [
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.db-*",
    "*.sqlite-*",
    "*.sqlite3-*",
]

GENERATED_ROOTS = [
    "data",
    "exports",
    "import_reports",
    "assets/questions",
]

CACHE_ROOTS = [
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".tikz_cache",
    ".edge-test-profile",
]

GENERATED_FILE_PATTERNS = [
    "reports/*.csv",
    "reports/*.json",
    "reports/*.sqlite3",
    "reports/*.db",
    "*.tmp",
    "*.bak",
    "*.orig",
    "*.rej",
    ".DS_Store",
    "Thumbs.db",
]

QUESTION_TEX_PATTERNS = [
    "*-G-*.tex",
    "*-M-*.tex",
    "*-W-*.tex",
    "*-XK-*.tex",
    "*-XS-*.tex",
    "*-QJ-*.tex",
    "*-JS-*.tex",
    "*-WK-*.tex",
]

ALLOW_TRACKED_GENERATED = {
    "data/.gitkeep",
    "data/indexes/.gitkeep",
    "data/backups/.gitkeep",
    "exports/.gitkeep",
    "assets/questions/.gitkeep",
    "reports/.gitkeep",
}

IGNORE_PROBES = [
    ".env",
    ".env.local",
    ".streamlit/secrets.toml",
    "__pycache__/module.pyc",
    ".pytest_cache/v/cache/nodeids",
    ".ruff_cache/content",
    ".tikz_cache/example.pdf",
    "data/mathcyclus.sqlite3",
    "data/mathcyclus_preview_test.sqlite3",
    "data/indexes/test.sqlite3",
    "data/backups/test.sqlite3",
    "reports/generated.csv",
    "reports/generated.json",
    "reports/generated.sqlite",
    "reports/generated.sqlite3",
    "reports/generated.db",
    "mathcyclus.sqlite3-wal",
    "mathcyclus.sqlite3-shm",
    "exports/generated.tex",
    "assets/questions/Q000001/figure.png",
    "2025-G-sample.tex",
    "2025-M-sample.tex",
    "question_bank_app000.py",
    "old_app.py",
    "log.csv",
]

SENSITIVE_TRACKED_PATTERNS = [
    "question_bank_app.py",
    "chapters/",
    ".tex",
]


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def run_git(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        input=input_text,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def git_available() -> bool:
    completed = run_git(["rev-parse", "--is-inside-work-tree"])
    return completed.returncode == 0 and completed.stdout.strip() == "true"


def list_tracked_files() -> set[str]:
    completed = run_git(["ls-files", "-z"])
    if completed.returncode != 0:
        return set()
    return {item.replace("\\", "/") for item in completed.stdout.split("\0") if item}


def list_status_entries() -> list[dict[str, str]]:
    completed = run_git(["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if completed.returncode != 0:
        return []
    parts = [part for part in completed.stdout.split("\0") if part]
    entries: list[dict[str, str]] = []
    index = 0
    while index < len(parts):
        entry = parts[index]
        status = entry[:2]
        path = entry[3:].replace("\\", "/")
        original_path = ""
        if status[0] in {"R", "C"}:
            index += 1
            if index < len(parts):
                original_path = parts[index].replace("\\", "/")
        entries.append({"status": status, "path": path, "original_path": original_path})
        index += 1
    return entries


def list_content_diff_paths() -> list[str]:
    completed = run_git(["diff", "--name-only", "-z"])
    if completed.returncode != 0:
        return []
    return [item.replace("\\", "/") for item in completed.stdout.split("\0") if item]


def check_ignored(paths: list[str]) -> set[str]:
    if not paths:
        return set()
    completed = subprocess.run(
        ["git", "check-ignore", "-z", "--stdin"],
        cwd=PROJECT_ROOT,
        input=("\0".join(paths) + "\0").encode("utf-8"),
        capture_output=True,
        check=False,
    )
    if completed.returncode not in {0, 1}:
        return set()
    return {
        item.decode("utf-8", errors="replace").replace("\\", "/")
        for item in completed.stdout.split(b"\0")
        if item
    }


def iter_existing_files() -> list[Path]:
    ignored_dirs = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".tikz_cache",
        ".edge-test-profile",
    }
    files: list[Path] = []
    stack = [PROJECT_ROOT]
    while stack:
        directory = stack.pop()
        try:
            children = list(directory.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if child.name not in ignored_dirs:
                    stack.append(child)
            elif child.is_file():
                files.append(child)
    return files


def matches_any(path: Path, patterns: list[str]) -> bool:
    return any(path.match(pattern) or path.name == pattern for pattern in patterns)


def is_inside_root(relative_path: str, root: str) -> bool:
    return relative_path == root or relative_path.startswith(root.rstrip("/") + "/")


def collect_risky_files(tracked: set[str]) -> dict[str, list[dict[str, Any]]]:
    files = iter_existing_files()
    relative_files = [relative_to_root(path) for path in files]
    ignored = check_ignored(relative_files)
    by_path = {relative_to_root(path): path for path in files}

    database_files: list[dict[str, Any]] = []
    generated_files: list[dict[str, Any]] = []
    question_tex_files: list[dict[str, Any]] = []
    temp_files: list[dict[str, Any]] = []

    for relative_path, path in sorted(by_path.items()):
        normalized = relative_path.replace("\\", "/")
        ignored_by_git = normalized in ignored
        tracked_by_git = normalized in tracked
        base = {
            "path": normalized,
            "ignored": ignored_by_git,
            "tracked": tracked_by_git,
            "size_bytes": path.stat().st_size,
        }

        if matches_any(Path(normalized), DATABASE_PATTERNS):
            database_files.append(base)

        generated_root_hit = any(is_inside_root(normalized, root) for root in GENERATED_ROOTS)
        generated_pattern_hit = matches_any(Path(normalized), GENERATED_FILE_PATTERNS)
        if (generated_root_hit or generated_pattern_hit) and normalized not in ALLOW_TRACKED_GENERATED:
            generated_files.append({**base, "root_or_pattern": "generated"})

        if matches_any(Path(normalized), QUESTION_TEX_PATTERNS):
            question_tex_files.append(base)

        if matches_any(Path(normalized), ["*.tmp", "*.bak", "*.orig", "*.rej", ".DS_Store", "Thumbs.db"]):
            temp_files.append(base)

    return {
        "database_files": database_files,
        "generated_files": generated_files,
        "question_tex_files": question_tex_files,
        "temp_files": temp_files,
    }


def risky_unignored(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if not item["ignored"] and not item["tracked"]]


def risky_tracked(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if item["tracked"]]


def is_sensitive_path(path: str) -> bool:
    return path == "question_bank_app.py" or path.endswith(".tex") or path.startswith("chapters/")


def sensitive_modified(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    sensitive: list[dict[str, str]] = []
    for entry in entries:
        if entry["status"] == "??":
            continue
        path = entry["path"]
        if is_sensitive_path(path):
            sensitive.append(entry)
    return sensitive


def sensitive_content_diff(paths: list[str]) -> list[dict[str, str]]:
    return [
        {"status": "M", "path": path, "original_path": ""}
        for path in paths
        if is_sensitive_path(path)
    ]


def build_report(stamp: str) -> dict[str, Any]:
    git_ok = git_available()
    tracked = list_tracked_files() if git_ok else set()
    status_entries = list_status_entries() if git_ok else []
    content_diff_paths = list_content_diff_paths() if git_ok else []
    risky_files = collect_risky_files(tracked) if git_ok else {
        "database_files": [],
        "generated_files": [],
        "question_tex_files": [],
        "temp_files": [],
    }

    ignored_probes = check_ignored(IGNORE_PROBES) if git_ok else set()
    missing_ignore_probes = [path for path in IGNORE_PROBES if path not in ignored_probes]
    sensitive_status_changes = sensitive_modified(status_entries)
    sensitive_changes = sensitive_content_diff(content_diff_paths)
    formal_db_relative = relative_to_root(FORMAL_DB)
    formal_db_ignored = formal_db_relative in ignored_probes
    formal_db_tracked = formal_db_relative in tracked

    database_unignored = risky_unignored(risky_files["database_files"])
    database_tracked = risky_tracked(risky_files["database_files"])
    generated_unignored = risky_unignored(risky_files["generated_files"])
    generated_tracked = [
        item
        for item in risky_tracked(risky_files["generated_files"])
        if item["path"] not in ALLOW_TRACKED_GENERATED
    ]
    question_tex_unignored = risky_unignored(risky_files["question_tex_files"])
    question_tex_tracked = risky_tracked(risky_files["question_tex_files"])
    temp_unignored = risky_unignored(risky_files["temp_files"])

    blockers: list[str] = []
    warnings: list[str] = []

    if not git_ok:
        blockers.append("Git 仓库状态不可读取，无法完成提交前卫生检查。")
    if FORMAL_DB.exists() and (not formal_db_ignored or formal_db_tracked):
        blockers.append("正式库 data/mathcyclus.sqlite3 存在，但未被忽略或已被 Git 跟踪。")
    if database_unignored:
        blockers.append("存在未被 .gitignore 忽略的数据库文件。")
    if database_tracked:
        blockers.append("存在已被 Git 跟踪的数据库文件。")
    if generated_unignored:
        blockers.append("存在未被 .gitignore 忽略的生成产物。")
    if generated_tracked:
        warnings.append("存在已被 Git 跟踪的生成产物；请确认是否确实需要版本管理。")
    if question_tex_unignored:
        warnings.append("存在未被忽略的题库 .tex 源文件。")
    if question_tex_tracked:
        warnings.append("存在已被 Git 跟踪的题库 .tex 源文件；请确认版权与仓库体积风险。")
    if temp_unignored:
        warnings.append("存在未被忽略的临时文件。")
    if missing_ignore_probes:
        blockers.append(".gitignore 没有覆盖部分关键探针路径。")
    if sensitive_changes:
        warnings.append("存在敏感 tracked 文件改动，需要提交前人工确认。")

    return {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stamp": stamp,
        "status": "blocked" if blockers else "warning" if warnings else "ok",
        "git_available": git_ok,
        "formal_db_exists": FORMAL_DB.exists(),
        "formal_db_ignored": formal_db_ignored,
        "formal_db_tracked": formal_db_tracked,
        "ignore_probes": {
            "total": len(IGNORE_PROBES),
            "ignored": sorted(ignored_probes),
            "missing": missing_ignore_probes,
        },
        "git_status": {
            "changed_count": len(status_entries),
            "changed_entries": status_entries,
            "content_diff_count": len(content_diff_paths),
            "content_diff_paths": content_diff_paths,
            "sensitive_status_modified": sensitive_status_changes,
            "sensitive_modified": sensitive_changes,
        },
        "risky_files": risky_files,
        "findings": {
            "database_unignored": database_unignored,
            "database_tracked": database_tracked,
            "generated_unignored": generated_unignored,
            "generated_tracked": generated_tracked,
            "question_tex_unignored": question_tex_unignored,
            "question_tex_tracked": question_tex_tracked,
            "temp_unignored": temp_unignored,
        },
        "blockers": blockers,
        "warnings": warnings,
    }


def markdown_items(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) or "- 无"


def markdown_file_table(items: list[dict[str, Any]], limit: int = 40) -> str:
    if not items:
        return "| 文件 | Git 忽略 | 已跟踪 | 大小 |\n| --- | --- | --- | ---: |\n| 无 | - | - | 0 |"
    lines = ["| 文件 | Git 忽略 | 已跟踪 | 大小 |", "| --- | --- | --- | ---: |"]
    for item in items[:limit]:
        lines.append(
            f"| `{item['path']}` | `{item['ignored']}` | `{item['tracked']}` | {item['size_bytes']} |"
        )
    if len(items) > limit:
        lines.append(f"| 另有 {len(items) - limit} 项未展示 | - | - | - |")
    return "\n".join(lines)


def markdown_status_entries(items: list[dict[str, str]], limit: int = 80) -> str:
    if not items:
        return "- 无"
    lines = []
    for item in items[:limit]:
        original = f"（原路径：`{item['original_path']}`）" if item.get("original_path") else ""
        lines.append(f"- `{item['status']}` `{item['path']}`{original}")
    if len(items) > limit:
        lines.append(f"- 另有 {len(items) - limit} 项未展示")
    return "\n".join(lines)


def write_report(report: dict[str, Any], md_path: Path, json_path: Path) -> None:
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    findings = report["findings"]
    probe_missing = "\n".join(f"- `{path}`" for path in report["ignore_probes"]["missing"]) or "- 无"

    md_path.write_text(
        f"""# 项目提交前卫生检查报告

> 生成时间：{report['created_at']}  
> 执行方式：只读检查；不修改数据库、`.tex`、前端主程序或 Git 状态。  
> 状态：`{report['status']}`  

## 结论

- 正式 SQLite 存在：`{report['formal_db_exists']}`
- 正式 SQLite 被忽略：`{report['formal_db_ignored']}`
- 正式 SQLite 已跟踪：`{report['formal_db_tracked']}`
- Git 状态可读：`{report['git_available']}`
- 真实内容 diff 文件数：{report['git_status']['content_diff_count']}
- 阻断项：{len(report['blockers'])}
- 警告项：{len(report['warnings'])}

## 阻断项

{markdown_items(report['blockers'])}

## 警告项

{markdown_items(report['warnings'])}

## 忽略规则探针

- 探针总数：{report['ignore_probes']['total']}
- 未覆盖探针：
{probe_missing}

## 敏感 tracked 内容改动

{markdown_status_entries(report['git_status']['sensitive_modified'])}

## 当前 Git 内容 diff

{markdown_items(report['git_status']['content_diff_paths'])}

## 当前 Git 状态

> 这里保留 `git status` 原始视图；在受限环境下，个别中文路径可能出现 stat cache 假修改，以“内容 diff”为准。

{markdown_status_entries(report['git_status']['changed_entries'])}

## 数据库文件风险

### 未忽略数据库

{markdown_file_table(findings['database_unignored'])}

### 已跟踪数据库

{markdown_file_table(findings['database_tracked'])}

## 生成产物风险

### 未忽略生成产物

{markdown_file_table(findings['generated_unignored'])}

### 已跟踪生成产物

{markdown_file_table(findings['generated_tracked'])}

## 题库 TeX 风险

### 未忽略题库 TeX

{markdown_file_table(findings['question_tex_unignored'])}

### 已跟踪题库 TeX

{markdown_file_table(findings['question_tex_tracked'])}

## 临时文件风险

{markdown_file_table(findings['temp_unignored'])}

## 使用建议

- `blocked`：先处理阻断项，再提交。
- `warning`：可以继续开发，但提交前要人工确认对应风险。
- `ok`：本脚本覆盖范围内没有发现提交卫生问题。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读检查项目提交前文件卫生状态。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = build_report(args.stamp)
    md_path = REPORTS_DIR / f"project_hygiene_{args.stamp}.md"
    json_path = REPORTS_DIR / f"project_hygiene_{args.stamp}.json"
    write_report(report, md_path, json_path)

    print(f"status={report['status']}")
    print(f"blockers={len(report['blockers'])}")
    print(f"warnings={len(report['warnings'])}")
    print(f"formal_db_exists={report['formal_db_exists']}")
    print(f"content_diff_files={report['git_status']['content_diff_count']}")
    print(f"status_entries={report['git_status']['changed_count']}")
    print(f"report={relative_to_root(md_path)}")
    print(f"json={relative_to_root(json_path)}")


if __name__ == "__main__":
    main()
